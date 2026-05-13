"""Tests for InMemoryStorage."""

import asyncio
from datetime import datetime, timezone
import time

from freezegun import freeze_time
import pytest

from radicalbit_ai_gateway.limiter.storage.memory import InMemoryStorage


class TestInMemoryStorage:
    @pytest.mark.asyncio
    async def test_increment_new_key(self) -> None:
        storage = InMemoryStorage()
        window_start = time.time_ns() // 1_000_000_000
        result, window_id = await storage.increment(
            'test-key', 5, ttl_seconds=60, window_start=window_start
        )
        assert result == 5
        assert window_id is not None

    @pytest.mark.asyncio
    async def test_increment_existing_key_same_window(self) -> None:
        storage = InMemoryStorage()
        window_start = time.time_ns() // 1_000_000_000
        await storage.increment(
            'test-key', 5, ttl_seconds=60, window_start=window_start
        )
        result, window_id = await storage.increment(
            'test-key', 3, ttl_seconds=60, window_start=window_start
        )
        assert result == 8

    @pytest.mark.asyncio
    async def test_increment_resets_on_expired_window(self) -> None:
        initial_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        with freeze_time(initial_time):
            storage = InMemoryStorage()
            window_start = int(initial_time.timestamp())
            await storage.increment(
                'test-key', 5, ttl_seconds=1, window_start=window_start
            )

        # Move time forward past TTL
        with freeze_time(datetime(2024, 1, 1, 12, 0, 2, tzinfo=timezone.utc)):
            window_start_2 = int(datetime.now(timezone.utc).timestamp())
            result, window_id = await storage.increment(
                'test-key', 3, ttl_seconds=60, window_start=window_start_2
            )
            assert result == 3  # Reset to just the new amount

    @pytest.mark.asyncio
    async def test_get_existing_key(self) -> None:
        storage = InMemoryStorage()
        window_start = time.time_ns() // 1_000_000_000
        await storage.increment(
            'test-key', 10, ttl_seconds=60, window_start=window_start
        )
        result = await storage.get('test-key')
        assert result == 10

    @pytest.mark.asyncio
    async def test_get_nonexistent_key(self) -> None:
        storage = InMemoryStorage()
        result = await storage.get('nonexistent')
        assert result is None

    @pytest.mark.asyncio
    async def test_get_expired_key(self) -> None:
        initial_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        with freeze_time(initial_time):
            storage = InMemoryStorage()
            window_start = int(initial_time.timestamp())
            await storage.increment(
                'test-key', 10, ttl_seconds=1, window_start=window_start
            )

        # Move time forward past TTL
        with freeze_time(datetime(2024, 1, 1, 12, 0, 2, tzinfo=timezone.utc)):
            result = await storage.get('test-key')
            assert result is None

    @pytest.mark.asyncio
    async def test_get_ttl_existing_key(self) -> None:
        storage = InMemoryStorage()
        before = time.time_ns() // 1_000_000_000
        window_start = before
        await storage.increment(
            'test-key', 10, ttl_seconds=60, window_start=window_start
        )
        ttl = await storage.get_ttl('test-key')
        assert ttl is not None
        assert ttl >= before + 60
        assert ttl <= (time.time_ns() // 1_000_000_000) + 61

    @pytest.mark.asyncio
    async def test_get_ttl_nonexistent_key(self) -> None:
        storage = InMemoryStorage()
        ttl = await storage.get_ttl('nonexistent')
        assert ttl is None

    @pytest.mark.asyncio
    async def test_get_ttl_expired_key(self) -> None:
        initial_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        with freeze_time(initial_time):
            storage = InMemoryStorage()
            window_start = int(initial_time.timestamp())
            await storage.increment(
                'test-key', 10, ttl_seconds=1, window_start=window_start
            )

        # Move time forward past TTL
        with freeze_time(datetime(2024, 1, 1, 12, 0, 2, tzinfo=timezone.utc)):
            ttl = await storage.get_ttl('test-key')
            assert ttl is None

    @pytest.mark.asyncio
    async def test_expired_key_is_cleaned_up_on_get(self) -> None:
        initial_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        with freeze_time(initial_time):
            storage = InMemoryStorage()
            window_start = int(initial_time.timestamp())
            await storage.increment(
                'test-key', 10, ttl_seconds=1, window_start=window_start
            )

        # Move time forward past TTL
        with freeze_time(datetime(2024, 1, 1, 12, 0, 2, tzinfo=timezone.utc)):
            # Access expired key - should be cleaned up
            await storage.get('test-key')

            # Verify key was removed from internal dict
            async with storage._lock:
                assert 'test-key' not in storage._data

    @pytest.mark.asyncio
    async def test_multiple_keys_are_isolated(self) -> None:
        storage = InMemoryStorage()
        window_start = time.time_ns() // 1_000_000_000
        await storage.increment('key1', 5, ttl_seconds=60, window_start=window_start)
        await storage.increment('key2', 10, ttl_seconds=60, window_start=window_start)

        assert await storage.get('key1') == 5
        assert await storage.get('key2') == 10

    @pytest.mark.asyncio
    async def test_concurrent_increments(self) -> None:
        storage = InMemoryStorage()

        async def increment_multiple_times(key: str, count: int) -> None:
            window_start = time.time_ns() // 1_000_000_000
            for _ in range(count):
                await storage.increment(
                    key, 1, ttl_seconds=60, window_start=window_start
                )

        # Run 10 concurrent tasks, each incrementing 100 times
        tasks = [increment_multiple_times('test-key', 100) for _ in range(10)]
        await asyncio.gather(*tasks)

        result = await storage.get('test-key')
        assert result == 1000  # 10 tasks * 100 increments

    @pytest.mark.asyncio
    async def test_get_window_id_new_key(self) -> None:
        storage = InMemoryStorage()
        window_id = await storage.get_window_id('nonexistent')
        assert window_id is None

    @pytest.mark.asyncio
    async def test_get_window_id_existing_key(self) -> None:
        storage = InMemoryStorage()
        window_start = time.time_ns() // 1_000_000_000
        await storage.increment(
            'test-key', 5, ttl_seconds=60, window_start=window_start
        )
        window_id = await storage.get_window_id('test-key')
        assert window_id is not None
        assert len(window_id) == 36  # UUID format

    @pytest.mark.asyncio
    async def test_window_id_persists_across_increments_same_window(self) -> None:
        storage = InMemoryStorage()
        window_start = time.time_ns() // 1_000_000_000
        await storage.increment(
            'test-key', 5, ttl_seconds=60, window_start=window_start
        )
        window_id_1 = await storage.get_window_id('test-key')

        await storage.increment(
            'test-key', 3, ttl_seconds=60, window_start=window_start
        )
        window_id_2 = await storage.get_window_id('test-key')

        assert window_id_1 == window_id_2

    @pytest.mark.asyncio
    async def test_window_id_is_none_for_expired_key(self) -> None:
        initial_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        with freeze_time(initial_time):
            storage = InMemoryStorage()
            window_start = int(initial_time.timestamp())
            await storage.increment(
                'test-key', 10, ttl_seconds=1, window_start=window_start
            )

        # Move time forward past TTL
        with freeze_time(datetime(2024, 1, 1, 12, 0, 2, tzinfo=timezone.utc)):
            window_id = await storage.get_window_id('test-key')
            assert window_id is None

    @pytest.mark.asyncio
    async def test_new_window_id_after_expiration(self) -> None:
        initial_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        with freeze_time(initial_time):
            storage = InMemoryStorage()
            window_start_1 = int(initial_time.timestamp())
            await storage.increment(
                'test-key', 5, ttl_seconds=1, window_start=window_start_1
            )
            window_id_1 = await storage.get_window_id('test-key')
            assert window_id_1 is not None

        # Move time forward past TTL
        with freeze_time(datetime(2024, 1, 1, 12, 0, 2, tzinfo=timezone.utc)):
            # Expired window creates new window with new ID
            window_start_2 = int(datetime.now(timezone.utc).timestamp())
            await storage.increment(
                'test-key', 3, ttl_seconds=60, window_start=window_start_2
            )
            window_id_2 = await storage.get_window_id('test-key')
            assert window_id_2 is not None
            assert window_id_1 != window_id_2
