"""End-to-end tests for the three-step config loading pipeline:

  resolve_secrets_from_string()        # step 1 – YAML string → raw dict
      ↓
  GatewayConfig.model_validate()       # step 2 – raw dict → validated model
      ↓
  build_gateway_routes_from_config()   # step 3 – model → live GatewayRoute objects

These tests also verify that project routes are registered with the
``project_name/route_name`` key, and that the resulting GatewayRoute can be
invoked end-to-end.
"""

import contextlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import uuid

from langchain_core.messages import HumanMessage
from openai.types.chat.chat_completion import ChatCompletion
import pook
import pytest

from tests.common.db_mock import API_KEY_UUID, GROUP_UUID, REQUEST_UUID
from tests.common.mocked_build_openai_chat_completion import (
    to_mock_openai_chat_completion,
)

from radicalbit_ai_gateway.ai_gateway import GatewayRoute, InvokeResponse
from radicalbit_ai_gateway.guardrails.guardrail_engine import GuardrailEngine
from radicalbit_ai_gateway.guardrails.judges.judge_engine import JudgeEngine
from radicalbit_ai_gateway.guardrails.presidio import PresidioEngine
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.project_entry import ProjectEntry
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.gateway_route_factory import (
    build_gateway_routes_from_config,
    build_project_route_registrar,
)
from radicalbit_ai_gateway.utils.secrets import resolve_secrets_from_string

_PROJECT_UUID = '2f1c6d4e-0000-4000-8000-0000000000aa'

# Minimal config with a literal api_key (no !secret refs needed here —
# secret resolution is already covered in test_secrets.py).
_PROJECT_CONFIG_YAML = """\
chat_models:
  - model_id: openai-gpt4o
    model: openai/gpt-4o-mini
    credentials:
      api_key: sk-test-key
routes:
  my-route:
    chat_models:
      - openai-gpt4o
"""


# ---------------------------------------------------------------------------
# Step 1+2: resolve + validate
# ---------------------------------------------------------------------------


def test_resolve_and_validate_produces_gateway_config():
    """Steps 1 and 2: a YAML string becomes a fully-validated GatewayConfig."""
    resolved = resolve_secrets_from_string(_PROJECT_CONFIG_YAML)
    config = GatewayConfig.model_validate(resolved)

    assert 'my-route' in config.routes
    assert config.chat_models_by_id['openai-gpt4o'].model == 'openai/gpt-4o-mini'


# ---------------------------------------------------------------------------
# Step 3: build routes
# ---------------------------------------------------------------------------


def _make_guardrail_engine() -> GuardrailEngine:
    cost_service = MagicMock(spec_set=CostService)
    prompt_manager = MagicMock()
    return GuardrailEngine(
        presidio_engine=PresidioEngine(),
        judge_engine=JudgeEngine(prompt_manager=prompt_manager),
        cost_service=cost_service,
        guardrails=[],
    )


def test_build_gateway_routes_from_config_keys():
    """Step 3: route keys match the names declared in the config."""
    resolved = resolve_secrets_from_string(_PROJECT_CONFIG_YAML)
    config = GatewayConfig.model_validate(resolved)
    cost_service = MagicMock(spec_set=CostService)

    routes = build_gateway_routes_from_config(
        config,
        guardrail_engine=_make_guardrail_engine(),
        redis_client=None,
        cost_service=cost_service,
        httpx_client=None,
        project_uuid=_PROJECT_UUID,
    )

    assert set(routes.keys()) == {'my-route'}
    assert isinstance(routes['my-route'], GatewayRoute)


_PROJECT_CONFIG_WITH_LIMITS_YAML = """\
chat_models:
  - model_id: openai-gpt4o
    model: openai/gpt-4o-mini
    credentials:
      api_key: sk-test-key
routes:
  my-route:
    chat_models:
      - openai-gpt4o
    rate_limiting:
      max_requests: 10
      window_size: 1 minute
    token_limiting:
      input:
        max_token: 1000
      output:
        max_token: 500
    budget_limiting:
      max_budget: 5.0
"""


def _build_limited_routes(project_uuid: str):
    resolved = resolve_secrets_from_string(_PROJECT_CONFIG_WITH_LIMITS_YAML)
    config = GatewayConfig.model_validate(resolved)
    return build_gateway_routes_from_config(
        config,
        guardrail_engine=_make_guardrail_engine(),
        redis_client=None,
        cost_service=MagicMock(spec_set=CostService),
        httpx_client=None,
        project_uuid=project_uuid,
    )


