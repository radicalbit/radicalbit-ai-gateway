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


def test_http_and_stdio_servers_parse_and_route_references_resolve():
    config = GatewayConfig.model_validate(
        _base_config(
            mcp_servers=[HTTP_SERVER, STDIO_SERVER],
            route_mcp_servers=['github', 'local-tools'],
        )
    )

    assert isinstance(config.mcp_servers_by_alias['github'], McpHttpServer)
    assert isinstance(config.mcp_servers_by_alias['local-tools'], McpStdioServer)
    assert config.mcp_servers_by_alias['github'].forward_headers == ['x-user-jwt']

    resolved = config.get_route_mcp_servers('my_route')
    assert [s.alias for s in resolved] == ['github', 'local-tools']


def test_get_route_mcp_servers_empty_for_route_without_servers():
    config = GatewayConfig.model_validate(_base_config(mcp_servers=[HTTP_SERVER]))
    assert config.get_route_mcp_servers('my_route') == []
    assert config.get_route_mcp_servers('unknown_route') == []


def test_missing_transport_rejected():
    server = {k: v for k, v in HTTP_SERVER.items() if k != 'transport'}
    with pytest.raises(ValueError, match='transport'):
        GatewayConfig.model_validate(_base_config(mcp_servers=[server]))


def test_unknown_key_rejected():
    server = {**STDIO_SERVER, 'unexpected': True}
    with pytest.raises(ValueError, match='unexpected'):
        GatewayConfig.model_validate(_base_config(mcp_servers=[server]))


def test_duplicate_top_level_aliases_rejected():
    with pytest.raises(ValueError, match='unique aliases.*github'):
        GatewayConfig.model_validate(
            _base_config(mcp_servers=[HTTP_SERVER, {**STDIO_SERVER, 'alias': 'github'}])
        )


def test_case_variant_duplicate_aliases_rejected():
    with pytest.raises(ValueError) as exc_info:
        GatewayConfig.model_validate(
            _base_config(mcp_servers=[HTTP_SERVER, {**STDIO_SERVER, 'alias': 'GitHub'}])
        )
    message = str(exc_info.value)
    assert 'case-insensitively' in message
    assert 'GitHub' in message
    assert 'github' in message


def test_route_reference_to_undefined_alias_rejected():
    with pytest.raises(
        ValueError, match='not declared in top-level mcp_servers: missing'
    ):
        GatewayConfig.model_validate(
            _base_config(mcp_servers=[HTTP_SERVER], route_mcp_servers=['missing'])
        )


def test_duplicate_route_references_rejected():
    with pytest.raises(ValueError, match='duplicate mcp_servers: github'):
        GatewayConfig.model_validate(
            _base_config(
                mcp_servers=[HTTP_SERVER], route_mcp_servers=['github', 'github']
            )
        )


def test_alias_with_double_underscore_rejected():
    with pytest.raises(ValueError, match='reserved as the alias/tool separator'):
        GatewayConfig.model_validate(
            _base_config(mcp_servers=[{**HTTP_SERVER, 'alias': 'git__hub'}])
        )


@pytest.mark.parametrize('alias', ['', '  ', 'my alias'])
def test_invalid_aliases_rejected(alias):
    with pytest.raises(ValueError):
        GatewayConfig.model_validate(
            _base_config(mcp_servers=[{**HTTP_SERVER, 'alias': alias}])
        )


@pytest.mark.parametrize(
    'header', ['Mcp-Session-Id', 'mcp-protocol-version', 'host', 'Content-Length']
)
def test_forbidden_forward_headers_rejected(header):
    with pytest.raises(ValueError, match='forward_headers must not contain'):
        GatewayConfig.model_validate(
            _base_config(mcp_servers=[{**HTTP_SERVER, 'forward_headers': [header]}])
        )


def test_authorization_allowed_as_forward_target():
    config = GatewayConfig.model_validate(
        _base_config(
            mcp_servers=[{**HTTP_SERVER, 'forward_headers': ['Authorization']}]
        )
    )
    assert config.mcp_servers_by_alias['github'].forward_headers == ['authorization']


