import asyncio
from collections.abc import Mapping
from contextvars import ContextVar
from importlib.metadata import PackageNotFoundError, version as _package_version
import logging
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from uuid import UUID

from fastapi import Request
from opentelemetry.trace import Status, StatusCode, get_current_span
from traceloop.sdk.decorators import task

from radicalbit_ai_gateway.auth.request_auth import authenticate_bearer_request
from radicalbit_ai_gateway.mcp_proxy import jsonrpc
from radicalbit_ai_gateway.mcp_proxy.errors import (
    JSON_RPC_UPSTREAM_ERROR,
    McpUpstreamError,
)
from radicalbit_ai_gateway.mcp_proxy.list_cache import (
    PROMPTS_LIST,
    RESOURCES_LIST,
    TOOLS_LIST,
    McpListCache,
)
from radicalbit_ai_gateway.mcp_proxy.upstream_client import McpUpstreamClient
from radicalbit_ai_gateway.middleware.request_event_context import RequestEventContext
from radicalbit_ai_gateway.models.mcp_authorized_request import McpAuthorizedRequest
from radicalbit_ai_gateway.models.mcp_dispatch_result import McpDispatchResult
from radicalbit_ai_gateway.models.mcp_server import ALIAS_TOOL_SEPARATOR, AnyMcpServer
from radicalbit_ai_gateway.models.project_entry import ProjectEntry
from radicalbit_ai_gateway.services.group_service import GroupService
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import McpTransportError
from radicalbit_ai_gateway.utils.request_context import get_current_request_tags
from radicalbit_ai_gateway.utils.trace_attributes import (
    OperationCategory,
    set_mcp_attributes,
    set_operation_category,
    set_trace_attributes,
)

logger = logging.getLogger(get_app_config().log_config.logger_name)

SUPPORTED_PROTOCOL_VERSIONS = ('2025-06-18', '2025-11-25')
LATEST_PROTOCOL_VERSION = '2025-11-25'
PROTOCOL_VERSION_HEADER = 'mcp-protocol-version'
MCP_SERVER_NAME = 'radicalbit-ai-gateway-mcp'

# Resources are identified by an arbitrary URI, not a name, so the
# '{alias}__{name}' prefix used for tools/prompts can't apply directly (an
# upstream URI's own scheme would collide with it). Instead the alias and the
# original URI are packed into an opaque, non-hierarchical URI (no '//'
# authority, like 'mailto:' or 'urn:') with both parts percent-encoded, so the
# encoding never depends on either's character set.
RESOURCE_URI_SCHEME = 'mcp-resource'

# Written inside a ``@task``, read back from the enclosing workflow scope. A
# task detaches its OTel context on exit, so nothing set inside one can reach
# the root span — but a ContextVar mutated by an awaited coroutine belongs to
# the enclosing request's context and outlives the task's return. Each request
# runs in its own asyncio task, whose context is a copy, so this never bleeds
# between requests.
_fanout_failed: ContextVar[tuple[str, ...]] = ContextVar(
    'mcp_fanout_failed', default=()
)


def gateway_version() -> str:
    try:
        return _package_version('radicalbit-ai-gateway')
    except PackageNotFoundError:
        return '0.0.0'


def negotiate_protocol_version(requested: object) -> str:
    """Echo the client's requested version when supported, else our latest.

    Version negotiation is a successful result carrying a version, not an
    error (spec §2 ``initialize``).
    """
    if isinstance(requested, str) and requested in SUPPORTED_PROTOCOL_VERSIONS:
        return requested
    return LATEST_PROTOCOL_VERSION


def split_alias_name(name: str) -> tuple[str, str] | None:
    """Split ``'{alias}__{name}'`` on the first separator.

    Returns ``(alias, name)`` or ``None`` when the name carries no alias
    prefix. Names containing further ``'__'`` keep them intact. Used for both
    tool and prompt names, which share the same ``{alias}__{name}`` scheme.
    """
    alias, sep, rest = name.partition(ALIAS_TOOL_SEPARATOR)
    if not sep or not alias or not rest:
        return None
    return alias, rest


