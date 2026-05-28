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
