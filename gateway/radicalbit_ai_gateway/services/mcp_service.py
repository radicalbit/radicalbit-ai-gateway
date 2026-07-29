import asyncio
from collections.abc import Mapping
from importlib.metadata import PackageNotFoundError, version as _package_version
import logging
from urllib.parse import quote, unquote
from uuid import UUID, uuid4

from fastapi import Request
from opentelemetry.trace import Status, StatusCode, get_current_span
from traceloop.sdk.decorators import task, workflow

from radicalbit_ai_gateway.auth.request_auth import authenticate_bearer_request
from radicalbit_ai_gateway.mcp_proxy import jsonrpc
from radicalbit_ai_gateway.mcp_proxy.errors import (
    JSON_RPC_UPSTREAM_ERROR,
    McpUpstreamError,
)
from radicalbit_ai_gateway.mcp_proxy.upstream_client import McpUpstreamClient
from radicalbit_ai_gateway.models.mcp_dispatch_result import McpDispatchResult
from radicalbit_ai_gateway.models.mcp_server import ALIAS_TOOL_SEPARATOR, AnyMcpServer
from radicalbit_ai_gateway.models.project_entry import ProjectEntry
from radicalbit_ai_gateway.services.group_service import GroupService
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import McpTransportError
from radicalbit_ai_gateway.utils.trace_attributes import (
    OperationCategory,
    ensure_endpoint_category,
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


def target_attributes(method: str, params: dict) -> dict:
    """Best-effort ``alias``/``target`` for the methods addressing one object.

    Resolved here rather than inside each handler because a ``@task`` detaches
    its context on exit: attributes set inside one reach that task's span only,
    never the enclosing ``mcp_request`` workflow span the traces list queries.
    Called from the workflow scope, these land on the root span and are
    inherited by the child task span.

    An unresolvable name is still reported, since knowing what the client asked
    for is what makes the failure diagnosable.
    """
    if method in ('tools/call', 'prompts/get'):
        name = params.get('name')
        split = split_alias_name(name) if isinstance(name, str) else None
    elif method == 'resources/read':
        uri = params.get('uri')
        split = decode_resource_uri(uri) if isinstance(uri, str) else None
    else:
        return {}
    return {'alias': split[0], 'target': split[1]} if split else {}


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

    @workflow(name='mcp_request')
    @ensure_endpoint_category
    async def handle_post(
        self, request: Request, project_name: str, route_name: str
    ) -> McpDispatchResult:
        """Authenticate and authorize the POST, then dispatch its JSON-RPC message."""
        # Stamped before origin/auth checks so rejected requests stay
        # correlatable. Unlike the /v1/* endpoints, whose request_uuid comes from
        # RequestEventMiddleware, MCP is not a tracked path there — so reuse an
        # existing id if one was set, else mint our own.
        request_uuid = getattr(request.state, 'request_uuid', None) or str(uuid4())
        request.state.request_uuid = request_uuid

        self._validate_origin(request)

        entry: ProjectEntry | None = request.app.state.project_configs.get(project_name)
        project_uuid = str(entry.uuid) if entry else ''
        set_trace_attributes(
            request_uuid=request_uuid,
            project_uuid=project_uuid,
            project_name=project_name,
            route_name=route_name,
        )

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
        if not self._group_service.check_key_uuid_for_route(
            f'{project_name}/{route_name}', UUID(key_details.api_key_uuid)
        ):
            raise McpTransportError(
                f'API Key not associated with route {route_name}',
                403,
                code='mcp_key_not_bound',
            )

        self._validate_protocol_version(request)

        try:
            body = await request.json()
        except Exception:
            return self._record_error_outcome(
                McpDispatchResult(
                    status_code=400,
                    payload=jsonrpc.error_message(
                        None, jsonrpc.PARSE_ERROR, 'Parse error'
                    ),
                )
            )

        servers = entry.config.get_route_mcp_servers(route_name)
        set_operation_category(OperationCategory.INVOCATION)
        return self._record_error_outcome(
            await self._dispatch(body, servers, request.headers)
        )

    @staticmethod
    def _record_error_outcome(result: McpDispatchResult) -> McpDispatchResult:
        """Mark the workflow span when the response carries a JSON-RPC error.

        ``_dispatch`` returns protocol and upstream failures as ``error``
        bodies over HTTP 200, so without this a failed ``tools/call`` is
        indistinguishable from a success in the traces UI. Returns ``result``
        so it can wrap a return statement.
        """
        error = (result.payload or {}).get('error')
        if not error:
            return result
        set_mcp_attributes(error_code=error.get('code'))
        span = get_current_span()
        if span and span.is_recording():
            span.set_status(Status(StatusCode.ERROR, error.get('message', '')))
        return result

    @staticmethod
    def _record_fanout(total: int, failed: list[str], count: int) -> None:
        """Record the outcome of a list method's fan-out on its own span.

        Partial upstream failures are otherwise log-only, so a short list
        can't be told from a degraded one. Always set, so ``mcp.result.count``
        is present and ``mcp.upstream.failed`` is empty rather than absent.
        """
        span = get_current_span()
        if span and span.is_recording():
            span.set_attribute('mcp.upstream.total', total)
            span.set_attribute('mcp.upstream.failed', ','.join(failed))
            span.set_attribute('mcp.result.count', count)

    async def _dispatch(
        self,
        body: dict,
        servers: list[AnyMcpServer],
        client_headers: Mapping[str, str] | None,
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

        set_mcp_attributes(**target_attributes(method, params or {}))

        try:
            if method == 'initialize':
                result = self._initialize(params or {})
            elif method == 'ping':
                result = {}
            elif method == 'tools/list':
                result = await self._tools_list(servers, client_headers)
            elif method == 'tools/call':
                result = await self._tools_call(params or {}, servers, client_headers)
            elif method == 'prompts/list':
                result = await self._prompts_list(servers, client_headers)
            elif method == 'prompts/get':
                result = await self._prompts_get(params or {}, servers, client_headers)
            elif method == 'resources/list':
                result = await self._resources_list(servers, client_headers)
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
    ) -> dict:
        """Fan out to the route's upstreams and merge their tools.

        Each tool name is prefixed ``'{alias}__{tool}'``; all other fields
        pass through verbatim. A failing upstream yields a partial list
        (logged), unless every upstream failed.
        """
        if not servers:
            return {'tools': []}
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
        return {'tools': tools}

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
    ) -> dict:
        """Fan out to the route's upstreams and merge their prompts.

        Same shape as :meth:`_tools_list`: each prompt name is prefixed
        ``'{alias}__{name}'``; a failing upstream yields a partial list
        (logged), unless every upstream failed.
        """
        if not servers:
            return {'prompts': []}
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
        return {'prompts': prompts}

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
    ) -> dict:
        """Fan out to the route's upstreams and merge their resources.

        Each resource ``uri`` is wrapped via :func:`encode_resource_uri` so
        ``resources/read`` can route it back to the right upstream; a failing
        upstream yields a partial list (logged), unless every upstream failed.
        """
        if not servers:
            return {'resources': []}
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
        return {'resources': resources}

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
