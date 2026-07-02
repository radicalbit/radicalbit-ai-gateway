from contextlib import asynccontextmanager
from functools import wraps
import json
import logging.config
import os
import time
from urllib.parse import urlparse
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from httpx_aiohttp import HttpxAiohttpClient
from openai.types import CreateEmbeddingResponse
from openai.types.embedding_create_params import EmbeddingCreateParams
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import start_http_server
from starlette.middleware.cors import CORSMiddleware
from traceloop.sdk import Instruments, Traceloop
from traceloop.sdk.decorators import task, workflow

from radicalbit_ai_gateway.ai_gateway import GatewayRoute
from radicalbit_ai_gateway.auth.api_key_validator import ApiKeyValidator
from radicalbit_ai_gateway.db.clickhouse_database import ClickHouseDatabase
from radicalbit_ai_gateway.db.dao.event_dao import EventDAO
from radicalbit_ai_gateway.db.dao.group_dao import GroupDAO
from radicalbit_ai_gateway.db.dao.group_route_dao import GroupRouteDAO
from radicalbit_ai_gateway.db.dao.key_dao import KeyDAO
from radicalbit_ai_gateway.db.dao.otel_traces_dao import OtelTracesDAO
from radicalbit_ai_gateway.db.dao.project_config_dao import ProjectConfigDAO
from radicalbit_ai_gateway.db.dao.project_dao import ProjectDAO
from radicalbit_ai_gateway.db.dao.request_event_dao import RequestEventDAO
from radicalbit_ai_gateway.db.database import Database
from radicalbit_ai_gateway.metrics.define_metrics import (
    request_latency_histogram,
    total_requests_counter,
)
from radicalbit_ai_gateway.middleware.request_event_context import RequestEventContext
from radicalbit_ai_gateway.middleware.request_event_middleware import (
    RequestEventMiddleware,
)
from radicalbit_ai_gateway.models.auth_dto import KeyDetails
from radicalbit_ai_gateway.models.chat_request import convert_openai_messages
from radicalbit_ai_gateway.models.project_dto import ProjectOut
from radicalbit_ai_gateway.plugins.loader import discover_plugins, init_plugins
from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.routes.configs_route import ConfigsRoute
from radicalbit_ai_gateway.routes.dashboard_route import DashboardRoute
from radicalbit_ai_gateway.routes.group_route import GroupRoute
from radicalbit_ai_gateway.routes.key_route import KeyRoute
from radicalbit_ai_gateway.routes.project_route import ProjectRoute, ProjectRouteConfig
from radicalbit_ai_gateway.routes.tracing_route import TracingRoute
from radicalbit_ai_gateway.routes.usage_route import UsageRoute
from radicalbit_ai_gateway.services.api_key_security import ApiKeySecurity
from radicalbit_ai_gateway.services.config_generator_service import (
    ConfigGeneratorService,
)
from radicalbit_ai_gateway.services.event_service import EventService
from radicalbit_ai_gateway.services.group_service import GroupService
from radicalbit_ai_gateway.services.key_service import KeyService
from radicalbit_ai_gateway.services.project_service import ProjectService
from radicalbit_ai_gateway.services.request_event_service import RequestEventService
from radicalbit_ai_gateway.services.tracing_service import TracingService
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import (
    ApiKeyError,
    AppError,
    AuthRegistryError,
    BudgetLimitExceeded,
    GatewayBadRequest,
    GatewayError,
    GuardrailError,
    InvalidApiKey,
    JudgeInternalError,
    MissingApiKey,
    ModelInvokerError,
    RequestRateLimitExceeded,
    TokenLimitExceeded,
    api_key_exception_handler,
    auth_registry_exception_handler,
    budget_limiter_exception_handler,
    gateway_exception_handler,
    guardrail_exception_handler,
    judge_exception_handler,
    model_invoker_exception_handler,
    rate_limit_exceeded_handler,
    token_limiter_exception_handler,
    unhandled_exception_handler,
)
from radicalbit_ai_gateway.utils.filtering_exporter import FilteringExporter
from radicalbit_ai_gateway.utils.gateway_route_factory import (
    build_project_route_registrar,
)
from radicalbit_ai_gateway.utils.logging_hooks import apply_log_filters
from radicalbit_ai_gateway.utils.open_ai_types import (
    CompletionCreateParams,
    ResponseCreateParamsCustom,
)
from radicalbit_ai_gateway.utils.request_context import (
    reset_route_context,
    set_current_route_config,
)
from radicalbit_ai_gateway.utils.responses_streaming import (
    build_skeleton_response,
    chat_chunks_to_response_events,
    list_chunks_to_response_events,
)
from radicalbit_ai_gateway.utils.responses_translation import (
    chat_completion_to_response,
    input_to_langchain_messages,
    responses_tools_to_chat_completions_tools,
    translate_tool_choice,
)
from radicalbit_ai_gateway.utils.streaming_response import (
    StreamingResponseWithStatusCode,
)
from radicalbit_ai_gateway.utils.telemetry_hooks import get_exporter_wrappers
from radicalbit_ai_gateway.utils.trace_attributes import (
    OperationCategory,
    ensure_endpoint_category,
    set_operation_category,
    set_trace_attributes,
)

