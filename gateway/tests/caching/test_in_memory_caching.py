import unittest

from freezegun import freeze_time
import pytest

from radicalbit_ai_gateway.caching.in_memory_cache import CacheToolsInMemory


class TestCacheToolsInMemory(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cache = CacheToolsInMemory(maxsize=10)
        self.cache_key = 'test-info'
        self.response = 'test-response'

    @pytest.mark.asyncio
    async def test_set_and_get_item(self):
        await self.cache.set(self.cache_key, self.response, 10)
        retrieved = await self.cache.get(self.cache_key)
        assert retrieved == self.response

    @pytest.mark.asyncio
    async def test_item_expires_after_ttl(self):
        start_time = '2025-08-27 14:20:00'
        with freeze_time(start_time) as freezer:
            await self.cache.set(self.cache_key, self.response, 10)
            assert await self.cache.get(self.cache_key) == self.response
            freezer.tick(11)
            retrieved = await self.cache.get(self.cache_key)
            assert retrieved is None

    @pytest.mark.asyncio
    async def test_get_nonexistent_item(self):
        retrieved = await self.cache.get(self.cache_key)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_overwrite_item(self):
        new_response = 'new-test-response'
        await self.cache.set(self.cache_key, self.response, 10)
        await self.cache.set(self.cache_key, new_response, 10)
        retrieved = await self.cache.get(self.cache_key)
        assert retrieved == new_response

    @pytest.mark.asyncio
    async def test_maxsize_eviction(self):
        small_cache = CacheToolsInMemory(maxsize=2)
        await small_cache.set('key-1', 'response-1', None)
        await small_cache.set('key-2', 'response-2', None)
        await small_cache.set('key-3', 'response-3', None)
        assert await small_cache.get('key-1') is None
        assert await small_cache.get('key-2') is not None
        assert await small_cache.get('key-3') is not None
