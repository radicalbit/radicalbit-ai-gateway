from unittest.mock import MagicMock, patch

import pytest

from radicalbit_ai_gateway.caching.gateway_cache import GatewayCache
from radicalbit_ai_gateway.caching.in_memory_cache import CacheToolsInMemory
from radicalbit_ai_gateway.caching.redis_cache import RedisCache
from radicalbit_ai_gateway.caching.semantic_caching import SemanticCache
from radicalbit_ai_gateway.mcp_proxy.list_cache import (
    DEFAULT_LIST_TTL_SECONDS,
    PROMPTS_LIST,
    RESOURCES_LIST,
    TOOLS_LIST,
    McpListCache,
    servers_signature,
)
from radicalbit_ai_gateway.models.auth_dto import KeyDetails
from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.models.mcp_authorized_request import McpAuthorizedRequest
from radicalbit_ai_gateway.models.mcp_server import McpHttpServer, McpStdioServer

GITHUB = McpHttpServer(alias='github', url='https://github.example.com/mcp/')
JIRA = McpHttpServer(alias='jira', url='https://jira.example.com/mcp/')
SERVERS = [GITHUB, JIRA]

PROJECT = 'project-uuid'
ROUTE = 'my-route'
KEY = 'key-uuid'

LIST_CACHE = 'radicalbit_ai_gateway.mcp_proxy.list_cache'


def _in_memory_cache() -> GatewayCache:
    return GatewayCache(CacheToolsInMemory())


def _authorized(
    servers: list = SERVERS,
    key_uuid: str = KEY,
    route_name: str = ROUTE,
    project_uuid: str = PROJECT,
) -> McpAuthorizedRequest:
    return McpAuthorizedRequest(
        request_uuid='request-uuid',
        project_name='my-project',
        project_uuid=project_uuid,
        route_name=route_name,
        route_key=f'my-project/{route_name}',
        key_details=KeyDetails(
            api_key_uuid=key_uuid,
            api_key_name='my-key',
            group_uuid='group-uuid',
            group_name='team-a',
            hashed_api_key='hashed',
        ),
        servers=servers,
    )


def _for_route(
    gateway_cache: GatewayCache | None = None,
    servers: list = SERVERS,
    ttl: int | None = None,
    key_uuid: str = KEY,
    route_name: str = ROUTE,
    project_uuid: str = PROJECT,
) -> McpListCache | None:
    return McpListCache.for_route(
        gateway_cache=gateway_cache
        if gateway_cache is not None
        else _in_memory_cache(),
        ttl=ttl,
        authorized=_authorized(
            servers=servers,
            key_uuid=key_uuid,
            route_name=route_name,
            project_uuid=project_uuid,
        ),
    )


def _cache(**kwargs) -> McpListCache:
    """Return the cache a cacheable route gets, narrowed out of the optional."""
    cache = _for_route(**kwargs)
    assert cache is not None, 'expected this route to be cacheable'
    return cache


def _http(alias='github', url='https://github.example.com/mcp/', **kwargs):
    return McpHttpServer(alias=alias, url=url, **kwargs)


def _stdio(**kwargs):
    return McpStdioServer(alias='local', command='python', **kwargs)


PER_CALLER = _http(forward_headers=['authorization'])


@pytest.mark.parametrize(
    'make',
    [
        pytest.param(
            lambda: McpListCache.for_route(None, None, _authorized()), id='no-caching'
        ),
        pytest.param(lambda: _for_route(servers=[]), id='no-servers'),
        # A list method has no query text to embed, so similarity search is moot.
        pytest.param(
            lambda: _for_route(
                gateway_cache=GatewayCache(MagicMock(spec_set=SemanticCache))
            ),
            id='semantic-cache',
        ),
        # The list may legitimately differ per caller, so no entry is shareable.
        pytest.param(
            lambda: _for_route(servers=[PER_CALLER, JIRA]), id='forward-headers-first'
        ),
        pytest.param(
            lambda: _for_route(servers=[JIRA, PER_CALLER]), id='forward-headers-last'
        ),
    ],
)
def test_a_route_that_cannot_share_a_list_gets_no_cache(make):
    assert make() is None


def test_each_list_method_has_its_own_key():
    keys = {_cache()._key(m) for m in (TOOLS_LIST, PROMPTS_LIST, RESOURCES_LIST)}
    assert len(keys) == 3


TENANT_A = _http(headers={'authorization': 'Bearer tenant-a'})


