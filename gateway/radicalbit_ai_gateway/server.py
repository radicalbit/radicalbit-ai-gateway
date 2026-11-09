import asyncio
from contextlib import asynccontextmanager, suppress
import logging.config
import os
from typing import Annotated
from urllib.parse import urlparse
from uuid import UUID

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from httpx_aiohttp import HttpxAiohttpClient
from openai.types import CreateEmbeddingResponse
from openai.types.embedding_create_params import EmbeddingCreateParams
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import start_http_server
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp
from traceloop.sdk import Traceloop

from radicalbit_ai_gateway.ai_gateway import GatewayRoute
from radicalbit_ai_gateway.alerting.alert_dispatch import AlertDispatcher
from radicalbit_ai_gateway.alerting.alert_store import build_alert_store
from radicalbit_ai_gateway.alerting.alert_window_scheduler import (
    run_alert_window_scheduler,
)
from radicalbit_ai_gateway.auth.api_key_validator import ApiKeyValidator
from radicalbit_ai_gateway.db.clickhouse_database import ClickHouseDatabase
from radicalbit_ai_gateway.db.dao.alert_dao import AlertDAO
from radicalbit_ai_gateway.db.dao.alert_rule_dao import AlertRuleDAO
from radicalbit_ai_gateway.db.dao.event_dao import EventDAO
from radicalbit_ai_gateway.db.dao.group_dao import GroupDAO
from radicalbit_ai_gateway.db.dao.group_route_dao import GroupRouteDAO
from radicalbit_ai_gateway.db.dao.key_dao import KeyDAO
from radicalbit_ai_gateway.db.dao.key_limit_dao import KeyLimitDAO
from radicalbit_ai_gateway.db.dao.otel_traces_dao import OtelTracesDAO
from radicalbit_ai_gateway.db.dao.project_budget_limit_dao import ProjectBudgetLimitDAO
from radicalbit_ai_gateway.db.dao.project_config_dao import ProjectConfigDAO
from radicalbit_ai_gateway.db.dao.project_dao import ProjectDAO
from radicalbit_ai_gateway.db.dao.request_event_dao import RequestEventDAO
from radicalbit_ai_gateway.db.database import Database
from radicalbit_ai_gateway.events.events_processor import set_alert_dispatcher
from radicalbit_ai_gateway.limiter.storage.shared import close_limit_storage
from radicalbit_ai_gateway.llm.tracing import TRACELOOP_INSTRUMENTS
from radicalbit_ai_gateway.mcp_proxy.upstream_client import McpUpstreamClient
from radicalbit_ai_gateway.messages.errors import with_messages_error_shapes
from radicalbit_ai_gateway.messages.request import MessageCreateParams
from radicalbit_ai_gateway.messages.serving import (
    anthropic_headers,
    serve_messages_stream,
)
from radicalbit_ai_gateway.middleware.request_event_context import RequestEventContext
from radicalbit_ai_gateway.middleware.request_event_middleware import (
    RequestEventMiddleware,
)
from radicalbit_ai_gateway.models.project_dto import ProjectOut
from radicalbit_ai_gateway.pipeline import (
    chat as chat_pipeline,
    embeddings as embeddings_pipeline,
    messages as messages_pipeline,
    responses as responses_pipeline,
    transcription as transcription_pipeline,
)
from radicalbit_ai_gateway.pipeline.admission import Admission
from radicalbit_ai_gateway.pipeline.chat import ChatRequest
from radicalbit_ai_gateway.pipeline.http import endpoint, sse_response
from radicalbit_ai_gateway.pipeline.transcription import Audio
from radicalbit_ai_gateway.plugins.loader import discover_plugins, init_plugins
from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.responses.serving import serve_stream
from radicalbit_ai_gateway.routes.alert_rule_route import AlertRuleRoute
from radicalbit_ai_gateway.routes.configs_route import ConfigsRoute, ConfigsRouteConfig
from radicalbit_ai_gateway.routes.dashboard_route import DashboardRoute
from radicalbit_ai_gateway.routes.decision_route import DecisionRoute
from radicalbit_ai_gateway.routes.group_route import GroupRoute
from radicalbit_ai_gateway.routes.key_route import KeyRoute
from radicalbit_ai_gateway.routes.mcp_route import McpRoute
from radicalbit_ai_gateway.routes.project_route import ProjectRoute, ProjectRouteConfig
from radicalbit_ai_gateway.routes.secrets_route import SecretsRoute, SecretsRouteConfig
from radicalbit_ai_gateway.routes.tag_route import TagRoute
from radicalbit_ai_gateway.routes.tracing_route import TracingRoute
from radicalbit_ai_gateway.routes.usage_route import UsageRoute
from radicalbit_ai_gateway.services.alert_rule_service import AlertRuleService
from radicalbit_ai_gateway.services.api_key_security import ApiKeySecurity
from radicalbit_ai_gateway.services.config_generator_service import (
    ConfigGeneratorService,
)
from radicalbit_ai_gateway.services.email_service import EmailService
from radicalbit_ai_gateway.services.event_service import EventService
from radicalbit_ai_gateway.services.group_service import GroupService
from radicalbit_ai_gateway.services.key_service import KeyService
from radicalbit_ai_gateway.services.mcp_service import McpService
from radicalbit_ai_gateway.services.mcp_usage_service import McpUsageService
from radicalbit_ai_gateway.services.project_service import ProjectService
from radicalbit_ai_gateway.services.request_event_service import RequestEventService
from radicalbit_ai_gateway.services.secret_service import SecretService
from radicalbit_ai_gateway.services.tracing_service import TracingService
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.dependencies import (
    get_gateway_routes,
    get_request_uuid,
)
from radicalbit_ai_gateway.utils.endpoint_helpers import (
    resolve_request_limits,
    set_anthropic_api_key_uuid,
    set_early_project_trace_attributes,
)
from radicalbit_ai_gateway.utils.exceptions import (
    AlertRuleInternalError,
    AlertRuleInvalidEventError,
    AlertRuleInvalidTargetError,
    AlertRuleNotFoundError,
    AlertRuleUnsupportedTimeAggregationError,
    ApiKeyError,
    AudioDurationLimitExceeded,
    AuthRegistryError,
    BudgetLimitExceeded,
    GatewayBadRequest,
    GatewayError,
    GatewayNotFoundError,
    GuardrailError,
    InvalidApiKey,
    JudgeInternalError,
    McpTransportError,
    ModelInvokerError,
    RequestRateLimitExceeded,
    SecretsBackendError,
    TokenLimitExceeded,
    alert_rule_exception_handler,
    api_key_exception_handler,
    audio_duration_limit_exceeded_handler,
    auth_registry_exception_handler,
    budget_limiter_exception_handler,
    gateway_exception_handler,
    guardrail_exception_handler,
    judge_exception_handler,
    mcp_transport_exception_handler,
    model_invoker_exception_handler,
    rate_limit_exceeded_handler,
    secrets_backend_exception_handler,
    token_limiter_exception_handler,
    unhandled_exception_handler,
    validation_error_param,
)
from radicalbit_ai_gateway.utils.gateway_route_factory import (
    build_project_route_registrar,
)
from radicalbit_ai_gateway.utils.logging_hooks import apply_log_filters
from radicalbit_ai_gateway.utils.open_ai_types import (
    CompletionCreateParams,
    ResponseCreateParamsCustom,
    TranscriptionCreateParamsCustom,
)
from radicalbit_ai_gateway.utils.request_context import (
    get_current_request_tags,
    set_current_route_config,
)
from radicalbit_ai_gateway.utils.streaming_response import (
    StreamingResponseWithStatusCode,
)
from radicalbit_ai_gateway.utils.telemetry_hooks import get_exporter_wrappers
from radicalbit_ai_gateway.utils.trace_attributes import (
    OperationCategory,
    in_request_trace,
    set_operation_category,
    set_trace_attributes,
)

