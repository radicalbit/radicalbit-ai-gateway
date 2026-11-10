"""The gateway the end-to-end tests drive: the FastAPI app on real routes,
built from a project config, with the providers faked at the transport.

``build_routes`` builds a project's routes as the gateway registers them.
``open_gateway`` serves them for one test: the caller is authenticated and a
member, the project has no budget, decision model retries do not wait, and
what the gateway emits (event rows, request events, HTTP metrics, the metrics
named, the route the log lines carry) is recorded on the ``Gateway`` it
yields. A test file keeps only its config, its scenarios and the views of
what was recorded that its golden values compare.
"""

from collections.abc import Iterable, Iterator
from contextlib import ExitStack, contextmanager
import logging
from typing import Any
from unittest.mock import MagicMock, patch

import anthropic
from fastapi.testclient import TestClient
import openai
import pook
from starlette.requests import Request

from tests.common import db_mock
from tests.common.audio import make_wav_bytes
from tests.common.provider_recorder import CannedResponse, ProviderRecorder

from radicalbit_ai_gateway import server
from radicalbit_ai_gateway.auth.api_key_validator import ApiKeyValidator
from radicalbit_ai_gateway.events import events_processor
from radicalbit_ai_gateway.guardrails.guardrails import Guardrails
from radicalbit_ai_gateway.guardrails.judges.decision_judge_engine import (
    DecisionJudgeEngine,
)
from radicalbit_ai_gateway.guardrails.judges.judge_engine import JudgeEngine
from radicalbit_ai_gateway.guardrails.presidio import PresidioEngine
from radicalbit_ai_gateway.invocation import decision_model_invoker
from radicalbit_ai_gateway.metrics import define_metrics
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.server import app, group_service, key_service
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.dependencies import get_request_uuid
from radicalbit_ai_gateway.utils.gateway_route_factory import (
    build_gateway_routes_from_config,
)
from radicalbit_ai_gateway.utils.request_context import current_route_config_ctx

LOGGER = get_app_config().log_config.logger_name
HEADERS = {'Authorization': f'Bearer {db_mock.PLAIN_KEY}'}
WAV = make_wav_bytes(1.0)
REQUEST_EVENT_EMIT = (
    'radicalbit_ai_gateway.middleware.request_event_middleware.emit_request_event'
)

# One engine for every route, as a gateway shares one across its projects: its
# analyzer is built on first use only.
_PRESIDIO = PresidioEngine()


def build_routes(
    config: dict | GatewayConfig,
    *,
    project_uuid: str = '',
    prompt_manager: PromptManager | None = None,
    cost_service: CostService | None = None,
) -> dict:
    """Build a project's routes from its config, keyed ``proj/<route>`` as the
    gateway serves them. The routes cache in memory (no Redis client).
    """
    if isinstance(config, dict):
        config = GatewayConfig.model_validate(config)
    cost_service = cost_service or CostService(
        chat_models_by_id=config.chat_models_by_id,
        embedding_models_by_id=config.embedding_models_by_id,
        transcription_models_by_id=config.transcription_models_by_id,
        decision_models_by_id=config.decision_models_by_id,
    )
    guardrails = Guardrails(
        presidio_engine=_PRESIDIO,
        judge_engine=JudgeEngine(
            prompt_manager=prompt_manager or MagicMock(spec_set=PromptManager)
        ),
        cost_service=cost_service,
        guardrails=config.guardrails,
        chat_models_by_id=config.chat_models_by_id,
        decision_judge_engine=DecisionJudgeEngine(
            decision_models=config.decision_models, cost_service=cost_service
        ),
    )
    routes = build_gateway_routes_from_config(
        config,
        guardrails,
        redis_client=None,
        cost_service=cost_service,
        httpx_client=None,
        project_uuid=project_uuid,
    )
    for route in routes.values():
        route.project_name = 'proj'
    return {f'proj/{name}': route for name, route in routes.items()}


def _mock_request_uuid(request: Request):
    request.state.request_uuid = str(db_mock.REQUEST_UUID)
    return str(db_mock.REQUEST_UUID)


class _RouteContext(logging.Filter):
    """Records the route each gateway log line is filtered on."""

    def __init__(self):
        super().__init__()
        self.routes: list[str | None] = []

    def filter(self, record: logging.LogRecord) -> bool:
        config = current_route_config_ctx.get()
        self.routes.append(config.route_name if config is not None else None)
        return True


