"""End-to-end span assertions for the MCP path, against a real OTel pipeline.

The mock-based tests in ``test_mcp_service.py`` verify that the helpers are
*called*; they cannot verify where the attributes actually land. That
distinction matters: Traceloop's ``@task`` detaches its context token on exit,
so anything set inside a task reaches that task's span only and never the
enclosing ``mcp_request`` workflow span — which is the span
``OtelTracesDAO.get_root_traces_paginated`` queries. These tests boot Traceloop
against an in-memory exporter and assert on the emitted spans.

Note: ``Traceloop.init`` installs a global tracer provider for the rest of the
session. That only means other tests emit spans nobody collects.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import uuid

from fastapi import FastAPI
from mcp import types
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
import pytest
from starlette.testclient import TestClient
from traceloop.sdk import Traceloop

from radicalbit_ai_gateway.mcp_proxy.errors import McpUpstreamError
from radicalbit_ai_gateway.mcp_proxy.upstream_client import McpUpstreamClient
from radicalbit_ai_gateway.models.auth_dto import KeyDetails
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.project_entry import ProjectEntry
from radicalbit_ai_gateway.routes.mcp_route import McpRoute
from radicalbit_ai_gateway.services.mcp_service import McpService, encode_resource_uri
from radicalbit_ai_gateway.utils.exceptions import (
    ApiKeyError,
    McpTransportError,
    api_key_exception_handler,
    mcp_transport_exception_handler,
)

PATH = '/proj/my-route/mcp'
AUTH = {'Authorization': 'Bearer sk-rb-abc'}
ASSOC = 'traceloop.association.properties.'
ROOT_SPAN = 'mcp_request.workflow'


@pytest.fixture(scope='module')
def exporter() -> InMemorySpanExporter:
    exp = InMemorySpanExporter()
    Traceloop.init(
        app_name='test-gateway',
        telemetry_enabled=False,
        disable_batch=True,
        processor=SimpleSpanProcessor(exp),
    )
    return exp


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
    # what was attempted, so the failure is diagnosable
    assert _mcp_attrs(root) == {
        'method': 'tools/call',
        'alias': 'nope',
        'target': 'missing',
        'error_code': '-32602',
    }


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
    assert attrs['mcp.upstream.total'] == 2
    assert attrs['mcp.upstream.failed'] == 'jira'
    assert attrs['mcp.result.count'] == 1


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
