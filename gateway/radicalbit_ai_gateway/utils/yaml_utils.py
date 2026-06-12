import difflib
from importlib.resources import files
import re

from pydantic import ValidationError
import yaml

from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.utils.exceptions import ProjectConfigValidationError

_KNOWN_CONFIG_FIELDS = sorted(
    set(GatewayConfig.model_fields) | set(GatewayRouteConfig.model_fields)
)


def _find_key_line(yaml_str: str, key: str) -> int | None:
    """Best-effort line number of a mapping key in the YAML.

    Returns the line only when the key is unambiguous (a single occurrence),
    to avoid pointing at the wrong place when a name appears more than once.
    """
    matches = list(
        re.finditer(rf'^[ \t]*{re.escape(key)}[ \t]*:', yaml_str, re.MULTILINE)
    )
    if len(matches) == 1:
        return yaml_str[: matches[0].start()].count('\n') + 1
    return None


def _format_validation_error(err: dict, yaml_str: str) -> str:
    loc = '.'.join(str(p) for p in err['loc'])
    msg = err['msg']
    if err['type'] == 'extra_forbidden' and err['loc']:
        field = str(err['loc'][-1])
        suggestion = difflib.get_close_matches(
            field, _KNOWN_CONFIG_FIELDS, n=1, cutoff=0.6
        )
        if suggestion:
            msg = f"{msg} (did you mean '{suggestion[0]}'?)"
    string_keys = [p for p in err['loc'] if isinstance(p, str)]
    line = _find_key_line(yaml_str, string_keys[-1]) if string_keys else None
    location = f' (line {line})' if line else ''
    return f"'{loc}'{location}: {msg}"


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
                _format_validation_error(err, yaml_str) for err in e.errors()
            )
            raise ProjectConfigValidationError(
                f'Invalid gateway configuration — {len(e.errors())} error(s): {details}'
            ) from e
        raise ProjectConfigValidationError(f'Invalid gateway configuration: {e}') from e
    return yaml_str


def get_default_config_template() -> str:
    return (
        files('radicalbit_ai_gateway.resources')
        .joinpath('default_config.yaml')
        .read_text()
    )