app_config = get_app_config()
logging_config_dict = app_config.log_config.model_dump()
logging.config.dictConfig(logging_config_dict)
logger = logging.getLogger(app_config.log_config.logger_name)

CHAT_FIELDS = {'model', 'messages', 'tools', 'tool_choice'}

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
key_limit_dao = KeyLimitDAO(database)
group_dao = GroupDAO(database)
group_route_dao = GroupRouteDAO(database)
project_dao = ProjectDAO(database)
project_config_dao = ProjectConfigDAO(database)
project_budget_limit_dao = ProjectBudgetLimitDAO(database)
event_dao = EventDAO(ch_database)
request_event_dao = RequestEventDAO(ch_database)
otel_traces_dao = OtelTracesDAO(ch_database)
api_key_security = ApiKeySecurity()

project_configs: dict = {}
key_service = KeyService(
    key_dao=key_dao,
    api_key_security=api_key_security,
    group_dao=group_dao,
    key_limit_dao=key_limit_dao,
)
group_service = GroupService(
    group_dao=group_dao,
    group_route_dao=group_route_dao,
    key_service=key_service,
    project_configs=project_configs,
)
project_service = ProjectService(
    project_dao=project_dao,
    project_config_dao=project_config_dao,
    project_budget_limit_dao=project_budget_limit_dao,
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
mcp_service = McpService(
    upstream_client=McpUpstreamClient(),
    group_service=group_service,
)
mcp_usage_service = McpUsageService(
    event_dao=event_dao,
    key_service=key_service,
    group_service=group_service,
)
secret_service = SecretService(project_config_dao=project_config_dao)

alert_rule_dao = AlertRuleDAO(database)
alert_rule_service = AlertRuleService(
    alert_rule_dao=alert_rule_dao,
    project_configs=project_configs,
    project_dao=project_dao,
    key_dao=key_dao,
    project_budget_limit_dao=project_budget_limit_dao,
    key_limit_dao=key_limit_dao,
    alert_dao=AlertDAO(ch_database),
)
alert_dispatcher = AlertDispatcher(
    alert_rule_dao=alert_rule_dao,
    email_service=EmailService(),
    store=build_alert_store(app_config.redis_config.redis_url),
)
set_alert_dispatcher(alert_dispatcher)
admission = Admission(group_service, project_budget_limit_dao)


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

    alert_window_scheduler = asyncio.create_task(
        run_alert_window_scheduler(
            alert_dispatcher.close_windows,
            app_config.alert_config.alert_window_tick_seconds,
        )
    )

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
        return BatchSpanProcessor(exporter)

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
            instruments=TRACELOOP_INSTRUMENTS,
        )
    logger.info('AI Gateway initialized successfully')
    yield
    logger.info('Shutting down AI Gateway')
    alert_window_scheduler.cancel()
    with suppress(asyncio.CancelledError):
        await alert_window_scheduler
    database.reset_connection()
    ch_database.reset_connection()
    await httpx_aiohttp_client.aclose()
    await close_limit_storage()
    server.shutdown()


