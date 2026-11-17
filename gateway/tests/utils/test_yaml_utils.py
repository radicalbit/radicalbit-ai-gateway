import time

import pytest

from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.utils import yaml_utils
from radicalbit_ai_gateway.utils.app_config import PromptManagerConfig, get_app_config
from radicalbit_ai_gateway.utils.exceptions import ProjectConfigValidationError
from radicalbit_ai_gateway.utils.yaml_utils import (
    check_no_literal_secrets,
    check_secret_references,
    extract_secret_references,
    find_route_budgets,
    parse_yaml_with_secret_placeholders,
    validate_gateway_config,
)


@pytest.mark.parametrize(
    ('yaml_content', 'expected'),
    [
        pytest.param(
            """
    username: !secret ${SECRET_USERNAME}
    password: !secret ${SECRET_PASSWORD}
    """,
            [],
            id='only-secret-references',
        ),
        pytest.param(
            """
    username: !secret ${SECRET_USERNAME}
    api_key: sk-rb-002
    password: sk-rb-001
    """,
            ['line 3: api_key: sk-rb-002'],
            id='literal-api-key',
        ),
    ],
)
def test_check_no_literal_secrets(yaml_content, expected):
    assert check_no_literal_secrets(yaml_content) == expected


def test_check_no_literal_secrets_counts_lines_after_blank_lines():
    assert check_no_literal_secrets('a: 1\n\n\napi_key: sk-1\n') == [
        'line 4: api_key: sk-1'
    ]


def test_check_no_literal_secrets_value_on_the_next_line_is_checked():
    assert check_no_literal_secrets('api_key:\n  sk-1\n') == [
        'line 1: api_key:\n  sk-1'
    ]


def test_check_no_literal_secrets_is_linear_on_a_crafted_config():
    # The previous pattern took about 25 s on this: quadratic in the newlines
    started = time.perf_counter()
    assert check_no_literal_secrets('api_key:' + '\n' * 200_000) == []
    assert time.perf_counter() - started < 1


def test_parse_yaml_with_secret_placeholders():
    yaml_content = """
    username: !secret ${SECRET_USERNAME}
    password: !secret ${SECRET_PASSWORD}
    """
    expected = {
        'username': '__secret_placeholder__',
        'password': '__secret_placeholder__',
    }
    assert parse_yaml_with_secret_placeholders(yaml_content) == expected


@pytest.fixture
def _secrets_file_with_empty(tmp_path):
    """Point the app config at a secrets file that has a valid key,
    an empty key, and is missing other keys.
    """
    secrets = tmp_path / 'secrets.yaml'
    secrets.write_text('VALID_KEY: some-value\nEMPTY_KEY: ""\n')
    original = get_app_config().gateway_secrets_path
    get_app_config().gateway_secrets_path = secrets
    yield
    get_app_config().gateway_secrets_path = original


_M1_WITH_SECRET = (
    'chat_models:\n'
    '  - model_id: m1\n'
    '    model: openai/gpt-4o-mini\n'
    '    credentials:\n'
    '      api_key: !secret {key}\n'
)
_DEFAULT_ROUTE = 'routes:\n  default-route:\n    chat_models: [m1]\n'
_MCP_CONFIG_PREFIX = (
    _M1_WITH_SECRET.format(key='VALID_KEY')
    + _DEFAULT_ROUTE
    + '    mcp_servers: [github]\n'
)
_MCP_HTTP_LITERAL_AUTH = _MCP_CONFIG_PREFIX + (
    'mcp_servers:\n'
    '  - alias: github\n'
    '    transport: streamable_http\n'
    '    url: https://api.example.com/mcp/\n'
    '    headers:\n'
    '      Authorization: Bearer literal-pat\n'
)


