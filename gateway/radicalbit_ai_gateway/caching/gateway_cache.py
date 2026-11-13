from radicalbit_ai_gateway.caching.abstract_cache import AbstractCache
from radicalbit_ai_gateway.caching.in_memory_cache import CacheToolsInMemory
from radicalbit_ai_gateway.caching.redis_cache import RedisCache
from radicalbit_ai_gateway.caching.semantic_caching import SemanticCache
from radicalbit_ai_gateway.models.caching import CacheType


class GatewayCache:
    """A route's cache backend: Redis, the semantic index, or memory.

    The response cache (``route_cache``) keys its entries itself; the MCP
    list cache keys its own here.
    """

    def __init__(self, cache_client: AbstractCache):
        self.cache_client = cache_client

    @property
    def cache_type(self) -> CacheType:
        if isinstance(self.cache_client, SemanticCache):
            return CacheType.SEMANTIC
        if isinstance(self.cache_client, RedisCache):
            return CacheType.EXACT
        if isinstance(self.cache_client, CacheToolsInMemory):
            return CacheType.IN_MEMORY
        return CacheType.UNKNOWN

    async def get(self, cache_key: str, **kwargs) -> str | None:
        return await self.cache_client.get(cache_key, **kwargs)

    async def set(
        self,
        cache_key: str,
        response: str,
        ttl: int | None,
        **kwargs,
    ):
        await self.cache_client.set(cache_key, response, ttl, **kwargs)

    def generate_mcp_list_cache_key(
        self,
        project_uuid: str,
        route_name: str,
        key_uuid: str,
        method: str,
        servers_signature: str,
    ) -> str:
        """Key a cached MCP list method (``tools/list`` and its siblings)."""
        request_signature = self._build_mcp_list_request_signature(
            method=method, servers_signature=servers_signature
        )
        return self.cache_client.generate_cache_key(
            project_uuid, route_name, request_signature, key_uuid
        )

    @staticmethod
    def _build_mcp_list_request_signature(
        method: str,
        servers_signature: str,
    ) -> str:
        return f'mcp_method:{method};mcp_servers:{servers_signature}'
