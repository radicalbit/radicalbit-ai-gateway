"""End-to-end telemetry assertions for the MCP path, with production wiring.

The mock-based tests in ``test_mcp_service.py`` verify that the helpers are
*called*; they cannot verify where the attributes actually land. That
distinction matters: Traceloop's ``@task`` detaches its context token on exit,
so anything set inside a task reaches that task's span only and never the
enclosing ``mcp_request`` workflow span — which is the span
``OtelTracesDAO.get_root_traces_paginated`` queries. These tests boot Traceloop
against an in-memory exporter and assert on the emitted spans, plus on the
REQUEST event payloads the same request produces.

Note: ``Traceloop.init`` installs a global tracer provider that cannot be
uninstalled, so the ``exporter`` fixture disables the wrapper on teardown. Without
that, every later test in the session keeps feeding this exporter and the run is
OOM-killed.
"""

from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

from fastapi import FastAPI
from mcp import types
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
import pytest
from starlette.testclient import TestClient
from traceloop.sdk import Traceloop
from traceloop.sdk.tracing.tracing import TracerWrapper

from radicalbit_ai_gateway.caching.gateway_cache import GatewayCache
from radicalbit_ai_gateway.caching.in_memory_cache import CacheToolsInMemory
from radicalbit_ai_gateway.mcp_proxy.errors import McpUpstreamError
from radicalbit_ai_gateway.mcp_proxy.upstream_client import McpUpstreamClient
from radicalbit_ai_gateway.middleware.request_event_middleware import (
    RequestEventMiddleware,
)
from radicalbit_ai_gateway.models.auth_dto import KeyDetails
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.project_entry import ProjectEntry
from radicalbit_ai_gateway.models.request_event_type import RequestStatus, RequestType
from radicalbit_ai_gateway.routes.mcp_route import McpRoute
from radicalbit_ai_gateway.services.mcp_service import McpService, encode_resource_uri
from radicalbit_ai_gateway.utils.exceptions import (
    ApiKeyError,
    InvalidApiKey,
    McpTransportError,
    api_key_exception_handler,
    mcp_transport_exception_handler,
)

PATH = '/proj/my-route/mcp'
AUTH = {'Authorization': 'Bearer sk-rb-abc'}
ASSOC = 'traceloop.association.properties.'
ROOT_SPAN = 'mcp_request.workflow'


@pytest.fixture(scope='module')
def exporter() -> Iterator[InMemorySpanExporter]:
    exp = InMemorySpanExporter()
    Traceloop.init(
        app_name='test-gateway',
        telemetry_enabled=False,
        disable_batch=True,
        processor=SimpleSpanProcessor(exp),
        # Omitting this enables every instrumentor Traceloop ships (openai,
        # httpx, ...), which monkeypatch their libraries globally and are not
        # undone by set_disabled below — they would stay installed for the rest
        # of the session. The MCP path needs none of them, and production only
        # enables LANGCHAIN.
        instruments=set(),
    )
    TracerWrapper.set_disabled(False)
    yield exp
    # Traceloop installs a global tracer provider that cannot be uninstalled, so
    # without this every later test in the session would keep emitting spans into
    # this exporter — unbounded growth that OOM-kills the full run. Disabling the
    # wrapper makes the decorators no-op again, restoring the behaviour the rest
    # of the suite has always had (Traceloop is never initialized in production
    # tests).
    TracerWrapper.set_disabled(True)
    exp.clear()


@pytest.fixture
def upstream() -> MagicMock:
    client = MagicMock(spec_set=McpUpstreamClient)
    client.call_tool = AsyncMock(return_value=types.CallToolResult(content=[]))
    client.get_prompt = AsyncMock(return_value=types.GetPromptResult(messages=[]))
    client.read_resource = AsyncMock(return_value=types.ReadResourceResult(contents=[]))
    return client