@pytest.mark.usefixtures('_secrets_file_with_empty')
@pytest.mark.parametrize(
    ('yaml_content', 'check_secrets', 'fragments'),
    [
        pytest.param(
            'key: valid\n  bad_indent: [unclosed',
            False,
            ['line', 'column'],
            id='yaml-error-location',
        ),
        pytest.param(
            'chat_models: not-a-list\nroutes: {}\n',
            False,
            ['chat_models', 'error(s)'],
            id='pydantic-error-field-path',
        ),
        pytest.param(
            'chat_models:\n'
            '  - model_id: gpt\n'
            '    model: openai/gpt-4o-mini\n'
            'routes: {}\n'
            'guardrails:\n'
            '  - name: judge\n'
            '    type: judge\n'
            '    where: input\n'
            '    behavior: block\n'
            '    parameters:\n'
            '      prompt_ref: non_existent_prompt.md\n'
            '      model_id: gpt\n',
            False,
            ['Prompt file not found: non_existent_prompt.md'],
            id='missing-judge-prompt-file',
        ),
        pytest.param(
            'chat_models:\n'
            '  - model_id: my-model\n'
            '    credentials:\n'
            '      api_key: sk-literal-key\n'
            'routes: {}\n',
            True,
            ['line 4'],
            id='literal-secret-line-number',
        ),
        pytest.param(
            _M1_WITH_SECRET.format(key='OPENAI_API_KEY')
            + _DEFAULT_ROUTE
            + '    unknown_field: 1\n',
            False,
            ['routes.default-route.unknown_field', 'Extra inputs are not permitted'],
            id='unknown-field-in-route',
        ),
        pytest.param(
            _M1_WITH_SECRET.format(key='OPENAI_API_KEY')
            + 'routes: {}\nunexpected_top: true\n',
            False,
            ['unexpected_top'],
            id='unknown-top-level-field',
        ),
        pytest.param(
            _M1_WITH_SECRET.format(key='OPENAI_API_KEY')
            + 'route:\n  default-route:\n    chat_models: [m1]\n',
            False,
            ["did you mean 'routes'?"],
            id='suggests-field-on-typo',
        ),
        pytest.param(
            _M1_WITH_SECRET.format(key='OPENAI_API_KEY')
            + 'rout:\n  default-route:\n    chat_models: [m1]\n',
            False,
            ["'rout' (line 6)"],
            id='extra-field-line',
        ),
        pytest.param(
            'chat_models:\n'
            '  - model_id: m1\n'
            '    model: openai/gpt-4o-mini\n'
            '    cached_input_cost_per_million_tokens: 0.5\n'
            'routes: {}\n',
            False,
            [
                "'chat_models.0.cached_input_cost_per_million_tokens' (line 4)",
                "did you mean 'input_cached_cost_per_million_tokens'?",
            ],
            id='suggests-field-with-reordered-words',
        ),
        pytest.param(
            'chat_models:\n'
            '  - model_id: m1\n'
            '    model: openai/gpt-4o-mini\n'
            '    retry_attemps: 5\n'
            'routes: {}\n',
            False,
            ["did you mean 'retry_attempts'?"],
            id='suggests-nested-field-on-typo',
        ),
        pytest.param(
            'chat_models:\n'
            '  - model_id: m1\n'
            '    model: openai/gpt-4o-mini\n'
            'guardrails:\n'
            '  - name: j\n'
            '    type: judge\n'
            '    parameters:\n'
            '      model_id: m1\n'
            '      prompt: hi\n'
            '      prompt_ref: toxicity_check.md\n'
            'routes:\n'
            '  default-route:\n'
            '    chat_models: [m1]\n',
            False,
            [
                'Invalid gateway configuration - 1 error(s)',
                "Only one between 'prompt' and 'prompt_ref' can be set.",
            ],
            id='only-the-guardrail-own-parameters',
        ),
        pytest.param(
            _M1_WITH_SECRET.format(key='NONEXISTENT') + _DEFAULT_ROUTE,
            True,
            ['NONEXISTENT', 'not found'],
            id='missing-secret',
        ),
        pytest.param(
            _M1_WITH_SECRET.format(key='EMPTY_KEY') + _DEFAULT_ROUTE,
            True,
            ['EMPTY_KEY', 'empty'],
            id='empty-secret',
        ),
        pytest.param(
            _MCP_HTTP_LITERAL_AUTH,
            True,
            ['mcp_servers[github].headers.Authorization', '!secret', 'line 15'],
            id='mcp-literal-authorization-header',
        ),
    ],
)
def test_validate_gateway_config_rejects_with_message(
    yaml_content, check_secrets, fragments
):
    with pytest.raises(ProjectConfigValidationError) as exc_info:
        validate_gateway_config(yaml_content, check_secrets=check_secrets)
    message = str(exc_info.value)
    for fragment in fragments:
        assert fragment in message


@pytest.mark.parametrize('error', [KeyError('routes'), TypeError('not a mapping')])
def test_validate_gateway_config_reports_a_non_validation_error(monkeypatch, error):
    def fail(parsed):
        raise error

    monkeypatch.setattr(yaml_utils.GatewayConfig, 'model_validate', fail)
    with pytest.raises(ProjectConfigValidationError) as exc_info:
        validate_gateway_config('routes: {}\n', check_secrets=False)
    assert exc_info.value.details == [
        {
            'loc': [],
            'msg': f'Invalid gateway configuration: {error}',
            'type': 'invalid_config',
        }
    ]


def test_validate_gateway_config_rejects_missing_model_prompt_file(tmp_path):
    PromptManager.set_global(
        PromptManager(PromptManagerConfig(prompts_dir=str(tmp_path)))
    )
    yaml_with_missing_prompt = (
        'chat_models:\n'
        '  - model_id: gpt\n'
        '    model: openai/gpt-4o-mini\n'
        '    prompt_ref: non_existent_prompt.md\n'
        'routes: {}\n'
    )
    try:
        with pytest.raises(ProjectConfigValidationError) as exc_info:
            validate_gateway_config(yaml_with_missing_prompt, check_secrets=False)
    finally:
        PromptManager._global_instance = None
    message = str(exc_info.value)
    assert 'Prompt file not found: non_existent_prompt.md' in message
    assert str(tmp_path) not in message


