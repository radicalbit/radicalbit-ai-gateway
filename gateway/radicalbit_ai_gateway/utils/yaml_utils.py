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
            line_no = yaml_content[: match.start()].count('\n') + 1
            violations.append(f'line {line_no}: {match.group(0).strip()}')
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
        mark = getattr(e, 'problem_mark', None)
        location = f' (line {mark.line + 1}, column {mark.column + 1})' if mark else ''
        problem = getattr(e, 'problem', None) or str(e)
        raise ProjectConfigValidationError(f'Invalid YAML{location}: {problem}') from e
    if check_secrets:
        violations = check_no_literal_secrets(yaml_str)
        if violations:
            raise ProjectConfigValidationError(
                f'Config contains literal secrets: {violations}. Use !secret references instead.'
            )
    try:
        GatewayConfig.model_validate(parsed)
    except (ValidationError, KeyError, TypeError) as e:
        if isinstance(e, ValidationError):
            details = '; '.join(
                f"'{'.'.join(str(p) for p in err['loc'])}': {err['msg']}"
                for err in e.errors()
            )
            raise ProjectConfigValidationError(
                f'Invalid gateway configuration — {len(e.errors())} error(s): {details}'
            ) from e
        raise ProjectConfigValidationError(f'Invalid gateway configuration: {e}') from e
    return yaml_str