def encode_resource_uri(alias: str, uri: str) -> str:
    """Wrap an upstream resource URI so ``resources/read`` can route it back."""
    return f'{RESOURCE_URI_SCHEME}:{quote(alias, safe="")}/{quote(uri, safe="")}'


def decode_resource_uri(uri: str) -> tuple[str, str] | None:
    """Reverse :func:`encode_resource_uri`.

    Returns ``(alias, original_uri)`` or ``None`` if ``uri`` isn't one of our
    wrapped resource URIs.
    """
    prefix = f'{RESOURCE_URI_SCHEME}:'
    if not uri.startswith(prefix):
        return None
    alias_enc, sep, uri_enc = uri[len(prefix) :].partition('/')
    if not sep or not alias_enc or not uri_enc:
        return None
    return unquote(alias_enc), unquote(uri_enc)


def strip_uri_credentials(uri: str) -> str:
    """Reduce a resource URI to the part that identifies the resource.

    Scheme, host and path are what make the attribute useful; the query and the
    ``user:pass@`` userinfo are where signed-URL tokens and basic-auth
    credentials live. Spans reach every configured OTLP endpoint, third-party
    ones included, so those parts must not travel with them.

    Malformed input is returned unchanged rather than raising — an attribute is
    never worth failing a request over, and an unparseable URI cannot resolve to
    a configured alias in the first place.
    """
    try:
        split = urlsplit(uri)
        authority = split.hostname or ''
        if authority and split.port:
            authority = f'{authority}:{split.port}'
        if not split.query and not split.fragment and authority == split.netloc:
            return uri
        return urlunsplit((split.scheme, authority, split.path, '', ''))
    except ValueError:
        return uri


def target_attributes(method: str, params: dict, servers: list[AnyMcpServer]) -> dict:
    """``alias``/``target`` for the methods addressing one object.

    Resolved here rather than inside each handler because a ``@task`` detaches
    its context on exit: attributes set inside one reach that task's span only,
    never the enclosing ``mcp_request`` workflow span the traces list queries.
    Called from the workflow scope, these land on the root span and are
    inherited by the child task span.

    Only a name resolving to a server configured on the route is recorded.
    ``params`` is client-controlled and these become span attributes — indexed
    dimensions — so echoing back an unresolvable name would let any caller mint
    unlimited distinct values in the trace backend. Diagnosability is kept
    without that: the rejected name still reaches the trace as the span status
    description (``Unknown tool: {name}``, set from the JSON-RPC error message
    by :meth:`McpService._record_error_outcome`), which is a free-text field
    rather than a dimension.
    """
    if method in ('tools/call', 'prompts/get'):
        name = params.get('name')
        split = split_alias_name(name) if isinstance(name, str) else None
    elif method == 'resources/read':
        uri = params.get('uri')
        split = decode_resource_uri(uri) if isinstance(uri, str) else None
    else:
        return {}
    if split is None or not any(server.alias == split[0] for server in servers):
        return {}
    alias, target = split
    return {
        'alias': alias,
        'target': strip_uri_credentials(target)
        if method == 'resources/read'
        else target,
    }


