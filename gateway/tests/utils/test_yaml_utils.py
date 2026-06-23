import pytest

from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import ProjectConfigValidationError
from radicalbit_ai_gateway.utils.yaml_utils import (
    check_no_literal_secrets,
    check_secret_references,
    extract_secret_references,
    parse_yaml_with_secret_placeholders,
    validate_gateway_config,
)


def test_check_no_literal_secrets():
    yaml_content = """
    username: !secret ${SECRET_USERNAME}
    password: !secret ${SECRET_PASSWORD}
    """
    assert check_no_literal_secrets(yaml_content) == []


def test_check_no_literal_secrets_with_literal():
    yaml_content = """
    username: !secret ${SECRET_USERNAME}
    api_key: sk-rb-002
    password: sk-rb-001
    """
    assert check_no_literal_secrets(yaml_content) == ['line 3: api_key: sk-rb-002']


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


def test_validate_gateway_config_yaml_error_includes_location():
    invalid_yaml = 'key: valid\n  bad_indent: [unclosed'
    with pytest.raises(ProjectConfigValidationError) as exc_info:
        validate_gateway_config(invalid_yaml, check_secrets=False)
    assert 'line' in str(exc_info.value)
    assert 'column' in str(exc_info.value)


def test_validate_gateway_config_pydantic_error_includes_field_path():
    yaml_with_bad_schema = 'chat_models: not-a-list\nroutes: {}\n'
    with pytest.raises(ProjectConfigValidationError) as exc_info:
        validate_gateway_config(yaml_with_bad_schema, check_secrets=False)
    message = str(exc_info.value)
    assert 'chat_models' in message
    assert 'error(s)' in message


def test_validate_gateway_config_secret_violation_includes_line_number():
    yaml_with_secret = (
        'chat_models:\n'
        '  - model_id: my-model\n'
        '    credentials:\n'
        '      api_key: sk-literal-key\n'
        'routes: {}\n'
    )
    with pytest.raises(ProjectConfigValidationError) as exc_info:
        validate_gateway_config(yaml_with_secret, check_secrets=True)
    assert 'line 4' in str(exc_info.value)


def test_validate_gateway_config_rejects_unknown_field_in_route():
    yaml_with_extra_in_route = (
        'chat_models:\n'
        '  - model_id: m1\n'
        '    model: openai/gpt-4o-mini\n'
        '    credentials:\n'
        '      api_key: !secret OPENAI_API_KEY\n'
        'routes:\n'
        '  default-route:\n'
        '    chat_models: [m1]\n'
        '    unknown_field: 1\n'
    )
    with pytest.raises(ProjectConfigValidationError) as exc_info:
        validate_gateway_config(yaml_with_extra_in_route, check_secrets=False)
    message = str(exc_info.value)
    assert 'routes.default-route.unknown_field' in message
    assert 'Extra inputs are not permitted' in message


def test_validate_gateway_config_rejects_unknown_top_level_field():
    yaml_with_extra_top = (
        'chat_models:\n'
        '  - model_id: m1\n'
        '    model: openai/gpt-4o-mini\n'
        '    credentials:\n'
        '      api_key: !secret OPENAI_API_KEY\n'
        'routes: {}\n'
        'unexpected_top: true\n'
    )
    with pytest.raises(ProjectConfigValidationError) as exc_info:
        validate_gateway_config(yaml_with_extra_top, check_secrets=False)
    assert 'unexpected_top' in str(exc_info.value)


def test_validate_gateway_config_suggests_correct_field_on_typo():
    yaml_with_typo = (
        'chat_models:\n'
        '  - model_id: m1\n'
        '    model: openai/gpt-4o-mini\n'
        '    credentials:\n'
        '      api_key: !secret OPENAI_API_KEY\n'
        'route:\n'
        '  default-route:\n'
        '    chat_models: [m1]\n'
    )
    with pytest.raises(ProjectConfigValidationError) as exc_info:
        validate_gateway_config(yaml_with_typo, check_secrets=False)
    message = str(exc_info.value)
    assert "did you mean 'routes'?" in message


