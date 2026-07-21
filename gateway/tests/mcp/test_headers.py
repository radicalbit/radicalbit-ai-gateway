from radicalbit_ai_gateway.mcp_proxy.headers import build_upstream_headers
from radicalbit_ai_gateway.models.mcp_server import McpHttpServer


def _server(**kwargs):
    return McpHttpServer(alias='github', url='https://api.example.com/mcp/', **kwargs)


def test_no_forwarding_without_allowlist():
    server = _server(headers={'X-Api-Key': 'static'})
    result = build_upstream_headers(server, {'X-User-Jwt': 'jwt-value'})
    assert result == {'X-Api-Key': 'static'}


def test_allowlisted_headers_forwarded_case_insensitively():
    server = _server(forward_headers=['X-User-Jwt'])
    result = build_upstream_headers(server, {'X-USER-JWT': 'jwt-value'})
    assert result == {'x-user-jwt': 'jwt-value'}


def test_static_headers_win_over_forwarded():
    server = _server(
        headers={'X-User-Jwt': 'operator-value'}, forward_headers=['X-User-Jwt']
    )
    result = build_upstream_headers(server, {'X-User-Jwt': 'client-value'})
    assert result == {'X-User-Jwt': 'operator-value'}


def test_plain_authorization_never_forwarded_even_when_allowlisted():
    server = _server(forward_headers=['authorization', 'x-user-jwt'])
    result = build_upstream_headers(
        server, {'Authorization': 'Bearer sk-rb-key', 'X-User-Jwt': 'jwt-value'}
    )
    assert result == {'x-user-jwt': 'jwt-value'}


def test_prefixed_header_fills_authorization_target():
    server = _server(forward_headers=['authorization'])
    result = build_upstream_headers(
        server,
        {
            'Authorization': 'Bearer sk-rb-key',
            'X-Mcp-Github-Authorization': 'Bearer user-jwt',
        },
    )
    assert result == {'authorization': 'Bearer user-jwt'}


def test_prefixed_header_for_other_alias_ignored():
    server = _server(forward_headers=['authorization', 'x-api-key'])
    result = build_upstream_headers(
        server,
        {
            'x-mcp-jira-authorization': 'Bearer jira-jwt',
            'x-mcp-github-x-api-key': 'github-key',
        },
    )
    assert result == {'x-api-key': 'github-key'}


def test_prefixed_wins_over_plain():
    server = _server(forward_headers=['x-user-jwt'])
    result = build_upstream_headers(
        server,
        {'X-User-Jwt': 'plain-value', 'x-mcp-github-x-user-jwt': 'targeted-value'},
    )
    assert result == {'x-user-jwt': 'targeted-value'}


def test_prefixed_target_must_be_allowlisted():
    server = _server(forward_headers=['x-user-jwt'])
    result = build_upstream_headers(
        server, {'x-mcp-github-authorization': 'Bearer user-jwt'}
    )
    assert result == {}


def test_prefixed_forbidden_target_ignored():
    server = _server(forward_headers=['x-user-jwt'])
    # bypass the pydantic validator to simulate a smuggled allowlist entry
    object.__setattr__(server, 'forward_headers', ['mcp-session-id', 'x-user-jwt'])
    result = build_upstream_headers(server, {'x-mcp-github-mcp-session-id': 'hijacked'})
    assert result == {}


def test_non_allowlisted_headers_dropped():
    server = _server(forward_headers=['x-user-jwt'])
    result = build_upstream_headers(
        server, {'X-User-Jwt': 'jwt', 'X-Other': 'nope', 'Cookie': 'session=1'}
    )
    assert result == {'x-user-jwt': 'jwt'}


def test_empty_inputs():
    server = _server()
    assert build_upstream_headers(server, None) == {}
    assert build_upstream_headers(server, {}) == {}
    static = _server(headers={'X-Api-Key': 'static'})
    assert build_upstream_headers(static, None) == {'X-Api-Key': 'static'}