@pytest.fixture
def client(exporter, upstream) -> TestClient:
    exporter.clear()
    config = GatewayConfig.model_validate(
        {
            'chat_models': [{'model_id': 'm1', 'model': 'openai/gpt-4o'}],
            'routes': {
                'my-route': {'chat_models': ['m1'], 'mcp_servers': ['github', 'jira']}
            },
            'mcp_servers': [
                {
                    'alias': 'github',
                    'transport': 'streamable_http',
                    'url': 'https://gh.example/mcp/',
                },
                {
                    'alias': 'jira',
                    'transport': 'streamable_http',
                    'url': 'https://jira.example/mcp/',
                },
            ],
        }
    )
    group_service = MagicMock()
    group_service.check_key_uuid_for_route.return_value = True

    app = FastAPI()
    # request_uuid is stamped here in production, so the test app must have it
    # too — otherwise the root span's request_uuid assertion proves nothing.
    app.add_middleware(RequestEventMiddleware)
    app.include_router(
        McpRoute.get_mcp_router(
            McpService(
                upstream_client=upstream,
                group_service=group_service,
                allowed_origins=['*'],
            )
        )
    )
    app.add_exception_handler(McpTransportError, mcp_transport_exception_handler)
    app.add_exception_handler(ApiKeyError, api_key_exception_handler)
    app.state.project_configs = {'proj': ProjectEntry(uuid=uuid.uuid4(), config=config)}
    # The endpoint resolves the route registry through get_gateway_routes,
    # which 503s when it is absent. This route declares no rate_limiting, so
    # an empty registry leaves every assertion below unchanged.
    app.state.routes = {}
    app.state.token_validator = SimpleNamespace(
        validate_token=AsyncMock(
            return_value=KeyDetails(
                api_key_uuid=str(uuid.uuid4()),
                api_key_name='my-key',
                group_uuid=str(uuid.uuid4()),
                group_name='team-a',
                hashed_api_key='h',
            )
        )
    )
    return TestClient(app)


@pytest.fixture
def cached_client(client) -> Iterator[TestClient]:
    """Return the same app, with the route declaring a ``caching:`` block.

    The base fixture leaves ``app.state.routes`` empty, which the endpoint
    reads as "no route-level features", so no list cache is built at all.
    """
    client.app.state.routes = {
        'proj/my-route': SimpleNamespace(
            request_rate_limiter=None,
            gateway_cache=GatewayCache(CacheToolsInMemory()),
            ttl=60,
        )
    }
    # A hit reports itself to the events pipeline; that is asserted in
    # test_list_cache.py and only noise here.
    with (
        patch('radicalbit_ai_gateway.mcp_proxy.list_cache.emit_event'),
        patch('radicalbit_ai_gateway.mcp_proxy.list_cache.cache_hit_counter'),
    ):
        yield client


def _post(client: TestClient, method: str, params: dict | None = None):
    body = {'jsonrpc': '2.0', 'id': 1, 'method': method}
    if params is not None:
        body['params'] = params
    return client.post(PATH, json=body, headers=AUTH)


def _span(exporter, name: str):
    matches = [s for s in exporter.get_finished_spans() if s.name == name]
    assert matches, (
        f'no {name} span emitted, got {[s.name for s in exporter.get_finished_spans()]}'
    )
    return matches[-1]


def _category(span) -> str | None:
    return (span.attributes or {}).get(f'{ASSOC}rb.gateway.operation_category')


def _mcp_attrs(span) -> dict:
    return {
        k.replace(f'{ASSOC}rb.gateway.mcp_', ''): v
        for k, v in (span.attributes or {}).items()
        if 'rb.gateway.mcp_' in k
    }


def test_root_span_carries_the_request_uuid(client, exporter):
    assert _post(client, 'ping').status_code == 200

    recorded = _span(exporter, ROOT_SPAN).attributes[f'{ASSOC}request_uuid']
    assert uuid.UUID(recorded).version == 4


def test_root_span_carries_the_auth_identity(client, exporter):
    """Supplied by authenticate_bearer_request, and must survive the MCP merge."""
    assert _post(client, 'ping').status_code == 200

    attrs = _span(exporter, ROOT_SPAN).attributes
    assert attrs[f'{ASSOC}api_key_name'] == 'my-key'
    assert attrs[f'{ASSOC}group_name'] == 'team-a'
    assert attrs[f'{ASSOC}project_name'] == 'proj'
    assert attrs[f'{ASSOC}route_name'] == 'my-route'


@pytest.mark.parametrize(
    ('method', 'params', 'expected_target'),
    [
        ('tools/call', {'name': 'github__get_issue'}, 'get_issue'),
        ('prompts/get', {'name': 'github__review'}, 'review'),
        (
            'resources/read',
            {'uri': encode_resource_uri('github', 'https://gh.example/readme')},
            'https://gh.example/readme',
        ),
    ],
)
def test_root_span_carries_method_alias_and_target(
    client, exporter, method, params, expected_target
):
    """The regression guard: these must reach the ROOT span, not just the task."""
    assert _post(client, method, params).status_code == 200

    assert _mcp_attrs(_span(exporter, ROOT_SPAN)) == {
        'method': method,
        'alias': 'github',
        'target': expected_target,
    }


def test_a_jsonrpc_error_marks_the_root_span(client, exporter):
    """HTTP is 200, so the span status is the only failure signal."""
    response = _post(client, 'tools/call', {'name': 'nope__missing'})

    assert response.status_code == 200
    root = _span(exporter, ROOT_SPAN)
    assert root.status.status_code is StatusCode.ERROR
    # 'nope' resolves to no configured upstream, so the client-supplied name is
    # kept out of the attributes (unbounded cardinality) ...
    assert _mcp_attrs(root) == {'method': 'tools/call', 'error_code': '-32602'}
    # ... and stays diagnosable through the free-text status description
    assert root.status.description == 'Unknown tool: nope__missing'


