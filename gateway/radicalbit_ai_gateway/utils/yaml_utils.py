from importlib.resources import files
import re

from pydantic import ValidationError
import yaml

from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.utils.exceptions import ProjectConfigValidationError

SENSITIVE_FIELD_PATTERN = re.compile(
    r'^\s*(?:api_key|azure_ad_token):\s*(.+)$',
    re.MULTILINE,
)
SECRET_REF_PATTERN = re.compile(r'^!secret\s+\S+$')


def check_no_literal_secrets(yaml_content: str) -> list[str]:
    violations = []
    for match in SENSITIVE_FIELD_PATTERN.finditer(yaml_content):
        value = match.group(1).strip()
        if value and not SECRET_REF_PATTERN.match(value):
            violations.append(match.group(0).strip())
    return violations


def parse_yaml_with_secret_placeholders(yaml_content: str) -> dict:
    loader = yaml.SafeLoader(yaml_content)

    def secret_constructor(loader, node):
        return '__secret_placeholder__'

    loader.add_constructor('!secret', secret_constructor)
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()


def validate_gateway_config(yaml_str: str, *, check_secrets: bool) -> str:
    try:
        parsed = parse_yaml_with_secret_placeholders(yaml_str)
    except yaml.YAMLError as e:
        raise ProjectConfigValidationError(f'Invalid YAML: {e}') from e
    if check_secrets:
        violations = check_no_literal_secrets(yaml_str)
        if violations:
            raise ProjectConfigValidationError(
                f'Config contains literal secrets: {violations}. Use !secret references instead.'
            )
    try:
        GatewayConfig.model_validate(parsed)
    except (ValidationError, KeyError, TypeError) as e:
        raise ProjectConfigValidationError(f'Invalid gateway configuration: {e}') from e
    return yaml_str


def get_default_config_template() -> str:
    return (
        files('radicalbit_ai_gateway.resources')
        .joinpath('default_config.yaml')
        .read_text()
    )
