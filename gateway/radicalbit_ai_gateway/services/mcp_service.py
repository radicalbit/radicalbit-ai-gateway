import asyncio
from collections.abc import Mapping
from importlib.metadata import PackageNotFoundError, version as _package_version
import logging
from uuid import UUID

from fastapi import Request
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


def split_tool_name(name: str) -> tuple[str, str] | None:
    """Split ``'{alias}__{tool}'`` on the first separator.

    Returns ``(alias, tool)`` or ``None`` when the name carries no alias
    prefix. Tool names containing further ``'__'`` keep them intact.
    """
    alias, sep, tool = name.partition(ALIAS_TOOL_SEPARATOR)
    if not sep or not alias or not tool:
        return None
    return alias, tool


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
        self._validate_origin(request)

        entry: ProjectEntry | None = request.app.state.project_configs.get(project_name)
        project_uuid = str(entry.uuid) if entry else ''
        set_trace_attributes(
            project_uuid=project_uuid, project_name=project_name, route_name=route_name
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
            return McpDispatchResult(
                status_code=400,
                payload=jsonrpc.error_message(None, jsonrpc.PARSE_ERROR, 'Parse error'),
            )

        servers = entry.config.get_route_mcp_servers(route_name)
        set_operation_category(OperationCategory.INVOCATION)
        return await self._dispatch(body, servers, request.headers)

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

        try:
            if method == 'initialize':
                result = self._initialize(params or {})
            elif method == 'ping':
                result = {}
            elif method == 'tools/list':
                result = await self._tools_list(servers, client_headers)
            elif method == 'tools/call':
                result = await self._tools_call(params or {}, servers, client_headers)
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
            'capabilities': {'tools': {}},
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
        split = split_tool_name(name)
        server = (
            next((s for s in servers if s.alias == split[0]), None) if split else None
        )
        if split is None or server is None:
            raise _McpMethodError(jsonrpc.INVALID_PARAMS, f'Unknown tool: {name}')
        set_mcp_attributes(method='tools/call', alias=split[0], tool_name=split[1])
        result = await self._upstream_client.call_tool(
            server, split[1], arguments, client_headers=client_headers
        )
        return result.model_dump(mode='json', by_alias=True, exclude_none=True)

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