@pytest.mark.parametrize(
    ('one', 'other', 'same'),
    [
        # Entries are scoped like every other cached response.
        pytest.param({}, {'key_uuid': 'another-key'}, False, id='another-key'),
        pytest.param({}, {'route_name': 'other-route'}, False, id='another-route'),
        pytest.param(
            {}, {'project_uuid': 'other-project'}, False, id='another-project'
        ),
        pytest.param(
            {'servers': [GITHUB, JIRA]},
            {'servers': [JIRA, GITHUB]},
            True,
            id='reordered-servers',
        ),
        # Same alias, different upstream: the old server's tools must not survive.
        pytest.param(
            {'servers': [GITHUB]},
            {'servers': [_http(url='https://elsewhere.example.com/mcp/')]},
            False,
            id='repointed-alias',
        ),
        pytest.param(
            {'servers': [GITHUB]}, {'servers': SERVERS}, False, id='added-server'
        ),
        pytest.param(
            {'servers': [_stdio(args=['-m', 'a'])]},
            {'servers': [_stdio(args=['-m', 'b'])]},
            False,
            id='stdio-command-line',
        ),
        # The credential selects which tools the upstream exposes, so it is
        # identity: another tenant's token, or a token where there was none.
        pytest.param(
            {'servers': [TENANT_A]},
            {'servers': [_http(headers={'authorization': 'Bearer tenant-b'})]},
            False,
            id='rotated-static-header',
        ),
        pytest.param(
            {'servers': [TENANT_A]}, {'servers': [GITHUB]}, False, id='added-credential'
        ),
        pytest.param(
            {'servers': [_stdio(env={'TOKEN': 'a'})]},
            {'servers': [_stdio(env={'TOKEN': 'b'})]},
            False,
            id='stdio-env',
        ),
        # The signature keys on the credential set, not on dict insertion order.
        pytest.param(
            {
                'servers': [
                    _http(headers={'authorization': 'Bearer t', 'x-tenant': 'a'})
                ]
            },
            {
                'servers': [
                    _http(headers={'x-tenant': 'a', 'authorization': 'Bearer t'})
                ]
            },
            True,
            id='reordered-headers',
        ),
    ],
)
def test_the_entry_key_follows_scope_and_upstream_identity(one, other, same):
    assert (_cache(**one)._key(TOOLS_LIST) == _cache(**other)._key(TOOLS_LIST)) is same


def test_a_credential_never_reaches_the_signature_in_the_clear():
    secret = 'Bearer super-secret'
    assert secret not in servers_signature([_http(headers={'authorization': secret})])


async def test_a_stored_result_round_trips():
    cache = _cache()
    result = {'tools': [{'name': 'github__get_issue', 'description': 'a tool'}]}
    await cache.set(TOOLS_LIST, result)
    assert await cache.get(TOOLS_LIST) == result
    assert await cache.get(PROMPTS_LIST) is None


@pytest.mark.parametrize(
    ('ttl', 'expected'),
    [(30, 30), (None, DEFAULT_LIST_TTL_SECONDS), (0, DEFAULT_LIST_TTL_SECONDS)],
)
async def test_the_caching_ttl_is_passed_through_and_an_entry_always_expires(
    ttl, expected
):
    client = MagicMock(spec_set=CacheToolsInMemory)
    cache = _cache(gateway_cache=GatewayCache(client), ttl=ttl)
    await cache.set(TOOLS_LIST, {'tools': []})
    assert client.set.await_args.args[2] == expected


@pytest.mark.parametrize(
    'stored',
    [
        '{not json',
        '["a", "list"]',
        '"a string"',
        '{}',
        '{"tools_v2": []}',
        '{"tools": {"get_issue": {}}}',
        '{"tools": null}',
    ],
)
async def test_an_unusable_entry_is_a_miss_not_an_error(stored):
    client = MagicMock(spec_set=CacheToolsInMemory)
    client.get.return_value = stored
    cache = _cache(gateway_cache=GatewayCache(client))
    assert await cache.get(TOOLS_LIST) is None


# ---------------------------------------------------------------------------
# Reporting a hit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ('gateway_cache', 'method', 'cache_type'),
    [
        # in-memory stands in for redis when the project has no cache: block
        (None, TOOLS_LIST, 'in-memory'),
        (GatewayCache(MagicMock(spec_set=RedisCache)), RESOURCES_LIST, 'exact'),
    ],
)
def test_a_hit_emits_a_cache_hit_event_under_the_callers_identity(
    gateway_cache, method, cache_type
):
    """The same event /v1 emits, so MCP hits reach the usage view and alerts.

    A list method invokes no model, so the event claims no model and no saving.
    """
    with (
        patch(f'{LIST_CACHE}.emit_event') as mock_emit,
        patch(f'{LIST_CACHE}.cache_hit_counter') as mock_counter,
    ):
        _cache(gateway_cache=gateway_cache).record_hit(method)

    event = mock_emit.call_args.args[0]
    assert event.event_type is EventType.CACHE_HIT
    assert event.value == 1.0
    assert event.route_name == ROUTE
    assert event.project_uuid == PROJECT
    assert event.api_key_uuid == KEY
    assert event.api_key_name == 'my-key'
    assert event.group_uuid == 'group-uuid'
    assert event.request_uuid == 'request-uuid'
    assert event.cache_type == cache_type
    assert event.model_id == ''
    assert event.cost == 0.0
    mock_counter.add.assert_called_once_with(1, {'route_name': ROUTE})


@pytest.mark.parametrize('method', ['tools/call', 'initialize'])
async def test_a_method_that_is_not_a_list_is_never_served(method):
    client = MagicMock(spec_set=CacheToolsInMemory)
    assert await _cache(gateway_cache=GatewayCache(client)).get(method) is None
    client.get.assert_not_awaited()