def test_a_successful_call_leaves_the_root_span_unset(client, exporter):
    assert _post(client, 'tools/call', {'name': 'github__get_issue'}).status_code == 200

    assert _span(exporter, ROOT_SPAN).status.status_code is not StatusCode.ERROR


def test_a_partial_fanout_failure_is_recorded_on_the_task_span(
    client, exporter, upstream
):
    upstream.list_tools = AsyncMock(
        side_effect=[
            types.ListToolsResult(tools=[types.Tool(name='t', inputSchema={})]),
            McpUpstreamError('jira', 'boom'),
        ]
    )

    assert _post(client, 'tools/list').status_code == 200

    attrs = _span(exporter, 'mcp_tools_list.task').attributes
    assert attrs['rb.gateway.mcp_upstream_total'] == 2
    assert attrs['rb.gateway.mcp_upstream_failed'] == 'jira'
    assert attrs['rb.gateway.mcp_result_count'] == 1


def test_a_partial_fanout_failure_also_reaches_the_root_span(
    client, exporter, upstream
):
    """The task span is invisible to the root-span query behind the traces list."""
    upstream.list_tools = AsyncMock(
        side_effect=[
            types.ListToolsResult(tools=[types.Tool(name='t', inputSchema={})]),
            McpUpstreamError('jira', 'boom'),
        ]
    )

    assert _post(client, 'tools/list').status_code == 200

    root = _span(exporter, ROOT_SPAN)
    assert _mcp_attrs(root) == {'method': 'tools/list', 'upstream_failed': 'jira'}
    # a degraded fan-out is still a 200 with results — not a failed request
    assert root.status.status_code is not StatusCode.ERROR


def test_a_healthy_fanout_leaves_the_root_span_without_the_degraded_marker(
    client, exporter, upstream
):
    upstream.list_tools = AsyncMock(return_value=types.ListToolsResult(tools=[]))

    assert _post(client, 'tools/list').status_code == 200

    assert _mcp_attrs(_span(exporter, ROOT_SPAN)) == {'method': 'tools/list'}


def test_one_requests_degradation_does_not_leak_into_the_next(
    client, exporter, upstream
):
    """The marker crosses a task boundary via a ContextVar, so prove the scope.

    Each request is its own asyncio task with a copied context; a module-level
    ContextVar would otherwise mark every later request as degraded.
    """
    upstream.list_tools = AsyncMock(
        side_effect=[
            types.ListToolsResult(tools=[]),
            McpUpstreamError('jira', 'boom'),
            types.ListToolsResult(tools=[]),
            types.ListToolsResult(tools=[]),
        ]
    )

    assert _post(client, 'tools/list').status_code == 200
    assert _mcp_attrs(_span(exporter, ROOT_SPAN))['upstream_failed'] == 'jira'

    assert _post(client, 'tools/list').status_code == 200
    assert 'upstream_failed' not in _mcp_attrs(_span(exporter, ROOT_SPAN))


def test_upstream_calls_get_their_own_child_span(client, exporter, upstream):
    """Real upstream latency is only visible if the outbound call is its own span."""
    assert _post(client, 'tools/call', {'name': 'github__get_issue'}).status_code == 200

    names = {s.name for s in exporter.get_finished_spans()}
    assert {'mcp_request.workflow', 'mcp_tools_call.task'} <= names


def test_a_parse_error_marks_the_root_span(client, exporter):
    """The 400 path returns before _dispatch, so it needs its own guard."""
    response = client.post(
        PATH, content=b'{not json', headers={**AUTH, 'Content-Type': 'application/json'}
    )

    assert response.status_code == 400
    assert response.json()['error']['code'] == -32700
    root = _span(exporter, ROOT_SPAN)
    assert root.status.status_code is StatusCode.ERROR
    assert _mcp_attrs(root) == {'error_code': '-32700'}


def test_a_notification_leaves_the_root_span_unset(client, exporter):
    response = client.post(
        PATH,
        json={'jsonrpc': '2.0', 'method': 'notifications/initialized'},
        headers=AUTH,
    )

    assert response.status_code == 202
    root = _span(exporter, ROOT_SPAN)
    assert root.status.status_code is not StatusCode.ERROR
    assert _mcp_attrs(root) == {'method': 'notifications/initialized'}


# ---------------------------------------------------------------------------
# REQUEST events (same wiring, other pipeline)
# ---------------------------------------------------------------------------

