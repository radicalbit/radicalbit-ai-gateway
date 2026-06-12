import pytest

from radicalbit_ai_gateway.utils.exceptions import ProjectConfigValidationError
from radicalbit_ai_gateway.utils.yaml_utils import (
    check_no_literal_secrets,
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
