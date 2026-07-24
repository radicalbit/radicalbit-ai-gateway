from unittest.mock import AsyncMock, MagicMock

from mcp import types
import pytest

from radicalbit_ai_gateway.mcp_proxy.errors import McpUpstreamError
from radicalbit_ai_gateway.mcp_proxy.upstream_client import McpUpstreamClient
from radicalbit_ai_gateway.models.mcp_server import McpHttpServer
from radicalbit_ai_gateway.services.mcp_service import (
    LATEST_PROTOCOL_VERSION,
    MCP_SERVER_NAME,
    McpService,
    negotiate_protocol_version,
    split_tool_name,
)

GITHUB = McpHttpServer(alias='github', url='https://github.example.com/mcp/')
JIRA = McpHttpServer(alias='jira', url='https://jira.example.com/mcp/')
SERVERS = [GITHUB, JIRA]


def _tool(name: str, description: str = 'a tool') -> types.Tool:
    return types.Tool(
        name=name,
        description=description,
        inputSchema={'type': 'object', 'properties': {}},
    )


def _service(upstream_client=None) -> McpService:
    return McpService(
        upstream_client=upstream_client or MagicMock(spec_set=McpUpstreamClient),
        group_service=MagicMock(),
        allowed_origins=['http://localhost:5173'],
    )


def _request(method: str, request_id=1, params=None) -> dict:
    body = {'jsonrpc': '2.0', 'id': request_id, 'method': method}
    if params is not None:
        body['params'] = params
    return body


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize('version', ['2025-06-18', '2025-11-25'])
def test_negotiate_echoes_supported_version(version):
    assert negotiate_protocol_version(version) == version


@pytest.mark.parametrize('version', ['2024-11-05', '2025-03-26', None, 42])
def test_negotiate_falls_back_to_latest(version):
    assert negotiate_protocol_version(version) == LATEST_PROTOCOL_VERSION


def test_split_tool_name():
    assert split_tool_name('github__get_issue') == ('github', 'get_issue')
    # only the first '__' separates alias and tool
    assert split_tool_name('github__ns__tool') == ('github', 'ns__tool')
    assert split_tool_name('no_separator') is None
    assert split_tool_name('__tool') is None
    assert split_tool_name('alias__') is None


