import time

from cachetools import LRUCache
from traceloop.sdk.decorators import task

from radicalbit_ai_gateway.caching.abstract_cache import AbstractCache


class CacheToolsInMemory(AbstractCache):
    def __init__(self, maxsize: int = 1024):
        self._cache = LRUCache(maxsize=maxsize)

    @task(name='get_in_memory_cache')
    async def get(self, cache_key: str, **kwargs) -> str | None:
        cached_item = self._cache.get(cache_key)
        if cached_item:
            value_stored, expiration_time = cached_item
            if expiration_time and time.time() > expiration_time:
                del self._cache[cache_key]
                return None
            return value_stored.get('response')
        return None

    @task(name='set_in_memory_cache')
    async def set(
        self,
        cache_key: str,
        response: str,
        ttl: int | None,
        **kwargs,
    ):
        expiration_time = (time.time() + ttl) if ttl else None
        value_to_store = {'response': response, 'exp': expiration_time}
        self._cache[cache_key] = (value_to_store, expiration_time)