app_config = get_app_config()
logging_config_dict = app_config.log_config.model_dump()
logging.config.dictConfig(logging_config_dict)
logger = logging.getLogger(app_config.log_config.logger_name)

# Async httpx client with httpx-aiohttp
httpx_aiohttp_client = HttpxAiohttpClient()

prompt_manager_config = app_config.prompt_manager_config
_PROMPT_MANAGER = PromptManager(prompt_manager_config)
PromptManager.set_global(_PROMPT_MANAGER)

# Ensure DEBUG logs are emitted when gateway debug mode is enabled,
# even if external runners pre-configured logging differently.
if app_config.gateway_debug_mode:
    try:
        # App logger
        logger.setLevel(logging.DEBUG)
        # Root and common servers' loggers
        logging.getLogger().setLevel(logging.DEBUG)
        logging.getLogger('uvicorn.error').setLevel(logging.DEBUG)
        logging.getLogger('uvicorn.access').setLevel(logging.DEBUG)
    except Exception:
        # Do not fail on logging setup
        pass

ch_database = ClickHouseDatabase(conf=app_config.clickhouse_config)
database = Database(conf=app_config.db_config)

discover_plugins()

key_dao = KeyDAO(database)
group_dao = GroupDAO(database)
group_route_dao = GroupRouteDAO(database)
project_dao = ProjectDAO(database)
project_config_dao = ProjectConfigDAO(database)
event_dao = EventDAO(ch_database)
request_event_dao = RequestEventDAO(ch_database)
otel_traces_dao = OtelTracesDAO(ch_database)
api_key_security = ApiKeySecurity()