class GatewayApp(FastAPI):
    """The gateway's FastAPI app.

    Every exception handler answers ``/v1/messages`` in the Messages API shape,
    plugins' handlers included. The handlers are wrapped when the middleware
    stack is built, at the first request: a handler added later has no effect
    anyway, so none is missed.
    """

    def build_middleware_stack(self) -> ASGIApp:
        handlers = self.exception_handlers
        self.exception_handlers = with_messages_error_shapes(handlers)
        try:
            return super().build_middleware_stack()
        finally:
            self.exception_handlers = handlers


app = GatewayApp(
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
        mcp_usage_service=mcp_usage_service,
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
app.include_router(
    ConfigsRoute.get_configs_router(
        project_service,
        config=getattr(app.state, 'configs_route_config', ConfigsRouteConfig()),
    ),
    prefix=prefix,
)
app.include_router(
    UsageRoute.get_usage_router(
        event_service=event_service,
        project_service=project_service,
        mcp_usage_service=mcp_usage_service,
    ),
    prefix=prefix,
)
app.include_router(
    TagRoute.get_tag_router(
        request_event_service=request_event_service,
        project_service=project_service,
    ),
    prefix=prefix,
)
app.include_router(
    SecretsRoute.get_secrets_router(
        secret_service,
        config=getattr(app.state, 'secrets_route_config', SecretsRouteConfig()),
    ),
    prefix=prefix,
)

# exception_handler
app.add_exception_handler(Exception, unhandled_exception_handler)
app.add_exception_handler(RequestRateLimitExceeded, rate_limit_exceeded_handler)
app.add_exception_handler(TokenLimitExceeded, token_limiter_exception_handler)
app.add_exception_handler(
    AudioDurationLimitExceeded, audio_duration_limit_exceeded_handler
)
app.add_exception_handler(GatewayError, gateway_exception_handler)
app.add_exception_handler(ModelInvokerError, model_invoker_exception_handler)
app.add_exception_handler(ApiKeyError, api_key_exception_handler)
app.add_exception_handler(GuardrailError, guardrail_exception_handler)
app.add_exception_handler(JudgeInternalError, judge_exception_handler)
app.add_exception_handler(BudgetLimitExceeded, budget_limiter_exception_handler)
app.add_exception_handler(AuthRegistryError, auth_registry_exception_handler)
app.add_exception_handler(McpTransportError, mcp_transport_exception_handler)
app.add_exception_handler(AlertRuleNotFoundError, alert_rule_exception_handler)
app.add_exception_handler(AlertRuleInvalidEventError, alert_rule_exception_handler)
app.add_exception_handler(AlertRuleInvalidTargetError, alert_rule_exception_handler)
app.add_exception_handler(
    AlertRuleUnsupportedTimeAggregationError, alert_rule_exception_handler
)
app.add_exception_handler(AlertRuleInternalError, alert_rule_exception_handler)
app.add_exception_handler(SecretsBackendError, secrets_backend_exception_handler)
app.include_router(KeyRoute.get_key_router(key_service), prefix=prefix)
app.include_router(
    AlertRuleRoute.get_alert_rule_router(alert_rule_service), prefix=prefix
)
# Root-level like /v1/... (NOT under /public/api/v1): inbound MCP proxy.
app.include_router(McpRoute.get_mcp_router(mcp_service))
# Root-level like /v1/...: Typesafe's decision endpoint, passed through.
app.include_router(DecisionRoute.get_decision_router(admission))
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
    # Messages API clients get theirs in Anthropic's format: see GatewayApp.
    if request.url.path.startswith('/v1/responses'):
        # Responses API clients read errors in OpenAI's format.
        first = exc.errors()[0] if exc.errors() else {}
        param = validation_error_param(first) or None
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                'error': {
                    'message': f'Invalid value for {param}: {first.get("msg")}'
                    if param
                    else 'Invalid request body',
                    'type': 'invalid_request_error',
                    'param': param,
                    'code': first.get('type'),
                }
            },
        )
    try:
        body = (await request.body()).decode()
    except RuntimeError:
        # Multipart/form requests (e.g. /v1/audio/transcriptions) have
        # already consumed the body stream by the time validation fails.
        body = ''
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        # exc.errors() can contain raw exception objects (e.g. the ctx.error of
        # a model_validator that raised ValueError), which plain json.dumps
        # cannot serialize — jsonable_encoder handles those.
        content=jsonable_encoder({'detail': exc.errors(), 'body': body}),
    )


