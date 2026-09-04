from unittest.mock import MagicMock, patch

import pytest

from radicalbit_ai_gateway.caching.gateway_cache import GatewayCache
from radicalbit_ai_gateway.caching.in_memory_cache import CacheToolsInMemory
from radicalbit_ai_gateway.caching.redis_cache import RedisCache
from radicalbit_ai_gateway.caching.semantic_caching import SemanticCache
from radicalbit_ai_gateway.mcp_proxy.list_cache import (
    PROMPTS_LIST,
    RESOURCES_LIST,
    TOOLS_LIST,
    McpListCache,
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


def test_a_route_without_caching_gets_no_cache():
    assert McpListCache.for_route(None, None, _authorized()) is None


def test_a_route_without_servers_gets_no_cache():
    assert _for_route(servers=[]) is None


def test_the_semantic_cache_is_excluded():
    """A list method has no query text to embed, so similarity search is moot."""
    semantic = GatewayCache(MagicMock(spec_set=SemanticCache))
    assert _for_route(gateway_cache=semantic) is None


def test_forward_headers_disables_caching_for_the_whole_route():
    """The list may legitimately differ per caller, so no entry is shareable."""
    per_caller = McpHttpServer(
        alias='github',
        url='https://github.example.com/mcp/',
        forward_headers=['authorization'],
    )
    assert _for_route(servers=[per_caller, JIRA]) is None
    assert _for_route(servers=[JIRA, per_caller]) is None


def test_stdio_servers_never_carry_forward_headers():
    stdio = McpStdioServer(alias='local', command='python', args=['-m', 'server'])
    assert _for_route(servers=[stdio]) is not None


def test_each_list_method_has_its_own_key():
    keys = {_cache()._key(m) for m in (TOOLS_LIST, PROMPTS_LIST, RESOURCES_LIST)}
    assert len(keys) == 3


@pytest.mark.parametrize(
    'other',
    [
        {'key_uuid': 'another-key'},
        {'route_name': 'other-route'},
        {'project_uuid': 'other-project'},
    ],
)
def test_entries_are_scoped_like_every_other_cached_response(other):
    assert _cache()._key(TOOLS_LIST) != _cache(**other)._key(TOOLS_LIST)


def test_reordering_the_same_servers_still_hits():
    assert _cache(servers=[GITHUB, JIRA])._key(TOOLS_LIST) == _cache(
        servers=[JIRA, GITHUB]
    )._key(TOOLS_LIST)


def test_repointing_an_alias_invalidates_the_entry():
    """Same alias, different upstream: the old server's tools must not survive."""
    moved = McpHttpServer(alias='github', url='https://elsewhere.example.com/mcp/')
    assert _cache(servers=[GITHUB])._key(TOOLS_LIST) != _cache(servers=[moved])._key(
        TOOLS_LIST
    )


def test_adding_a_server_invalidates_the_entry():
    assert _cache(servers=[GITHUB])._key(TOOLS_LIST) != _cache(servers=SERVERS)._key(
        TOOLS_LIST
    )


def test_a_stdio_server_is_identified_by_its_command_line():
    base = McpStdioServer(alias='local', command='python', args=['-m', 'a'])
    other_args = McpStdioServer(alias='local', command='python', args=['-m', 'b'])
    assert _cache(servers=[base])._key(TOOLS_LIST) != _cache(servers=[other_args])._key(
        TOOLS_LIST
    )


async def test_a_stored_result_round_trips():
    cache = _cache()
    result = {'tools': [{'name': 'github__get_issue', 'description': 'a tool'}]}
    await cache.set(TOOLS_LIST, result)
    assert await cache.get(TOOLS_LIST) == result
    assert await cache.get(PROMPTS_LIST) is None


async def test_the_ttl_from_the_caching_block_is_passed_through():
    client = MagicMock(spec_set=CacheToolsInMemory)
    cache = _cache(gateway_cache=GatewayCache(client), ttl=30)
    await cache.set(TOOLS_LIST, {'tools': []})
    assert client.set.await_args.args[2] == 30


@pytest.mark.parametrize('stored', ['{not json', '["a", "list"]', '"a string"'])
async def test_an_unusable_entry_is_a_miss_not_an_error(stored):
    client = MagicMock(spec_set=CacheToolsInMemory)
    client.get.return_value = stored
    cache = _cache(gateway_cache=GatewayCache(client))
    assert await cache.get(TOOLS_LIST) is None


# ---------------------------------------------------------------------------
# Reporting a hit
# ---------------------------------------------------------------------------


def test_a_hit_emits_a_cache_hit_event_under_the_callers_identity():
    """The same event /v1 emits, so MCP hits reach the usage view and alerts."""
    with (
        patch(f'{LIST_CACHE}.emit_event') as mock_emit,
        patch(f'{LIST_CACHE}.cache_hit_counter') as mock_counter,
    ):
        _cache().record_hit(TOOLS_LIST)

    event = mock_emit.call_args.args[0]
    assert event.event_type is EventType.CACHE_HIT
    assert event.value == 1.0
    assert event.route_name == ROUTE
    assert event.project_uuid == PROJECT
    assert event.api_key_uuid == KEY
    assert event.api_key_name == 'my-key'
    assert event.group_uuid == 'group-uuid'
    assert event.request_uuid == 'request-uuid'
    # in-memory stands in for redis when the project has no cache: block
    assert event.cache_type == 'in-memory'
    mock_counter.add.assert_called_once_with(1, {'route_name': ROUTE})


def test_the_event_claims_no_model_and_no_saving():
    """A list method invokes no model, so it prices nothing."""
    with (
        patch(f'{LIST_CACHE}.emit_event') as mock_emit,
        patch(f'{LIST_CACHE}.cache_hit_counter'),
    ):
        _cache().record_hit(PROMPTS_LIST)

    event = mock_emit.call_args.args[0]
    assert event.model_id == ''
    # nothing is claimed against the cache-savings columns either
    assert event.cost == 0.0


def test_an_exact_cache_reports_its_own_type():
    exact = GatewayCache(MagicMock(spec_set=RedisCache))
    with (
        patch(f'{LIST_CACHE}.emit_event') as mock_emit,
        patch(f'{LIST_CACHE}.cache_hit_counter'),
    ):
        _cache(gateway_cache=exact).record_hit(RESOURCES_LIST)

    assert mock_emit.call_args.args[0].cache_type == 'exact'
