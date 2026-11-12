import pytest

from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.mcp_server import McpHttpServer, McpStdioServer


def _base_config(mcp_servers=None, route_mcp_servers=None):
    route = {'chat_models': ['m1']}
    if route_mcp_servers is not None:
        route['mcp_servers'] = route_mcp_servers
    raw = {
        'chat_models': [{'model_id': 'm1', 'model': 'openai/gpt-4o'}],
        'routes': {'my_route': route},
    }
    if mcp_servers is not None:
        raw['mcp_servers'] = mcp_servers
    return raw


HTTP_SERVER = {
    'alias': 'github',
    'transport': 'streamable_http',
    'url': 'https://api.example.com/mcp/',
    'headers': {'Authorization': '__secret_placeholder__'},
    'forward_headers': ['X-User-Jwt'],
    'timeout': 30,
}

STDIO_SERVER = {
    'alias': 'local-tools',
    'transport': 'stdio',
    'command': 'python',
    'args': ['-m', 'my_mcp_server'],
    'env': {'API_TOKEN': '__secret_placeholder__'},
}

ALLOWLIST_FIELDS = ['allowed_tools', 'allowed_prompts', 'allowed_resources']


def test_http_and_stdio_servers_parse_and_route_references_resolve():
    config = GatewayConfig.model_validate(
        _base_config(
            mcp_servers=[HTTP_SERVER, STDIO_SERVER],
            route_mcp_servers=['github', 'local-tools'],
        )
    )

    assert isinstance(config.mcp_servers_by_alias['github'], McpHttpServer)
    assert isinstance(config.mcp_servers_by_alias['local-tools'], McpStdioServer)

    resolved = config.get_route_mcp_servers('my_route')
    assert [s.alias for s in resolved] == ['github', 'local-tools']


def test_get_route_mcp_servers_empty_for_route_without_servers():
    config = GatewayConfig.model_validate(_base_config(mcp_servers=[HTTP_SERVER]))
    assert config.get_route_mcp_servers('my_route') == []
    assert config.get_route_mcp_servers('unknown_route') == []


@pytest.mark.parametrize(
    ('mcp_servers', 'route_mcp_servers', 'match'),
    [
        pytest.param(
            [{k: v for k, v in HTTP_SERVER.items() if k != 'transport'}],
            None,
            'transport',
            id='missing-transport',
        ),
        pytest.param(
            [{**STDIO_SERVER, 'unexpected': True}], None, 'unexpected', id='unknown-key'
        ),
        pytest.param(
            [HTTP_SERVER, {**STDIO_SERVER, 'alias': 'GitHub'}],
            None,
            r'unique aliases \(case-insensitively\)\. Duplicates found: GitHub, github',
            id='case-variant-duplicate-aliases',
        ),
        pytest.param(
            [HTTP_SERVER],
            ['missing'],
            'not declared in top-level mcp_servers: missing',
            id='route-references-undefined-alias',
        ),
        pytest.param(
            [HTTP_SERVER],
            ['github', 'github'],
            'duplicate mcp_servers: github',
            id='duplicate-route-references',
        ),
        pytest.param(
            [{**HTTP_SERVER, 'alias': 'git__hub'}],
            None,
            'reserved as the alias/tool separator',
            id='alias-with-double-underscore',
        ),
        pytest.param([{**HTTP_SERVER, 'alias': ''}], None, None, id='empty-alias'),
        pytest.param([{**HTTP_SERVER, 'alias': '  '}], None, None, id='blank-alias'),
        pytest.param(
            [{**HTTP_SERVER, 'alias': 'my alias'}], None, None, id='alias-with-space'
        ),
        pytest.param([{**HTTP_SERVER, 'timeout': 0}], None, None, id='zero-timeout'),
        *(
            pytest.param(
                [{**HTTP_SERVER, 'forward_headers': [header]}],
                None,
                'forward_headers must not contain',
                id=f'forbidden-forward-header-{header}',
            )
            for header in (
                'Mcp-Session-Id',
                'mcp-protocol-version',
                'host',
                'Content-Length',
            )
        ),
        *(
            pytest.param(
                [{**HTTP_SERVER, field: [entry]}],
                None,
                f'{field} entries must not be empty',
                id=f'blank-{field}-entry',
            )
            for field, entry in zip(ALLOWLIST_FIELDS, ['', '   ', ''], strict=True)
        ),
    ],
)
def test_invalid_mcp_server_config_rejected(mcp_servers, route_mcp_servers, match):
    with pytest.raises(ValueError, match=match):
        GatewayConfig.model_validate(
            _base_config(mcp_servers=mcp_servers, route_mcp_servers=route_mcp_servers)
        )


def test_forward_headers_are_normalized_and_deduped():
    """Authorization is allowed, unlike the protocol headers."""
    headers = ['Authorization', 'X-User-Jwt', 'x-user-jwt', 'X-A']
    config = GatewayConfig.model_validate(
        _base_config(mcp_servers=[{**HTTP_SERVER, 'forward_headers': headers}])
    )
    assert config.mcp_servers_by_alias['github'].forward_headers == [
        'authorization',
        'x-user-jwt',
        'x-a',
    ]


def test_allowlist_entries_are_stripped_and_deduped_in_order_on_stdio_too():
    config = GatewayConfig.model_validate(
        _base_config(
            mcp_servers=[
                {**STDIO_SERVER, **{f: [' b ', 'a', 'b'] for f in ALLOWLIST_FIELDS}}
            ]
        )
    )
    server = config.mcp_servers_by_alias['local-tools']
    assert [getattr(server, f) for f in ALLOWLIST_FIELDS] == [['b', 'a']] * 3


UNSET = object()


@pytest.mark.parametrize(
    ('field', 'method', 'allowlist', 'value', 'allowed'),
    [
        # Unset reads as None and allows anything.
        ('allowed_tools', 'tool_allowed', UNSET, 'get_issue', True),
        ('allowed_prompts', 'prompt_allowed', UNSET, 'review', True),
        ('allowed_resources', 'resource_allowed', UNSET, 'https://h.example/r', True),
        # Empty is kept distinct from unset and allows nothing.
        ('allowed_tools', 'tool_allowed', [], 'get_issue', False),
        ('allowed_prompts', 'prompt_allowed', [], 'review', False),
        ('allowed_resources', 'resource_allowed', [], 'https://h.example/r', False),
        # The allowlist is matched before the '{alias}__' prefix is applied.
        ('allowed_tools', 'tool_allowed', ['get_issue'], 'get_issue', True),
        ('allowed_tools', 'tool_allowed', ['get_issue'], 'github__get_issue', False),
    ],
)
def test_allowlist_decides_what_a_server_exposes(
    field, method, allowlist, value, allowed
):
    server_config = (
        HTTP_SERVER if allowlist is UNSET else {**HTTP_SERVER, field: allowlist}
    )
    config = GatewayConfig.model_validate(_base_config(mcp_servers=[server_config]))
    server = config.mcp_servers_by_alias['github']
    assert getattr(server, field) == (None if allowlist is UNSET else allowlist)
    assert getattr(server, method)(value) is allowed
