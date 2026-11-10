import asyncio
from contextlib import asynccontextmanager, suppress
import logging.config
import os
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from httpx_aiohttp import HttpxAiohttpClient
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import start_http_server
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp
from traceloop.sdk import Traceloop

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
from radicalbit_ai_gateway.endpoints.chat_completions.route import ChatCompletionsRoute
from radicalbit_ai_gateway.endpoints.common.admission import Admission
from radicalbit_ai_gateway.endpoints.decision.route import DecisionRoute
from radicalbit_ai_gateway.endpoints.embeddings.route import EmbeddingsRoute
from radicalbit_ai_gateway.endpoints.mcp.route import McpRoute
from radicalbit_ai_gateway.endpoints.messages.errors import with_messages_error_shapes
from radicalbit_ai_gateway.endpoints.messages.route import MessagesRoute
from radicalbit_ai_gateway.endpoints.responses.route import ResponsesRoute
from radicalbit_ai_gateway.endpoints.transcriptions.route import TranscriptionsRoute
from radicalbit_ai_gateway.events.events_processor import set_alert_dispatcher
from radicalbit_ai_gateway.gateway_route.factory import build_project_route_registrar
from radicalbit_ai_gateway.limiter.storage.shared import close_limit_storage
from radicalbit_ai_gateway.llm.tracing import TRACELOOP_INSTRUMENTS
from radicalbit_ai_gateway.mcp_proxy.upstream_client import McpUpstreamClient
from radicalbit_ai_gateway.middleware.request_event_middleware import (
    RequestEventMiddleware,
)
from radicalbit_ai_gateway.models.project_dto import ProjectOut
from radicalbit_ai_gateway.plugins.loader import discover_plugins, init_plugins
from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.routes.alert_rule_route import AlertRuleRoute
from radicalbit_ai_gateway.routes.configs_route import ConfigsRoute, ConfigsRouteConfig
from radicalbit_ai_gateway.routes.dashboard_route import DashboardRoute
from radicalbit_ai_gateway.routes.group_route import GroupRoute
from radicalbit_ai_gateway.routes.key_route import KeyRoute
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
    GatewayError,
    GuardrailError,
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
from radicalbit_ai_gateway.utils.logging_hooks import apply_log_filters
from radicalbit_ai_gateway.utils.telemetry_hooks import get_exporter_wrappers

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
mcp_service = McpService(upstream_client=McpUpstreamClient())
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
app.include_router(McpRoute.get_mcp_router(mcp_service, admission))
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
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        # exc.errors() can contain raw exception objects (e.g. the ctx.error of
        # a model_validator that raised ValueError), which plain json.dumps
        # cannot serialize — jsonable_encoder handles those.
        content=jsonable_encoder({'detail': exc.errors(), 'body': body}),
    )


@app.get('/health')
async def health_check():
    return {
        'status': 'ok',
        'service': 'Radicalbit AI Gateway',
        'version': '0.1.0',
        'gateway_initialized': app.state.routes is not None,
    }


# Root-level like /v1/...: the OpenAI-compatible proxy endpoints. Included
# after /health and before the static catch-all, and the responses router last
# so its /v1/responses/{path:path} catch-all shadows none of the others.
app.include_router(ChatCompletionsRoute.get_chat_completions_router(admission))
app.include_router(EmbeddingsRoute.get_embeddings_router(admission))
app.include_router(TranscriptionsRoute.get_transcriptions_router(admission))
app.include_router(ResponsesRoute.get_responses_router(admission))
app.include_router(MessagesRoute.get_messages_router(admission))


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
