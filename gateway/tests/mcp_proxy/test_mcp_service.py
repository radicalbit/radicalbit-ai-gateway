from unittest.mock import AsyncMock, MagicMock, patch

from mcp import types
import pytest

from radicalbit_ai_gateway.caching.gateway_cache import GatewayCache
from radicalbit_ai_gateway.caching.in_memory_cache import CacheToolsInMemory
from radicalbit_ai_gateway.mcp_proxy.errors import McpUpstreamError
from radicalbit_ai_gateway.mcp_proxy.list_cache import McpListCache
from radicalbit_ai_gateway.mcp_proxy.upstream_client import McpUpstreamClient
from radicalbit_ai_gateway.models.auth_dto import KeyDetails
from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.models.mcp_authorized_request import McpAuthorizedRequest
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
from radicalbit_ai_gateway.utils.request_context import set_current_request_tags

GITHUB = McpHttpServer(alias='github', url='https://github.example.com/mcp/')
JIRA = McpHttpServer(alias='jira', url='https://jira.example.com/mcp/')
SERVERS = [GITHUB, JIRA]

MCP_SERVICE = 'radicalbit_ai_gateway.services.mcp_service'
EVENTS_PROCESSOR = 'radicalbit_ai_gateway.events.events_processor'
LIST_CACHE = 'radicalbit_ai_gateway.mcp_proxy.list_cache'

RESOURCE_A = 'https://github.example.com/a'
RESOURCE_B = 'https://github.example.com/b'
HEADERS = {'x-user-jwt': 'jwt-1'}


def _tool(name: str) -> types.Tool:
    return types.Tool(
        name=name,
        description='a tool',
        inputSchema={'type': 'object', 'properties': {}},
    )


def _prompt(name: str) -> types.Prompt:
    return types.Prompt(name=name, description='a prompt')


def _resource(uri: str) -> types.Resource:
    return types.Resource(uri=uri, name='a resource')


# kind -> (upstream method, result type, item factory, id field, passthrough)
LISTS = {
    'tools': (
        'list_tools',
        types.ListToolsResult,
        _tool,
        'name',
        {'description': 'a tool', 'inputSchema': {'type': 'object', 'properties': {}}},
    ),
    'prompts': (
        'list_prompts',
        types.ListPromptsResult,
        _prompt,
        'name',
        {'description': 'a prompt'},
    ),
    'resources': (
        'list_resources',
        types.ListResourcesResult,
        _resource,
        'uri',
        {'name': 'a resource'},
    ),
}
KINDS = pytest.mark.parametrize('kind', list(LISTS))


def _raw(kind: str, name: str) -> str:
    """Return the upstream identifier: a name, or for resources a uri."""
    return f'https://github.example.com/{name}' if kind == 'resources' else name


def _exposed(kind: str, alias: str, name: str) -> str:
    """Return the identifier the gateway exposes for an upstream item."""
    raw = _raw(kind, name)
    return encode_resource_uri(alias, raw) if kind == 'resources' else f'{alias}__{raw}'


def _listing(kind: str, *names: str):
    _, result_type, item, _, _ = LISTS[kind]
    return result_type(**{kind: [item(_raw(kind, n)) for n in names]})


def _ids(kind: str, payload: dict) -> list[str]:
    return [item[LISTS[kind][3]] for item in payload['result'][kind]]


def _service(upstream_client=None) -> McpService:
    return McpService(
        upstream_client=upstream_client or MagicMock(spec_set=McpUpstreamClient),
        allowed_origins=['http://localhost:5173'],
    )


def _request(method: str, request_id=1, params=None) -> dict:
    body = {'jsonrpc': '2.0', 'id': request_id, 'method': method}
    if params is not None:
        body['params'] = params
    return body


def _error(code: int, message: str, request_id=1) -> dict:
    return {
        'jsonrpc': '2.0',
        'id': request_id,
        'error': {'code': code, 'message': message},
    }


def _authorized(servers=None) -> McpAuthorizedRequest:
    """Build the authorization result an endpoint hands to dispatch."""
    return McpAuthorizedRequest(
        request_uuid='request-uuid',
        project_name='my-project',
        project_uuid='project-uuid',
        route_name='my-route',
        route_key='my-project/my-route',
        key_details=KeyDetails(
            api_key_uuid='key-uuid',
            api_key_name='my-key',
            group_uuid='group-uuid',
            group_name='team-a',
            hashed_api_key='hashed',
        ),
        servers=SERVERS if servers is None else servers,
    )


async def _dispatch(
    body, servers=SERVERS, client=None, headers=None, cache=None, service=None
):
    return await (service or _service(client))._dispatch(
        body, servers, headers, cache, authorized=_authorized()
    )


def _server(**kwargs) -> McpHttpServer:
    return McpHttpServer(
        alias='github', url='https://github.example.com/mcp/', **kwargs
    )


