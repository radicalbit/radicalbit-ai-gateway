"""Tests for RedisStorage."""

import asyncio
import time

import pytest

from radicalbit_ai_gateway.limiter.storage.redis import RedisStorage


@pytest.fixture
async def redis_storage(redis_connection_url: str) -> RedisStorage:
    """Create RedisStorage using testcontainers redis."""
    storage = RedisStorage(uri=redis_connection_url)
    yield storage
    await storage.close()


class TestRedisStorage:
    @pytest.mark.asyncio
    async def test_increment_new_key(self, redis_storage: RedisStorage) -> None:
        window_start = time.time_ns() // 1_000_000_000
        result, window_id = await redis_storage.increment(
            'test-key-1', 5, ttl_seconds=60, window_start=window_start
        )
        assert result == 5
        assert window_id is not None

    @pytest.mark.asyncio
    async def test_increment_existing_key_same_window(
        self, redis_storage: RedisStorage
    ) -> None:
        window_start = time.time_ns() // 1_000_000_000
        await redis_storage.increment(
            'test-key-2', 5, ttl_seconds=60, window_start=window_start
        )
        result, _ = await redis_storage.increment(
            'test-key-2', 3, ttl_seconds=60, window_start=window_start
        )
        assert result == 8

    @pytest.mark.asyncio
    async def test_get_existing_key(self, redis_storage: RedisStorage) -> None:
        window_start = time.time_ns() // 1_000_000_000
        await redis_storage.increment(
            'test-key-4', 10, ttl_seconds=60, window_start=window_start
        )
        result = await redis_storage.get('test-key-4')
        assert result == 10

    @pytest.mark.asyncio
    async def test_get_nonexistent_key(self, redis_storage: RedisStorage) -> None:
        result = await redis_storage.get('nonexistent-key')
        assert result is None

    @pytest.mark.asyncio
    async def test_get_ttl_existing_key(self, redis_storage: RedisStorage) -> None:
        before = time.time()
        window_start = time.time_ns() // 1_000_000_000
        await redis_storage.increment(
            'test-key-5', 10, ttl_seconds=60, window_start=window_start
        )
        ttl = await redis_storage.get_ttl('test-key-5')
        assert ttl is not None
        assert ttl >= before + 59  # Some tolerance
        assert ttl <= time.time() + 61

    @pytest.mark.asyncio
    async def test_get_ttl_nonexistent_key(self, redis_storage: RedisStorage) -> None:
        ttl = await redis_storage.get_ttl('nonexistent-ttl-key')
        assert ttl is None

    @pytest.mark.asyncio
    async def test_multiple_keys_are_isolated(
        self, redis_storage: RedisStorage
    ) -> None:
        window_start = time.time_ns() // 1_000_000_000
        await redis_storage.increment(
            'key-a', 5, ttl_seconds=60, window_start=window_start
        )
        await redis_storage.increment(
            'key-b', 10, ttl_seconds=60, window_start=window_start
        )

        assert await redis_storage.get('key-a') == 5
        assert await redis_storage.get('key-b') == 10

    @pytest.mark.asyncio
    async def test_get_window_id_new_key(self, redis_storage: RedisStorage) -> None:
        window_id = await redis_storage.get_window_id('nonexistent-window-id')
        assert window_id is None

    @pytest.mark.asyncio
    async def test_get_window_id_existing_key(
        self, redis_storage: RedisStorage
    ) -> None:
        window_start = time.time_ns() // 1_000_000_000
        await redis_storage.increment(
            'test-key-window-id', 5, ttl_seconds=60, window_start=window_start
        )
        window_id = await redis_storage.get_window_id('test-key-window-id')
        assert window_id is not None
        assert len(window_id) == 36  # UUID format

    @pytest.mark.asyncio
    async def test_window_id_persists_across_increments(
        self, redis_storage: RedisStorage
    ) -> None:
        window_start = time.time_ns() // 1_000_000_000
        await redis_storage.increment(
            'test-key-window-persist', 5, ttl_seconds=60, window_start=window_start
        )
        window_id_1 = await redis_storage.get_window_id('test-key-window-persist')

        await redis_storage.increment(
            'test-key-window-persist', 3, ttl_seconds=60, window_start=window_start
        )
        window_id_2 = await redis_storage.get_window_id('test-key-window-persist')

        assert window_id_1 == window_id_2

    @pytest.mark.asyncio
    async def test_window_id_is_none_for_expired_key(
        self, redis_storage: RedisStorage
    ) -> None:
        key = 'test-key-window-expired'
        window_start = time.time_ns() // 1_000_000_000
        await redis_storage.increment(key, 10, ttl_seconds=1, window_start=window_start)
        window_id = await redis_storage.get_window_id(key)
        assert window_id is not None

        # Wait for expiry
        await asyncio.sleep(1.1)
        window_id = await redis_storage.get_window_id(key)
        assert window_id is None

    @pytest.mark.asyncio
    async def test_new_window_id_after_expiry(
        self, redis_storage: RedisStorage
    ) -> None:
        key = 'test-key-new-window'
        window_start_1 = time.time_ns() // 1_000_000_000
        await redis_storage.increment(
            key, 5, ttl_seconds=1, window_start=window_start_1
        )
        window_id_1 = await redis_storage.get_window_id(key)
        assert window_id_1 is not None

        # Wait for expiry
        await asyncio.sleep(1.1)

        # Create new window
        window_start_2 = time.time_ns() // 1_000_000_000
        await redis_storage.increment(
            key, 3, ttl_seconds=60, window_start=window_start_2
        )
        window_id_2 = await redis_storage.get_window_id(key)
        assert window_id_2 is not None
        assert window_id_1 != window_id_2

    @pytest.mark.asyncio
    async def test_delete_removes_existing_key(
        self, redis_storage: RedisStorage
    ) -> None:
        window_start = time.time_ns() // 1_000_000_000
        await redis_storage.increment(
            'test-key-delete', 5, ttl_seconds=60, window_start=window_start
        )
        await redis_storage.delete('test-key-delete')
        assert await redis_storage.get('test-key-delete') is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_key_is_a_noop(
        self, redis_storage: RedisStorage
    ) -> None:
        await redis_storage.delete('nonexistent-key')  # must not raise
        assert await redis_storage.get('nonexistent-key') is None


class TestRedisStorageBatches:
    @pytest.mark.asyncio
    async def test_get_many_reads_every_key_in_order(
        self, redis_storage: RedisStorage
    ) -> None:
        window_start = time.time_ns() // 1_000_000_000
        await redis_storage.increment('batch-get-a', 3, 60, window_start)
        await redis_storage.increment('batch-get-b', 7, 60, window_start)

        values = await redis_storage.get_many(
            ['batch-get-b', 'batch-get-missing', 'batch-get-a']
        )

        assert values == [7, None, 3]

    @pytest.mark.asyncio
    async def test_increment_many_matches_one_increment_each(
        self, redis_storage: RedisStorage
    ) -> None:
        window_start = time.time_ns() // 1_000_000_000
        _, window_id = await redis_storage.increment('batch-inc-a', 2, 60, window_start)

        results = await redis_storage.increment_many(
            [
                ('batch-inc-a', 5, 60, window_start),
                ('batch-inc-b', 4, 3600, window_start),
                ('batch-inc-a', 1, 60, window_start),
            ]
        )

        assert [value for value, _ in results] == [7, 4, 8]
        assert results[0][1] == results[2][1] == window_id
        ttl = await redis_storage.get_ttl('batch-inc-b')
        assert ttl > time.time() + 3000
