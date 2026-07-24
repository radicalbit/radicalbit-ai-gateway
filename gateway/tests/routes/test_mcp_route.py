from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import uuid

from fastapi import FastAPI
import httpx
from mcp import types
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.testclient import TestClient

from radicalbit_ai_gateway.mcp_proxy.upstream_client import McpUpstreamClient
from radicalbit_ai_gateway.models.auth_dto import KeyDetails
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.project_entry import ProjectEntry
from radicalbit_ai_gateway.routes.mcp_route import McpRoute
from radicalbit_ai_gateway.services.mcp_service import McpService
from radicalbit_ai_gateway.utils.exceptions import (
    ApiKeyError,
    InvalidApiKey,
    McpTransportError,
    api_key_exception_handler,
    mcp_transport_exception_handler,
)

KEY_DETAILS = KeyDetails(
    api_key_uuid=str(uuid.uuid4()),
    api_key_name='my-key',
    group_uuid=str(uuid.uuid4()),
    group_name='team-a',
    hashed_api_key='hashed',
)

AUTH = {'Authorization': 'Bearer sk-rb-abc'}
ALLOWED_ORIGIN = 'http://localhost:5173'

PATH = '/proj/my-route/mcp'


def _gateway_config() -> GatewayConfig:
    return GatewayConfig.model_validate(
        {
            'chat_models': [{'model_id': 'm1', 'model': 'openai/gpt-4o'}],
            'routes': {
                'my-route': {'chat_models': ['m1'], 'mcp_servers': ['github']},
                'other-route': {'chat_models': ['m1'], 'mcp_servers': ['jira']},
                'bare-route': {'chat_models': ['m1']},
            },
            'mcp_servers': [
                {
                    'alias': 'github',
                    'transport': 'streamable_http',
                    'url': 'https://github.example.com/mcp/',
                },
                {
                    'alias': 'jira',
                    'transport': 'streamable_http',
                    'url': 'https://jira.example.com/mcp/',
                },
            ],
        }
    )


def _make_client(
    upstream_client=None,
    *,
    key_bound: bool = True,
    with_project: bool = True,
) -> tuple[TestClient, MagicMock]:
    app = FastAPI(title='AI Gateway', debug=True)
    group_service = MagicMock()
    group_service.check_key_uuid_for_route.return_value = key_bound
    service = McpService(
        upstream_client=upstream_client or MagicMock(spec_set=McpUpstreamClient),
        group_service=group_service,
        allowed_origins=[ALLOWED_ORIGIN],
    )
    app.include_router(McpRoute.get_mcp_router(service))
    app.add_exception_handler(McpTransportError, mcp_transport_exception_handler)
    app.add_exception_handler(ApiKeyError, api_key_exception_handler)
    app.state.project_configs = (
        {'proj': ProjectEntry(uuid=uuid.uuid4(), config=_gateway_config())}
        if with_project
        else {}
    )
    app.state.token_validator = SimpleNamespace(
        validate_token=AsyncMock(return_value=KEY_DETAILS)
    )
    return TestClient(app), group_service


def _ping(request_id=1) -> dict:
    return {'jsonrpc': '2.0', 'id': request_id, 'method': 'ping'}


# ---------------------------------------------------------------------------
# Transport / HTTP level
# ---------------------------------------------------------------------------


def test_get_and_delete_are_method_not_allowed():
    client, _ = _make_client()
    for method in ('get', 'delete'):
        res = getattr(client, method)(PATH, headers=AUTH)
        assert res.status_code == 405
        assert res.headers['allow'] == 'POST'


def test_missing_bearer_is_401():
    client, _ = _make_client()
    res = client.post(PATH, json=_ping())
    assert res.status_code == 401


def test_invalid_key_is_401():
    client, _ = _make_client()
    client.app.state.token_validator.validate_token.side_effect = InvalidApiKey(
        'Invalid API key'
    )
    res = client.post(PATH, json=_ping(), headers=AUTH)
    assert res.status_code == 401


