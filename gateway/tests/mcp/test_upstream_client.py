import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import sys
from unittest.mock import AsyncMock, patch

import httpx
from mcp import types
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import McpError
import pytest

from radicalbit_ai_gateway.mcp_proxy.errors import McpUpstreamError
from radicalbit_ai_gateway.mcp_proxy.upstream_client import McpUpstreamClient
from radicalbit_ai_gateway.models.mcp_server import McpHttpServer, McpStdioServer

FIXTURE_SERVER = Path(__file__).parent / 'fixtures' / 'simple_server.py'

HTTP_SERVER = McpHttpServer(
    alias='http-upstream',
    url='https://upstream.example.com/mcp/',
    headers={'Authorization': 'Bearer secret-pat'},
)

STDIO_SERVER = McpStdioServer(
    alias='stdio-upstream',
    command=sys.executable,
    args=[str(FIXTURE_SERVER)],
)


def _client_with_mock_session(session: AsyncMock) -> McpUpstreamClient:
    """Patch McpUpstreamClient._session to yield the given mock session."""
    client = McpUpstreamClient()

    @asynccontextmanager
    async def fake_session(server, client_headers):
        yield session

    client._session = fake_session
    return client


# ---------------------------------------------------------------------------
# Unit tests (mocked session)
# ---------------------------------------------------------------------------


async def test_each_operation_calls_matching_session_method():
    session = AsyncMock()
    client = _client_with_mock_session(session)

    await client.list_tools(HTTP_SERVER, cursor='c1')
    session.list_tools.assert_awaited_once_with('c1')

    await client.call_tool(HTTP_SERVER, 'echo', {'text': 'hi'})
    session.call_tool.assert_awaited_once_with('echo', {'text': 'hi'})

    await client.list_prompts(HTTP_SERVER)
    session.list_prompts.assert_awaited_once_with(None)

    await client.get_prompt(HTTP_SERVER, 'greeting', {'name': 'x'})
    session.get_prompt.assert_awaited_once_with('greeting', {'name': 'x'})

    await client.list_resources(HTTP_SERVER)
    session.list_resources.assert_awaited_once_with(None)

    await client.read_resource(HTTP_SERVER, 'note://welcome')
    (uri,) = session.read_resource.await_args.args
    assert str(uri) == 'note://welcome'


async def test_timeout_produces_sanitized_error():
    session = AsyncMock()

    async def hang(*args, **kwargs):
        await asyncio.sleep(10)

    session.list_tools.side_effect = hang
    server = HTTP_SERVER.model_copy(update={'timeout': 0.05})
    client = _client_with_mock_session(session)

    with pytest.raises(McpUpstreamError) as exc_info:
        await client.list_tools(server)
    err = exc_info.value
    assert err.code == -32000
    assert err.alias == 'http-upstream'
    assert 'timed out' in err.message
    assert 'upstream.example.com' not in err.message
    assert 'secret-pat' not in err.message


async def test_transport_failure_maps_to_generic_error():
    session = AsyncMock()
    session.list_tools.side_effect = ConnectionError(
        'refused https://upstream.example.com'
    )
    client = _client_with_mock_session(session)

    with pytest.raises(McpUpstreamError) as exc_info:
        await client.list_tools(HTTP_SERVER)
    assert exc_info.value.code == -32000
    assert 'upstream.example.com' not in exc_info.value.message


async def test_exception_group_maps_to_generic_error():
    session = AsyncMock()
    session.list_tools.side_effect = BaseExceptionGroup(
        'transport', [ConnectionError('boom')]
    )
    client = _client_with_mock_session(session)

    with pytest.raises(McpUpstreamError) as exc_info:
        await client.list_tools(HTTP_SERVER)
    assert exc_info.value.code == -32000


async def test_group_wrapped_timeout_classified_as_timeout():
    session = AsyncMock()
    session.list_tools.side_effect = BaseExceptionGroup('transport', [TimeoutError()])
    client = _client_with_mock_session(session)

    with pytest.raises(McpUpstreamError) as exc_info:
        await client.list_tools(HTTP_SERVER)
    assert exc_info.value.code == -32000
    assert 'timed out' in exc_info.value.message


async def test_group_with_base_exception_propagates():
    session = AsyncMock()
    session.list_tools.side_effect = BaseExceptionGroup(
        'shutdown', [KeyboardInterrupt()]
    )
    client = _client_with_mock_session(session)

    with pytest.raises(BaseExceptionGroup) as exc_info:
        await client.list_tools(HTTP_SERVER)
    assert exc_info.group_contains(KeyboardInterrupt)


async def test_upstream_jsonrpc_error_preserves_code_and_message():
    session = AsyncMock()
    session.call_tool.side_effect = McpError(
        types.ErrorData(code=-32602, message='Unknown tool: nope')
    )
    client = _client_with_mock_session(session)

    with pytest.raises(McpUpstreamError) as exc_info:
        await client.call_tool(HTTP_SERVER, 'nope', {})
    assert exc_info.value.code == -32602
    assert exc_info.value.message == 'Unknown tool: nope'


async def test_tool_is_error_result_passed_through():
    result = types.CallToolResult(
        content=[types.TextContent(type='text', text='tool blew up')], isError=True
    )
    session = AsyncMock()
    session.call_tool.return_value = result
    client = _client_with_mock_session(session)

    returned = await client.call_tool(HTTP_SERVER, 'echo', {})
    assert returned is result
    assert returned.isError is True


