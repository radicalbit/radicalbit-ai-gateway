"""Route-level caching for the MCP list methods.

``tools/list``, ``prompts/list`` and ``resources/list`` fan out to every
upstream server on the route, and :class:`McpUpstreamClient` runs a full
``initialize`` handshake per operation — so one list is N x (TCP + TLS +
handshake), re-issued by agent clients on every reconnect. The three are also
the only MCP methods that are safe to cache: everything else either carries
caller-supplied arguments or is side-effecting by definition.

This wraps the route's existing ``GatewayCache`` (the same ``caching:`` block
the /v1 endpoints use, no new YAML) and owns the guards that decide when a
route may not be cached at all — see :meth:`McpListCache.for_route`.
"""

import json
import logging

from radicalbit_ai_gateway.caching.gateway_cache import GatewayCache
from radicalbit_ai_gateway.events.events_processor import emit_event
from radicalbit_ai_gateway.metrics.define_metrics import cache_hit_counter
from radicalbit_ai_gateway.models.caching import CacheType
from radicalbit_ai_gateway.models.event_payload import CacheEventPayload
from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.models.mcp_authorized_request import McpAuthorizedRequest
from radicalbit_ai_gateway.models.mcp_server import AnyMcpServer, McpHttpServer
from radicalbit_ai_gateway.utils.app_config import get_app_config

logger = logging.getLogger(get_app_config().log_config.logger_name)

CACHEABLE_CACHE_TYPES = frozenset({CacheType.EXACT, CacheType.IN_MEMORY})

TOOLS_LIST = 'tools/list'
PROMPTS_LIST = 'prompts/list'
RESOURCES_LIST = 'resources/list'


def servers_signature(servers: list[AnyMcpServer]) -> str:
    """Identify the upstream set a cached list was produced from."""
    parts = []
    for server in sorted(servers, key=lambda s: s.alias):
        if isinstance(server, McpHttpServer):
            endpoint = server.url
        else:
            endpoint = json.dumps([server.command, *server.args, server.cwd or ''])
        parts.append(f'{server.alias}|{server.transport}|{endpoint}')
    return ';'.join(parts)


class McpListCache:
    """A route's cache for the three MCP list methods, or nothing at all."""

    def __init__(
        self,
        gateway_cache: GatewayCache,
        ttl: int | None,
        authorized: McpAuthorizedRequest,
        signature: str,
    ):
        self._cache = gateway_cache
        self._ttl = ttl
        self._authorized = authorized
        self._signature = signature

    @classmethod
    def for_route(
        cls,
        gateway_cache: GatewayCache | None,
        ttl: int | None,
        authorized: McpAuthorizedRequest,
    ) -> 'McpListCache | None':
        """Build the cache for a route, or ``None`` when it must not cache.

        Three reasons a route gets no cache:

        - it declares no ``caching:`` block (``gateway_cache is None``);
        - it declares a *semantic* cache, which cannot answer a query-less
          lookup (see :data:`CACHEABLE_CACHE_TYPES`);
        - one of its servers declares ``forward_headers``. That is a
          correctness rule, not hygiene: the upstream fills a header from the
          inbound request, so two callers with different credentials can
          legitimately be shown different tool lists. Skipping those routes
          entirely is provably safe and keeps credential material out of cache
          keys.
        """
        servers = authorized.servers
        if gateway_cache is None or not servers:
            return None
        if gateway_cache.cache_type not in CACHEABLE_CACHE_TYPES:
            logger.debug(
                'MCP list caching disabled on route %s: cache type %s is not cacheable',
                authorized.route_name,
                gateway_cache.cache_type.value,
            )
            return None
        if any(
            isinstance(server, McpHttpServer) and server.forward_headers
            for server in servers
        ):
            logger.debug(
                'MCP list caching disabled on route %s: an upstream declares '
                'forward_headers, so its list may vary per caller',
                authorized.route_name,
            )
            return None
        return cls(
            gateway_cache=gateway_cache,
            ttl=ttl,
            authorized=authorized,
            signature=servers_signature(servers),
        )

    async def get(self, method: str) -> dict | None:
        """Return the cached result for ``method``, or ``None`` on a miss."""
        try:
            raw = await self._cache.get(self._key(method))
        except Exception:
            logger.warning('MCP %s cache lookup failed', method, exc_info=True)
            return None
        if not raw:
            return None
        try:
            cached = json.loads(raw)
        except ValueError:
            logger.warning('MCP %s cache entry is not valid JSON, ignoring', method)
            return None
        if not isinstance(cached, dict):
            logger.warning('MCP %s cache entry is not a JSON object, ignoring', method)
            return None
        return cached

    async def set(self, method: str, result: dict) -> None:
        """Store ``result`` for ``method``. Never raises."""
        try:
            await self._cache.set(
                cache_key=self._key(method),
                response=json.dumps(result),
                ttl=self._ttl,
            )
        except Exception:
            logger.warning('MCP %s cache write failed', method, exc_info=True)

    def record_hit(self, method: str) -> None:
        """Report a hit to the events pipeline and the cache-hit metric."""
        logger.debug(
            'MCP %s served from cache on route %s',
            method,
            self._authorized.route_name,
        )
        key_details = self._authorized.key_details
        emit_event(
            CacheEventPayload(
                value=1.0,
                request_uuid=self._authorized.request_uuid,
                event_type=EventType.CACHE_HIT,
                route_name=self._authorized.route_name,
                api_key_uuid=key_details.api_key_uuid,
                api_key_name=key_details.api_key_name,
                group_uuid=key_details.group_uuid,
                group_name=key_details.group_name,
                project_uuid=self._authorized.project_uuid,
                project_name=self._authorized.project_name,
                cost=0.0,
                cache_type=str(self._cache.cache_type.value),
                model_id='',
            )
        )
        cache_hit_counter.add(1, {'route_name': self._authorized.route_name})

    def _key(self, method: str) -> str:
        return self._cache.generate_mcp_list_cache_key(
            project_uuid=self._authorized.project_uuid,
            route_name=self._authorized.route_name,
            key_uuid=self._authorized.key_details.api_key_uuid,
            method=method,
            servers_signature=self._signature,
        )
