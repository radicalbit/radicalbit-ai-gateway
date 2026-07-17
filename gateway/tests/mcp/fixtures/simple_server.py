"""Minimal MCP server used by upstream-client integration tests.

Run over stdio: ``python tests/mcp/fixtures/simple_server.py``.
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP('simple-test-server')


@mcp.tool()
def echo(text: str) -> str:
    """Echo the given text back."""
    return f'echo: {text}'


@mcp.prompt()
def greeting(name: str) -> str:
    """Return a greeting prompt."""
    return f'Say hello to {name}.'


@mcp.resource('note://welcome')
def welcome_note() -> str:
    """Return a static welcome note."""
    return 'welcome to the test server'


if __name__ == '__main__':
    mcp.run(transport='stdio')
