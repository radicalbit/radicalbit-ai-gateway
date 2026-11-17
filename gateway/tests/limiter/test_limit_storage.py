"""The limiter storage contract, on Redis and in memory alike.

A counter lives in a window: it accumulates under one window id until its TTL
expires, then the next increment opens a new window with a new id. In memory
the clock is frozen and ticked past the TTL; on Redis the key is expired now.
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
import time
from typing import Callable

from freezegun import freeze_time
import pytest
from redis import Redis

from radicalbit_ai_gateway.limiter.storage.base import Storage
from radicalbit_ai_gateway.limiter.storage.memory import InMemoryStorage
from radicalbit_ai_gateway.limiter.storage.redis import RedisStorage

KEY = 'test-key'


def _now() -> int:
    return time.time_ns() // 1_000_000_000


@dataclass
class Backend:
    storage: Storage
    expire: Callable[[str], None]
    # Redis reports a whole-second TTL that may already have ticked down.
    ttl_slack: int


def _expire_on_redis(client: Redis, key: str) -> None:
    """Let Redis expire *key* now rather than wait out its one-second TTL."""
    client.pexpire(key, 1)
    while client.exists(key):
        time.sleep(0.005)


@pytest.fixture(params=['memory', 'redis'])
async def backend(request):
    if request.param == 'memory':
        with freeze_time(datetime(2024, 1, 1, 12, tzinfo=UTC)) as frozen:
            yield Backend(InMemoryStorage(), lambda key: frozen.tick(2), ttl_slack=0)
        return
    url = request.getfixturevalue('redis_connection_url')
    client = Redis.from_url(url)
    client.flushdb()
    storage = RedisStorage(uri=url)
    yield Backend(storage, lambda key: _expire_on_redis(client, key), ttl_slack=1)
    await storage.close()


async def test_a_counter_accumulates_in_one_window_under_one_id(backend) -> None:
    storage = backend.storage

    value, window_id = await storage.increment(
        KEY, 5, ttl_seconds=60, window_start=_now()
    )
    assert value == 5
    assert window_id is not None
    assert await storage.get_window_id(KEY) == window_id
    assert len(window_id) == 36  # UUID format

    value, same_id = await storage.increment(
        KEY, 3, ttl_seconds=60, window_start=_now()
    )
    assert value == 8
    assert same_id == window_id
    assert await storage.get(KEY) == 8
    assert await storage.get_window_id(KEY) == window_id


async def test_a_missing_key_reads_as_none_and_deleting_it_is_a_noop(backend) -> None:
    storage = backend.storage

    assert await storage.get('nonexistent') is None
    assert await storage.get_ttl('nonexistent') is None
    assert await storage.get_window_id('nonexistent') is None
    await storage.delete('nonexistent')  # must not raise
    assert await storage.get('nonexistent') is None


async def test_the_ttl_is_the_expiry_timestamp(backend) -> None:
    before = _now()
    await backend.storage.increment(KEY, 10, ttl_seconds=60, window_start=before)

    ttl = await backend.storage.get_ttl(KEY)

    assert ttl is not None
    assert before + 60 - backend.ttl_slack <= ttl <= _now() + 61


async def test_an_expired_window_reads_as_none_and_restarts_with_a_new_id(
    backend,
) -> None:
    storage = backend.storage
    _, first_id = await storage.increment(KEY, 5, ttl_seconds=1, window_start=_now())
    assert await storage.get_window_id(KEY) == first_id

    backend.expire(KEY)

    assert await storage.get(KEY) is None
    assert await storage.get_ttl(KEY) is None
    assert await storage.get_window_id(KEY) is None
    value, second_id = await storage.increment(
        KEY, 3, ttl_seconds=60, window_start=_now()
    )
    assert value == 3
    assert second_id is not None
    assert second_id != first_id
    assert await storage.get_window_id(KEY) == second_id


async def test_keys_are_isolated_and_delete_removes_one(backend) -> None:
    storage = backend.storage
    await storage.increment('key1', 5, ttl_seconds=60, window_start=_now())
    await storage.increment('key2', 10, ttl_seconds=60, window_start=_now())

    assert await storage.get('key1') == 5
    assert await storage.get('key2') == 10

    await storage.delete('key1')

    assert await storage.get('key1') is None
    assert await storage.get('key2') == 10


async def test_get_many_reads_every_key_in_order(backend) -> None:
    storage = backend.storage
    await storage.increment('a', 3, 60, _now())
    await storage.increment('b', 7, 60, _now())

    assert await storage.get_many(['b', 'missing', 'a']) == [7, None, 3]


async def test_increment_many_matches_one_increment_each(backend) -> None:
    storage = backend.storage
    _, window_id = await storage.increment('a', 2, 60, _now())

    results = await storage.increment_many(
        [('a', 5, 60, _now()), ('b', 4, 3600, _now()), ('a', 1, 60, _now())]
    )

    assert [value for value, _ in results] == [7, 4, 8]
    assert results[0][1] == results[2][1] == window_id
    assert await storage.get_ttl('b') > _now() + 3000


async def test_in_memory_an_expired_key_is_cleaned_up_on_get() -> None:
    with freeze_time(datetime(2024, 1, 1, 12, tzinfo=UTC)) as frozen:
        storage = InMemoryStorage()
        await storage.increment(KEY, 10, ttl_seconds=1, window_start=_now())
        frozen.tick(2)

        await storage.get(KEY)

        async with storage._lock:
            assert KEY not in storage._data


async def test_in_memory_concurrent_increments_are_all_counted() -> None:
    storage = InMemoryStorage()

    async def increment_100_times() -> None:
        for _ in range(100):
            await storage.increment(KEY, 1, ttl_seconds=60, window_start=_now())

    await asyncio.gather(*(increment_100_times() for _ in range(10)))

    assert await storage.get(KEY) == 1000