def test_validate_gateway_config_extra_field_includes_line():
    yaml_with_typo = (
        'chat_models:\n'
        '  - model_id: m1\n'
        '    model: openai/gpt-4o-mini\n'
        '    credentials:\n'
        '      api_key: !secret OPENAI_API_KEY\n'
        'rout:\n'
        '  default-route:\n'
        '    chat_models: [m1]\n'
    )
    with pytest.raises(ProjectConfigValidationError) as exc_info:
        validate_gateway_config(yaml_with_typo, check_secrets=False)
    assert "'rout' (line 6)" in str(exc_info.value)


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


@pytest.mark.usefixtures('_secrets_file_with_empty')
def test_check_secret_references_valid():
    yaml_content = 'value: !secret VALID_KEY\n'
    assert check_secret_references(yaml_content) == []


@pytest.mark.usefixtures('_secrets_file_with_empty')
def test_check_secret_references_missing_key():
    yaml_content = 'value: !secret NONEXISTENT\n'
    violations = check_secret_references(yaml_content)
    assert len(violations) == 1
    assert 'NONEXISTENT' in violations[0]
    assert 'not found' in violations[0]


@pytest.mark.usefixtures('_secrets_file_with_empty')
def test_check_secret_references_empty_value():
    yaml_content = 'value: !secret EMPTY_KEY\n'
    violations = check_secret_references(yaml_content)
    assert len(violations) == 1
    assert 'EMPTY_KEY' in violations[0]
    assert 'empty' in violations[0]


@pytest.mark.usefixtures('_secrets_file_with_empty')
def test_check_secret_references_multiple_violations():
    yaml_content = (
        'a: !secret NONEXISTENT\nb: !secret EMPTY_KEY\nc: !secret VALID_KEY\n'
    )
    violations = check_secret_references(yaml_content)
    assert len(violations) == 2


# ---------------------------------------------------------------------------
# validate_gateway_config — secret reference validation
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures('_secrets_file_with_empty')
def test_validate_gateway_config_rejects_missing_secret():
    yaml_str = (
        'chat_models:\n'
        '  - model_id: m1\n'
        '    model: openai/gpt-4o-mini\n'
        '    credentials:\n'
        '      api_key: !secret NONEXISTENT\n'
        'routes:\n'
        '  default-route:\n'
        '    chat_models: [m1]\n'
    )
    with pytest.raises(ProjectConfigValidationError) as exc_info:
        validate_gateway_config(yaml_str, check_secrets=True)
    assert 'NONEXISTENT' in str(exc_info.value)
    assert 'not found' in str(exc_info.value)


@pytest.mark.usefixtures('_secrets_file_with_empty')
def test_validate_gateway_config_rejects_empty_secret():
    yaml_str = (
        'chat_models:\n'
        '  - model_id: m1\n'
        '    model: openai/gpt-4o-mini\n'
        '    credentials:\n'
        '      api_key: !secret EMPTY_KEY\n'
        'routes:\n'
        '  default-route:\n'
        '    chat_models: [m1]\n'
    )
    with pytest.raises(ProjectConfigValidationError) as exc_info:
        validate_gateway_config(yaml_str, check_secrets=True)
    assert 'EMPTY_KEY' in str(exc_info.value)
    assert 'empty' in str(exc_info.value)


@pytest.mark.usefixtures('_secrets_file_with_empty')
def test_validate_gateway_config_skips_secret_check_when_disabled():
    yaml_str = (
        'chat_models:\n'
        '  - model_id: m1\n'
        '    model: openai/gpt-4o-mini\n'
        '    credentials:\n'
        '      api_key: !secret NONEXISTENT\n'
        'routes:\n'
        '  default-route:\n'
        '    chat_models: [m1]\n'
    )
    # Should NOT raise — secret validation is off
    validate_gateway_config(yaml_str, check_secrets=False)