def test_forward_headers_normalized_and_deduped():
    config = GatewayConfig.model_validate(
        _base_config(
            mcp_servers=[
                {**HTTP_SERVER, 'forward_headers': ['X-User-Jwt', 'x-user-jwt', 'X-A']}
            ]
        )
    )
    assert config.mcp_servers_by_alias['github'].forward_headers == [
        'x-user-jwt',
        'x-a',
    ]


def test_timeout_must_be_positive():
    with pytest.raises(ValueError):
        GatewayConfig.model_validate(
            _base_config(mcp_servers=[{**HTTP_SERVER, 'timeout': 0}])
        )


ALLOWLIST_FIELDS = ['allowed_tools', 'allowed_prompts', 'allowed_resources']


@pytest.mark.parametrize('field', ALLOWLIST_FIELDS)
def test_allowlists_default_to_none_meaning_everything(field):
    config = GatewayConfig.model_validate(_base_config(mcp_servers=[HTTP_SERVER]))
    assert getattr(config.mcp_servers_by_alias['github'], field) is None


@pytest.mark.parametrize('field', ALLOWLIST_FIELDS)
def test_an_empty_allowlist_is_kept_distinct_from_unset(field):
    config = GatewayConfig.model_validate(
        _base_config(mcp_servers=[{**HTTP_SERVER, field: []}])
    )
    assert getattr(config.mcp_servers_by_alias['github'], field) == []


@pytest.mark.parametrize('field', ALLOWLIST_FIELDS)
def test_allowlist_entries_are_stripped_and_deduped_in_order(field):
    config = GatewayConfig.model_validate(
        _base_config(mcp_servers=[{**HTTP_SERVER, field: [' b ', 'a', 'b']}])
    )
    assert getattr(config.mcp_servers_by_alias['github'], field) == ['b', 'a']


@pytest.mark.parametrize('field', ALLOWLIST_FIELDS)
@pytest.mark.parametrize('entry', ['', '   '])
def test_blank_allowlist_entries_rejected(field, entry):
    with pytest.raises(ValueError, match=f'{field} entries must not be empty'):
        GatewayConfig.model_validate(
            _base_config(mcp_servers=[{**HTTP_SERVER, field: [entry]}])
        )


@pytest.mark.parametrize('field', ALLOWLIST_FIELDS)
def test_allowlists_apply_to_stdio_servers_too(field):
    config = GatewayConfig.model_validate(
        _base_config(mcp_servers=[{**STDIO_SERVER, field: ['x']}])
    )
    assert getattr(config.mcp_servers_by_alias['local-tools'], field) == ['x']


def test_allowlists_name_upstream_names_not_the_prefixed_ones():
    """The allowlist is matched before the '{alias}__' prefix is applied."""
    config = GatewayConfig.model_validate(
        _base_config(mcp_servers=[{**HTTP_SERVER, 'allowed_tools': ['get_issue']}])
    )
    server = config.mcp_servers_by_alias['github']
    assert server.tool_allowed('get_issue')
    assert not server.tool_allowed('github__get_issue')


@pytest.mark.parametrize(
    ('field', 'method', 'value'),
    [
        ('allowed_tools', 'tool_allowed', 'get_issue'),
        ('allowed_prompts', 'prompt_allowed', 'review'),
        ('allowed_resources', 'resource_allowed', 'https://h.example/readme'),
    ],
)
def test_unset_allowlist_allows_anything(field, method, value):
    config = GatewayConfig.model_validate(_base_config(mcp_servers=[HTTP_SERVER]))
    server = config.mcp_servers_by_alias['github']
    assert getattr(server, method)(value)


@pytest.mark.parametrize(
    ('field', 'method', 'value'),
    [
        ('allowed_tools', 'tool_allowed', 'get_issue'),
        ('allowed_prompts', 'prompt_allowed', 'review'),
        ('allowed_resources', 'resource_allowed', 'https://h.example/readme'),
    ],
)
def test_empty_allowlist_allows_nothing(field, method, value):
    config = GatewayConfig.model_validate(
        _base_config(mcp_servers=[{**HTTP_SERVER, field: []}])
    )
    server = config.mcp_servers_by_alias['github']
    assert not getattr(server, method)(value)
