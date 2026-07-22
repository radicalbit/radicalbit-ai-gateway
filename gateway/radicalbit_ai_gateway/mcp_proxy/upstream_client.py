import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
import logging
from typing import TypeVar

from mcp import ClientSession, types
from mcp.client.stdio import (
    StdioServerParameters,
    get_default_environment,
    stdio_client,
)
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.exceptions import McpError as SdkMcpError
from pydantic import AnyUrl

from radicalbit_ai_gateway.mcp_proxy.errors import McpUpstreamError
from radicalbit_ai_gateway.mcp_proxy.headers import build_upstream_headers
from radicalbit_ai_gateway.models.mcp_server import (
    AnyMcpServer,
    McpHttpServer,
    McpStdioServer,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30.0

T = TypeVar('T')


class McpUpstreamClient:
    """Stateless outbound MCP client: one ephemeral session per operation.

    Each operation opens a transport to the upstream server, runs the full
    initialize handshake, performs the single request, and closes. The
    per-server ``timeout`` (or ``default_timeout``) bounds the whole
    lifecycle, connection setup inclu   ded.
    """

    def __init__(
        self,
        default_timeout: float = DEFAULT_TIMEOUT_SECONDS,
        httpx_client_factory=None,
    ):
        self._default_timeout = default_timeout
        self._httpx_client_factory = httpx_client_factory

    async def list_tools(
        self,
        server: AnyMcpServer,
        *,
        cursor: str | None = None,
        client_headers: Mapping[str, str] | None = None,
    ) -> types.ListToolsResult:
        return await self._run(
            server, lambda session: session.list_tools(cursor), client_headers
        )

    async def call_tool(
        self,
        server: AnyMcpServer,
        name: str,
        arguments: dict | None = None,
        *,
        client_headers: Mapping[str, str] | None = None,
    ) -> types.CallToolResult:
        return await self._run(
            server, lambda session: session.call_tool(name, arguments), client_headers
        )

    async def list_prompts(
        self,
        server: AnyMcpServer,
        *,
        cursor: str | None = None,
        client_headers: Mapping[str, str] | None = None,
    ) -> types.ListPromptsResult:
        return await self._run(
            server, lambda session: session.list_prompts(cursor), client_headers
        )

    async def get_prompt(
        self,
        server: AnyMcpServer,
        name: str,
        arguments: dict[str, str] | None = None,
        *,
        client_headers: Mapping[str, str] | None = None,
    ) -> types.GetPromptResult:
        return await self._run(
            server, lambda session: session.get_prompt(name, arguments), client_headers
        )

    async def list_resources(
        self,
        server: AnyMcpServer,
        *,
        cursor: str | None = None,
        client_headers: Mapping[str, str] | None = None,
    ) -> types.ListResourcesResult:
        return await self._run(
            server, lambda session: session.list_resources(cursor), client_headers
        )

    async def read_resource(
        self,
        server: AnyMcpServer,
        uri: str,
        *,
        client_headers: Mapping[str, str] | None = None,
    ) -> types.ReadResourceResult:
        return await self._run(
            server, lambda session: session.read_resource(AnyUrl(uri)), client_headers
        )

    @asynccontextmanager
    async def _session(
        self,
        server: AnyMcpServer,
        client_headers: Mapping[str, str] | None,
    ) -> AsyncIterator[ClientSession]:
        if isinstance(server, McpHttpServer):
            kwargs = {}
            if self._httpx_client_factory is not None:
                kwargs['httpx_client_factory'] = self._httpx_client_factory
            transport = streamablehttp_client(
                server.url,
                headers=build_upstream_headers(server, client_headers),
                **kwargs,
            )
            async with (
                transport as (read, write, _get_session_id),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                yield session
        elif isinstance(server, McpStdioServer):
            params = StdioServerParameters(
                command=server.command,
                args=server.args,
                env={**get_default_environment(), **(server.env or {})},
                cwd=server.cwd,
            )
            async with (
                stdio_client(params) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                yield session
        else:
            raise TypeError(f'Unsupported MCP server type: {type(server).__name__}')

    async def _run(
        self,
        server: AnyMcpServer,
        op: Callable[[ClientSession], Awaitable[T]],
        client_headers: Mapping[str, str] | None,
    ) -> T:
        timeout = server.timeout or self._default_timeout
        try:
            async with asyncio.timeout(timeout):
                async with self._session(server, client_headers) as session:
                    return await op(session)
        except TimeoutError as e:
            logger.warning(
                'MCP upstream %s timed out after %.1fs', server.alias, timeout
            )
            raise McpUpstreamError(
                server.alias, f"Upstream MCP server '{server.alias}' timed out"
            ) from e
        except SdkMcpError as e:
            raise McpUpstreamError(
                server.alias, e.error.message, code=e.error.code
            ) from e
        except BaseExceptionGroup as eg:
            if eg.split(Exception)[1] is not None:
                # KeyboardInterrupt/SystemExit inside the group: propagate.
                raise
            if eg.subgroup(TimeoutError):
                logger.warning(
                    'MCP upstream %s timed out after %.1fs', server.alias, timeout
                )
                raise McpUpstreamError(
                    server.alias, f"Upstream MCP server '{server.alias}' timed out"
                ) from eg
            logger.exception('MCP upstream %s transport failure', server.alias)
            raise McpUpstreamError(
                server.alias, f"Upstream MCP server '{server.alias}' request failed"
            ) from eg
        except Exception as e:
            logger.exception('MCP upstream %s request failed', server.alias)
            raise McpUpstreamError(
                server.alias, f"Upstream MCP server '{server.alias}' request failed"
            ) from e