def _list_client() -> MagicMock:
    """Build an upstream advertising a, b and c for every list method."""
    client = MagicMock(spec_set=McpUpstreamClient)
    for kind, (attr, *_) in LISTS.items():
        setattr(client, attr, AsyncMock(return_value=_listing(kind, 'a', 'b', 'c')))
    return client


def _invoking_client() -> MagicMock:
    """Build an upstream that answers all three addressed methods."""
    client = MagicMock(spec_set=McpUpstreamClient)
    client.call_tool = AsyncMock(return_value=types.CallToolResult(content=[]))
    client.get_prompt = AsyncMock(return_value=types.GetPromptResult(messages=[]))
    client.read_resource = AsyncMock(return_value=types.ReadResourceResult(contents=[]))
    return client


def _attrs(mock_set_attrs) -> dict:
    """Every attribute dispatch set on the span, merged in call order."""
    merged: dict = {}
    for c in mock_set_attrs.call_args_list:
        merged.update(c.kwargs)
    return merged


def _recording_span() -> MagicMock:
    span = MagicMock()
    span.is_recording.return_value = True
    return span


def _span_attrs(span: MagicMock) -> dict:
    return {c.args[0]: c.args[1] for c in span.set_attribute.call_args_list}


def _fanout(total: int, failed: str, count: int) -> dict:
    return {
        'rb.gateway.mcp_upstream_total': total,
        'rb.gateway.mcp_upstream_failed': failed,
        'rb.gateway.mcp_result_count': count,
    }


@pytest.fixture(autouse=True)
def recorded_events():
    """Collect the event dicts dispatch records, instead of the Celery buffer.

    Autouse, and it has to be: every dispatch here is given an authorization
    result, so an addressed method emits for real. Without this the whole
    module would talk to Celery.

    The dict is what the worker inserts. Asserting on it covers the payload
    dispatch builds and the column it maps to, in one place.
    """
    recorded: list[dict] = []
    with patch(f'{EVENTS_PROCESSOR}._events_buffer') as buffer:
        buffer.add.side_effect = recorded.append
        yield recorded


@pytest.fixture(autouse=True)
def emitted_cache_hits():
    """Keep CACHE_HIT events out of the real buffer; assert on the mock instead.

    Autouse so no unit test reaches the Celery event buffer, and named so the
    tests that care about the event can request it.
    """
    with (
        patch(f'{LIST_CACHE}.emit_event') as mock_emit,
        patch(f'{LIST_CACHE}.cache_hit_counter'),
    ):
        yield mock_emit


@pytest.fixture(autouse=True)
def _forget_unadvertised_warnings():
    """Clear the process-global warn-once guard so tests do not inherit it."""
    _warned_unadvertised.clear()
    yield
    _warned_unadvertised.clear()


def _mcp_events(recorded: list[dict]) -> list[dict]:
    """Return only the MCP invocation events out of everything recorded."""
    return [
        event for event in recorded if event['EVENT_TYPE'] is EventType.MCP_INVOCATION
    ]


def _invocation(recorded: list[dict]) -> tuple[str, str, str]:
    """Return the single MCP invocation recorded, as (method, alias, target)."""
    (event,) = _mcp_events(recorded)
    return event['MCP_METHOD'], event['MCP_ALIAS'], event['MCP_TARGET']


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ('version', 'expected'),
    [
        ('2025-06-18', '2025-06-18'),
        ('2025-11-25', '2025-11-25'),
        ('2024-11-05', LATEST_PROTOCOL_VERSION),
        ('2025-03-26', LATEST_PROTOCOL_VERSION),
        (None, LATEST_PROTOCOL_VERSION),
        (42, LATEST_PROTOCOL_VERSION),
    ],
)
def test_negotiate_echoes_a_supported_version_or_falls_back_to_latest(
    version, expected
):
    assert negotiate_protocol_version(version) == expected


def test_split_alias_name():
    assert split_alias_name('github__get_issue') == ('github', 'get_issue')
    # only the first '__' separates alias and name
    assert split_alias_name('github__ns__tool') == ('github', 'ns__tool')
    assert split_alias_name('no_separator') is None
    assert split_alias_name('__tool') is None
    assert split_alias_name('alias__') is None


@pytest.mark.parametrize(
    ('alias', 'uri'),
    [
        ('github', 'https://example.com/a/b?x=1'),
        ('my alias/x', 'file:///etc/hosts#frag'),  # reserved characters
    ],
)
def test_resource_uri_round_trips(alias, uri):
    assert decode_resource_uri(encode_resource_uri(alias, uri)) == (alias, uri)


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

BAD_ID = 'Invalid Request: id must be a string or integer'