def test_build_gateway_routes_scopes_every_limiter_by_project():
    """Step 3: the project reaches all four limiter windows.

    Route names are unique only within a project, so an unscoped key makes two
    projects declaring 'my-route' share one window.
    """
    project_uuid = '2f1c6d4e-0000-4000-8000-00000000000a'
    route = _build_limited_routes(project_uuid)['my-route']

    items = [
        route.request_rate_limiter.item,
        route.token_limiter.input_item,
        route.token_limiter.output_item,
        route.budget_limiter.item,
    ]
    assert all(item is not None for item in items)
    for item in items:
        assert item.project_uuid == project_uuid
        # The bare route name is what metrics, limit events and logs report.
        assert item.route_name == 'my-route'


def test_build_gateway_routes_gives_each_project_its_own_keys():
    """Two projects declaring the same route must not collide in storage."""
    routes_a = _build_limited_routes('2f1c6d4e-0000-4000-8000-00000000000a')
    routes_b = _build_limited_routes('2f1c6d4e-0000-4000-8000-00000000000b')

    def keys(routes):
        route = routes['my-route']
        limiter = route.request_rate_limiter.limiter
        return {
            limiter._build_key(item)
            for item in (
                route.request_rate_limiter.item,
                route.token_limiter.input_item,
                route.token_limiter.output_item,
                route.budget_limiter.item,
            )
        }

    keys_a, keys_b = keys(routes_a), keys(routes_b)
    assert len(keys_a) == 4
    assert keys_a.isdisjoint(keys_b)


_PROJECT_CONFIG_WITH_TRANSCRIPTION_YAML = """\
chat_models:
  - model_id: openai-gpt4o
    model: openai/gpt-4o-mini
    credentials:
      api_key: sk-test-key
transcription_models:
  - model_id: openai-whisper
    model: openai/whisper-1
    credentials:
      api_key: sk-test-key
routes:
  my-route:
    chat_models:
      - openai-gpt4o
    transcription_models:
      - openai-whisper
"""


def test_build_gateway_routes_from_config_resolves_transcription_models():
    """Step 3: a route's transcription_models resolve to Model instances on
    the GatewayRoute. No invoker is built yet (that's AG-891's job — this
    ticket, AG-896, only covers config schema + wiring).
    """
    resolved = resolve_secrets_from_string(_PROJECT_CONFIG_WITH_TRANSCRIPTION_YAML)
    config = GatewayConfig.model_validate(resolved)
    cost_service = MagicMock(spec_set=CostService)

    routes = build_gateway_routes_from_config(
        config,
        guardrail_engine=_make_guardrail_engine(),
        redis_client=None,
        cost_service=cost_service,
        httpx_client=None,
        project_uuid=_PROJECT_UUID,
    )

    route = routes['my-route']
    assert [m.model_id for m in route._transcription_models] == ['openai-whisper']
    # chat_invoker is unaffected by the new wiring
    assert route.chat_invoker is not None


def test_build_gateway_routes_from_config_wires_transcription_invoker():
    """A route with transcription_models gets a working transcription_invoker
    built from the resolved Model list.
    """
    resolved = resolve_secrets_from_string(_PROJECT_CONFIG_WITH_TRANSCRIPTION_YAML)
    config = GatewayConfig.model_validate(resolved)
    cost_service = MagicMock(spec_set=CostService)

    routes = build_gateway_routes_from_config(
        config,
        guardrail_engine=_make_guardrail_engine(),
        redis_client=None,
        cost_service=cost_service,
        httpx_client=None,
        project_uuid=_PROJECT_UUID,
    )

    route = routes['my-route']
    assert route.transcription_invoker is not None
    assert 'openai-whisper' in route.transcription_invoker.model_map


_PROJECT_CONFIG_TRANSCRIPTION_ONLY_ROUTE_YAML = """\
chat_models:
  - model_id: openai-gpt4o
    model: openai/gpt-4o-mini
    credentials:
      api_key: sk-test-key
transcription_models:
  - model_id: openai-whisper
    model: openai/whisper-1
    credentials:
      api_key: sk-test-key
routes:
  transcription-only-route:
    transcription_models:
      - openai-whisper
"""