project_configs: dict = {}
key_service = KeyService(
    key_dao=key_dao,
    api_key_security=api_key_security,
    group_dao=group_dao,
)
group_service = GroupService(
    group_dao=group_dao,
    group_route_dao=group_route_dao,
    key_service=key_service,
    project_configs=project_configs,
)
project_service = ProjectService(
    project_dao=project_dao, project_config_dao=project_config_dao
)
config_generator_service = ConfigGeneratorService()
event_service = EventService(
    event_dao=event_dao,
    key_service=key_service,
    group_service=group_service,
    request_event_dao=request_event_dao,
)
request_event_service = RequestEventService(request_event_dao=request_event_dao)
tracing_service = TracingService(
    otel_traces_dao=otel_traces_dao,
    key_service=key_service,
    group_service=group_service,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # setup database
    database.connect()
    ch_database.connect()
    if app_config.db_config.db_type == 'postgresql':
        database.init_mappings()
    app.state.project_configs = project_configs
    app.state.routes = {}

    register_fn, _ = build_project_route_registrar(app, httpx_aiohttp_client)

    async def _safe_register(project_out: ProjectOut) -> None:
        try:
            served = next(
                (
                    c
                    for c in project_out.configs
                    if c.uuid == project_out.served_config_uuid
                ),
                None,
            )
            if served and served.config_file:
                await register_fn(
                    project_out.uuid,
                    project_out.name,
                    served.config_file,
                )
                logger.info('Loaded project routes at startup: %s', project_out.name)
            else:
                logger.info(
                    'Skipping project %s at startup — no served config',
                    project_out.name,
                )
        except Exception:
            logger.exception(
                'Failed to load config for project %s at startup — skipping',
                project_out.name,
            )

    for project in project_service.get_all_active():
        await _safe_register(project)

    server, _ = start_http_server(int(app_config.prometheus_metrics_port))

    # Telemetry
    def _otlp_endpoint(url: str) -> str:
        """Append /v1/traces if the URL has no explicit path (OTLPSpanExporter uses the value as-is)."""
        parsed = urlparse(url)
        if not parsed.path or parsed.path == '/':
            return url.rstrip('/') + '/v1/traces'
        return url

    processors = []

    def _build_processor(exporter: OTLPSpanExporter) -> BatchSpanProcessor:
        for wrap in get_exporter_wrappers():
            exporter = wrap(exporter)
        return BatchSpanProcessor(FilteringExporter(exporter))

    if app_config.telemetry_config.collector_base_url:
        endpoint = _otlp_endpoint(app_config.telemetry_config.collector_base_url)
        processors.append(_build_processor(OTLPSpanExporter(endpoint=endpoint)))
        logger.info('Configured otel-collector for url: %s', endpoint)

    for exp_cfg in app_config.telemetry_config.otlp_exporters:
        headers = dict(exp_cfg.headers or {})
        if exp_cfg.api_key:
            headers['Authorization'] = f'Bearer {exp_cfg.api_key}'
        endpoint = _otlp_endpoint(exp_cfg.url)
        processors.append(
            _build_processor(OTLPSpanExporter(endpoint=endpoint, headers=headers))
        )
        logger.info('Configured extra processor for url: %s', endpoint)

    if processors:
        Traceloop.init(
            app_name='radicalbit-ai-gateway',
            telemetry_enabled=False,
            processor=processors,
            instruments={Instruments.LANGCHAIN},
        )
    logger.info('AI Gateway initialized successfully')
    yield
    logger.info('Shutting down AI Gateway')
    database.reset_connection()
    ch_database.reset_connection()
    await httpx_aiohttp_client.aclose()
    server.shutdown()


app = FastAPI(
    title='Radicalbit AI Gateway',
    description='A FastAPI server for the Radicalbit AI Gateway',
    version='0.1.0',
    lifespan=lifespan,
)

# Register the default token validator before plugins load.
# Auth plugins (e.g. keycloak_idp) may wrap or replace it via app.state.token_validator.
app.state.token_validator = ApiKeyValidator(key_service=key_service)

# load plugins
init_plugins(app)

# Attach plugin-registered log filters, now that plugins have registered them.
apply_log_filters(logger)

# middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=app_config.cors_config.cors_allow_origins,
    allow_credentials=app_config.cors_config.cors_allow_credentials,
    allow_methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
    allow_headers=['*'],
)
app.add_middleware(RequestEventMiddleware)

# router
prefix = f'/public/api/{app_config.endpoint_version}'
app.include_router(
    DashboardRoute.get_dashboard_router(
        event_service=event_service,
        request_event_service=request_event_service,
        project_service=project_service,
    ),
    prefix=prefix,
)
app.include_router(
    TracingRoute.get_tracing_router(
        tracing_service=tracing_service,
        project_service=project_service,
    ),
    prefix=prefix,
)
app.include_router(ConfigsRoute.get_configs_router(project_service), prefix=prefix)
app.include_router(
    UsageRoute.get_usage_router(
        event_service=event_service,
        project_service=project_service,
    ),
    prefix=prefix,
)

# exception_handler
app.add_exception_handler(Exception, unhandled_exception_handler)
app.add_exception_handler(RequestRateLimitExceeded, rate_limit_exceeded_handler)
app.add_exception_handler(TokenLimitExceeded, token_limiter_exception_handler)
app.add_exception_handler(GatewayError, gateway_exception_handler)
app.add_exception_handler(ModelInvokerError, model_invoker_exception_handler)
app.add_exception_handler(ApiKeyError, api_key_exception_handler)
app.add_exception_handler(GuardrailError, guardrail_exception_handler)
app.add_exception_handler(JudgeInternalError, judge_exception_handler)
app.add_exception_handler(BudgetLimitExceeded, budget_limiter_exception_handler)
app.add_exception_handler(AuthRegistryError, auth_registry_exception_handler)
app.include_router(KeyRoute.get_key_router(key_service), prefix=prefix)
app.include_router(
    GroupRoute.get_group_router(group_service, project_service),
    prefix=prefix,
)
_register, _deregister = build_project_route_registrar(app, httpx_aiohttp_client)
app.include_router(
    ProjectRoute.get_project_router(
        project_service,
        group_service,
        register_project_routes=_register,
        deregister_project_routes=_deregister,
        config=getattr(app.state, 'project_route_config', ProjectRouteConfig()),
        config_generator_service=config_generator_service,
    ),
    prefix=prefix,
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = [{'loc': e.get('loc'), 'type': e.get('type')} for e in exc.errors()]
    logger.error('Validation error: %s', errors)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={'detail': exc.errors(), 'body': (await request.body()).decode()},
    )