@pytest.mark.usefixtures('_secrets_file_with_empty')
def test_mcp_literal_env_token_rejected():
    yaml_str = _MCP_CONFIG_PREFIX + (
        'mcp_servers:\n'
        '  - alias: github\n'
        '    transport: stdio\n'
        '    command: python\n'
        '    args: [-m, my_server]\n'
        '    env:\n'
        '      API_TOKEN: literal-token\n'
        '      LOG_LEVEL: debug\n'
    )
    with pytest.raises(ProjectConfigValidationError) as exc_info:
        validate_gateway_config(yaml_str, check_secrets=True)
    message = str(exc_info.value)
    assert 'mcp_servers[github].env.API_TOKEN' in message
    assert 'LOG_LEVEL' not in message


@pytest.mark.usefixtures('_secrets_file_with_empty')
@pytest.mark.parametrize(
    ('yaml_content', 'check_secrets'),
    [
        pytest.param(
            _M1_WITH_SECRET.format(key='NONEXISTENT') + _DEFAULT_ROUTE,
            False,
            id='secret-check-disabled',
        ),
        pytest.param(
            _MCP_CONFIG_PREFIX
            + (
                'mcp_servers:\n'
                '  - alias: github\n'
                '    transport: streamable_http\n'
                '    url: https://api.example.com/mcp/\n'
                '    headers:\n'
                '      Authorization: !secret VALID_KEY\n'
                '      X-Client-Name: gateway\n'
            ),
            True,
            id='mcp-secret-header-and-benign-literal',
        ),
        pytest.param(
            _MCP_HTTP_LITERAL_AUTH, False, id='mcp-secrets-skipped-when-check-disabled'
        ),
    ],
)
def test_validate_gateway_config_accepts(yaml_content, check_secrets):
    validate_gateway_config(yaml_content, check_secrets=check_secrets)


# ---------------------------------------------------------------------------
# extract_secret_references
# ---------------------------------------------------------------------------


def test_extract_secret_references_finds_keys_with_lines():
    yaml_content = (
        'chat_models:\n'
        '  - model_id: m1\n'
        '    credentials:\n'
        '      api_key: !secret MY_KEY\n'
        'cache:\n'
        '  redis_host: !secret REDIS_HOST\n'
    )
    refs = extract_secret_references(yaml_content)
    keys = {k for k, _ in refs}
    assert keys == {'MY_KEY', 'REDIS_HOST'}
    assert all(line is not None for _, line in refs)


def test_extract_secret_references_returns_empty_for_no_secrets():
    yaml_content = 'chat_models:\n  - model_id: m1\nroutes: {}\n'
    assert extract_secret_references(yaml_content) == []


# ---------------------------------------------------------------------------
# check_secret_references
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures('_secrets_file_with_empty')
@pytest.mark.parametrize(
    ('yaml_content', 'expected'),
    [
        pytest.param('value: !secret VALID_KEY\n', [], id='valid'),
        pytest.param(
            'value: !secret NONEXISTENT\n',
            [['NONEXISTENT', 'not found']],
            id='missing-key',
        ),
        pytest.param(
            'value: !secret EMPTY_KEY\n', [['EMPTY_KEY', 'empty']], id='empty-value'
        ),
        pytest.param(
            'a: !secret NONEXISTENT\nb: !secret EMPTY_KEY\nc: !secret VALID_KEY\n',
            [['NONEXISTENT', 'not found'], ['EMPTY_KEY', 'empty']],
            id='multiple-violations',
        ),
    ],
)
def test_check_secret_references(yaml_content, expected):
    violations = check_secret_references(yaml_content)
    assert len(violations) == len(expected)
    for violation, fragments in zip(violations, expected, strict=True):
        for fragment in fragments:
            assert fragment in violation


_ROUTE_BUDGETS_YAML = """\
chat_models:
  - model_id: cheap
    model: mock/gateway
  - model_id: smart
    model: mock/gateway
routing:
  - name: by-budget
    type: deterministic
    rule: budget
    default_model_id: smart
    output_mapping:
      - model_id: cheap
        conditions:
          threshold: 0.8
routes:
  plain:
    chat_models:
      - cheap
  capped:
    chat_models:
      - cheap
    budget_limiting:
      window_size: "1 day"
      max_budget: 5.0
  routed:
    chat_models:
      - cheap
      - smart
    routing: by-budget
    budget_limiting:
      window_size: "1 day"
      max_budget: 10.0
"""


@pytest.mark.parametrize(
    ('yaml_content', 'budget_limiting', 'budget_routing'),
    [
        pytest.param(
            _ROUTE_BUDGETS_YAML,
            ['capped', 'routed'],
            ['routed'],
            id='routes-with-budget',
        ),
        pytest.param(
            'chat_models:\n  - model_id: cheap\n    model: mock/gateway\n'
            'routes:\n  plain:\n    chat_models:\n      - cheap\n',
            [],
            [],
            id='no-route-budgets',
        ),
    ],
)
def test_find_route_budgets_names_the_routes_with_their_own_budget(
    yaml_content, budget_limiting, budget_routing
):
    budgets = find_route_budgets(yaml_content)
    assert budgets.budget_limiting == budget_limiting
    assert budgets.budget_routing == budget_routing