def test_build_gateway_routes_from_config_transcription_only_route():
    """A route that references only transcription_models (no chat_models) is
    valid: it builds with no chat_invoker but a working transcription_invoker.
    """
    resolved = resolve_secrets_from_string(
        _PROJECT_CONFIG_TRANSCRIPTION_ONLY_ROUTE_YAML
    )
    config = GatewayConfig.model_validate(resolved)
    cost_service = MagicMock(spec_set=CostService)

    routes = build_gateway_routes_from_config(
        config,
        guardrail_engine=_make_guardrail_engine(),
        redis_client=None,
        cost_service=cost_service,
        httpx_client=None,
        project_uuid=_PROJECT_UUID,
    )

    route = routes['transcription-only-route']
    assert route.chat_invoker is None
    assert route.transcription_invoker is not None
    assert 'openai-whisper' in route.transcription_invoker.model_map


def test_build_gateway_routes_empty_config():
    """Step 3: an empty config produces an empty routes dict."""
    config = GatewayConfig.model_validate({'routes': {}, 'chat_models': []})
    routes = build_gateway_routes_from_config(
        config,
        guardrail_engine=_make_guardrail_engine(),
        redis_client=None,
        cost_service=MagicMock(spec_set=CostService),
        httpx_client=None,
        project_uuid=_PROJECT_UUID,
    )
    assert routes == {}


# ---------------------------------------------------------------------------
# Full pipeline: steps 1+2+3 + invocation with project prefix
# ---------------------------------------------------------------------------


@patch('radicalbit_ai_gateway.invocation.model_invoker.emit_event', autospec=True)
@pook.activate
@pytest.mark.asyncio
async def test_project_route_full_pipeline(mock_emit_event, fake_redis_client):
    """All three steps + route invocation via 'project_name/route_name'."""
    pook.enable_network()

    # Step 1
    resolved = resolve_secrets_from_string(_PROJECT_CONFIG_YAML)

    # Step 2
    config = GatewayConfig.model_validate(resolved)

    # Step 3 – build routes, then register with project prefix
    cost_service = MagicMock(spec_set=CostService)
    routes = build_gateway_routes_from_config(
        config,
        guardrail_engine=_make_guardrail_engine(),
        redis_client=None,
        cost_service=cost_service,
        httpx_client=None,
        project_uuid=_PROJECT_UUID,
    )

    project_name = 'my-project'
    app_routes = {}
    for route_name, route in routes.items():
        full_key = f'{project_name}/{route_name}'
        app_routes[full_key] = route

    full_route_name = 'my-project/my-route'
    assert full_route_name in app_routes

    # Invoke the route (mocking the OpenAI HTTP call with pook)
    mocked_response = to_mock_openai_chat_completion(content='Rome')
    pook.post(
        url='https://api.openai.com/v1/chat/completions',
        reply=200,
        response_json=mocked_response.model_dump_json(),
    )

    invoke_response = await app_routes[full_route_name].invoke(
        request_uuid=str(REQUEST_UUID),
        api_key_uuid=str(API_KEY_UUID),
        api_key_name='rb-key',
        messages=[HumanMessage(content='What is the capital of Italy?')],
        route_name='my-route',
        tools=[],
        tool_choice=None,
        group_uuid=str(GROUP_UUID),
        group_name='test-group',
    )

    assert isinstance(invoke_response, InvokeResponse)
    assert isinstance(invoke_response.content, ChatCompletion)
    assert invoke_response.content.choices[0].message.content == 'Rome'

    pook.disable_network()


# ---------------------------------------------------------------------------
# Per-project GuardrailEngine isolation
# ---------------------------------------------------------------------------

_PROJECT_A_YAML = """\
chat_models:
  - model_id: openai-gpt4o
    model: openai/gpt-4o-mini
    credentials:
      api_key: sk-test-key
guardrails:
  - name: pii-check
    type: STARTS_WITH
    parameters:
      type: CHECK
      values:
        - "bad-word-A"
routes:
  route-a:
    chat_models:
      - openai-gpt4o
    guardrails:
      - pii-check
"""

_PROJECT_B_YAML = """\
chat_models:
  - model_id: openai-gpt4o
    model: openai/gpt-4o-mini
    credentials:
      api_key: sk-test-key
guardrails:
  - name: pii-check
    type: STARTS_WITH
    parameters:
      type: CHECK
      values:
        - "bad-word-B"
routes:
  route-b:
    chat_models:
      - openai-gpt4o
    guardrails:
      - pii-check
"""