async def get_ai_gateway_dependency(request: Request):
    return await get_gateway_routes(request)


@app.get('/health')
async def health_check():
    return {
        'status': 'ok',
        'service': 'Radicalbit AI Gateway',
        'version': '0.1.0',
        'gateway_initialized': app.state.routes is not None,
    }


def _log_chat_request(
    request: Request, params: CompletionCreateParams, route_name: str
) -> None:
    logger.debug('Chat completion request: %s', params)
    client_host = request.client.host if request.client else 'unknown'
    logger.debug(
        'Received request: method=%s path=%s client=%s',
        request.method,
        request.url.path,
        client_host,
    )
    logger.debug('Received completion_create_params: %s', params)
    logger.debug('Messages: %s', list(params.get('messages')))
    logger.debug('Tools: %s', list(params.get('tools') or []))
    logger.debug(
        'Received params: %s',
        {k: v for k, v in params.items() if k not in CHAT_FIELDS},
    )
    logger.info('Invoked route name: %s', route_name)


# This endpoint must follow the openai standard
# https://platform.openai.com/docs/api-reference/chat/create
@app.post('/v1/chat/completions')
@endpoint('chat_completions')
async def chat_completions(
    request: Request,
    completion_create_params: CompletionCreateParams,
    gateway_routes: dict[str, GatewayRoute] = Depends(get_ai_gateway_dependency),
    request_uuid: str = Depends(get_request_uuid),
):
    scope = await admission.admit(
        request,
        gateway_routes,
        completion_create_params.get('model', 'unknown'),
        request_uuid,
        streaming=bool(completion_create_params.get('stream')),
        announce=lambda route_name: _log_chat_request(
            request, completion_create_params, route_name
        ),
    )
    chat = ChatRequest.of(completion_create_params)
    if chat.stream:
        items = await chat_pipeline.stream(scope, chat)
        buffered = scope.route.guardrails.has_output
        return sse_response(
            items,
            scope.headers(),
            done_log='Streaming finished (Buffered): [DONE]'
            if buffered
            else 'Streaming finished: [DONE]',
        )

    completion = await chat_pipeline.complete(scope, chat)
    logger.info('Invoke response: %s', completion)
    request.state.otel_model_name = completion.model
    set_operation_category(OperationCategory.ENDPOINT)
    return JSONResponse(content=jsonable_encoder(completion), headers=scope.headers())


