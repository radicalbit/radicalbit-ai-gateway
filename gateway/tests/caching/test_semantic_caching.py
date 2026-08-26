"""Semantic cache isolation.

The exact cache is isolated by its storage key alone; a semantic lookup is not.
It is a KNN query over a single prefix-less index that spans every project, so
isolation lives entirely in the tag filter — the schema, the stored mapping and
the query have to agree on the project.
"""

import asyncio
import re

import numpy as np
import pytest
from redis.exceptions import ResponseError

from tests.common.db_mock import API_KEY_UUID, SAMPLE_PROJECT_UUID, TEST_PROJECT_UUID

from radicalbit_ai_gateway.caching.semantic_caching import SemanticCache

PROJECT_A = str(TEST_PROJECT_UUID)
PROJECT_B = str(SAMPLE_PROJECT_UUID)
ROUTE_NAME = 'default'
KEY_UUID = str(API_KEY_UUID)
DIM = 4

_TAG_FILTER = re.compile(r'@(\w+):\{([^}]*)\}')
_KNN = re.compile(r'KNN (\d+)')


class FakeSearchIndex:
    """Enough of RediSearch to exercise the tag filter and the KNN ordering."""

    def __init__(self, client: 'FakeSearchRedis', index_name: str):
        self.client = client
        self.index_name = index_name

    async def create_index(self, schema, definition=None) -> None:
        if self.index_name in self.client.indexes:
            raise ResponseError('Index already exists')
        self.client.indexes[self.index_name] = [field.name for field in schema]

    async def search(self, query, query_params=None):
        indexed_fields = self.client.indexes.get(self.index_name)
        if indexed_fields is None:
            raise ResponseError(f'{self.index_name}: no such index')

        query_string = query.query_string()
        self.client.queries.append(query_string)
        # Matched verbatim, as valkey-search does: an escaped value will not
        # match a stored tag, which is what makes escaping a regression here.
        filters = dict(_TAG_FILTER.findall(query_string))
        unknown = set(filters) - set(indexed_fields)
        if unknown:
            raise ResponseError(f'Unknown field(s) at index: {sorted(unknown)}')

        query_vector = np.frombuffer(query_params['query_vector'], dtype=np.float32)
        matches = []
        for document in self.client.hashes.values():
            if any(document.get(field) != value for field, value in filters.items()):
                continue
            stored = np.frombuffer(document['embedding'], dtype=np.float32)
            distance = 1 - float(
                np.dot(stored, query_vector)
                / (np.linalg.norm(stored) * np.linalg.norm(query_vector))
            )
            matches.append(FakeDocument(document['response'], distance))
        matches.sort(key=lambda document: float(document.score))
        return FakeSearchResult(matches[: int(_KNN.search(query_string).group(1))])


class FakeDocument:
    def __init__(self, response: str, score: float):
        self.response = response
        self.score = str(score)


class FakeSearchResult:
    def __init__(self, docs: list[FakeDocument]):
        self.docs = docs


class FakeSearchRedis:
    def __init__(self):
        self.hashes: dict[str, dict] = {}
        self.indexes: dict[str, list[str]] = {}
        self.queries: list[str] = []
        self.expirations: dict[str, int] = {}

    def ft(self, index_name: str) -> FakeSearchIndex:
        return FakeSearchIndex(self, index_name)

    async def hset(self, name: str, mapping: dict | None = None) -> None:
        self.hashes.setdefault(name, {}).update(mapping or {})

    async def expire(self, name: str, ttl: int) -> None:
        self.expirations[name] = ttl


async def _build_cache(redis_client: FakeSearchRedis) -> SemanticCache:
    cache = SemanticCache(
        redis_client=redis_client,
        similarity_threshold=0.8,
        dim=DIM,
        distance_metric='cosine',
    )
    # The constructor creates the index in the background.
    await asyncio.gather(*list(cache._background_tasks))
    return cache


def _embedding(*values: float) -> np.ndarray:
    return np.array(values, dtype=np.float32)


def _cache_key(project_uuid: str) -> str:
    return f'response:aigateway:cache:{project_uuid}:{ROUTE_NAME}:{KEY_UUID}:abc123'


@pytest.mark.asyncio
async def test_index_declares_the_project_field():
    redis_client = FakeSearchRedis()
    await _build_cache(redis_client)
    assert 'project_uuid' in redis_client.indexes['ai_gateway_idx']