@pytest.mark.parametrize(
    ('body', 'message', 'attrs'),
    [
        ('not a dict', 'Invalid Request', {}),
        (
            [{'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}],  # batching unsupported
            'Invalid Request',
            {},
        ),
        ({'id': 1, 'method': 'tools/call'}, 'Invalid Request', {}),  # no jsonrpc
        ({'jsonrpc': '1.0', 'id': 1, 'method': 'ping'}, 'Invalid Request', {}),
        ({'jsonrpc': '2.0', 'id': 1}, 'Invalid Request', {}),  # missing method
        ({'jsonrpc': '2.0', 'id': 1, 'method': 7}, 'Invalid Request', {}),
        # an id the protocol does not allow: rejected before anything is addressed
        *(
            (
                {'jsonrpc': '2.0', 'id': request_id, 'method': 'tools/call'},
                BAD_ID,
                {'method': 'tools/call'},
            )
            for request_id in (None, True, 1.5, {'x': 1})
        ),
    ],
)
async def test_an_invalid_envelope_is_400_and_records_nothing(
    recorded_events, body, message, attrs
):
    with patch(f'{MCP_SERVICE}.set_mcp_attributes') as mock_set_attrs:
        result = await _dispatch(body)

    assert result.status_code == 400
    assert result.payload == _error(-32600, message, request_id=None)
    assert _attrs(mock_set_attrs) == attrs
    assert _mcp_events(recorded_events) == []


@pytest.mark.parametrize('request_id', [0, 1, 'abc'])
async def test_valid_request_ids_echoed(request_id):
    result = await _dispatch(_request('ping', request_id=request_id))
    assert result.status_code == 200
    assert result.payload == {'jsonrpc': '2.0', 'id': request_id, 'result': {}}


@pytest.mark.parametrize(
    'method', ['notifications/initialized', 'notifications/cancelled']
)
async def test_a_notification_gets_202_no_body_and_is_still_traced(
    recorded_events, method
):
    """Notifications return no body, but still belong in traces."""
    with patch(f'{MCP_SERVICE}.set_mcp_attributes') as mock_set_attrs:
        result = await _dispatch({'jsonrpc': '2.0', 'method': method})

    assert result.status_code == 202
    assert result.payload is None
    assert _attrs(mock_set_attrs) == {'method': method}
    assert _mcp_events(recorded_events) == []


@pytest.mark.parametrize(
    'method', ['initialize', 'ping', 'tools/list', 'prompts/list', 'resources/list']
)
async def test_a_method_addressing_no_single_target_records_only_the_method(
    recorded_events, method
):
    """target_attributes and invocation events only apply to the
    object-addressing methods, even when params carry a name.
    """
    with patch(f'{MCP_SERVICE}.set_mcp_attributes') as mock_set_attrs:
        result = await _dispatch(
            _request(method, params={'name': 'github__x'}), client=_list_client()
        )

    assert result.status_code == 200
    assert 'result' in result.payload
    assert _attrs(mock_set_attrs) == {'method': method}
    assert _mcp_events(recorded_events) == []


async def test_an_unknown_method_is_32601_and_still_attributed(recorded_events):
    with patch(f'{MCP_SERVICE}.set_mcp_attributes') as mock_set_attrs:
        result = await _dispatch(_request('completion/complete'))

    assert result.status_code == 200
    assert result.payload == _error(-32601, 'Method not found: completion/complete')
    assert _attrs(mock_set_attrs) == {'method': 'completion/complete'}
    assert _mcp_events(recorded_events) == []


@pytest.mark.parametrize('params', [[1, 2], 5])
async def test_non_object_params_is_32602_and_addresses_nothing(
    recorded_events, params
):
    result = await _dispatch(_request('tools/call', params=params))

    assert result.status_code == 200
    assert result.payload == _error(-32602, 'params must be an object')
    assert _mcp_events(recorded_events) == []


# ---------------------------------------------------------------------------
# initialize
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ('requested', 'negotiated'),
    [('2025-06-18', '2025-06-18'), ('2024-11-05', LATEST_PROTOCOL_VERSION)],
)
async def test_initialize_negotiates_and_advertises_capabilities(requested, negotiated):
    result = await _dispatch(
        _request('initialize', params={'protocolVersion': requested})
    )

    assert result.status_code == 200
    payload_result = result.payload['result']
    assert payload_result['protocolVersion'] == negotiated
    # no listChanged on any of the three
    assert payload_result['capabilities'] == {
        'tools': {},
        'prompts': {},
        'resources': {},
    }
    assert payload_result['serverInfo']['name'] == MCP_SERVER_NAME
    assert payload_result['serverInfo']['version']


# ---------------------------------------------------------------------------
# List methods
# ---------------------------------------------------------------------------


@KINDS
async def test_a_list_fans_out_prefixes_and_records_a_healthy_fanout(kind):
    """The fan-out is always recorded, so a healthy one is distinguishable
    from an absent one. Non-identifier fields pass through verbatim.
    """
    attr, _, _, id_field, passthrough = LISTS[kind]
    client = MagicMock(spec_set=McpUpstreamClient)
    setattr(
        client,
        attr,
        AsyncMock(
            side_effect=[_listing(kind, 'get', 'create'), _listing(kind, 'search')]
        ),
    )
    span = _recording_span()

    with patch(f'{MCP_SERVICE}.get_current_span', return_value=span):
        result = await _dispatch(
            _request(f'{kind}/list'), client=client, headers=HEADERS
        )

    assert result.status_code == 200
    assert _ids(kind, result.payload) == [
        _exposed(kind, 'github', 'get'),
        _exposed(kind, 'github', 'create'),
        _exposed(kind, 'jira', 'search'),
    ]
    first = result.payload['result'][kind][0]
    assert {k: first[k] for k in passthrough} == passthrough
    calls = getattr(client, attr).await_args_list
    assert [c.args for c in calls] == [(server,) for server in SERVERS]
    assert all(c.kwargs['client_headers'] == HEADERS for c in calls)
    assert _span_attrs(span) == _fanout(2, '', 3)


@KINDS
async def test_a_list_without_servers_is_empty(kind):
    result = await _dispatch(_request(f'{kind}/list'), servers=[])
    assert result.status_code == 200
    assert result.payload['result'] == {kind: []}


@KINDS
async def test_a_list_tolerates_one_failing_upstream_and_records_it(kind):
    attr = LISTS[kind][0]
    client = MagicMock(spec_set=McpUpstreamClient)
    setattr(
        client,
        attr,
        AsyncMock(
            side_effect=[McpUpstreamError('github', 'boom'), _listing(kind, 'search')]
        ),
    )
    span = _recording_span()

    with patch(f'{MCP_SERVICE}.get_current_span', return_value=span):
        result = await _dispatch(_request(f'{kind}/list'), client=client)

    assert result.status_code == 200
    assert _ids(kind, result.payload) == [_exposed(kind, 'jira', 'search')]
    assert _span_attrs(span) == _fanout(2, 'github', 1)


@KINDS
async def test_a_list_with_every_upstream_failing_is_32000(kind):
    """The upstream's own message never reaches the client."""
    client = MagicMock(spec_set=McpUpstreamClient)
    setattr(
        client, LISTS[kind][0], AsyncMock(side_effect=McpUpstreamError('x', 'boom'))
    )

    result = await _dispatch(_request(f'{kind}/list'), client=client)

    assert result.status_code == 200
    assert result.payload == _error(-32000, 'All upstream MCP servers failed')


async def test_fanout_is_not_recorded_on_a_non_recording_span():
    client = MagicMock(spec_set=McpUpstreamClient)
    client.list_tools = AsyncMock(return_value=types.ListToolsResult(tools=[]))
    span = MagicMock()
    span.is_recording.return_value = False

    with patch(f'{MCP_SERVICE}.get_current_span', return_value=span):
        await _dispatch(_request('tools/list'), client=client)

    span.set_attribute.assert_not_called()


def _gated(kind: str, allow: list[str] | None, alias: str = 'github'):
    url = f'https://{alias}.example.com/mcp/'
    if allow is None:
        return McpHttpServer(alias=alias, url=url)
    entries = [_raw(kind, n) for n in allow]
    return McpHttpServer(alias=alias, url=url, **{f'allowed_{kind}': entries})


@pytest.mark.parametrize(
    ('kind', 'servers', 'exposed', 'contacted', 'unadvertised'),
    [
        ('tools', [_gated('tools', ['a', 'b'])], ['a', 'b'], ['github'], None),
        ('tools', [_gated('tools', None)], ['a', 'b', 'c'], ['github'], None),
        # Nothing can come back, so the round trip is pure cost.
        ('tools', [_gated('tools', [])], [], [], None),
        # An entry the upstream never advertises is inert, and warned about:
        # the upstream is unreachable at config load, so this is the only place.
        (
            'tools',
            [_gated('tools', ['a', 'nonexistent'])],
            ['a'],
            ['github'],
            'nonexistent',
        ),
        ('prompts', [_gated('prompts', ['b'])], ['b'], ['github'], None),
        ('prompts', [_gated('prompts', None)], ['a', 'b', 'c'], ['github'], None),
        ('prompts', [_gated('prompts', [])], [], [], None),
        ('resources', [_gated('resources', ['b'])], ['b'], ['github'], None),
        ('resources', [_gated('resources', None)], ['a', 'b', 'c'], ['github'], None),
        ('resources', [_gated('resources', [])], [], [], None),
        # An allowlist is scoped to its own server.
        (
            'tools',
            [_gated('tools', ['a']), _gated('tools', None, 'jira')],
            ['a', 'jira:a', 'jira:b', 'jira:c'],
            ['github', 'jira'],
            None,
        ),
        # A fully gated server is skipped, and does not read as a failed one.
        (
            'tools',
            [_gated('tools', []), _gated('tools', None, 'jira')],
            ['jira:a', 'jira:b', 'jira:c'],
            ['jira'],
            None,
        ),
    ],
)
async def test_a_list_exposes_only_what_the_allowlist_permits(
    kind, servers, exposed, contacted, unadvertised
):
    """No allowlist exposes everything, an empty one exposes nothing."""
    client = _list_client()
    span = _recording_span()

    with (
        patch(f'{MCP_SERVICE}.get_current_span', return_value=span),
        patch(f'{MCP_SERVICE}.logger') as mock_logger,
    ):
        result = await _dispatch(_request(f'{kind}/list'), servers, client)

    assert _ids(kind, result.payload) == [
        _exposed(kind, *(e.split(':') if ':' in e else ('github', e))) for e in exposed
    ]
    assert [
        c.args[0].alias for c in getattr(client, LISTS[kind][0]).await_args_list
    ] == (contacted)
    assert _span_attrs(span) == _fanout(len(servers), '', len(exposed))
    assert [c.args[1:] for c in mock_logger.warning.call_args_list] == (
        [('github', kind, unadvertised)] if unadvertised else []
    )


@pytest.mark.parametrize(
    ('kind', 'entry'),
    [
        ('tools', 'nonexistent'),
        ('prompts', 'nonexistent'),
        ('resources', 'https://nowhere.example/x'),
    ],
)
async def test_an_unadvertised_entry_is_warned_about_only_once(kind, entry):
    """Once per process, not once per request: this is a config typo, not news."""
    client = _list_client()
    servers = [_server(**{f'allowed_{kind}': [entry]})]

    with patch(f'{MCP_SERVICE}.logger') as mock_logger:
        for _ in range(3):
            await _dispatch(_request(f'{kind}/list'), servers, client)

    assert [c.args[1:] for c in mock_logger.warning.call_args_list] == [
        ('github', kind, entry)
    ]


async def test_every_contacted_upstream_failing_still_raises_when_one_is_gated():
    client = MagicMock(spec_set=McpUpstreamClient)
    client.list_tools = AsyncMock(side_effect=McpUpstreamError('jira', 'boom'))

    result = await _dispatch(
        _request('tools/list'), [_server(allowed_tools=[]), JIRA], client
    )

    assert result.payload == _error(-32000, 'All upstream MCP servers failed')


# ---------------------------------------------------------------------------
# Addressed calls: tools/call, prompts/get, resources/read
# ---------------------------------------------------------------------------

README = 'https://github.example.com/readme'
# Signed-URL tokens live in the query; the path is the resource identity.
SIGNED_README = 'https://user:pw@github.example.com/readme?token=s3cret#frag'
ARGS = {'id': '42'}


@pytest.mark.parametrize(
    ('method', 'params', 'upstream', 'returned', 'forwarded', 'target', 'expected'),
    [
        (
            'tools/call',
            # only the first '__' separates alias and name
            {'name': 'github__ns__get_issue', 'arguments': ARGS},
            'call_tool',
            types.CallToolResult(
                content=[types.TextContent(type='text', text='issue #42')],
                isError=False,
            ),
            (GITHUB, 'ns__get_issue', ARGS),
            'ns__get_issue',
            {
                'content': [{'type': 'text', 'text': 'issue #42'}],
                'isError': False,
                # Added by the SDK in mcp 2.x; always serialized, older peers
                # ignore it.
                'resultType': 'complete',
            },
        ),
        (
            'prompts/get',
            {'name': 'github__ns__summarize', 'arguments': ARGS},
            'get_prompt',
            types.GetPromptResult(
                description='a rendered prompt',
                messages=[
                    types.PromptMessage(
                        role='user', content=types.TextContent(type='text', text='hi')
                    )
                ],
            ),
            (GITHUB, 'ns__summarize', ARGS),
            'ns__summarize',
            {
                'description': 'a rendered prompt',
                'messages': [
                    {'role': 'user', 'content': {'type': 'text', 'text': 'hi'}}
                ],
                'resultType': 'complete',
            },
        ),
        (
            'resources/read',
            {'uri': encode_resource_uri('github', SIGNED_README)},
            'read_resource',
            types.ReadResourceResult(
                contents=[
                    types.TextResourceContents(
                        uri=README, text='hello', mimeType='text/plain'
                    )
                ]
            ),
            # the upstream still gets the URI whole ...
            (GITHUB, SIGNED_README),
            # ... only the span attribute and the event are redacted
            README,
            {
                'ttlMs': 0,
                'cacheScope': 'private',
                'contents': [
                    {
                        'uri': encode_resource_uri('github', README),
                        'mimeType': 'text/plain',
                        'text': 'hello',
                    }
                ],
                'resultType': 'complete',
            },
        ),
    ],
)
async def test_an_addressed_call_is_forwarded_traced_and_recorded(
    recorded_events, method, params, upstream, returned, forwarded, target, expected
):
    """The result passes through, re-aliased where it carries a uri. The
    target is the tool, prompt or resource without the alias prefix: the
    same value on the span and on the invocation event, one per call so a
    count and a sum of values agree.
    """
    client = MagicMock(spec_set=McpUpstreamClient)
    setattr(client, upstream, AsyncMock(return_value=returned))

    with patch(f'{MCP_SERVICE}.set_mcp_attributes') as mock_set_attrs:
        result = await _dispatch(
            _request(method, params=params), client=client, headers=HEADERS
        )

    assert result.status_code == 200
    assert result.payload == {'jsonrpc': '2.0', 'id': 1, 'result': expected}
    getattr(client, upstream).assert_awaited_once_with(
        *forwarded, client_headers=HEADERS
    )
    assert _attrs(mock_set_attrs) == {
        'method': method,
        'alias': 'github',
        'target': target,
    }
    assert _invocation(recorded_events) == (method, 'github', target)
    (event,) = _mcp_events(recorded_events)
    assert event['VALUE'] == 1.0


async def test_tools_call_is_error_result_passes_through():
    client = MagicMock(spec_set=McpUpstreamClient)
    client.call_tool = AsyncMock(
        return_value=types.CallToolResult(
            content=[types.TextContent(type='text', text='rate limited')], isError=True
        )
    )

    result = await _dispatch(
        _request('tools/call', params={'name': 'github__get_issue'}), client=client
    )

    assert result.status_code == 200
    assert result.payload['result']['isError'] is True


def _rejections(method: str, noun: str, field: str) -> list:
    requires = f'{method} requires a string params.{field}'
    return [
        *(
            (method, {'name': n}, SERVERS, f'Unknown {noun}: {n}', {})
            for n in ('unknown__x', 'no_separator', 'github', 'confluence__x')
        ),
        (method, {'name': ''}, SERVERS, requires, {}),
        (method, {}, SERVERS, requires, {}),
        (method, {'name': 7}, SERVERS, requires, {}),
        (
            method,
            {'name': 'github__x', 'arguments': 'not-a-dict'},
            SERVERS,
            'params.arguments must be an object',
            {'alias': 'github', 'target': 'x'},
        ),
        # A top-level alias not exposed on this route is invisible.
        (
            method,
            {'name': 'jira__search'},
            [GITHUB],
            f'Unknown {noun}: jira__search',
            {},
        ),
    ]


ENCODED_FOREIGN = encode_resource_uri('confluence', 'https://x')
ENCODED_JIRA = encode_resource_uri('jira', 'https://jira.example.com/board')


@pytest.mark.parametrize(
    ('method', 'params', 'servers', 'message', 'attributed'),
    [
        *_rejections('tools/call', 'tool', 'name'),
        *_rejections('prompts/get', 'prompt', 'name'),
        *(
            ('resources/read', params, SERVERS, message, {})
            for params, message in (
                ({}, 'resources/read requires a string params.uri'),
                ({'uri': 7}, 'resources/read requires a string params.uri'),
                ({'uri': ''}, 'resources/read requires a string params.uri'),
                # not one of our wrapped URIs
                (
                    {'uri': 'https://example.com/plain'},
                    'Unknown resource: https://example.com/plain',
                ),
                ({'uri': ENCODED_FOREIGN}, f'Unknown resource: {ENCODED_FOREIGN}'),
            )
        ),
        (
            'resources/read',
            {'uri': ENCODED_JIRA},
            [GITHUB],
            f'Unknown resource: {ENCODED_JIRA}',
            {},
        ),
    ],
)
async def test_a_call_naming_nothing_on_the_route_is_32602_and_never_forwarded(
    recorded_events, method, params, servers, message, attributed
):
    """Params is client-controlled, so a name resolving to no configured
    server is never echoed into a span attribute or the event (unbounded
    cardinality); it stays diagnosable from the error message, which becomes
    the span status description. It is not blamed on an allowlist either.
    Misdirected traffic is still counted, without an alias, so the totals
    stay comparable.
    """
    client = _invoking_client()

    with patch(f'{MCP_SERVICE}.set_mcp_attributes') as mock_set_attrs:
        result = await _dispatch(_request(method, params=params), servers, client)

    assert result.status_code == 200
    assert result.payload == _error(-32602, message)
    client.call_tool.assert_not_awaited()
    client.get_prompt.assert_not_awaited()
    client.read_resource.assert_not_awaited()
    assert _attrs(mock_set_attrs) == {'method': method, **attributed}
    assert _invocation(recorded_events) == (
        method,
        attributed.get('alias', ''),
        attributed.get('target', ''),
    )


TIMED_OUT = "Upstream MCP server 'github' timed out"


@pytest.mark.parametrize(
    ('method', 'params', 'upstream'),
    [
        ('tools/call', {'name': 'github__get_issue'}, 'call_tool'),
        ('prompts/get', {'name': 'github__summarize'}, 'get_prompt'),
        (
            'resources/read',
            {'uri': encode_resource_uri('github', README)},
            'read_resource',
        ),
    ],
)
async def test_an_upstream_error_maps_to_32000_and_is_still_recorded(
    recorded_events, method, params, upstream
):
    """An operator needs to see a key that keeps failing, not lose it."""
    client = MagicMock(spec_set=McpUpstreamClient)
    setattr(
        client, upstream, AsyncMock(side_effect=McpUpstreamError('github', TIMED_OUT))
    )

    result = await _dispatch(_request(method, params=params), client=client)

    assert result.status_code == 200
    assert result.payload == _error(-32000, TIMED_OUT)
    assert _invocation(recorded_events)[:2] == (method, 'github')


async def test_unexpected_exception_is_sanitized_internal_error():
    client = MagicMock(spec_set=McpUpstreamClient)
    client.call_tool = AsyncMock(side_effect=ValueError('secret detail'))

    result = await _dispatch(
        _request('tools/call', params={'name': 'github__get_issue'}), client=client
    )

    assert result.status_code == 200
    assert result.payload == _error(-32603, 'Internal error')


WRAPPED_A = encode_resource_uri('github', RESOURCE_A)


@pytest.mark.parametrize(
    ('method', 'params', 'upstream', 'allowlist', 'target', 'denied_message'),
    [
        (
            'tools/call',
            {'name': 'github__a'},
            'call_tool',
            {'allowed_tools': ['a']},
            'a',
            None,
        ),
        *(
            (
                'tools/call',
                {'name': 'github__a'},
                'call_tool',
                {'allowed_tools': allow},
                'a',
                'Unknown tool: github__a',
            )
            for allow in (['b'], [])
        ),
        (
            'prompts/get',
            {'name': 'github__a'},
            'get_prompt',
            {'allowed_prompts': ['a']},
            'a',
            None,
        ),
        *(
            (
                'prompts/get',
                {'name': 'github__a'},
                'get_prompt',
                {'allowed_prompts': allow},
                'a',
                'Unknown prompt: github__a',
            )
            for allow in (['b'], [])
        ),
        (
            'resources/read',
            {'uri': WRAPPED_A},
            'read_resource',
            {'allowed_resources': [RESOURCE_A]},
            RESOURCE_A,
            None,
        ),
        *(
            (
                'resources/read',
                {'uri': WRAPPED_A},
                'read_resource',
                {'allowed_resources': allow},
                RESOURCE_A,
                f'Unknown resource: {WRAPPED_A}',
            )
            for allow in ([RESOURCE_B], [])
        ),
    ],
)
async def test_a_call_outside_the_allowlist_is_rejected_attributably(
    recorded_events, method, params, upstream, allowlist, target, denied_message
):
    """Never listed is no defense: a cached list will still call it.

    A denial is indistinguishable from a target that does not exist, so the
    allowlist does not confirm what it hides; the ``denied`` span attribute
    is what tells a policy rejection from a typo. A denied call is still an
    invocation.
    """
    client = _invoking_client()

    with patch(f'{MCP_SERVICE}.set_mcp_attributes') as mock_set_attrs:
        result = await _dispatch(
            _request(method, params=params), [_server(**allowlist)], client
        )

    forwarded = getattr(client, upstream)
    expected_attrs = {'method': method, 'alias': 'github', 'target': target}
    if denied_message is None:
        assert 'error' not in result.payload
        assert forwarded.await_args.args[1] == target
        assert _attrs(mock_set_attrs) == expected_attrs
    else:
        assert result.status_code == 200
        assert result.payload == _error(-32602, denied_message)
        forwarded.assert_not_awaited()
        assert _attrs(mock_set_attrs) == {**expected_attrs, 'denied': 'allowlist'}
    assert _invocation(recorded_events) == (method, 'github', target)


async def test_an_invocation_carries_the_request_envelope(recorded_events):
    set_current_request_tags(('env=prod', 'team=retail'))
    try:
        await _dispatch(
            _request('tools/call', params={'name': 'github__get_issue'}),
            client=_invoking_client(),
        )
    finally:
        set_current_request_tags(())

    (event,) = _mcp_events(recorded_events)
    assert event['REQUEST_UUID'] == 'request-uuid'
    assert event['ROUTE_NAME'] == 'my-route'
    assert event['API_KEY_UUID'] == 'key-uuid'
    assert event['API_KEY_NAME'] == 'my-key'
    assert event['GROUP_UUID'] == 'group-uuid'
    assert event['GROUP_NAME'] == 'team-a'
    assert event['PROJECT_UUID'] == 'project-uuid'
    assert event['PROJECT_NAME'] == 'my-project'
    assert event['TAGS'] == ['env=prod', 'team=retail']


async def test_recording_never_fails_the_call():
    """Observability must not be able to take the proxy down."""
    client = _invoking_client()
    with patch(f'{MCP_SERVICE}.emit_event', side_effect=RuntimeError('broker down')):
        result = await _dispatch(
            _request('tools/call', params={'name': 'github__get_issue'}),
            client=client,
        )

    assert result.status_code == 200
    assert 'result' in result.payload
    client.call_tool.assert_awaited_once()


# ---------------------------------------------------------------------------
# List cache
# ---------------------------------------------------------------------------


def _list_cache(servers=SERVERS) -> McpListCache:
    """Build a real in-memory cache, wired as the endpoint wires it.

    for_route returns None for a route that must not be cached; these tests all
    use cacheable routes, so the assert both narrows the type and fails loudly
    if a guard ever starts firing on one of them.
    """
    cache = McpListCache.for_route(
        gateway_cache=GatewayCache(CacheToolsInMemory()),
        ttl=None,
        authorized=_authorized(servers),
    )
    assert cache is not None, 'expected these servers to be cacheable'
    return cache


@KINDS
async def test_a_second_list_is_served_from_cache_and_reported(
    emitted_cache_hits, kind
):
    """One fan-out for the two requests, not one per server per request. A
    hit contacted no upstream, so its span records no fan-out counts, and it
    reaches the usage view and alert rules as a CACHE_HIT event.
    """
    attr = LISTS[kind][0]
    client = MagicMock(spec_set=McpUpstreamClient)
    setattr(
        client,
        attr,
        AsyncMock(side_effect=[_listing(kind, 'get'), _listing(kind, 'search')]),
    )
    service, cache = _service(client), _list_cache()
    request = _request(f'{kind}/list')

    first = await _dispatch(request, cache=cache, service=service)
    assert emitted_cache_hits.call_count == 0  # the miss that populated it
    span = _recording_span()
    with patch(f'{MCP_SERVICE}.get_current_span', return_value=span):
        second = await _dispatch(request, cache=cache, service=service)

    assert second.payload['result'] == first.payload['result']
    # the wrapped uri survives the round trip through the cache
    assert _ids(kind, second.payload) == [
        _exposed(kind, 'github', 'get'),
        _exposed(kind, 'jira', 'search'),
    ]
    assert getattr(client, attr).await_count == len(SERVERS)
    assert _span_attrs(span) == {
        'rb.gateway.mcp_cache_hit': True,
        'rb.gateway.mcp_result_count': 2,
    }
    event = emitted_cache_hits.call_args.args[0]
    assert event.event_type is EventType.CACHE_HIT
    assert event.route_name == 'my-route'
    assert event.api_key_uuid == 'key-uuid'
    assert emitted_cache_hits.call_count == 1


async def test_one_cached_method_never_answers_another():
    client = MagicMock(spec_set=McpUpstreamClient)
    client.list_tools = AsyncMock(return_value=types.ListToolsResult(tools=[]))
    client.list_prompts = AsyncMock(return_value=_listing('prompts', 'summarize'))
    service, cache = _service(client), _list_cache()

    await _dispatch(_request('tools/list'), cache=cache, service=service)
    result = await _dispatch(_request('prompts/list'), cache=cache, service=service)

    assert _ids('prompts', result.payload) == [
        'github__summarize',
        'jira__summarize',
    ]


@pytest.mark.parametrize(
    ('first_answers', 'degraded_ids'),
    [
        pytest.param(
            [McpUpstreamError('github', 'boom'), _listing('tools', 'search')],
            ['jira__search'],
            id='partial',
        ),
        pytest.param(
            [McpUpstreamError('github', 'boom'), McpUpstreamError('jira', 'boom')],
            None,
            id='failed',
        ),
    ],
)
async def test_a_degraded_fanout_is_never_cached(
    emitted_cache_hits, first_answers, degraded_ids
):
    """A transient outage must not pin a truncated list for the whole TTL."""
    client = MagicMock(spec_set=McpUpstreamClient)
    client.list_tools = AsyncMock(
        side_effect=[
            *first_answers,
            _listing('tools', 'get_issue'),
            _listing('tools', 'search'),
        ]
    )
    service, cache = _service(client), _list_cache()

    degraded = await _dispatch(_request('tools/list'), cache=cache, service=service)
    recovered = await _dispatch(_request('tools/list'), cache=cache, service=service)

    if degraded_ids is None:
        assert degraded.payload == _error(-32000, 'All upstream MCP servers failed')
    else:
        assert _ids('tools', degraded.payload) == degraded_ids
    assert _ids('tools', recovered.payload) == ['github__get_issue', 'jira__search']
    assert client.list_tools.await_count == 2 * len(SERVERS)
    emitted_cache_hits.assert_not_called()