async def test_per_project_guardrail_engine_isolation():
    """Each project gets its own GuardrailEngine; same-named guardrails in different
    projects must not overwrite each other.
    """
    presidio_engine = PresidioEngine()
    judge_engine = MagicMock(spec_set=JudgeEngine)

    app_state = SimpleNamespace(
        presidio_engine=presidio_engine,
        judge_engine=judge_engine,
        redis_client=None,
        routes={},
        project_configs={},
    )
    app = SimpleNamespace(state=app_state)

    registrar, _deregistrar = build_project_route_registrar(app, httpx_client=None)
    await registrar('aaaa-aaaa', 'project-a', _PROJECT_A_YAML)
    await registrar('bbbb-bbbb', 'project-b', _PROJECT_B_YAML)

    engine_a = app.state.routes['project-a/route-a'].guardrail_engine
    engine_b = app.state.routes['project-b/route-b'].guardrail_engine

    assert engine_a is not engine_b

    guardrail_a = engine_a._guardrails_by_name['pii-check']
    guardrail_b = engine_b._guardrails_by_name['pii-check']

    assert guardrail_a.parameters.values == ['bad-word-A']
    assert guardrail_b.parameters.values == ['bad-word-B']


# ---------------------------------------------------------------------------
# Startup: load active project configs
# ---------------------------------------------------------------------------


def _make_app_state(**kwargs):
    return SimpleNamespace(
        presidio_engine=PresidioEngine(),
        judge_engine=MagicMock(spec_set=JudgeEngine),
        redis_client=None,
        routes={},
        project_configs={},
        **kwargs,
    )


async def test_startup_loads_active_projects():
    """register_fn is called once per project with a non-null config_file."""
    app_state = _make_app_state()
    app = SimpleNamespace(state=app_state)

    register_fn, _deregister_fn = build_project_route_registrar(app, httpx_client=None)
    active_projects = [
        SimpleNamespace(
            uuid='aaaa-aaaa',
            name='project-a',
            config_file=_PROJECT_A_YAML,
        ),
        SimpleNamespace(
            uuid='bbbb-bbbb',
            name='project-b',
            config_file=_PROJECT_B_YAML,
        ),
    ]
    for project in active_projects:
        await register_fn(project.uuid, project.name, project.config_file)

    assert 'project-a/route-a' in app.state.routes
    assert 'project-b/route-b' in app.state.routes
    assert 'project-a' in app.state.project_configs
    assert 'project-b' in app.state.project_configs
    entry_a: ProjectEntry = app.state.project_configs['project-a']
    assert entry_a.uuid == 'aaaa-aaaa'
    assert isinstance(entry_a.config, GatewayConfig)
    entry_b: ProjectEntry = app.state.project_configs['project-b']
    assert entry_b.uuid == 'bbbb-bbbb'


async def test_startup_skips_failed_project():
    """A broken config for one project must not prevent others from loading."""
    app_state = _make_app_state()
    app = SimpleNamespace(state=app_state)

    register_fn, _deregister_fn = build_project_route_registrar(app, httpx_client=None)

    # Project A loads fine; project bad has invalid YAML
    with contextlib.suppress(Exception):
        await register_fn('bad-project', '{{not valid yaml', '')

    await register_fn('aaaa-bbbb', 'project-a', _PROJECT_A_YAML)

    assert 'bad-project' not in app.state.project_configs
    assert 'project-a/route-a' in app.state.routes


_CACHED_PROJECT_YAML = """\
cache:
  redis_host: localhost
  redis_port: 6379
chat_models:
  - model_id: openai-gpt4o
    model: openai/gpt-4o-mini
    credentials:
      api_key: sk-test-key
routes:
  my-route:
    chat_models:
      - openai-gpt4o
    caching:
      type: exact
      ttl: 60
"""


@pytest.mark.asyncio
async def test_cache_client_asks_for_resp2():
    """The cache client must negotiate RESP2.

    redis-py defaults to RESP3 and then parses FT.SEARCH replies as a map,
    while valkey-search answers with a flat array. The mismatch raises
    AttributeError inside the client, which SemanticCache.get swallows and
    reports as a miss, so every semantic lookup fails.
    """
    app = SimpleNamespace(
        state=SimpleNamespace(
            presidio_engine=PresidioEngine(),
            judge_engine=MagicMock(spec_set=JudgeEngine),
            redis_client=None,
            routes={},
            project_configs={},
        )
    )
    registrar, _deregistrar = build_project_route_registrar(app, httpx_client=None)

    with patch(
        'radicalbit_ai_gateway.utils.gateway_route_factory.redis.asyncio.Redis',
        autospec=True,
    ) as mock_redis:
        await registrar(uuid.uuid4(), 'cached-project', _CACHED_PROJECT_YAML)

    assert mock_redis.call_args.kwargs['protocol'] == 2