@task(name='auth_api_key')
async def set_api_key_uuid(
    request: Request, project_uuid: str, project_name: str
) -> KeyDetails:
    auth = request.headers.get('authorization')
    if not auth or not auth.startswith('Bearer '):
        raise MissingApiKey('Missing API key')
    token = auth.split(' ')[1]

    key_details = await request.app.state.token_validator.validate_token(
        token,
    )
    request.state.api_key_uuid = key_details.api_key_uuid
    request.state.api_key_name = key_details.api_key_name
    request.state.group_uuid = key_details.group_uuid
    request.state.group_name = key_details.group_name
    ctx = RequestEventContext.get_or_create(request)
    ctx.api_key_uuid = key_details.api_key_uuid
    ctx.api_key_name = key_details.api_key_name
    ctx.group_uuid = key_details.group_uuid
    ctx.group_name = key_details.group_name
    set_trace_attributes(
        api_key_uuid=key_details.api_key_uuid,
        api_key_name=key_details.api_key_name,
        group_uuid=key_details.group_uuid,
        group_name=key_details.group_name,
        project_uuid=project_uuid,
        project_name=project_name,
    )
    return key_details


async def set_request_uuid(request: Request) -> str:
    return request.state.request_uuid


async def get_ai_gateway_dependency():
    if app.state.routes is None:
        raise HTTPException(
            status_code=503,
            detail='AI Gateway not initialized. Please check server configuration.',
        )
    return app.state.routes


def _set_early_project_trace_attributes(
    route_key: str | None,
    route: GatewayRoute | None,
) -> None:
    """Set project identity on the span before route validation and auth.

    Ensures traces from failed requests (unknown route, bad API key) remain
    visible in project-scoped queries.
    """
    if route is not None:
        set_trace_attributes(
            project_uuid=route.project_uuid, project_name=route.project_name
        )
        return
    project_name, _, route_name_part = (route_key or '').partition('/')
    entry = getattr(app.state, 'project_configs', {}).get(project_name)
    if entry:
        set_trace_attributes(
            project_uuid=str(entry.uuid),
            project_name=project_name,
            route_name=route_name_part or route_key,
        )
    else:
        set_trace_attributes(route_name=route_name_part or route_key)


@app.get('/health')
async def health_check():
    return {
        'status': 'ok',
        'service': 'Radicalbit AI Gateway',
        'version': '0.1.0',
        'gateway_initialized': app.state.routes is not None,
    }


def record_metrics(
    method: str,
    path: str,
    status_code: int,
    route_name: str,
    latency_ms: float,
    model_name: str | None = None,
):
    attributes = {
        'http.method': method,
        'http.route': path,
        'http.status_code': status_code,
        'route.name': route_name,
        'model_name': model_name,
    }
    request_latency_histogram.record(latency_ms, attributes=attributes)
    total_requests_counter.add(1, attributes=attributes)
    log_message = 'Metrics recorded for {} {}: status={}, route={}, latency={:.2f}ms'
    logger.debug(log_message.format(method, path, status_code, route_name, latency_ms))


def otel_metrics_decorator(func):
    @wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        start_time = time.monotonic()
        status_code = 200

        try:
            return await func(request, *args, **kwargs)
        except Exception:
            status_code = 500
            raise
        finally:
            # Get metrics data from request state (set by the decorated function)
            route_name = getattr(request.state, 'otel_route_name', 'unknown')
            model_name = getattr(request.state, 'otel_model_name', None)

            latency_ms = (time.monotonic() - start_time) * 1000
            record_metrics(
                request.method,
                request.url.path,
                status_code,
                route_name,
                latency_ms,
                model_name,
            )

    return wrapper


