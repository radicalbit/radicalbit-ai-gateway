from unittest.mock import AsyncMock, MagicMock, patch

from mcp import types
import pytest

from radicalbit_ai_gateway.mcp_proxy.errors import McpUpstreamError
from radicalbit_ai_gateway.mcp_proxy.upstream_client import McpUpstreamClient
from radicalbit_ai_gateway.models.mcp_server import McpHttpServer
from radicalbit_ai_gateway.services.mcp_service import (
    LATEST_PROTOCOL_VERSION,
    MCP_SERVER_NAME,
    McpService,
    _warned_unadvertised,
    decode_resource_uri,
    encode_resource_uri,
    negotiate_protocol_version,
    split_alias_name,
    strip_uri_credentials,
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


def _prompt(name: str, description: str = 'a prompt') -> types.Prompt:
    return types.Prompt(name=name, description=description)


def _resource(uri: str, name: str = 'a resource') -> types.Resource:
    return types.Resource(uri=uri, name=name)


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


RESOURCE_A = 'https://github.example.com/a'
RESOURCE_B = 'https://github.example.com/b'


def _server(**kwargs) -> McpHttpServer:
    return McpHttpServer(
        alias='github', url='https://github.example.com/mcp/', **kwargs
    )


def _list_client() -> MagicMock:
    client = MagicMock(spec_set=McpUpstreamClient)
    client.list_tools = AsyncMock(
        return_value=types.ListToolsResult(tools=[_tool('a'), _tool('b'), _tool('c')])
    )
    client.list_prompts = AsyncMock(
        return_value=types.ListPromptsResult(
            prompts=[_prompt('a'), _prompt('b'), _prompt('c')]
        )
    )
    client.list_resources = AsyncMock(
        return_value=types.ListResourcesResult(
            resources=[_resource(RESOURCE_A), _resource(RESOURCE_B)]
        )
    )
    return client


@pytest.fixture(autouse=True)
def _forget_unadvertised_warnings():
    """Clear the process-global warn-once guard so tests do not inherit it."""
    _warned_unadvertised.clear()
    yield
    _warned_unadvertised.clear()


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize('version', ['2025-06-18', '2025-11-25'])
def test_negotiate_echoes_supported_version(version):
    assert negotiate_protocol_version(version) == version


@pytest.mark.parametrize('version', ['2024-11-05', '2025-03-26', None, 42])
def test_negotiate_falls_back_to_latest(version):
    assert negotiate_protocol_version(version) == LATEST_PROTOCOL_VERSION


def test_split_alias_name():
    assert split_alias_name('github__get_issue') == ('github', 'get_issue')
    # only the first '__' separates alias and name
    assert split_alias_name('github__ns__tool') == ('github', 'ns__tool')
    assert split_alias_name('no_separator') is None
    assert split_alias_name('__tool') is None
    assert split_alias_name('alias__') is None


def test_resource_uri_round_trips():
    encoded = encode_resource_uri('github', 'https://example.com/a/b?x=1')
    assert decode_resource_uri(encoded) == ('github', 'https://example.com/a/b?x=1')


def test_resource_uri_round_trips_reserved_characters():
    encoded = encode_resource_uri('my alias/x', 'file:///etc/hosts#frag')
    assert decode_resource_uri(encoded) == ('my alias/x', 'file:///etc/hosts#frag')


@pytest.mark.parametrize(
    'uri',
    ['https://example.com/plain', 'mcp-resource:no-slash', 'mcp-resource:/', ''],
)
def test_decode_resource_uri_rejects_foreign_or_malformed(uri):
    assert decode_resource_uri(uri) is None


@pytest.mark.parametrize(
    ('uri', 'expected'),
    [
        # the identifying part survives untouched
        ('https://h.example/readme', 'https://h.example/readme'),
        ('https://h.example:8443/readme', 'https://h.example:8443/readme'),
        ('urn:isbn:123', 'urn:isbn:123'),
        ('file:///etc/hosts', 'file:///etc/hosts'),
        # signed-URL tokens and basic-auth credentials do not
        ('https://h.example/r?token=s3cret', 'https://h.example/r'),
        ('https://h.example/r#frag', 'https://h.example/r'),
        ('https://user:pass@h.example/r', 'https://h.example/r'),
        ('file:///etc/hosts?x=1', 'file:///etc/hosts'),
        # unparseable input is passed through rather than raising
        ('https://h.example:99999/r', 'https://h.example:99999/r'),
        ('not a uri at all', 'not a uri at all'),
        ('', ''),
    ],
)
def test_strip_uri_credentials(uri, expected):
    assert strip_uri_credentials(uri) == expected


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
    result = await _service()._dispatch(_request('completion/complete'), SERVERS, None)
    assert result.status_code == 200
    assert result.payload['error']['code'] == -32601
    assert 'completion/complete' in result.payload['error']['message']


async def test_non_object_params_is_32602():
    result = await _service()._dispatch(
        _request('tools/call', params=[1, 2]), SERVERS, None
    )
    assert result.status_code == 200
    assert result.payload['error']['code'] == -32602


# ---------------------------------------------------------------------------
# initialize / ping
# ---------------------------------------------------------------------------


async def test_initialize_advertises_capabilities():
    result = await _service()._dispatch(
        _request('initialize', params={'protocolVersion': '2025-06-18'}),
        SERVERS,
        None,
    )
    assert result.status_code == 200
    payload_result = result.payload['result']
    assert payload_result['protocolVersion'] == '2025-06-18'
    # no listChanged on any of the three
    assert payload_result['capabilities'] == {
        'tools': {},
        'prompts': {},
        'resources': {},
    }
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


# ---------------------------------------------------------------------------
# prompts/list
# ---------------------------------------------------------------------------


async def test_prompts_list_fans_out_and_prefixes():
    client = MagicMock(spec_set=McpUpstreamClient)
    client.list_prompts = AsyncMock(
        side_effect=[
            types.ListPromptsResult(
                prompts=[_prompt('summarize'), _prompt('translate')]
            ),
            types.ListPromptsResult(prompts=[_prompt('search')]),
        ]
    )
    headers = {'x-user-jwt': 'jwt-1'}

    result = await _service(client)._dispatch(
        _request('prompts/list'), SERVERS, headers
    )

    assert result.status_code == 200
    prompts = result.payload['result']['prompts']
    assert [p['name'] for p in prompts] == [
        'github__summarize',
        'github__translate',
        'jira__search',
    ]
    assert prompts[0]['description'] == 'a prompt'
    for call, server in zip(client.list_prompts.await_args_list, SERVERS, strict=True):
        assert call.args == (server,)
        assert call.kwargs['client_headers'] == headers


async def test_prompts_list_without_servers_is_empty():
    result = await _service()._dispatch(_request('prompts/list'), [], None)
    assert result.status_code == 200
    assert result.payload['result'] == {'prompts': []}


async def test_prompts_list_tolerates_one_failing_upstream():
    client = MagicMock(spec_set=McpUpstreamClient)
    client.list_prompts = AsyncMock(
        side_effect=[
            McpUpstreamError('github', 'boom'),
            types.ListPromptsResult(prompts=[_prompt('search')]),
        ]
    )
    result = await _service(client)._dispatch(_request('prompts/list'), SERVERS, None)
    assert result.status_code == 200
    assert [p['name'] for p in result.payload['result']['prompts']] == ['jira__search']


async def test_prompts_list_all_upstreams_failing_is_32000():
    client = MagicMock(spec_set=McpUpstreamClient)
    client.list_prompts = AsyncMock(side_effect=McpUpstreamError('github', 'boom'))
    result = await _service(client)._dispatch(_request('prompts/list'), SERVERS, None)
    assert result.status_code == 200
    assert result.payload['error']['code'] == -32000


# ---------------------------------------------------------------------------
# prompts/get
# ---------------------------------------------------------------------------


async def test_prompts_get_forwards_and_passes_result_through():
    result = types.GetPromptResult(
        description='a rendered prompt',
        messages=[
            types.PromptMessage(
                role='user', content=types.TextContent(type='text', text='hello')
            )
        ],
    )
    client = MagicMock(spec_set=McpUpstreamClient)
    client.get_prompt = AsyncMock(return_value=result)
    headers = {'x-user-jwt': 'jwt-1'}

    dispatch_result = await _service(client)._dispatch(
        _request(
            'prompts/get',
            params={'name': 'github__summarize', 'arguments': {'id': '42'}},
        ),
        SERVERS,
        headers,
    )

    assert dispatch_result.status_code == 200
    assert dispatch_result.payload['result']['description'] == 'a rendered prompt'
    client.get_prompt.assert_awaited_once_with(
        GITHUB, 'summarize', {'id': '42'}, client_headers=headers
    )


async def test_prompts_get_splits_on_first_separator_only():
    client = MagicMock(spec_set=McpUpstreamClient)
    client.get_prompt = AsyncMock(return_value=types.GetPromptResult(messages=[]))
    await _service(client)._dispatch(
        _request('prompts/get', params={'name': 'github__ns__prompt'}), SERVERS, None
    )
    assert client.get_prompt.await_args.args[1] == 'ns__prompt'


@pytest.mark.parametrize(
    'name', ['unknown__prompt', 'no_separator', 'github', '', 'confluence__x']
)
async def test_prompts_get_unknown_prompt_is_32602(name):
    client = MagicMock(spec_set=McpUpstreamClient)
    client.get_prompt = AsyncMock()
    result = await _service(client)._dispatch(
        _request('prompts/get', params={'name': name}), SERVERS, None
    )
    assert result.status_code == 200
    assert result.payload['error']['code'] == -32602
    client.get_prompt.assert_not_awaited()


async def test_prompts_get_alias_outside_scope_is_32602():
    client = MagicMock(spec_set=McpUpstreamClient)
    client.get_prompt = AsyncMock()
    result = await _service(client)._dispatch(
        _request('prompts/get', params={'name': 'jira__search'}), [GITHUB], None
    )
    assert result.status_code == 200
    assert result.payload['error']['code'] == -32602
    client.get_prompt.assert_not_awaited()


@pytest.mark.parametrize(
    'params',
    [{}, {'name': 7}, {'name': 'github__x', 'arguments': 'not-a-dict'}],
)
async def test_prompts_get_bad_params_is_32602(params):
    result = await _service()._dispatch(
        _request('prompts/get', params=params), SERVERS, None
    )
    assert result.status_code == 200
    assert result.payload['error']['code'] == -32602


async def test_prompts_get_upstream_error_maps_to_jsonrpc_error():
    client = MagicMock(spec_set=McpUpstreamClient)
    client.get_prompt = AsyncMock(
        side_effect=McpUpstreamError('github', "Upstream MCP server 'github' timed out")
    )
    result = await _service(client)._dispatch(
        _request('prompts/get', params={'name': 'github__summarize'}), SERVERS, None
    )
    assert result.status_code == 200
    assert result.payload['error']['code'] == -32000
    assert 'timed out' in result.payload['error']['message']


# ---------------------------------------------------------------------------
# resources/list
# ---------------------------------------------------------------------------


async def test_resources_list_fans_out_and_aliases_uris():
    client = MagicMock(spec_set=McpUpstreamClient)
    client.list_resources = AsyncMock(
        side_effect=[
            types.ListResourcesResult(
                resources=[_resource('https://github.example.com/readme')]
            ),
            types.ListResourcesResult(
                resources=[_resource('https://jira.example.com/board')]
            ),
        ]
    )
    headers = {'x-user-jwt': 'jwt-1'}

    result = await _service(client)._dispatch(
        _request('resources/list'), SERVERS, headers
    )

    assert result.status_code == 200
    resources = result.payload['result']['resources']
    assert decode_resource_uri(resources[0]['uri']) == (
        'github',
        'https://github.example.com/readme',
    )
    assert decode_resource_uri(resources[1]['uri']) == (
        'jira',
        'https://jira.example.com/board',
    )
    assert resources[0]['name'] == 'a resource'
    for call, server in zip(
        client.list_resources.await_args_list, SERVERS, strict=True
    ):
        assert call.args == (server,)
        assert call.kwargs['client_headers'] == headers


async def test_resources_list_without_servers_is_empty():
    result = await _service()._dispatch(_request('resources/list'), [], None)
    assert result.status_code == 200
    assert result.payload['result'] == {'resources': []}


async def test_resources_list_tolerates_one_failing_upstream():
    client = MagicMock(spec_set=McpUpstreamClient)
    client.list_resources = AsyncMock(
        side_effect=[
            McpUpstreamError('github', 'boom'),
            types.ListResourcesResult(
                resources=[_resource('https://jira.example.com/board')]
            ),
        ]
    )
    result = await _service(client)._dispatch(_request('resources/list'), SERVERS, None)
    assert result.status_code == 200
    resources = result.payload['result']['resources']
    assert len(resources) == 1
    assert decode_resource_uri(resources[0]['uri'])[0] == 'jira'


async def test_resources_list_all_upstreams_failing_is_32000():
    client = MagicMock(spec_set=McpUpstreamClient)
    client.list_resources = AsyncMock(side_effect=McpUpstreamError('github', 'boom'))
    result = await _service(client)._dispatch(_request('resources/list'), SERVERS, None)
    assert result.status_code == 200
    assert result.payload['error']['code'] == -32000


# ---------------------------------------------------------------------------
# resources/read
# ---------------------------------------------------------------------------


async def test_resources_read_forwards_and_realiases_result():
    upstream_uri = 'https://github.example.com/readme'
    result = types.ReadResourceResult(
        contents=[
            types.TextResourceContents(
                uri=upstream_uri, text='hello', mimeType='text/plain'
            )
        ]
    )
    client = MagicMock(spec_set=McpUpstreamClient)
    client.read_resource = AsyncMock(return_value=result)
    headers = {'x-user-jwt': 'jwt-1'}
    encoded = encode_resource_uri('github', upstream_uri)

    dispatch_result = await _service(client)._dispatch(
        _request('resources/read', params={'uri': encoded}), SERVERS, headers
    )

    assert dispatch_result.status_code == 200
    contents = dispatch_result.payload['result']['contents']
    assert contents[0]['text'] == 'hello'
    assert decode_resource_uri(contents[0]['uri']) == ('github', upstream_uri)
    client.read_resource.assert_awaited_once_with(
        GITHUB, upstream_uri, client_headers=headers
    )


@pytest.mark.parametrize(
    'params',
    [
        {},
        {'uri': 7},
        {'uri': ''},
        {'uri': 'https://example.com/plain'},  # not one of our wrapped URIs
        {'uri': encode_resource_uri('confluence', 'https://x')},  # out of scope
    ],
)
async def test_resources_read_bad_or_unknown_uri_is_32602(params):
    client = MagicMock(spec_set=McpUpstreamClient)
    client.read_resource = AsyncMock()
    result = await _service(client)._dispatch(
        _request('resources/read', params=params), SERVERS, None
    )
    assert result.status_code == 200
    assert result.payload['error']['code'] == -32602
    client.read_resource.assert_not_awaited()


async def test_resources_read_alias_outside_scope_is_32602():
    client = MagicMock(spec_set=McpUpstreamClient)
    client.read_resource = AsyncMock()
    encoded = encode_resource_uri('jira', 'https://jira.example.com/board')
    result = await _service(client)._dispatch(
        _request('resources/read', params={'uri': encoded}), [GITHUB], None
    )
    assert result.status_code == 200
    assert result.payload['error']['code'] == -32602
    client.read_resource.assert_not_awaited()


async def test_resources_read_upstream_error_maps_to_jsonrpc_error():
    client = MagicMock(spec_set=McpUpstreamClient)
    client.read_resource = AsyncMock(
        side_effect=McpUpstreamError('github', "Upstream MCP server 'github' timed out")
    )
    encoded = encode_resource_uri('github', 'https://github.example.com/readme')
    result = await _service(client)._dispatch(
        _request('resources/read', params={'uri': encoded}), SERVERS, None
    )
    assert result.status_code == 200
    assert result.payload['error']['code'] == -32000
    assert 'timed out' in result.payload['error']['message']


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------

MCP_SERVICE = 'radicalbit_ai_gateway.services.mcp_service'


def _recorded_methods(mock_set_attrs) -> list[str]:
    return [
        c.kwargs['method']
        for c in mock_set_attrs.call_args_list
        if c.kwargs.get('method') is not None
    ]


@pytest.mark.parametrize(
    'method',
    [
        'initialize',
        'ping',
        'tools/list',
        'tools/call',
        'prompts/list',
        'prompts/get',
        'resources/list',
        'resources/read',
        'completion/complete',  # unsupported, still attributed
    ],
)
async def test_dispatch_records_the_method_for_every_request(method):
    client = MagicMock(spec_set=McpUpstreamClient)
    client.list_tools = AsyncMock(return_value=types.ListToolsResult(tools=[]))
    client.list_prompts = AsyncMock(return_value=types.ListPromptsResult(prompts=[]))
    client.list_resources = AsyncMock(
        return_value=types.ListResourcesResult(resources=[])
    )

    with patch(f'{MCP_SERVICE}.set_mcp_attributes') as mock_set_attrs:
        await _service(client)._dispatch(_request(method), SERVERS, None)

    assert _recorded_methods(mock_set_attrs) == [method]


async def test_dispatch_records_the_method_for_notifications():
    """Notifications return 202 with no body, but still belong in traces."""
    body = {'jsonrpc': '2.0', 'method': 'notifications/initialized'}

    with patch(f'{MCP_SERVICE}.set_mcp_attributes') as mock_set_attrs:
        result = await _service()._dispatch(body, SERVERS, None)

    assert result.status_code == 202
    assert _recorded_methods(mock_set_attrs) == ['notifications/initialized']


async def test_dispatch_records_no_method_for_a_malformed_envelope():
    with patch(f'{MCP_SERVICE}.set_mcp_attributes') as mock_set_attrs:
        await _service()._dispatch({'jsonrpc': '1.0'}, SERVERS, None)

    assert _recorded_methods(mock_set_attrs) == []


async def test_tools_call_records_alias_and_target():
    client = MagicMock(spec_set=McpUpstreamClient)
    client.call_tool = AsyncMock(return_value=types.CallToolResult(content=[]))

    with patch(f'{MCP_SERVICE}.set_mcp_attributes') as mock_set_attrs:
        await _service(client)._dispatch(
            _request('tools/call', params={'name': 'github__get_issue'}),
            SERVERS,
            None,
        )

    mock_set_attrs.assert_any_call(alias='github', target='get_issue')


async def test_prompts_get_records_alias_and_target():
    client = MagicMock(spec_set=McpUpstreamClient)
    client.get_prompt = AsyncMock(return_value=types.GetPromptResult(messages=[]))

    with patch(f'{MCP_SERVICE}.set_mcp_attributes') as mock_set_attrs:
        await _service(client)._dispatch(
            _request('prompts/get', params={'name': 'github__review'}), SERVERS, None
        )

    mock_set_attrs.assert_any_call(alias='github', target='review')


async def test_resources_read_records_alias_and_the_upstream_uri():
    upstream_uri = 'https://github.example.com/readme'
    client = MagicMock(spec_set=McpUpstreamClient)
    client.read_resource = AsyncMock(return_value=types.ReadResourceResult(contents=[]))

    with patch(f'{MCP_SERVICE}.set_mcp_attributes') as mock_set_attrs:
        await _service(client)._dispatch(
            _request(
                'resources/read',
                params={'uri': encode_resource_uri('github', upstream_uri)},
            ),
            SERVERS,
            None,
        )

    # the decoded upstream URI, not the wrapped mcp-resource: form
    mock_set_attrs.assert_any_call(alias='github', target=upstream_uri)


async def test_a_target_naming_no_known_upstream_records_nothing():
    """params.name is client-controlled: echoing it back is unbounded cardinality.

    The name is still diagnosable from the span status description, which
    _record_error_outcome sets from the JSON-RPC error message.
    """
    client = MagicMock(spec_set=McpUpstreamClient)
    client.call_tool = AsyncMock()

    with patch(f'{MCP_SERVICE}.set_mcp_attributes') as mock_set_attrs:
        result = await _service(client)._dispatch(
            _request('tools/call', params={'name': 'unknown__tool'}), SERVERS, None
        )

    assert result.payload['error']['code'] == -32602
    assert 'unknown__tool' in result.payload['error']['message']
    assert all(c.kwargs.get('alias') is None for c in mock_set_attrs.call_args_list)
    assert all(c.kwargs.get('target') is None for c in mock_set_attrs.call_args_list)


async def test_a_resource_uris_credentials_are_stripped_before_reaching_a_span():
    """Signed-URL tokens live in the query; the path is the resource identity."""
    upstream_uri = 'https://user:pw@github.example.com/readme?token=s3cret#frag'
    client = MagicMock(spec_set=McpUpstreamClient)
    client.read_resource = AsyncMock(return_value=types.ReadResourceResult(contents=[]))

    with patch(f'{MCP_SERVICE}.set_mcp_attributes') as mock_set_attrs:
        await _service(client)._dispatch(
            _request(
                'resources/read',
                params={'uri': encode_resource_uri('github', upstream_uri)},
            ),
            SERVERS,
            None,
        )

    mock_set_attrs.assert_any_call(
        alias='github', target='https://github.example.com/readme'
    )
    # only the span attribute is redacted; the upstream still gets the URI whole
    assert client.read_resource.await_args.args[1] == upstream_uri


@pytest.mark.parametrize(
    'params',
    [
        {'name': 'no_separator'},  # unsplittable
        {'name': 7},  # not a string
        {},  # absent
    ],
)
async def test_an_unsplittable_target_records_nothing(params):
    client = MagicMock(spec_set=McpUpstreamClient)
    client.call_tool = AsyncMock()

    with patch(f'{MCP_SERVICE}.set_mcp_attributes') as mock_set_attrs:
        await _service(client)._dispatch(
            _request('tools/call', params=params), SERVERS, None
        )

    assert all(c.kwargs.get('alias') is None for c in mock_set_attrs.call_args_list)


@pytest.mark.parametrize(
    'method', ['initialize', 'ping', 'tools/list', 'prompts/list', 'resources/list']
)
async def test_methods_without_a_single_target_record_none(method):
    """target_attributes only applies to the object-addressing methods."""
    client = MagicMock(spec_set=McpUpstreamClient)
    client.list_tools = AsyncMock(return_value=types.ListToolsResult(tools=[]))
    client.list_prompts = AsyncMock(return_value=types.ListPromptsResult(prompts=[]))
    client.list_resources = AsyncMock(
        return_value=types.ListResourcesResult(resources=[])
    )

    with patch(f'{MCP_SERVICE}.set_mcp_attributes') as mock_set_attrs:
        await _service(client)._dispatch(
            _request(method, params={'name': 'github__x'}), SERVERS, None
        )

    assert all(c.kwargs.get('target') is None for c in mock_set_attrs.call_args_list)


def _recording_span() -> MagicMock:
    span = MagicMock()
    span.is_recording.return_value = True
    return span


def _span_attrs(span: MagicMock) -> dict:
    return {c.args[0]: c.args[1] for c in span.set_attribute.call_args_list}


async def test_tools_list_records_fanout_on_a_partial_failure():
    client = MagicMock(spec_set=McpUpstreamClient)
    client.list_tools = AsyncMock(
        side_effect=[
            McpUpstreamError('github', 'boom'),
            types.ListToolsResult(tools=[_tool('search')]),
        ]
    )
    span = _recording_span()

    with patch(f'{MCP_SERVICE}.get_current_span', return_value=span):
        await _service(client)._dispatch(_request('tools/list'), SERVERS, None)

    assert _span_attrs(span) == {
        'rb.gateway.mcp_upstream_total': 2,
        'rb.gateway.mcp_upstream_failed': 'github',
        'rb.gateway.mcp_result_count': 1,
    }


async def test_list_records_fanout_on_full_success():
    """Always recorded, so a healthy fan-out is distinguishable from an absent one."""
    client = MagicMock(spec_set=McpUpstreamClient)
    client.list_prompts = AsyncMock(
        side_effect=[
            types.ListPromptsResult(prompts=[_prompt('a'), _prompt('b')]),
            types.ListPromptsResult(prompts=[_prompt('c')]),
        ]
    )
    span = _recording_span()

    with patch(f'{MCP_SERVICE}.get_current_span', return_value=span):
        await _service(client)._dispatch(_request('prompts/list'), SERVERS, None)

    assert _span_attrs(span) == {
        'rb.gateway.mcp_upstream_total': 2,
        'rb.gateway.mcp_upstream_failed': '',
        'rb.gateway.mcp_result_count': 3,
    }


async def test_resources_list_records_fanout():
    client = MagicMock(spec_set=McpUpstreamClient)
    client.list_resources = AsyncMock(
        side_effect=[
            types.ListResourcesResult(resources=[_resource('https://a.example/1')]),
            McpUpstreamError('jira', 'boom'),
        ]
    )
    span = _recording_span()

    with patch(f'{MCP_SERVICE}.get_current_span', return_value=span):
        await _service(client)._dispatch(_request('resources/list'), SERVERS, None)

    assert _span_attrs(span)['rb.gateway.mcp_upstream_failed'] == 'jira'


async def test_fanout_is_not_recorded_on_a_non_recording_span():
    client = MagicMock(spec_set=McpUpstreamClient)
    client.list_tools = AsyncMock(return_value=types.ListToolsResult(tools=[]))
    span = MagicMock()
    span.is_recording.return_value = False

    with patch(f'{MCP_SERVICE}.get_current_span', return_value=span):
        await _service(client)._dispatch(_request('tools/list'), SERVERS, None)

    span.set_attribute.assert_not_called()


async def test_tools_list_exposes_only_the_allowlisted_tools():
    client = _list_client()
    result = await _service(client)._dispatch(
        _request('tools/list'), [_server(allowed_tools=['a', 'b'])], None
    )
    assert [t['name'] for t in result.payload['result']['tools']] == [
        'github__a',
        'github__b',
    ]


async def test_tools_list_with_no_allowlist_exposes_everything():
    client = _list_client()
    result = await _service(client)._dispatch(_request('tools/list'), [_server()], None)
    assert [t['name'] for t in result.payload['result']['tools']] == [
        'github__a',
        'github__b',
        'github__c',
    ]


async def test_tools_list_with_an_empty_allowlist_exposes_nothing():
    client = _list_client()
    result = await _service(client)._dispatch(
        _request('tools/list'), [_server(allowed_tools=[])], None
    )
    assert result.payload['result']['tools'] == []


async def test_an_empty_tool_allowlist_skips_the_upstream_entirely():
    """Nothing can come back, so the round trip is pure cost."""
    client = _list_client()
    await _service(client)._dispatch(
        _request('tools/list'), [_server(allowed_tools=[])], None
    )
    client.list_tools.assert_not_awaited()


async def test_an_allowlist_entry_the_upstream_never_advertises_is_inert():
    client = _list_client()
    result = await _service(client)._dispatch(
        _request('tools/list'), [_server(allowed_tools=['a', 'nonexistent'])], None
    )
    assert [t['name'] for t in result.payload['result']['tools']] == ['github__a']


async def test_tools_call_forwards_an_allowlisted_tool():
    client = MagicMock(spec_set=McpUpstreamClient)
    client.call_tool = AsyncMock(return_value=types.CallToolResult(content=[]))
    result = await _service(client)._dispatch(
        _request('tools/call', params={'name': 'github__a'}),
        [_server(allowed_tools=['a'])],
        None,
    )
    assert 'error' not in result.payload
    assert client.call_tool.await_args.args[1] == 'a'


@pytest.mark.parametrize('allowed_tools', [['b'], []])
async def test_tools_call_rejects_a_tool_outside_the_allowlist(allowed_tools):
    """Never listed is no defense: a cached tools/list will still call it."""
    client = MagicMock(spec_set=McpUpstreamClient)
    client.call_tool = AsyncMock()
    result = await _service(client)._dispatch(
        _request('tools/call', params={'name': 'github__a'}),
        [_server(allowed_tools=allowed_tools)],
        None,
    )
    assert result.status_code == 200
    assert result.payload['error']['code'] == -32602
    # indistinguishable from a tool that does not exist: the allowlist does not
    # confirm what it hides
    assert result.payload['error']['message'] == 'Unknown tool: github__a'
    client.call_tool.assert_not_awaited()


async def test_prompts_list_exposes_only_the_allowlisted_prompts():
    client = _list_client()
    result = await _service(client)._dispatch(
        _request('prompts/list'), [_server(allowed_prompts=['b'])], None
    )
    assert [p['name'] for p in result.payload['result']['prompts']] == ['github__b']


async def test_prompts_list_with_an_empty_allowlist_exposes_nothing():
    client = _list_client()
    result = await _service(client)._dispatch(
        _request('prompts/list'), [_server(allowed_prompts=[])], None
    )
    assert result.payload['result']['prompts'] == []
    client.list_prompts.assert_not_awaited()


async def test_prompts_list_with_no_allowlist_exposes_everything():
    client = _list_client()
    result = await _service(client)._dispatch(
        _request('prompts/list'), [_server()], None
    )
    assert len(result.payload['result']['prompts']) == 3


@pytest.mark.parametrize('allowed_prompts', [['b'], []])
async def test_prompts_get_rejects_a_prompt_outside_the_allowlist(allowed_prompts):
    client = MagicMock(spec_set=McpUpstreamClient)
    client.get_prompt = AsyncMock()
    result = await _service(client)._dispatch(
        _request('prompts/get', params={'name': 'github__a'}),
        [_server(allowed_prompts=allowed_prompts)],
        None,
    )
    assert result.payload['error']['code'] == -32602
    assert result.payload['error']['message'] == 'Unknown prompt: github__a'
    client.get_prompt.assert_not_awaited()


async def test_prompts_get_forwards_an_allowlisted_prompt():
    client = MagicMock(spec_set=McpUpstreamClient)
    client.get_prompt = AsyncMock(return_value=types.GetPromptResult(messages=[]))
    result = await _service(client)._dispatch(
        _request('prompts/get', params={'name': 'github__a'}),
        [_server(allowed_prompts=['a'])],
        None,
    )
    assert 'error' not in result.payload


async def test_resources_list_exposes_only_the_allowlisted_uris():
    client = _list_client()
    result = await _service(client)._dispatch(
        _request('resources/list'), [_server(allowed_resources=[RESOURCE_B])], None
    )
    uris = [r['uri'] for r in result.payload['result']['resources']]
    assert uris == [encode_resource_uri('github', RESOURCE_B)]


async def test_resources_list_with_an_empty_allowlist_exposes_nothing():
    client = _list_client()
    result = await _service(client)._dispatch(
        _request('resources/list'), [_server(allowed_resources=[])], None
    )
    assert result.payload['result']['resources'] == []
    client.list_resources.assert_not_awaited()


async def test_resources_list_with_no_allowlist_exposes_everything():
    client = _list_client()
    result = await _service(client)._dispatch(
        _request('resources/list'), [_server()], None
    )
    assert len(result.payload['result']['resources']) == 2


@pytest.mark.parametrize('allowed_resources', [[RESOURCE_B], []])
async def test_resources_read_rejects_a_uri_outside_the_allowlist(allowed_resources):
    client = MagicMock(spec_set=McpUpstreamClient)
    client.read_resource = AsyncMock()
    wrapped = encode_resource_uri('github', RESOURCE_A)
    result = await _service(client)._dispatch(
        _request('resources/read', params={'uri': wrapped}),
        [_server(allowed_resources=allowed_resources)],
        None,
    )
    assert result.payload['error']['code'] == -32602
    assert result.payload['error']['message'] == f'Unknown resource: {wrapped}'
    client.read_resource.assert_not_awaited()


async def test_resources_read_forwards_an_allowlisted_uri():
    client = MagicMock(spec_set=McpUpstreamClient)
    client.read_resource = AsyncMock(return_value=types.ReadResourceResult(contents=[]))
    result = await _service(client)._dispatch(
        _request(
            'resources/read',
            params={'uri': encode_resource_uri('github', RESOURCE_A)},
        ),
        [_server(allowed_resources=[RESOURCE_A])],
        None,
    )
    assert 'error' not in result.payload
    assert client.read_resource.await_args.args[1] == RESOURCE_A


async def test_allowlists_are_scoped_to_their_own_server():
    client = _list_client()
    servers = [
        _server(allowed_tools=['a']),
        McpHttpServer(alias='jira', url='https://jira.example.com/mcp/'),
    ]
    result = await _service(client)._dispatch(_request('tools/list'), servers, None)
    assert [t['name'] for t in result.payload['result']['tools']] == [
        'github__a',
        'jira__a',
        'jira__b',
        'jira__c',
    ]


async def test_a_fully_gated_server_does_not_count_as_a_failed_upstream():
    """Skipping an empty allowlist must not read as a degraded fan-out."""
    client = MagicMock(spec_set=McpUpstreamClient)
    client.list_tools = AsyncMock(
        return_value=types.ListToolsResult(tools=[_tool('a')])
    )
    servers = [
        _server(allowed_tools=[]),
        McpHttpServer(alias='jira', url='https://jira.example.com/mcp/'),
    ]
    result = await _service(client)._dispatch(_request('tools/list'), servers, None)
    assert [t['name'] for t in result.payload['result']['tools']] == ['jira__a']


async def test_every_contacted_upstream_failing_still_raises_when_one_is_gated():
    client = MagicMock(spec_set=McpUpstreamClient)
    client.list_tools = AsyncMock(side_effect=McpUpstreamError('jira', 'boom'))
    servers = [
        _server(allowed_tools=[]),
        McpHttpServer(alias='jira', url='https://jira.example.com/mcp/'),
    ]
    result = await _service(client)._dispatch(_request('tools/list'), servers, None)
    assert result.payload['error']['code'] == -32000


async def test_an_allowlist_rejection_is_attributable_in_traces():
    client = MagicMock(spec_set=McpUpstreamClient)
    client.call_tool = AsyncMock()

    with patch(f'{MCP_SERVICE}.set_mcp_attributes') as mock_set_attrs:
        await _service(client)._dispatch(
            _request('tools/call', params={'name': 'github__a'}),
            [_server(allowed_tools=[])],
            None,
        )

    mock_set_attrs.assert_any_call(denied='allowlist')


async def test_an_unknown_alias_is_not_attributed_to_the_allowlist():
    client = MagicMock(spec_set=McpUpstreamClient)
    client.call_tool = AsyncMock()

    with patch(f'{MCP_SERVICE}.set_mcp_attributes') as mock_set_attrs:
        await _service(client)._dispatch(
            _request('tools/call', params={'name': 'nope__a'}), SERVERS, None
        )

    assert all(c.kwargs.get('denied') is None for c in mock_set_attrs.call_args_list)


UNADVERTISED = [
    ('tools', 'allowed_tools', 'nonexistent'),
    ('prompts', 'allowed_prompts', 'nonexistent'),
    ('resources', 'allowed_resources', 'https://nowhere.example/x'),
]


@pytest.mark.parametrize(('kind', 'field', 'entry'), UNADVERTISED)
async def test_an_unadvertised_allowlist_entry_is_warned_about_at_runtime(
    kind, field, entry
):
    """The upstream is unreachable at config load, so this is the only place."""
    client = _list_client()
    with patch(f'{MCP_SERVICE}.logger') as mock_logger:
        await _service(client)._dispatch(
            _request(f'{kind}/list'), [_server(**{field: [entry]})], None
        )
    warnings = [c.args for c in mock_logger.warning.call_args_list]
    assert any(entry in args for args in warnings), warnings


@pytest.mark.parametrize(('kind', 'field', 'entry'), UNADVERTISED)
async def test_an_unadvertised_entry_is_warned_about_only_once(kind, field, entry):
    """Once per process, not once per request: this is a config typo, not news."""
    client = _list_client()
    servers = [_server(**{field: [entry]})]
    with patch(f'{MCP_SERVICE}.logger') as mock_logger:
        for _ in range(3):
            await _service(client)._dispatch(_request(f'{kind}/list'), servers, None)
    assert mock_logger.warning.call_count == 1


@pytest.mark.parametrize(('kind', 'field', 'entry'), UNADVERTISED)
async def test_a_fully_advertised_allowlist_warns_about_nothing(kind, field, entry):
    advertised = {'tools': 'a', 'prompts': 'a', 'resources': RESOURCE_A}[kind]
    client = _list_client()
    with patch(f'{MCP_SERVICE}.logger') as mock_logger:
        await _service(client)._dispatch(
            _request(f'{kind}/list'), [_server(**{field: [advertised]})], None
        )
    mock_logger.warning.assert_not_called()