EMIT = 'radicalbit_ai_gateway.middleware.request_event_middleware.emit_request_event'


def test_the_request_event_carries_route_project_and_key_identity(client):
    """Empty identity columns would make the rows useless to the dashboard."""
    with patch(EMIT) as emit:
        assert (
            _post(client, 'tools/call', {'name': 'github__get_issue'}).status_code
            == 200
        )

    payload = emit.call_args.args[0]
    assert payload.request_type is RequestType.MCP
    assert payload.route_name == 'my-route'
    assert payload.project_name == 'proj'
    assert payload.project_uuid
    assert payload.api_key_name == 'my-key'
    assert payload.group_name == 'team-a'
    assert payload.status is RequestStatus.SUCCESS
    assert payload.duration_ms > 0


def test_the_request_event_shares_the_request_uuid_with_the_span(client, exporter):
    """Pin the join that the traces and events pipelines rely on."""
    with patch(EMIT) as emit:
        assert _post(client, 'ping').status_code == 200

    span_uuid = _span(exporter, ROOT_SPAN).attributes[f'{ASSOC}request_uuid']
    assert emit.call_args.args[0].request_uuid == span_uuid


def test_a_jsonrpc_error_is_a_handled_error_in_the_request_event(client):
    with patch(EMIT) as emit:
        assert _post(client, 'tools/call', {'name': 'nope__missing'}).status_code == 200

    payload = emit.call_args.args[0]
    assert payload.http_status_code == 200
    assert payload.status is RequestStatus.HANDLED_ERROR
    assert payload.error_type == 'mcp_jsonrpc_error'
    assert payload.error_code == '-32602'


def test_a_notification_emits_no_request_event(client):
    with patch(EMIT) as emit:
        response = client.post(
            PATH,
            json={'jsonrpc': '2.0', 'method': 'notifications/initialized'},
            headers=AUTH,
        )

    assert response.status_code == 202
    emit.assert_not_called()


def test_an_auth_failure_still_reports_the_route_it_targeted(client):
    """Context is populated before auth, so 401s stay attributable to a route."""
    client.app.state.token_validator = SimpleNamespace(
        validate_token=AsyncMock(side_effect=InvalidApiKey('nope'))
    )

    with patch(EMIT) as emit:
        assert _post(client, 'ping').status_code == 401

    payload = emit.call_args.args[0]
    assert payload.route_name == 'my-route'
    assert payload.project_name == 'proj'
    assert payload.status is RequestStatus.HANDLED_ERROR


LIST_SPAN = 'mcp_tools_list.task'


def test_a_list_served_from_cache_is_categorised_as_cache(
    cached_client, exporter, upstream
):
    """A hit contacted no upstream, so it must not be bucketed as one.

    Asserted on the emitted span rather than on a call to
    set_operation_category, because where it lands is the whole point:
    get_category_latencies groups every span by this attribute, and the task
    span inherits the INVOCATION that dispatch set before it knew the method.
    """
    upstream.list_tools = AsyncMock(return_value=types.ListToolsResult(tools=[]))

    assert _post(cached_client, 'tools/list').status_code == 200
    assert _category(_span(exporter, LIST_SPAN)) == 'invocation'

    assert _post(cached_client, 'tools/list').status_code == 200
    assert _category(_span(exporter, LIST_SPAN)) == 'cache'
    # and the second request really was a hit, not a second fan-out
    assert upstream.list_tools.await_count == 2


def test_the_root_span_of_a_cache_hit_stays_the_endpoint_bucket(
    cached_client, exporter, upstream
):
    """ensure_endpoint_category owns the root span; the phases are per-span."""
    upstream.list_tools = AsyncMock(return_value=types.ListToolsResult(tools=[]))

    assert _post(cached_client, 'tools/list').status_code == 200
    assert _post(cached_client, 'tools/list').status_code == 200

    assert _category(_span(exporter, ROOT_SPAN)) == 'endpoint'


def test_a_cache_hit_does_not_recategorise_the_next_requests_fanout(
    cached_client, exporter, upstream
):
    """The correction is attached inside a task, so prove it unwinds with it."""
    upstream.list_tools = AsyncMock(return_value=types.ListToolsResult(tools=[]))
    upstream.list_prompts = AsyncMock(return_value=types.ListPromptsResult(prompts=[]))

    assert _post(cached_client, 'tools/list').status_code == 200
    assert _post(cached_client, 'tools/list').status_code == 200
    assert _category(_span(exporter, LIST_SPAN)) == 'cache'

    # a different list method on the same route: a miss, and its own category
    assert _post(cached_client, 'prompts/list').status_code == 200
    assert _category(_span(exporter, 'mcp_prompts_list.task')) == 'invocation'
