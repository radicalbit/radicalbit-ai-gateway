import time
from typing import TypedDict

from cachetools import LRUCache
from typing_extensions import override

from radicalbit_ai_gateway.caching.abstract_cache import AbstractCache
from radicalbit_ai_gateway.telemetry.tracing import task


class _StoredValue(TypedDict):
    response: str
    exp: float | None


class CacheToolsInMemory(AbstractCache):
    def __init__(self, maxsize: int = 1024):
        self._cache: LRUCache[str, tuple[_StoredValue, float | None]] = LRUCache(
            maxsize=maxsize
        )

    @override
    @task(name='get_in_memory_cache')
    async def get(self, cache_key: str, **kwargs) -> str | None:
        cached_item = self._cache.get(cache_key)
        if cached_item:
            value_stored, expiration_time = cached_item
            if expiration_time is not None and time.time() > expiration_time:
                del self._cache[cache_key]
                return None
            return value_stored.get('response')
        return None

    @override
    @task(name='set_in_memory_cache')
    async def set(
        self,
        cache_key: str,
        response: str,
        ttl: int | None,
        **kwargs,
    ):
        expiration_time = (time.time() + ttl) if ttl is not None and ttl != 0 else None
        value_to_store: _StoredValue = {'response': response, 'exp': expiration_time}
        self._cache[cache_key] = (value_to_store, expiration_time)