def test_disallowed_origin_is_403():
    client, _ = _make_client()
    res = client.post(
        PATH, json=_ping(), headers={**AUTH, 'Origin': 'http://evil.example'}
    )
    assert res.status_code == 403


def test_allowed_origin_passes():
    client, _ = _make_client()
    res = client.post(PATH, json=_ping(), headers={**AUTH, 'Origin': ALLOWED_ORIGIN})
    assert res.status_code == 200


def test_unknown_project_is_404():
    client, _ = _make_client(with_project=False)
    res = client.post(PATH, json=_ping(), headers=AUTH)
    assert res.status_code == 404


def test_unknown_route_is_404():
    client, _ = _make_client()
    res = client.post('/proj/nope/mcp', json=_ping(), headers=AUTH)
    assert res.status_code == 404


def test_key_not_bound_to_route_is_403():
    client, group_service = _make_client(key_bound=False)
    res = client.post(PATH, json=_ping(), headers=AUTH)
    assert res.status_code == 403
    group_service.check_key_uuid_for_route.assert_called_once_with(
        'proj/my-route', uuid.UUID(KEY_DETAILS.api_key_uuid)
    )


def test_unsupported_protocol_version_is_400():
    client, _ = _make_client()
    res = client.post(
        PATH, json=_ping(), headers={**AUTH, 'MCP-Protocol-Version': '2024-11-05'}
    )
    assert res.status_code == 400


def test_supported_and_absent_protocol_versions_pass():
    client, _ = _make_client()
    for headers in (
        AUTH,
        {**AUTH, 'MCP-Protocol-Version': '2025-06-18'},
        {**AUTH, 'MCP-Protocol-Version': '2025-11-25'},
    ):
        res = client.post(PATH, json=_ping(), headers=headers)
        assert res.status_code == 200


def test_stateless_no_session_id_and_json_content_type():
    client, _ = _make_client()
    res = client.post(PATH, json=_ping(), headers=AUTH)
    assert 'mcp-session-id' not in res.headers
    assert res.headers['content-type'].startswith('application/json')


def test_parse_error_is_400_with_jsonrpc_body():
    client, _ = _make_client()
    res = client.post(
        PATH,
        content=b'{not json',
        headers={**AUTH, 'Content-Type': 'application/json'},
    )
    assert res.status_code == 400
    assert res.json()['error']['code'] == -32700


# ---------------------------------------------------------------------------
# Protocol behavior end-to-end
# ---------------------------------------------------------------------------


def test_initialize_lifecycle():
    client, _ = _make_client()

    res = client.post(
        PATH,
        json={
            'jsonrpc': '2.0',
            'id': 1,
            'method': 'initialize',
            'params': {
                'protocolVersion': '2025-06-18',
                'capabilities': {},
                'clientInfo': {'name': 'test-client', 'version': '1.0'},
            },
        },
        headers=AUTH,
    )
    assert res.status_code == 200
    result = res.json()['result']
    assert result['protocolVersion'] == '2025-06-18'
    assert result['capabilities'] == {'tools': {}, 'prompts': {}, 'resources': {}}

    res = client.post(
        PATH,
        json={'jsonrpc': '2.0', 'method': 'notifications/initialized'},
        headers=AUTH,
    )
    assert res.status_code == 202
    assert res.content == b''

    res = client.post(PATH, json=_ping('123'), headers=AUTH)
    assert res.json() == {'jsonrpc': '2.0', 'id': '123', 'result': {}}


def test_unknown_method_is_32601_over_200():
    client, _ = _make_client()
    res = client.post(
        PATH,
        json={'jsonrpc': '2.0', 'id': 1, 'method': 'completion/complete'},
        headers=AUTH,
    )
    assert res.status_code == 200
    assert res.json()['error']['code'] == -32601


