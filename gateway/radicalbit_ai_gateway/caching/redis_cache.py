from redis.asyncio import Redis
from traceloop.sdk.decorators import task

from radicalbit_ai_gateway.caching.abstract_cache import AbstractCache


class RedisCache(AbstractCache):
    def __init__(self, redis_client: Redis):
        self.redis_client = redis_client

    @task(name='get_exact_cache')
    async def get(self, cache_key: str, **kwargs) -> str | None:
        return await self.redis_client.hget(name=cache_key, key='response')

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
        if ttl:
            await pipeline.expire(cache_key, ttl)
        await pipeline.execute()
