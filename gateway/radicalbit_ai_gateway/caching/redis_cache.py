from redis.asyncio import Redis
from typing_extensions import override

from radicalbit_ai_gateway.caching.abstract_cache import AbstractCache
from radicalbit_ai_gateway.telemetry.tracing import task


class RedisCache(AbstractCache):
    def __init__(self, redis_client: Redis):
        self.redis_client = redis_client

    @override
    @task(name='get_exact_cache')
    async def get(self, cache_key: str, **kwargs) -> str | None:
        value = await self.redis_client.hget(name=cache_key, key='response')
        # Bytes unless the client decodes responses.
        return value.decode() if isinstance(value, bytes) else value

    @override
    @task(name='set_exact_cache')
    async def set(
        self,
        cache_key: str,
        response: str,
        ttl: int | None,
        **kwargs,
    ):
        pipeline = self.redis_client.pipeline()
        await pipeline.hset(name=cache_key, key='response', value=response)
        if ttl is not None and ttl != 0:
            await pipeline.expire(cache_key, ttl)
        await pipeline.execute()