class Gateway:
    """Sends requests to the app and keeps what each one caused.

    Each ``post`` starts the records afresh. With canned ``replies`` the
    providers are faked at the transport and must ask for every reply;
    ``upstream`` then holds their requests. With ``replies=None`` the request
    goes out as it is (for tests that mock providers otherwise).
    """

    text = 'Where is Paris?'
    embed_texts: tuple[str, ...] = ('Where is Paris?',)

    def __init__(self, client: TestClient, routes: dict | None, api_key, caplog):
        self.client = client
        self.routes = routes
        self.api_key = api_key
        self.caplog = caplog
        self.headers = dict(HEADERS)
        self.member = True
        self.event_rows: list[dict] = []
        self.request_events: list = []
        self.http_metrics: list[dict] = []
        self.metrics: list[tuple] = []
        self.route_context = _RouteContext()
        self.upstream: list[dict] = []

    def clear(self) -> None:
        self.event_rows.clear()
        self.request_events.clear()
        self.http_metrics.clear()
        self.metrics.clear()
        self.route_context.routes.clear()
        self.upstream = []

    def post(
        self,
        path: str,
        replies: list[CannedResponse] | None = None,
        key: bool = True,
        headers: dict | None = None,
        **kwargs,
    ):
        self.clear()
        headers = {**(self.headers if key else {}), **(headers or {})}
        if replies is None:
            return self.client.post(path, headers=headers, **kwargs)
        with ProviderRecorder(replies) as recorder:
            response = self.client.post(path, headers=headers, **kwargs)
        assert recorder.unused == 0, 'a canned reply was not asked for'
        self.upstream = recorder.requests
        return response

    def chat(self, replies=None, route='chat', text=None, key=True, **params):
        return self.post(
            '/v1/chat/completions',
            replies,
            key=key,
            json={
                'model': f'proj/{route}',
                'messages': [{'role': 'user', 'content': text or self.text}],
                **params,
            },
        )

    def responses(self, replies=None, route='chat', text=None, key=True, **params):
        return self.post(
            '/v1/responses',
            replies,
            key=key,
            json={'model': f'proj/{route}', 'input': text or self.text, **params},
        )

    def embed(self, replies=None, route='embed', texts=None, key=True):
        return self.post(
            '/v1/embeddings',
            replies,
            key=key,
            json={'model': f'proj/{route}', 'input': list(texts or self.embed_texts)},
        )

    def transcribe(
        self, replies=None, route='audio', stream=False, audio=WAV, key=True
    ):
        return self.post(
            '/v1/audio/transcriptions',
            replies,
            key=key,
            data={'model': f'proj/{route}', 'stream': str(stream).lower()},
            files={'file': ('a.wav', audio, 'audio/wav')},
        )

    def decide(self, replies=None, route='agent', ticket='printer on fire', key=True):
        return self.post(
            '/v1/systemone',
            replies,
            key=key,
            json={
                'model': f'proj/{route}',
                'state': {'ticket': ticket},
                'questions': {'urgent': {'type': 'noul', 'instructions': 'Urgent?'}},
            },
        )


@contextmanager
def open_gateway(
    routes: dict | None = None,
    *,
    caplog=None,
    metrics: Iterable[tuple[str, str]] = (),
    patches: Iterable[Any] = (),
    api_key=None,
    use_pook: bool = False,
    gateway_class: type[Gateway] = Gateway,
) -> Iterator[Gateway]:
    """Serve ``routes`` (when given) for the duration of the block.

    ``metrics`` names the ``define_metrics`` instruments and methods to record
    as ``(name, value, attributes)``; ``patches`` are started with the rest;
    ``use_pook`` turns pook on for tests that mock providers with it. With
    ``caplog``, the gateway logs at DEBUG.
    """
    api_key = api_key or db_mock.get_sample_key_with_group(
        group_uuid=db_mock.GROUP_UUID
    )
    gateway = gateway_class(TestClient(app), routes, api_key, caplog)

    def record(name):
        return lambda value, attributes: gateway.metrics.append(
            (name, value, dict(attributes))
        )

    with ExitStack() as stack:
        saved_overrides = dict(app.dependency_overrides)
        saved_validator = app.state.token_validator
        saved_routes = getattr(app.state, 'routes', None)
        stack.callback(setattr, app, 'dependency_overrides', saved_overrides)
        stack.callback(setattr, app.state, 'token_validator', saved_validator)
        if saved_routes is not None:
            stack.callback(setattr, app.state, 'routes', saved_routes)
        app.dependency_overrides[get_request_uuid] = _mock_request_uuid
        app.state.token_validator = ApiKeyValidator(key_service=key_service)
        if routes is not None:
            app.state.routes = routes
        for patcher in [
            patch.object(key_service, 'get_key_by_hashed_key', return_value=api_key),
            patch.object(
                group_service,
                'check_key_uuid_for_route',
                side_effect=lambda *_: gateway.member,
            ),
            patch.object(
                server.project_budget_limit_dao, 'get_by_project_uuid', return_value=[]
            ),
            patch.object(
                events_processor._events_buffer,
                'add',
                side_effect=gateway.event_rows.append,
            ),
            patch(REQUEST_EVENT_EMIT, side_effect=gateway.request_events.append),
            patch.object(
                define_metrics.total_requests_counter,
                'add',
                side_effect=lambda value, attributes: gateway.http_metrics.append(
                    dict(attributes)
                ),
            ),
            # The SDKs' own retries would ask for more canned replies.
            patch.object(
                openai._base_client.BaseClient, '_should_retry', return_value=False
            ),
            patch.object(
                anthropic._base_client.BaseClient, '_should_retry', return_value=False
            ),
            # Decision model retries are made, without the wait between them.
            patch.object(decision_model_invoker, 'BACKOFF_BASE_SECONDS', 0),
            *(
                patch.object(
                    getattr(define_metrics, name), method, side_effect=record(name)
                )
                for name, method in metrics
            ),
            *patches,
        ]:
            stack.enter_context(patcher)
        logger = logging.getLogger(LOGGER)
        logger.addFilter(gateway.route_context)
        stack.callback(logger.removeFilter, gateway.route_context)
        if caplog is not None:
            caplog.set_level(logging.DEBUG, logger=LOGGER)
        if use_pook:
            pook.on()
            # The TestClient talks httpx too: let only its own host through.
            pook.enable_network('testserver')
            stack.callback(pook.disable_network)
            stack.callback(pook.off)
        yield gateway