# This endpoint must follow the openai standard
@app.post(
    '/v1/embeddings',
    response_model=CreateEmbeddingResponse,
    response_model_exclude_none=True,
)
@endpoint('embeddings')
async def embeddings(
    request: Request,
    embedding_create_params: EmbeddingCreateParams,
    gateway_routes: dict[str, GatewayRoute] = Depends(get_ai_gateway_dependency),
    request_uuid: str = Depends(get_request_uuid),
):
    scope = await admission.admit(
        request, gateway_routes, embedding_create_params.get('model'), request_uuid
    )
    input_texts = embedding_create_params.get('input')
    if isinstance(input_texts, str):
        input_texts = [input_texts]

    set_operation_category(OperationCategory.ENDPOINT)
    return await embeddings_pipeline.embed(scope, input_texts)


@app.post('/v1/audio/transcriptions')
@endpoint('audio_transcriptions')
async def audio_transcriptions(
    request: Request,
    transcription_params: Annotated[TranscriptionCreateParamsCustom, Form()],
    gateway_routes: dict[str, GatewayRoute] = Depends(get_ai_gateway_dependency),
    request_uuid: str = Depends(get_request_uuid),
):
    scope = await admission.admit(
        request,
        gateway_routes,
        transcription_params.model,
        request_uuid,
        streaming=transcription_params.stream,
    )
    file = transcription_params.file
    audio = Audio(
        content=await file.read(),
        filename=file.filename or 'audio',
        content_type=file.content_type,
        language=transcription_params.language,
        prompt=transcription_params.prompt,
        temperature=transcription_params.temperature,
        response_format=transcription_params.response_format,
    )
    set_operation_category(OperationCategory.ENDPOINT)
    if transcription_params.stream:
        return sse_response(
            await transcription_pipeline.stream(scope, audio),
            item_log='Streaming transcription event: %s',
            error_log='Unhandled error during transcription streaming',
        )
    result = await transcription_pipeline.transcribe(scope, audio)
    return JSONResponse(content=jsonable_encoder(result))


# This endpoint follows the OpenAI Responses API standard:
# https://platform.openai.com/docs/api-reference/responses
# A request is served by a model that serves the Responses API, as the client
# sent it once the route's policies applied.
@app.post('/v1/responses')
@endpoint('responses')
async def responses(
    request: Request,
    response_create_params: ResponseCreateParamsCustom,
    gateway_routes: dict[str, GatewayRoute] = Depends(get_ai_gateway_dependency),
    request_uuid: str = Depends(get_request_uuid),
):
    def announce(route_name: str) -> None:
        logger.debug('Responses API request: %s', response_create_params)
        logger.info('Invoked route name (responses): %s', route_name)

    is_stream = bool(response_create_params.get('stream'))
    scope = await admission.admit(
        request,
        gateway_routes,
        response_create_params.get('model', 'unknown'),
        request_uuid,
        streaming=is_stream,
        announce=announce,
    )
    # The request as the client sent it: the gateway's policies apply to it,
    # then it goes upstream.
    body = await request.json()

    if is_stream:
        frames = await responses_pipeline.stream(scope, body)
        set_operation_category(OperationCategory.ENDPOINT)
        return StreamingResponseWithStatusCode(
            in_request_trace(serve_stream(frames)),
            media_type='text/event-stream',
            headers=scope.headers(),
        )

    response = await responses_pipeline.respond(scope, body)
    set_operation_category(OperationCategory.ENDPOINT)
    return JSONResponse(content=response, headers=scope.headers())