# This endpoint must follow the openai standard
# https://platform.openai.com/docs/api-reference/chat/create
@app.post(
    '/v1/chat/completions',
)
@otel_metrics_decorator
@workflow(name='chat_completions')
@ensure_endpoint_category
@reset_route_context
async def chat_completions(
    request: Request,
    completion_create_params: CompletionCreateParams,
    gateway_routes: dict[str, GatewayRoute] = Depends(get_ai_gateway_dependency),
    request_uuid: str = Depends(set_request_uuid),
):
    route_key = completion_create_params.get('model', 'unknown')
    route = gateway_routes.get(route_key)

    _set_early_project_trace_attributes(route_key, route)

    if route is None:
        raise GatewayBadRequest(
            f'The route name [{route_key}] was not found in the config'
        )
    route_name = route.gateway_route_config.route_name
    # Publish the route config for per-route log filtering (cleared by the decorator).
    set_current_route_config(route.gateway_route_config)
    # Mark the root workflow span with ENDPOINT category
    set_operation_category(OperationCategory.ENDPOINT)

    # Set early trace attributes
    set_trace_attributes(request_uuid=request_uuid, route_name=route_name)

    ctx = RequestEventContext.get_or_create(request)
    ctx.route_name = route_name
    ctx.is_streaming = bool(completion_create_params.get('stream'))
    set_operation_category(OperationCategory.AUTH)
    key_details = await set_api_key_uuid(
        request, route.project_uuid, route.project_name
    )

    # Set auth-related trace attributes
    set_trace_attributes(
        api_key_uuid=key_details.api_key_uuid,
        api_key_name=key_details.api_key_name,
        group_uuid=key_details.group_uuid,
        group_name=key_details.group_name,
        project_uuid=route.project_uuid,
        project_name=route.project_name,
    )

    logger.debug('Chat completion request: %s', completion_create_params)
    request.state.otel_route_name = route_name

    client_host = request.client.host if request.client else 'unknown'
    logger.debug(
        'Received request: method=%s path=%s client=%s',
        request.method,
        request.url.path,
        client_host,
    )
    logger.debug('Received completion_create_params: %s', completion_create_params)
    messages = list(completion_create_params.get('messages'))
    logger.debug('Messages: %s', messages)

    tools = list(completion_create_params.get('tools') or [])
    logger.debug('Tools: %s', tools)

    tool_choice = completion_create_params.get('tool_choice', 'auto')
    known_keys = {'model', 'messages', 'tools', 'tool_choice'}
    extra_params = {
        key: value
        for key, value in completion_create_params.items()
        if key not in known_keys
    }
    logger.debug('Received params: %s', extra_params)

    logger.info('Invoked route name: %s', route_name)
    if not group_service.check_key_uuid_for_route(
        route_key, UUID(key_details.api_key_uuid)
    ):
        raise InvalidApiKey(f'API Key not associated with route {route_name}')

    ctx.project_uuid = route.project_uuid
    ctx.project_name = route.project_name

    if route.request_rate_limiter:
        set_operation_category(OperationCategory.LIMITING)
        await route.request_rate_limiter.check_and_count_request(
            request_uuid=request_uuid,
            api_key_uuid=key_details.api_key_uuid,
            group_uuid=key_details.group_uuid,
            api_key_name=key_details.api_key_name,
            group_name=key_details.group_name,
            project_uuid=route.project_uuid,
            project_name=route.project_name,
        )

    langchain_messages = convert_openai_messages(messages)
    if completion_create_params.get('stream'):
        prepared = await route.prepare_stream(
            request_uuid=request_uuid,
            api_key_uuid=key_details.api_key_uuid,
            api_key_name=key_details.api_key_name,
            messages=langchain_messages,
            route_name=route_name,
            tools=tools,
            tool_choice=tool_choice,
            group_uuid=key_details.group_uuid,
            group_name=key_details.group_name,
            **extra_params,
        )

        if route.has_output_guardrails():
            # Perform full buffering and checking BEFORE starting the stream response
            chunks, headers = await route.invoke_stream_buffered(
                prepared=prepared,
                request_uuid=request_uuid,
                api_key_uuid=key_details.api_key_uuid,
                api_key_name=key_details.api_key_name,
                route_name=route_name,
                tools=tools,
                tool_choice=tool_choice,
                group_uuid=key_details.group_uuid,
                group_name=key_details.group_name,
                **extra_params,
            )

            async def event_generator():
                for chunk in chunks:
                    chunk_json = chunk.model_dump_json(exclude_none=True)
                    logger.debug('Streaming chunk: %s', chunk_json)
                    yield f'data: {chunk_json}\n\n'
                logger.debug('Streaming finished (Buffered): [DONE]')
                yield 'data: [DONE]\n\n'

        else:
            # Standard streaming (Low Latency)
            headers = {}
            if prepared.guardrails_block_triggered:
                headers['X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED'] = 'true'
            if prepared.guardrails_input_triggered:
                headers['X-RB-AIGATEWAY-GUARDRAILS-WARN'] = 'true'
            if prepared.cached_response:
                headers['X-RB-AIGATEWAY-CACHE-HIT'] = 'true'

            async def event_generator():
                try:
                    async for chunk in route.invoke_stream(
                        prepared=prepared,
                        request_uuid=request_uuid,
                        api_key_uuid=key_details.api_key_uuid,
                        api_key_name=key_details.api_key_name,
                        route_name=route_name,
                        tools=tools,
                        tool_choice=tool_choice,
                        group_uuid=key_details.group_uuid,
                        group_name=key_details.group_name,
                        **extra_params,
                    ):
                        chunk_json = chunk.model_dump_json(exclude_none=True)
                        logger.debug('Streaming chunk: %s', chunk_json)
                        yield f'data: {chunk_json}\n\n'
                    logger.debug('Streaming finished: [DONE]')
                    yield 'data: [DONE]\n\n'
                except AppError as exc:
                    error_body = json.dumps(
                        {
                            'error': {
                                'message': exc.client_message,
                                'type': 'model_invoker_error',
                                'param': None,
                                'code': exc.status_code,
                            }
                        }
                    )
                    yield error_body, exc.status_code
                except Exception:
                    logger.exception('Unhandled error during streaming')
                    error_body = json.dumps(
                        {
                            'error': {
                                'message': 'Unhandled error during streaming',
                                'type': 'internal_error',
                                'param': None,
                                'code': 500,
                            }
                        }
                    )
                    yield error_body, 500

        set_operation_category(OperationCategory.ENDPOINT)
        return StreamingResponseWithStatusCode(
            event_generator(), media_type='text/event-stream', headers=headers
        )

    invoke_response = await route.invoke(
        request_uuid=request_uuid,
        api_key_uuid=key_details.api_key_uuid,
        api_key_name=key_details.api_key_name,
        messages=langchain_messages,
        route_name=route_name,
        tools=tools,
        tool_choice=tool_choice,
        group_uuid=key_details.group_uuid,
        group_name=key_details.group_name,
        **extra_params,
    )
    # Log the response we are about to send
    logger.info('Invoke response: %s', invoke_response.content)

    # Extract model name from response for metrics
    model_name = None
    try:
        if hasattr(invoke_response.content, 'model'):
            model_name = invoke_response.content.model
        elif isinstance(invoke_response.content, dict):
            model_name = invoke_response.content.get('model')
    except Exception:
        model_name = None

    # Set model name in request state for the decorator
    request.state.otel_model_name = model_name

    set_operation_category(OperationCategory.ENDPOINT)
    return JSONResponse(
        content=jsonable_encoder(invoke_response.content),
        headers=invoke_response.headers,
    )