@pytest.mark.asyncio
async def test_semantic_lookup_still_hits_after_the_key_format_change():
    """Regression test for deriving the filter from the key by position.

    ``cache_key.split(':')[3]`` used to yield the route name; with the project
    inserted ahead of it, it yields the project UUID instead, the filter becomes
    ``@route_name:{<uuid>}`` and the lookup misses silently — no exception, no
    log. The scope now travels as explicit kwargs.
    """
    redis_client = FakeSearchRedis()
    cache = await _build_cache(redis_client)
    embeddings = _embedding(1, 0, 0, 0)
    scope = {
        'project_uuid': PROJECT_A,
        'route_name': ROUTE_NAME,
        'key_uuid': KEY_UUID,
        'embeddings': embeddings,
    }

    await cache.set(_cache_key(PROJECT_A), 'Paris', 120, **scope)
    assert await cache.get(_cache_key(PROJECT_A), **scope) == 'Paris'
    assert redis_client.expirations[_cache_key(PROJECT_A)] == 120


@pytest.mark.asyncio
async def test_semantic_lookup_does_not_leak_across_projects():
    """Same route name, same API key, one index: no cross-project match.

    Covers both leak paths from the report — a group bound to routes in two
    projects, and a key reassigned to another project's group — since either way
    the same ``key_uuid`` queries the same route name.
    """
    redis_client = FakeSearchRedis()
    cache = await _build_cache(redis_client)
    embeddings = _embedding(1, 0, 0, 0)

    await cache.set(
        _cache_key(PROJECT_A),
        'Paris',
        None,
        project_uuid=PROJECT_A,
        route_name=ROUTE_NAME,
        key_uuid=KEY_UUID,
        embeddings=embeddings,
    )

    assert (
        await cache.get(
            _cache_key(PROJECT_B),
            project_uuid=PROJECT_B,
            route_name=ROUTE_NAME,
            key_uuid=KEY_UUID,
            embeddings=embeddings,
        )
        is None
    )


@pytest.mark.asyncio
async def test_semantic_lookup_ignores_another_route_in_the_same_project():
    redis_client = FakeSearchRedis()
    cache = await _build_cache(redis_client)
    embeddings = _embedding(1, 0, 0, 0)

    await cache.set(
        _cache_key(PROJECT_A),
        'Paris',
        None,
        project_uuid=PROJECT_A,
        route_name=ROUTE_NAME,
        key_uuid=KEY_UUID,
        embeddings=embeddings,
    )

    assert (
        await cache.get(
            _cache_key(PROJECT_A),
            project_uuid=PROJECT_A,
            route_name='another-route',
            key_uuid=KEY_UUID,
            embeddings=embeddings,
        )
        is None
    )


@pytest.mark.asyncio
async def test_a_distant_embedding_is_not_a_hit():
    redis_client = FakeSearchRedis()
    cache = await _build_cache(redis_client)
    scope = {
        'project_uuid': PROJECT_A,
        'route_name': ROUTE_NAME,
        'key_uuid': KEY_UUID,
    }

    await cache.set(
        _cache_key(PROJECT_A),
        'Paris',
        None,
        embeddings=_embedding(1, 0, 0, 0),
        **scope,
    )

    assert (
        await cache.get(
            _cache_key(PROJECT_A), embeddings=_embedding(0, 1, 0, 0), **scope
        )
        is None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize('missing', ['project_uuid', 'route_name', 'key_uuid'])
async def test_an_incomplete_scope_fails_loudly(missing: str):
    """A missing scope value must raise, not degrade to a silent miss."""
    redis_client = FakeSearchRedis()
    cache = await _build_cache(redis_client)
    scope = {
        'project_uuid': PROJECT_A,
        'route_name': ROUTE_NAME,
        'key_uuid': KEY_UUID,
        'embeddings': _embedding(1, 0, 0, 0),
    }
    del scope[missing]

    with pytest.raises(ValueError, match=missing):
        await cache.get(_cache_key(PROJECT_A), **scope)


@pytest.mark.asyncio
@pytest.mark.parametrize('missing', ['project_uuid', 'route_name'])
async def test_writing_without_a_scope_fails_loudly(missing: str):
    redis_client = FakeSearchRedis()
    cache = await _build_cache(redis_client)
    scope = {
        'project_uuid': PROJECT_A,
        'route_name': ROUTE_NAME,
        'key_uuid': KEY_UUID,
        'embeddings': _embedding(1, 0, 0, 0),
    }
    del scope[missing]

    with pytest.raises(ValueError, match=missing):
        await cache.set(_cache_key(PROJECT_A), 'Paris', None, **scope)


def test_tag_values_are_not_escaped():
    """valkey-search matches tag values verbatim.

    Escaping the ``-`` in a route name or UUID makes the backslash part of the
    value, so the filter matches nothing. Verified against valkey-search 8.1.4:
    the unescaped filter returns the document, the escaped one returns zero.
    """
    conditions = SemanticCache._build_filter_conditions(
        project_uuid=PROJECT_A, route_name='rb-gateway', key_uuid=KEY_UUID
    )
    assert '\\' not in conditions
    assert '@route_name:{rb-gateway}' in conditions
    assert f'@project_uuid:{{{PROJECT_A}}}' in conditions