def test_tools_list_exposes_only_route_servers():
    upstream = MagicMock(spec_set=McpUpstreamClient)
    upstream.list_tools = AsyncMock(
        return_value=types.ListToolsResult(
            tools=[
                types.Tool(name='get_issue', inputSchema={'type': 'object'}),
            ]
        )
    )
    client, _ = _make_client(upstream)
    res = client.post(
        PATH,
        json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'},
        headers=AUTH,
    )
    assert res.status_code == 200
    assert [t['name'] for t in res.json()['result']['tools']] == ['github__get_issue']
    # fan-out hit only the route's server ('jira' belongs to other-route)
    upstream.list_tools.assert_awaited_once()
    assert upstream.list_tools.await_args.args[0].alias == 'github'


def test_tools_list_on_route_without_servers_is_empty():
    client, _ = _make_client()
    res = client.post(
        '/proj/bare-route/mcp',
        json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'},
        headers=AUTH,
    )
    assert res.status_code == 200
    assert res.json()['result'] == {'tools': []}


def test_tools_call_forwards_and_other_routes_alias_is_invisible():
    upstream = MagicMock(spec_set=McpUpstreamClient)
    upstream.call_tool = AsyncMock(
        return_value=types.CallToolResult(
            content=[types.TextContent(type='text', text='ok')], isError=False
        )
    )
    client, _ = _make_client(upstream)

    res = client.post(
        PATH,
        json={
            'jsonrpc': '2.0',
            'id': 2,
            'method': 'tools/call',
            'params': {'name': 'github__get_issue', 'arguments': {'id': '42'}},
        },
        headers=AUTH,
    )
    assert res.status_code == 200
    assert res.json()['result']['content'] == [{'type': 'text', 'text': 'ok'}]
    args = upstream.call_tool.await_args.args
    assert (args[0].alias, args[1], args[2]) == ('github', 'get_issue', {'id': '42'})

    # 'jira' is defined top-level but referenced only by other-route
    res = client.post(
        PATH,
        json={
            'jsonrpc': '2.0',
            'id': 3,
            'method': 'tools/call',
            'params': {'name': 'jira__search', 'arguments': {}},
        },
        headers=AUTH,
    )
    assert res.status_code == 200
    assert res.json()['error']['code'] == -32602


# ---------------------------------------------------------------------------
# End-to-end: client → gateway → real in-process FastMCP upstream
# ---------------------------------------------------------------------------


async def test_end_to_end_against_real_upstream():
    upstream = FastMCP(
        'upstream',
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=['testserver'], allowed_origins=['http://testserver']
        ),
    )

    @upstream.tool()
    def echo(text: str) -> str:
        """Echo the given text back."""
        return f'echo: {text}'

    upstream_app = upstream.streamable_http_app()

    def upstream_client_factory(headers=None, timeout=None, auth=None):
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=upstream_app),
            base_url='http://testserver',
            headers=headers,
            timeout=timeout,
            auth=auth,
        )

    real_upstream_client = McpUpstreamClient(
        default_timeout=20.0, httpx_client_factory=upstream_client_factory
    )
    client, _ = _make_client(real_upstream_client)
    client.app.state.project_configs['proj'].config.mcp_servers_by_alias[
        'github'
    ].url = 'http://testserver/mcp'

    async with upstream_app.router.lifespan_context(upstream_app):
        gateway = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=client.app),
            base_url='http://gateway',
        )
        async with gateway:
            res = await gateway.post(
                PATH,
                json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'},
                headers=AUTH,
            )
            assert res.status_code == 200
            tools = res.json()['result']['tools']
            assert [t['name'] for t in tools] == ['github__echo']
            assert tools[0]['inputSchema']['required'] == ['text']

            res = await gateway.post(
                PATH,
                json={
                    'jsonrpc': '2.0',
                    'id': 2,
                    'method': 'tools/call',
                    'params': {'name': 'github__echo', 'arguments': {'text': 'hi'}},
                },
                headers=AUTH,
            )
            assert res.status_code == 200
            result = res.json()['result']
            assert result['isError'] is False
            assert result['content'][0] == {'type': 'text', 'text': 'echo: hi'}