class _McpMethodError(Exception):
    """Protocol-level failure inside a dispatched method → JSON-RPC error."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class McpService:
    """Stateless inbound MCP server proxying to a route's upstream servers."""

    def __init__(
        self,
        upstream_client: McpUpstreamClient,
        group_service: GroupService,
        allowed_origins: list[str] | None = None,
    ):
        self._upstream_client = upstream_client
        self._group_service = group_service
        self._allowed_origins = (
            allowed_origins
            if allowed_origins is not None
            else get_app_config().cors_config.cors_allow_origins
        )

    async def authorize(
        self,
        request: Request,
        project_name: str,
        route_name: str,
        request_uuid: str,
    ) -> McpAuthorizedRequest:
        """Attribute the POST, then authenticate and authorize it.

        Everything that can reject before the route's own features apply:
        Origin, bearer auth, an unknown project or route, and a key not bound
        to it. The caller applies the route-level features to the result and
        then calls :meth:`dispatch` — the same division the /v1 endpoints use,
        where the endpoint orchestrates features and the route object only
        carries the instances.
        """
        entry: ProjectEntry | None = request.app.state.project_configs.get(project_name)
        project_uuid = str(entry.uuid) if entry else ''

        # Populated before the first check that can reject, so every outcome —
        # a rejected Origin, a missing, invalid or unbound key — still names the
        # route and project it targeted in both the span and the REQUEST event.
        set_trace_attributes(
            request_uuid=request_uuid,
            project_uuid=project_uuid,
            project_name=project_name,
            route_name=route_name,
            tags=list(get_current_request_tags()),
        )
        ctx = RequestEventContext.get_or_create(request)
        ctx.route_name = route_name
        ctx.project_uuid = project_uuid
        ctx.project_name = project_name

        self._validate_origin(request)

        set_operation_category(OperationCategory.AUTH)
        key_details = await authenticate_bearer_request(
            request, project_uuid, project_name
        )

        if entry is None or route_name not in entry.config.routes:
            raise McpTransportError(
                f"Unknown project or route: '{project_name}/{route_name}'",
                404,
                code='mcp_route_not_found',
            )
        route_key = f'{project_name}/{route_name}'
        if not self._group_service.check_key_uuid_for_route(
            route_key, UUID(key_details.api_key_uuid)
        ):
            raise McpTransportError(
                f'API Key not associated with route {route_name}',
                403,
                code='mcp_key_not_bound',
            )

        return McpAuthorizedRequest(
            request_uuid=request_uuid,
            project_name=project_name,
            project_uuid=project_uuid,
            route_name=route_name,
            route_key=route_key,
            key_details=key_details,
            servers=entry.config.get_route_mcp_servers(route_name),
        )

    async def dispatch(
        self,
        request: Request,
        authorized: McpAuthorizedRequest,
        list_cache: McpListCache | None = None,
    ) -> McpDispatchResult:
        """Dispatch the JSON-RPC message on an already-authorized request.

        ``list_cache`` is the route's cache for the three list methods, or
        ``None`` when the route declares no caching or must not be cached. Like
        the limiters, it is resolved by the caller and only carried here — see
        :meth:`McpListCache.for_route`.
        """
        self._validate_protocol_version(request)

        try:
            body = await request.json()
        except Exception:
            return self._record_error_outcome(
                request,
                McpDispatchResult(
                    status_code=400,
                    payload=jsonrpc.error_message(
                        None, jsonrpc.PARSE_ERROR, 'Parse error'
                    ),
                ),
            )

        set_operation_category(OperationCategory.INVOCATION)
        result = await self._dispatch(
            body, authorized.servers, request.headers, list_cache
        )
        self._record_degradation()
        return self._record_error_outcome(request, result)

    @staticmethod
    def _record_error_outcome(
        request: Request, result: McpDispatchResult
    ) -> McpDispatchResult:
        """Report a JSON-RPC error body to both telemetry pipelines.

        ``_dispatch`` returns protocol and upstream failures as ``error`` bodies
        over HTTP 200, so without this a failed ``tools/call`` is
        indistinguishable from a success in the traces UI and lands in
        ``request_event`` as ``success``. Returns ``result`` so it can wrap a
        return statement.
        """
        error = (result.payload or {}).get('error')
        if not error:
            return result
        code = error.get('code')
        set_mcp_attributes(error_code=code)
        span = get_current_span()
        if span and span.is_recording():
            span.set_status(Status(StatusCode.ERROR, error.get('message', '')))
        ctx = RequestEventContext.get(request)
        if ctx:
            # Read back by _determine_status to downgrade the 200 to an error.
            ctx.error_type = 'mcp_jsonrpc_error'
            ctx.error_code = str(code) if code is not None else None
        return result

    @staticmethod
    def _record_fanout(total: int, failed: list[str], count: int) -> None:
        """Record the outcome of a list method's fan-out on its own span.

        Partial upstream failures are otherwise log-only, so a short list can't
        be told from a degraded one. Always set, so
        ``rb.gateway.mcp_result_count`` is present and
        ``rb.gateway.mcp_upstream_failed`` is empty rather than absent.
        """
        _fanout_failed.set(tuple(failed))
        span = get_current_span()
        if span and span.is_recording():
            span.set_attribute('rb.gateway.mcp_upstream_total', total)
            span.set_attribute('rb.gateway.mcp_upstream_failed', ','.join(failed))
            span.set_attribute('rb.gateway.mcp_result_count', count)

    @staticmethod
    def _record_cache_hit(count: int) -> None:
        """Record a list method served from cache on its own span.

        Deliberately not routed through :meth:`_record_fanout`: no upstream was
        contacted, so ``mcp_upstream_total``/``mcp_upstream_failed`` would be
        fiction. ``mcp_result_count`` is still set, so a list's size stays
        comparable across hits and misses; a span without
        ``mcp_cache_hit`` is a miss.
        """
        span = get_current_span()
        if span and span.is_recording():
            span.set_attribute('rb.gateway.mcp_cache_hit', True)
            span.set_attribute('rb.gateway.mcp_result_count', count)

    async def _cached_list(
        self,
        list_cache: McpListCache | None,
        method: str,
        key: str,
    ) -> dict | None:
        """Return the cached result for a list method, or ``None`` to fan out."""
        if list_cache is None:
            return None
        cached = await list_cache.get(method)
        if cached is None:
            return None
        self._record_cache_hit(len(cached.get(key) or ()))
        list_cache.record_hit(method)
        return cached

    @staticmethod
    async def _store_list(
        list_cache: McpListCache | None,
        method: str,
        result: dict,
        failed: list[str],
    ) -> None:
        """Cache a list method's result, unless the fan-out was degraded.

        A partial result must never be written: one transient upstream outage
        would otherwise pin a truncated list for the whole TTL, and the client
        silently loses the tools of a server that is healthy again.
        """
        if list_cache is None or failed:
            return
        await list_cache.set(method, result)

    @staticmethod
    def _record_degradation() -> None:
        """Hoist a fan-out's failed upstreams onto the root span.

        :meth:`_record_fanout` can only reach the task's own span, which the
        root-span query behind the traces list never reads — so "which requests
        were served from a degraded fan-out?" would be unanswerable there. Only
        the failures are hoisted: the counts stay per-task detail, while this is
        the signal worth filtering a trace list on.
        """
        failed = _fanout_failed.get()
        if failed:
            set_mcp_attributes(upstream_failed=','.join(failed))

    async def _dispatch(
        self,
        body: dict,
        servers: list[AnyMcpServer],
        client_headers: Mapping[str, str] | None,
        list_cache: McpListCache | None = None,
    ) -> McpDispatchResult:
        """Dispatch one JSON-RPC message; returns its HTTP-level outcome.

        ``payload`` is ``None`` for notifications (202, empty body).
        """
        if (
            not isinstance(body, dict)
            or body.get('jsonrpc') != '2.0'
            or not isinstance(body.get('method'), str)
        ):
            return McpDispatchResult(
                status_code=400,
                payload=jsonrpc.error_message(
                    None, jsonrpc.INVALID_REQUEST, 'Invalid Request'
                ),
            )
        method = body['method']
        # Recorded before the notification early-return so every dispatched
        # message is attributable by method, not just the ones that reply.
        set_mcp_attributes(method=method)

        if 'id' not in body:
            # Notifications (e.g. notifications/initialized) get no response.
            # The 202 is load-bearing beyond HTTP semantics: it is the only
            # signal RequestEventMiddleware._emit_event has for "notification,
            # emit no REQUEST event". Keep the two in step.
            logger.debug('MCP notification accepted: %s', method)
            return McpDispatchResult(status_code=202)

        request_id = body['id']
        if not jsonrpc.is_valid_request_id(request_id):
            return McpDispatchResult(
                status_code=400,
                payload=jsonrpc.error_message(
                    None,
                    jsonrpc.INVALID_REQUEST,
                    'Invalid Request: id must be a string or integer',
                ),
            )

        params = body.get('params')
        if params is not None and not isinstance(params, dict):
            return McpDispatchResult(
                status_code=200,
                payload=jsonrpc.error_message(
                    request_id, jsonrpc.INVALID_PARAMS, 'params must be an object'
                ),
            )

        set_mcp_attributes(**target_attributes(method, params or {}, servers))

        try:
            if method == 'initialize':
                result = self._initialize(params or {})
            elif method == 'ping':
                result = {}
            elif method == 'tools/list':
                result = await self._tools_list(servers, client_headers, list_cache)
            elif method == 'tools/call':
                result = await self._tools_call(params or {}, servers, client_headers)
            elif method == 'prompts/list':
                result = await self._prompts_list(servers, client_headers, list_cache)
            elif method == 'prompts/get':
                result = await self._prompts_get(params or {}, servers, client_headers)
            elif method == 'resources/list':
                result = await self._resources_list(servers, client_headers, list_cache)
            elif method == 'resources/read':
                result = await self._resources_read(
                    params or {}, servers, client_headers
                )
            else:
                return McpDispatchResult(
                    status_code=200,
                    payload=jsonrpc.error_message(
                        request_id,
                        jsonrpc.METHOD_NOT_FOUND,
                        f'Method not found: {method}',
                    ),
                )
        except _McpMethodError as e:
            return McpDispatchResult(
                status_code=200,
                payload=jsonrpc.error_message(request_id, e.code, e.message),
            )
        except McpUpstreamError as e:
            return McpDispatchResult(
                status_code=200,
                payload=jsonrpc.error_message(request_id, e.code, e.message),
            )
        except Exception:
            logger.exception('MCP %s failed', method)
            return McpDispatchResult(
                status_code=200,
                payload=jsonrpc.error_message(
                    request_id, jsonrpc.INTERNAL_ERROR, 'Internal error'
                ),
            )
        return McpDispatchResult(
            status_code=200, payload=jsonrpc.result_message(request_id, result)
        )

    @task(name='mcp_initialize')
    def _initialize(self, params: dict) -> dict:
        return {
            'protocolVersion': negotiate_protocol_version(
                params.get('protocolVersion')
            ),
            'capabilities': {'tools': {}, 'prompts': {}, 'resources': {}},
            'serverInfo': {'name': MCP_SERVER_NAME, 'version': gateway_version()},
        }

    @task(name='mcp_tools_list')
    async def _tools_list(
        self,
        servers: list[AnyMcpServer],
        client_headers: Mapping[str, str] | None,
        list_cache: McpListCache | None = None,
    ) -> dict:
        """Fan out to the route's upstreams and merge their tools.

        Each tool name is prefixed ``'{alias}__{tool}'``; all other fields
        pass through verbatim. A failing upstream yields a partial list
        (logged), unless every upstream failed.

        Served from ``list_cache`` when the route declares caching; a degraded
        fan-out is never written back.
        """
        if not servers:
            return {'tools': []}
        cached = await self._cached_list(list_cache, TOOLS_LIST, 'tools')
        if cached is not None:
            return cached
        results = await asyncio.gather(
            *(
                self._upstream_client.list_tools(s, client_headers=client_headers)
                for s in servers
            ),
            return_exceptions=True,
        )
        tools: list[dict] = []
        failed: list[str] = []
        for server, result in zip(servers, results, strict=True):
            if isinstance(result, BaseException):
                # McpUpstreamError is already logged in detail at the raise site.
                failed.append(server.alias)
                continue
            for tool in result.tools:
                data = tool.model_dump(mode='json', by_alias=True, exclude_none=True)
                data['name'] = f'{server.alias}{ALIAS_TOOL_SEPARATOR}{tool.name}'
                tools.append(data)
        self._record_fanout(len(servers), failed, len(tools))
        if failed:
            if len(failed) == len(servers):
                raise _McpMethodError(
                    JSON_RPC_UPSTREAM_ERROR, 'All upstream MCP servers failed'
                )
            logger.warning(
                'tools/list: partial result, upstream MCP servers failed: %s',
                ', '.join(failed),
            )
        result = {'tools': tools}
        await self._store_list(list_cache, TOOLS_LIST, result, failed)
        return result

    @task(name='mcp_tools_call')
    async def _tools_call(
        self,
        params: dict,
        servers: list[AnyMcpServer],
        client_headers: Mapping[str, str] | None,
    ) -> dict:
        """Resolve the ``'{alias}__{tool}'`` prefix and forward the call.

        The upstream ``CallToolResult`` passes through unchanged, including
        ``isError: true`` (tool-execution errors are results, not JSON-RPC
        errors).
        """
        name = params.get('name')
        if not isinstance(name, str) or not name:
            raise _McpMethodError(
                jsonrpc.INVALID_PARAMS, 'tools/call requires a string params.name'
            )
        arguments = params.get('arguments')
        if arguments is not None and not isinstance(arguments, dict):
            raise _McpMethodError(
                jsonrpc.INVALID_PARAMS, 'params.arguments must be an object'
            )
        split = split_alias_name(name)
        server = (
            next((s for s in servers if s.alias == split[0]), None) if split else None
        )
        if split is None or server is None:
            raise _McpMethodError(jsonrpc.INVALID_PARAMS, f'Unknown tool: {name}')
        result = await self._upstream_client.call_tool(
            server, split[1], arguments, client_headers=client_headers
        )
        return result.model_dump(mode='json', by_alias=True, exclude_none=True)

    @task(name='mcp_prompts_list')
    async def _prompts_list(
        self,
        servers: list[AnyMcpServer],
        client_headers: Mapping[str, str] | None,
        list_cache: McpListCache | None = None,
    ) -> dict:
        """Fan out to the route's upstreams and merge their prompts.

        Same shape as :meth:`_tools_list`: each prompt name is prefixed
        ``'{alias}__{name}'``; a failing upstream yields a partial list
        (logged), unless every upstream failed. Cached like it, too.
        """
        if not servers:
            return {'prompts': []}
        cached = await self._cached_list(list_cache, PROMPTS_LIST, 'prompts')
        if cached is not None:
            return cached
        results = await asyncio.gather(
            *(
                self._upstream_client.list_prompts(s, client_headers=client_headers)
                for s in servers
            ),
            return_exceptions=True,
        )
        prompts: list[dict] = []
        failed: list[str] = []
        for server, result in zip(servers, results, strict=True):
            if isinstance(result, BaseException):
                failed.append(server.alias)
                continue
            for prompt in result.prompts:
                data = prompt.model_dump(mode='json', by_alias=True, exclude_none=True)
                data['name'] = f'{server.alias}{ALIAS_TOOL_SEPARATOR}{prompt.name}'
                prompts.append(data)
        self._record_fanout(len(servers), failed, len(prompts))
        if failed:
            if len(failed) == len(servers):
                raise _McpMethodError(
                    JSON_RPC_UPSTREAM_ERROR, 'All upstream MCP servers failed'
                )
            logger.warning(
                'prompts/list: partial result, upstream MCP servers failed: %s',
                ', '.join(failed),
            )
        result = {'prompts': prompts}
        await self._store_list(list_cache, PROMPTS_LIST, result, failed)
        return result

    @task(name='mcp_prompts_get')
    async def _prompts_get(
        self,
        params: dict,
        servers: list[AnyMcpServer],
        client_headers: Mapping[str, str] | None,
    ) -> dict:
        """Resolve the ``'{alias}__{name}'`` prefix and forward the call.

        Same shape as :meth:`_tools_call`.
        """
        name = params.get('name')
        if not isinstance(name, str) or not name:
            raise _McpMethodError(
                jsonrpc.INVALID_PARAMS, 'prompts/get requires a string params.name'
            )
        arguments = params.get('arguments')
        if arguments is not None and not isinstance(arguments, dict):
            raise _McpMethodError(
                jsonrpc.INVALID_PARAMS, 'params.arguments must be an object'
            )
        split = split_alias_name(name)
        server = (
            next((s for s in servers if s.alias == split[0]), None) if split else None
        )
        if split is None or server is None:
            raise _McpMethodError(jsonrpc.INVALID_PARAMS, f'Unknown prompt: {name}')
        result = await self._upstream_client.get_prompt(
            server, split[1], arguments, client_headers=client_headers
        )
        return result.model_dump(mode='json', by_alias=True, exclude_none=True)

    @task(name='mcp_resources_list')
    async def _resources_list(
        self,
        servers: list[AnyMcpServer],
        client_headers: Mapping[str, str] | None,
        list_cache: McpListCache | None = None,
    ) -> dict:
        """Fan out to the route's upstreams and merge their resources.

        Each resource ``uri`` is wrapped via :func:`encode_resource_uri` so
        ``resources/read`` can route it back to the right upstream; a failing
        upstream yields a partial list (logged), unless every upstream failed.
        Cached like :meth:`_tools_list`.
        """
        if not servers:
            return {'resources': []}
        cached = await self._cached_list(list_cache, RESOURCES_LIST, 'resources')
        if cached is not None:
            return cached
        results = await asyncio.gather(
            *(
                self._upstream_client.list_resources(s, client_headers=client_headers)
                for s in servers
            ),
            return_exceptions=True,
        )
        resources: list[dict] = []
        failed: list[str] = []
        for server, result in zip(servers, results, strict=True):
            if isinstance(result, BaseException):
                failed.append(server.alias)
                continue
            for resource in result.resources:
                data = resource.model_dump(
                    mode='json', by_alias=True, exclude_none=True
                )
                data['uri'] = encode_resource_uri(server.alias, data['uri'])
                resources.append(data)
        self._record_fanout(len(servers), failed, len(resources))
        if failed:
            if len(failed) == len(servers):
                raise _McpMethodError(
                    JSON_RPC_UPSTREAM_ERROR, 'All upstream MCP servers failed'
                )
            logger.warning(
                'resources/list: partial result, upstream MCP servers failed: %s',
                ', '.join(failed),
            )
        result = {'resources': resources}
        await self._store_list(list_cache, RESOURCES_LIST, result, failed)
        return result

    @task(name='mcp_resources_read')
    async def _resources_read(
        self,
        params: dict,
        servers: list[AnyMcpServer],
        client_headers: Mapping[str, str] | None,
    ) -> dict:
        """Unwrap the aliased ``uri`` and forward the read.

        The returned ``contents[].uri`` is re-wrapped so the raw upstream URI
        never reaches the client (mirrors how ``tools/list``'s prefix keeps
        the upstream's raw tool name from being client-visible).
        """
        uri = params.get('uri')
        if not isinstance(uri, str) or not uri:
            raise _McpMethodError(
                jsonrpc.INVALID_PARAMS, 'resources/read requires a string params.uri'
            )
        decoded = decode_resource_uri(uri)
        server = (
            next((s for s in servers if s.alias == decoded[0]), None)
            if decoded
            else None
        )
        if decoded is None or server is None:
            raise _McpMethodError(jsonrpc.INVALID_PARAMS, f'Unknown resource: {uri}')
        alias, upstream_uri = decoded
        result = await self._upstream_client.read_resource(
            server, upstream_uri, client_headers=client_headers
        )
        data = result.model_dump(mode='json', by_alias=True, exclude_none=True)
        for content in data.get('contents', []):
            if 'uri' in content:
                content['uri'] = encode_resource_uri(alias, content['uri'])
        return data

    def _validate_origin(self, request: Request) -> None:
        """DNS-rebinding defense: reject browser Origins not in the allowlist.

        Requests without an ``Origin`` header (non-browser clients) pass.
        """
        origin = request.headers.get('origin')
        if origin is None:
            return
        if '*' in self._allowed_origins or origin in self._allowed_origins:
            return
        raise McpTransportError(
            'Origin not allowed',
            403,
            code='mcp_origin_forbidden',
            log_message=f'MCP request from disallowed origin: {origin}',
        )

    @staticmethod
    def _validate_protocol_version(request: Request) -> None:
        """Reject unsupported ``MCP-Protocol-Version`` headers with 400.

        An absent header is tolerated (the spec says to assume the
        pre-header revision ``2025-03-26``); behavior does not differ
        across revisions for this tools-only proxy.
        """
        version = request.headers.get(PROTOCOL_VERSION_HEADER)
        if version is not None and version not in SUPPORTED_PROTOCOL_VERSIONS:
            raise McpTransportError(
                f'Unsupported MCP protocol version: {version}. '
                f'Supported: {", ".join(SUPPORTED_PROTOCOL_VERSIONS)}',
                400,
                code='mcp_unsupported_protocol_version',
            )