async def test_http_transport_receives_built_headers():
    with patch(
        'radicalbit_ai_gateway.mcp_proxy.upstream_client.streamablehttp_client'
    ) as transport:
        transport.side_effect = RuntimeError('stop here')
        client = McpUpstreamClient()
        server = HTTP_SERVER.model_copy(update={'forward_headers': ['x-user-jwt']})

        with pytest.raises(McpUpstreamError):
            await client.list_tools(
                server,
                client_headers={
                    'X-User-Jwt': 'jwt-1',
                    'Authorization': 'Bearer sk-rb-x',
                },
            )
        transport.assert_called_once()
        _, kwargs = transport.call_args
        assert kwargs['headers'] == {
            'x-user-jwt': 'jwt-1',
            'Authorization': 'Bearer secret-pat',
        }


# ---------------------------------------------------------------------------
# Integration tests (real SDK over stdio subprocess)
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    return McpUpstreamClient(default_timeout=20.0)


async def test_stdio_list_and_call_tool(client):
    tools = await client.list_tools(STDIO_SERVER)
    assert [t.name for t in tools.tools] == ['echo']

    result = await client.call_tool(STDIO_SERVER, 'echo', {'text': 'hi'})
    assert result.isError is False
    assert result.content[0].text == 'echo: hi'


async def test_stdio_prompts(client):
    prompts = await client.list_prompts(STDIO_SERVER)
    assert [p.name for p in prompts.prompts] == ['greeting']

    prompt = await client.get_prompt(STDIO_SERVER, 'greeting', {'name': 'Ada'})
    assert 'Ada' in prompt.messages[0].content.text


async def test_stdio_resources(client):
    resources = await client.list_resources(STDIO_SERVER)
    assert [str(r.uri) for r in resources.resources] == ['note://welcome']

    content = await client.read_resource(STDIO_SERVER, 'note://welcome')
    assert content.contents[0].text == 'welcome to the test server'


async def test_stdio_unknown_tool_is_error_result(client):
    result = await client.call_tool(STDIO_SERVER, 'does-not-exist', {})
    assert result.isError is True


async def test_stdio_spawn_failure_maps_to_sanitized_error():
    broken = McpStdioServer(
        alias='broken', command='/nonexistent-binary-xyz', timeout=5
    )
    client = McpUpstreamClient()
    with pytest.raises(McpUpstreamError) as exc_info:
        await client.list_tools(broken)
    assert exc_info.value.code == -32000
    assert '/nonexistent-binary-xyz' not in exc_info.value.message


# ---------------------------------------------------------------------------
# Integration tests (real SDK over in-process Streamable HTTP / ASGI)
# ---------------------------------------------------------------------------


def _build_http_upstream():
    """In-process stateless Streamable HTTP MCP server plus a matching
    (client, McpHttpServer) pair wired through httpx.ASGITransport.

    Returns ``(app, client, server, received_headers)``; the caller must run
    the test body inside ``app.router.lifespan_context(app)`` (entering the
    anyio task group in a fixture breaks pytest-asyncio task affinity).
    """
    upstream = FastMCP(
        'http-test-server',
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=['testserver'], allowed_origins=['http://testserver']
        ),
    )

    received_headers: dict[str, str] = {}

    @upstream.tool()
    def echo(text: str) -> str:
        """Echo the given text back."""
        return f'echo: {text}'

    app = upstream.streamable_http_app()

    class HeaderRecorder:
        """ASGI middleware capturing the headers the upstream receives."""

        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope['type'] == 'http':
                received_headers.update(
                    {k.decode(): v.decode() for k, v in scope['headers']}
                )
            await self.app(scope, receive, send)

    wrapped = HeaderRecorder(app)

    def client_factory(headers=None, timeout=None, auth=None):
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=wrapped),
            base_url='http://testserver',
            headers=headers,
            timeout=timeout,
            auth=auth,
        )

    client = McpUpstreamClient(
        default_timeout=20.0, httpx_client_factory=client_factory
    )
    server = McpHttpServer(
        alias='http-upstream',
        url='http://testserver/mcp',
        headers={'X-Api-Key': 'static-secret'},
        forward_headers=['x-user-jwt', 'authorization'],
    )
    return app, client, server, received_headers


async def test_http_list_and_call_tool():
    app, client, server, received_headers = _build_http_upstream()

    async with app.router.lifespan_context(app):
        tools = await client.list_tools(server)
        assert [t.name for t in tools.tools] == ['echo']

        result = await client.call_tool(
            server,
            'echo',
            {'text': 'hi'},
            client_headers={
                'X-User-Jwt': 'jwt-1',
                'Authorization': 'Bearer sk-rb-x',
                'X-Mcp-Http-Upstream-Authorization': 'Bearer user-jwt',
            },
        )
        assert result.isError is False
        assert result.content[0].text == 'echo: hi'

    assert received_headers['x-api-key'] == 'static-secret'
    assert received_headers['x-user-jwt'] == 'jwt-1'
    # the prefixed header fills the upstream authorization; the gateway key never does
    assert received_headers['authorization'] == 'Bearer user-jwt'