# This endpoint must follow the openai standard
@app.post(
    '/v1/embeddings',
    response_model=CreateEmbeddingResponse,
    response_model_exclude_none=True,
)
@otel_metrics_decorator
@workflow(name='embeddings')
@ensure_endpoint_category
async def embeddings(
    request: Request,
    embedding_create_params: EmbeddingCreateParams,
    gateway_routes: dict[str, GatewayRoute] = Depends(get_ai_gateway_dependency),
    request_uuid: str = Depends(set_request_uuid),
):
    route_key = embedding_create_params.get('model')
    route = gateway_routes.get(route_key)

    _set_early_project_trace_attributes(route_key, route)

    if route is None:
        raise GatewayBadRequest(
            f'The route name [{route_key}] was not found in the config'
        )
    route_name = route.gateway_route_config.route_name
    input_texts = embedding_create_params.get('input')

    # Mark the root workflow span with ENDPOINT category
    set_operation_category(OperationCategory.ENDPOINT)

    # Set early trace attributes
    set_trace_attributes(request_uuid=request_uuid, route_name=route_name)

    # Populate request event context first (before auth, so route_name is always captured)
    ctx = RequestEventContext.get_or_create(request)
    ctx.route_name = route_name
    ctx.is_streaming = False

    # Validate API key after context is populated
    set_operation_category(OperationCategory.AUTH)
    key_details = await set_api_key_uuid(
        request, route.project_uuid, route.project_name
    )

    # Set auth-related trace attributes
    set_trace_attributes(
        api_key_uuid=key_details.api_key_uuid,
        api_key_name=key_details.api_key_name,
        group_uuid=key_details.group_uuid,
        group_name=key_details.group_name,
        project_uuid=route.project_uuid,
        project_name=route.project_name,
    )

    if isinstance(input_texts, str):
        input_texts = [input_texts]

    if not group_service.check_key_uuid_for_route(
        route_key, UUID(key_details.api_key_uuid)
    ):
        raise InvalidApiKey('Incorrect API key provided.')

    ctx.project_uuid = route.project_uuid
    ctx.project_name = route.project_name

    # Check and count request rate limits BEFORE any processing
    if route.request_rate_limiter:
        await route.request_rate_limiter.check_and_count_request(
            request_uuid=request_uuid,
            api_key_uuid=key_details.api_key_uuid,
            group_uuid=key_details.group_uuid,
            api_key_name=key_details.api_key_name,
            group_name=key_details.group_name,
            project_uuid=route.project_uuid,
            project_name=route.project_name,
        )

    set_operation_category(OperationCategory.ENDPOINT)
    return await route.invoke_embeddings(
        request_uuid=request_uuid,
        api_key_uuid=key_details.api_key_uuid,
        api_key_name=key_details.api_key_name,
        route_name=route_name,
        input_texts=input_texts,
        group_uuid=key_details.group_uuid,
        group_name=key_details.group_name,
    )