# The Responses API endpoints the gateway does not serve yet: those on stored
# responses (retrieve, delete, cancel, input_items), compact and input_tokens.
@app.api_route('/v1/responses/{path:path}', methods=['GET', 'POST', 'DELETE'])
async def responses_unsupported(request: Request, path: str):
    raise GatewayNotFoundError(
        f'{request.method} /v1/responses/{path} is not supported by the gateway yet'
    )


# This endpoint follows the Anthropic Messages API:
# https://docs.claude.com/en/api/messages
# A request is served by a model that serves the Messages API, as the client
# sent it with only `model` swapped. It is never translated.
@app.post('/v1/messages')
@endpoint('messages')
async def messages(
    request: Request,
    message_create_params: MessageCreateParams,
    gateway_routes: dict[str, GatewayRoute] = Depends(get_ai_gateway_dependency),
    request_uuid: str = Depends(get_request_uuid),
):
    # Mark the root workflow span with ENDPOINT category
    set_operation_category(OperationCategory.ENDPOINT)

    route_key = message_create_params['model']
    route = gateway_routes.get(route_key)

    set_early_project_trace_attributes(request, route_key, route)

    if route is None:
        raise GatewayBadRequest(
            f'The route name [{route_key}] was not found in the config'
        )
    route_name = route.gateway_route_config.route_name
    # Publish the route config for per-route log filtering (cleared by the decorator).
    set_current_route_config(route.gateway_route_config)
    request.state.otel_route_name = route_name

    set_trace_attributes(
        request_uuid=request_uuid,
        route_name=route_name,
        tags=list(get_current_request_tags()),
    )

    is_stream = bool(message_create_params.get('stream'))
    ctx = RequestEventContext.get_or_create(request)
    ctx.route_name = route_name
    ctx.is_streaming = is_stream

    set_operation_category(OperationCategory.AUTH)
    key_details = await set_anthropic_api_key_uuid(
        request, route.project_uuid, route.project_name
    )

    set_trace_attributes(
        api_key_uuid=key_details.api_key_uuid,
        api_key_name=key_details.api_key_name,
        group_uuid=key_details.group_uuid,
        group_name=key_details.group_name,
        project_uuid=route.project_uuid,
        project_name=route.project_name,
        tags=list(get_current_request_tags()),
    )

    # The request as the client sent it, unknown fields included.
    body = await request.json()

    logger.info('Invoked route name (messages): %s', route_name)

    if not group_service.check_key_uuid_for_route(
        route_key, UUID(key_details.api_key_uuid)
    ):
        raise InvalidApiKey(f'API Key not associated with route {route_name}')

    ctx.project_uuid = route.project_uuid
    ctx.project_name = route.project_name
    # Routing charges its calls to the request's limits. Checking them goes
    # here, as on the Responses API: AG-1132.
    request_limits = await resolve_request_limits(
        route, key_details, request_uuid, project_budget_limit_dao
    )

    scope = route.for_request(request_limits.identity, request_limits)
    prepared = await messages_pipeline.prepare(
        scope, body, anthropic_headers(request.headers)
    )

    if is_stream:
        set_operation_category(OperationCategory.ENDPOINT)
        return StreamingResponseWithStatusCode(
            in_request_trace(
                serve_messages_stream(messages_pipeline.stream(scope, prepared))
            ),
            media_type='text/event-stream',
        )

    message = await messages_pipeline.respond(scope, prepared)
    set_operation_category(OperationCategory.ENDPOINT)
    return JSONResponse(content=message)


# The Messages API endpoints the gateway does not serve: count_tokens, batches.
@app.api_route(
    '/v1/messages/{path:path}',
    methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'],
)
async def messages_unsupported(request: Request, path: str):
    raise GatewayNotFoundError(
        f'{request.method} /v1/messages/{path} is not supported by the gateway'
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