# ---------------------------------------------------------------------------
# JSON-RPC envelope
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    'body',
    [
        'not a dict',
        [{'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}],  # batching unsupported
        {'id': 1, 'method': 'ping'},  # missing jsonrpc
        {'jsonrpc': '1.0', 'id': 1, 'method': 'ping'},
        {'jsonrpc': '2.0', 'id': 1},  # missing method
        {'jsonrpc': '2.0', 'id': 1, 'method': 7},
    ],
)
async def test_invalid_envelope_is_400_invalid_request(body):
    result = await _service()._dispatch(body, SERVERS, None)
    assert result.status_code == 400
    assert result.payload['error']['code'] == -32600
    assert result.payload['id'] is None


@pytest.mark.parametrize('request_id', [None, True, 1.5, {'x': 1}])
async def test_invalid_request_id_rejected(request_id):
    result = await _service()._dispatch(
        _request('ping', request_id=request_id), SERVERS, None
    )
    assert result.status_code == 400
    assert result.payload['error']['code'] == -32600


@pytest.mark.parametrize('request_id', [0, 1, 'abc'])
async def test_valid_request_ids_echoed(request_id):
    result = await _service()._dispatch(
        _request('ping', request_id=request_id), SERVERS, None
    )
    assert result.status_code == 200
    assert result.payload == {'jsonrpc': '2.0', 'id': request_id, 'result': {}}


async def test_notifications_get_202_and_no_body():
    service = _service()
    for method in ('notifications/initialized', 'notifications/cancelled'):
        result = await service._dispatch(
            {'jsonrpc': '2.0', 'method': method}, SERVERS, None
        )
        assert result.status_code == 202
        assert result.payload is None


async def test_unknown_method_is_32601():
    result = await _service()._dispatch(_request('resources/list'), SERVERS, None)
    assert result.status_code == 200
    assert result.payload['error']['code'] == -32601
    assert 'resources/list' in result.payload['error']['message']


async def test_non_object_params_is_32602():
    result = await _service()._dispatch(
        _request('tools/call', params=[1, 2]), SERVERS, None
    )
    assert result.status_code == 200
    assert result.payload['error']['code'] == -32602


# ---------------------------------------------------------------------------
# initialize / ping
# ---------------------------------------------------------------------------


async def test_initialize_advertises_tools_only():
    result = await _service()._dispatch(
        _request('initialize', params={'protocolVersion': '2025-06-18'}),
        SERVERS,
        None,
    )
    assert result.status_code == 200
    payload_result = result.payload['result']
    assert payload_result['protocolVersion'] == '2025-06-18'
    assert payload_result['capabilities'] == {'tools': {}}  # no listChanged
    assert payload_result['serverInfo']['name'] == MCP_SERVER_NAME
    assert payload_result['serverInfo']['version']


async def test_initialize_negotiates_unsupported_version():
    result = await _service()._dispatch(
        _request('initialize', params={'protocolVersion': '2024-11-05'}),
        SERVERS,
        None,
    )
    assert result.status_code == 200
    assert result.payload['result']['protocolVersion'] == LATEST_PROTOCOL_VERSION


# ---------------------------------------------------------------------------
# tools/list
# ---------------------------------------------------------------------------


async def test_tools_list_fans_out_and_prefixes():
    client = MagicMock(spec_set=McpUpstreamClient)
    client.list_tools = AsyncMock(
        side_effect=[
            types.ListToolsResult(tools=[_tool('get_issue'), _tool('create_issue')]),
            types.ListToolsResult(tools=[_tool('search')]),
        ]
    )
    headers = {'x-user-jwt': 'jwt-1'}

    result = await _service(client)._dispatch(_request('tools/list'), SERVERS, headers)

    assert result.status_code == 200
    tools = result.payload['result']['tools']
    assert [t['name'] for t in tools] == [
        'github__get_issue',
        'github__create_issue',
        'jira__search',
    ]
    # non-name fields pass through verbatim
    assert tools[0]['description'] == 'a tool'
    assert tools[0]['inputSchema'] == {'type': 'object', 'properties': {}}
    for call, server in zip(client.list_tools.await_args_list, SERVERS, strict=True):
        assert call.args == (server,)
        assert call.kwargs['client_headers'] == headers


async def test_tools_list_without_servers_is_empty():
    result = await _service()._dispatch(_request('tools/list'), [], None)
    assert result.status_code == 200
    assert result.payload['result'] == {'tools': []}


async def test_tools_list_tolerates_one_failing_upstream():
    client = MagicMock(spec_set=McpUpstreamClient)
    client.list_tools = AsyncMock(
        side_effect=[
            McpUpstreamError('github', 'boom'),
            types.ListToolsResult(tools=[_tool('search')]),
        ]
    )
    result = await _service(client)._dispatch(_request('tools/list'), SERVERS, None)
    assert result.status_code == 200
    assert [t['name'] for t in result.payload['result']['tools']] == ['jira__search']


async def test_tools_list_all_upstreams_failing_is_32000():
    client = MagicMock(spec_set=McpUpstreamClient)
    client.list_tools = AsyncMock(side_effect=McpUpstreamError('github', 'boom'))
    result = await _service(client)._dispatch(_request('tools/list'), SERVERS, None)
    assert result.status_code == 200
    assert result.payload['error']['code'] == -32000
    assert 'boom' not in result.payload['error']['message']


# ---------------------------------------------------------------------------
# tools/call
# ---------------------------------------------------------------------------


async def test_tools_call_forwards_and_passes_result_through():
    result = types.CallToolResult(
        content=[types.TextContent(type='text', text='issue #42')],
        isError=False,
    )
    client = MagicMock(spec_set=McpUpstreamClient)
    client.call_tool = AsyncMock(return_value=result)
    headers = {'x-user-jwt': 'jwt-1'}

    dispatch_result = await _service(client)._dispatch(
        _request(
            'tools/call',
            params={'name': 'github__get_issue', 'arguments': {'id': '42'}},
        ),
        SERVERS,
        headers,
    )

    assert dispatch_result.status_code == 200
    assert dispatch_result.payload['result'] == {
        'content': [{'type': 'text', 'text': 'issue #42'}],
        'isError': False,
    }
    client.call_tool.assert_awaited_once_with(
        GITHUB, 'get_issue', {'id': '42'}, client_headers=headers
    )


async def test_tools_call_is_error_result_passes_through():
    result = types.CallToolResult(
        content=[types.TextContent(type='text', text='rate limited')], isError=True
    )
    client = MagicMock(spec_set=McpUpstreamClient)
    client.call_tool = AsyncMock(return_value=result)

    dispatch_result = await _service(client)._dispatch(
        _request('tools/call', params={'name': 'github__get_issue'}), SERVERS, None
    )
    assert dispatch_result.status_code == 200
    assert dispatch_result.payload['result']['isError'] is True


async def test_tools_call_splits_on_first_separator_only():
    client = MagicMock(spec_set=McpUpstreamClient)
    client.call_tool = AsyncMock(return_value=types.CallToolResult(content=[]))
    await _service(client)._dispatch(
        _request('tools/call', params={'name': 'github__ns__tool'}), SERVERS, None
    )
    assert client.call_tool.await_args.args[1] == 'ns__tool'


@pytest.mark.parametrize(
    'name', ['unknown__tool', 'no_separator', 'github', '', 'confluence__x']
)
async def test_tools_call_unknown_tool_is_32602(name):
    client = MagicMock(spec_set=McpUpstreamClient)
    client.call_tool = AsyncMock()
    result = await _service(client)._dispatch(
        _request('tools/call', params={'name': name}), SERVERS, None
    )
    assert result.status_code == 200
    assert result.payload['error']['code'] == -32602
    client.call_tool.assert_not_awaited()


async def test_tools_call_alias_outside_scope_is_32602():
    """A top-level alias not exposed on this route is invisible."""
    client = MagicMock(spec_set=McpUpstreamClient)
    client.call_tool = AsyncMock()
    result = await _service(client)._dispatch(
        _request('tools/call', params={'name': 'jira__search'}), [GITHUB], None
    )
    assert result.status_code == 200
    assert result.payload['error']['code'] == -32602
    client.call_tool.assert_not_awaited()


@pytest.mark.parametrize(
    'params',
    [{}, {'name': 7}, {'name': 'github__x', 'arguments': 'not-a-dict'}],
)
async def test_tools_call_bad_params_is_32602(params):
    result = await _service()._dispatch(
        _request('tools/call', params=params), SERVERS, None
    )
    assert result.status_code == 200
    assert result.payload['error']['code'] == -32602


async def test_tools_call_upstream_error_maps_to_jsonrpc_error():
    client = MagicMock(spec_set=McpUpstreamClient)
    client.call_tool = AsyncMock(
        side_effect=McpUpstreamError('github', "Upstream MCP server 'github' timed out")
    )
    result = await _service(client)._dispatch(
        _request('tools/call', params={'name': 'github__get_issue'}), SERVERS, None
    )
    assert result.status_code == 200
    assert result.payload['error']['code'] == -32000
    assert 'timed out' in result.payload['error']['message']


async def test_unexpected_exception_is_sanitized_internal_error():
    client = MagicMock(spec_set=McpUpstreamClient)
    client.call_tool = AsyncMock(side_effect=ValueError('secret detail'))
    result = await _service(client)._dispatch(
        _request('tools/call', params={'name': 'github__get_issue'}), SERVERS, None
    )
    assert result.status_code == 200
    assert result.payload['error']['code'] == -32603
    assert 'secret detail' not in result.payload['error']['message']