# This endpoint follows the OpenAI Responses API standard (stateless Phase 1):
# https://platform.openai.com/docs/api-reference/responses
@app.post('/v1/responses')
@otel_metrics_decorator
@workflow(name='responses')
@ensure_endpoint_category
@reset_route_context
async def responses(
    request: Request,
    response_create_params: ResponseCreateParamsCustom,
    gateway_routes: dict[str, GatewayRoute] = Depends(get_ai_gateway_dependency),
    request_uuid: str = Depends(set_request_uuid),
):
    # Mark the root workflow span with ENDPOINT category
    set_operation_category(OperationCategory.ENDPOINT)

    if response_create_params.get('previous_response_id'):
        raise GatewayBadRequest(
            'previous_response_id is not supported by this gateway (stateless mode only)'
        )

    route_key = response_create_params.get('model', 'unknown')
    route = gateway_routes.get(route_key)

    _set_early_project_trace_attributes(route_key, route)

    if route is None:
        raise GatewayBadRequest(
            f'The route name [{route_key}] was not found in the config'
        )
    route_name = route.gateway_route_config.route_name
    # Publish the route config for per-route log filtering (cleared by the decorator).
    # Logged after resolution so the request dump is subject to that filtering.
    set_current_route_config(route.gateway_route_config)
    logger.debug('Responses API request: %s', response_create_params)
    request.state.otel_route_name = route_name

    # Set early trace attributes
    set_trace_attributes(request_uuid=request_uuid, route_name=route_name)

    ctx = RequestEventContext.get_or_create(request)
    ctx.route_name = route_name
    ctx.is_streaming = bool(response_create_params.get('stream'))

    set_operation_category(OperationCategory.AUTH)
    key_details = await set_api_key_uuid(
        request, route.project_uuid, route.project_name
    )

    # Set auth-related trace attributes
    set_trace_attributes(
        api_key_uuid=key_details.api_key_uuid,
        api_key_name=key_details.api_key_name,
        group_uuid=key_details.group_uuid,
        group_name=key_details.group_name,
        project_uuid=route.project_uuid,
        project_name=route.project_name,
    )

    instructions = response_create_params.get('instructions')
    raw_input = response_create_params.get('input', '')
    raw_tools = list(response_create_params.get('tools') or [])
    raw_tool_choice = response_create_params.get('tool_choice')
    is_stream = bool(response_create_params.get('stream'))

    # Translate to Chat Completions-compatible formats
    langchain_messages = input_to_langchain_messages(raw_input, instructions)
    tools = responses_tools_to_chat_completions_tools(raw_tools)
    tool_choice = translate_tool_choice(raw_tool_choice)

    # Build extra params (temperature, top_p, max_output_tokens → max_completion_tokens, …)
    known_keys = {
        'model',
        'input',
        'instructions',
        'tools',
        'tool_choice',
        'stream',
        'previous_response_id',
        'store',
        'stream_options',
        'background',
        'metadata',  # OpenAI-only, not a Chat Completions runtime param
    }
    extra_params = {
        key: value
        for key, value in response_create_params.items()
        if key not in known_keys and value is not None
    }
    # Map Responses API token limit param to the Chat Completions name
    if 'max_output_tokens' in extra_params:
        extra_params.setdefault(
            'max_completion_tokens', extra_params.pop('max_output_tokens')
        )
    # Inject stream_options so providers include usage in the final streaming chunk
    if is_stream:
        extra_params.setdefault('stream_options', {'include_usage': True})

    logger.info('Invoked route name (responses): %s', route_name)

    if not group_service.check_key_uuid_for_route(
        route_key, UUID(key_details.api_key_uuid)
    ):
        raise InvalidApiKey(f'API Key not associated with route {route_name}')

    ctx.project_uuid = route.project_uuid
    ctx.project_name = route.project_name

    if route.request_rate_limiter:
        set_operation_category(OperationCategory.LIMITING)
        await route.request_rate_limiter.check_and_count_request(
            request_uuid=request_uuid,
            api_key_uuid=key_details.api_key_uuid,
            group_uuid=key_details.group_uuid,
            api_key_name=key_details.api_key_name,
            group_name=key_details.group_name,
            project_uuid=route.project_uuid,
            project_name=route.project_name,
        )

    if is_stream:
        skeleton = build_skeleton_response(
            route_name=route_name,
            request_id=request_uuid,
            instructions=instructions,
            temperature=response_create_params.get('temperature'),
            top_p=response_create_params.get('top_p'),
            tool_choice=str(tool_choice) if isinstance(tool_choice, str) else 'auto',
        )

        prepared = await route.prepare_stream(
            request_uuid=request_uuid,
            api_key_uuid=key_details.api_key_uuid,
            api_key_name=key_details.api_key_name,
            messages=langchain_messages,
            route_name=route_name,
            tools=tools,
            tool_choice=tool_choice,
            group_uuid=key_details.group_uuid,
            group_name=key_details.group_name,
            **extra_params,
        )

        headers: dict[str, str] = {}

        if route.has_output_guardrails():
            chunks, headers = await route.invoke_stream_buffered(
                prepared=prepared,
                request_uuid=request_uuid,
                api_key_uuid=key_details.api_key_uuid,
                api_key_name=key_details.api_key_name,
                route_name=route_name,
                tools=tools,
                tool_choice=tool_choice,
                group_uuid=key_details.group_uuid,
                group_name=key_details.group_name,
                **extra_params,
            )

            async def event_generator_buffered():
                async for sse_line in list_chunks_to_response_events(chunks, skeleton):
                    yield sse_line
                yield 'data: [DONE]\n\n'

            set_operation_category(OperationCategory.ENDPOINT)
            return StreamingResponse(
                event_generator_buffered(),
                media_type='text/event-stream',
                headers=headers,
            )

        if prepared.guardrails_block_triggered:
            headers['X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED'] = 'true'
        if prepared.cached_response:
            headers['X-RB-AIGATEWAY-CACHE-HIT'] = 'true'

        async def event_generator():
            async for sse_line in chat_chunks_to_response_events(
                route.invoke_stream(
                    prepared=prepared,
                    request_uuid=request_uuid,
                    api_key_uuid=key_details.api_key_uuid,
                    api_key_name=key_details.api_key_name,
                    route_name=route_name,
                    tools=tools,
                    tool_choice=tool_choice,
                    group_uuid=key_details.group_uuid,
                    group_name=key_details.group_name,
                    **extra_params,
                ),
                skeleton,
            ):
                yield sse_line
            yield 'data: [DONE]\n\n'

        set_operation_category(OperationCategory.ENDPOINT)
        return StreamingResponse(
            event_generator(),
            media_type='text/event-stream',
            headers=headers,
        )

    # Non-streaming path
    invoke_response = await route.invoke(
        request_uuid=request_uuid,
        api_key_uuid=key_details.api_key_uuid,
        api_key_name=key_details.api_key_name,
        messages=langchain_messages,
        route_name=route_name,
        tools=tools,
        tool_choice=tool_choice,
        group_uuid=key_details.group_uuid,
        group_name=key_details.group_name,
        **extra_params,
    )

    response_obj = chat_completion_to_response(invoke_response.content, route_name)
    set_operation_category(OperationCategory.ENDPOINT)
    return JSONResponse(
        content=jsonable_encoder(response_obj),
        headers=invoke_response.headers,
    )


# mount static files application (https://fastapi.tiangolo.com/tutorial/static-files/)
if os.path.isdir('static'):
    templates = Jinja2Templates(directory='static')

    app.mount('/assets', StaticFiles(directory='static/assets'), name='static')

    @app.get('/{rest_of_path:path}')
    async def react_app(req: Request, rest_of_path: str):
        # Return 404 for unmatched API routes
        if rest_of_path.startswith(('public/api/', 'v1/')):
            raise HTTPException(status_code=404, detail='Not Found')
        return templates.TemplateResponse(req, 'index.html')
