import difflib
from importlib.resources import files
import re

from pydantic import ValidationError
from pydantic_core import ErrorDetails
import yaml

from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.utils.exceptions import ProjectConfigValidationError
from radicalbit_ai_gateway.utils.secrets import get_secret_provider

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


def _format_validation_error(err: ErrorDetails, yaml_str: str) -> str:
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

SECRET_PLACEHOLDER = '__secret_placeholder__'

# Keys under mcp_servers[].headers / mcp_servers[].env whose values look
# sensitive and therefore must be !secret references.
_SENSITIVE_KEY_PATTERN = re.compile(
    r'(?i)(authorization|api[-_]?key|token|secret|password|cookie|credential)'
)


def check_no_literal_secrets(yaml_content: str) -> list[str]:
    violations = []
    for match in SENSITIVE_FIELD_PATTERN.finditer(yaml_content):
        value = match.group(1).strip()
        if value and not SECRET_REF_PATTERN.match(value):
            line_no = yaml_content[: match.start()].count('\n') + 1
            violations.append(f'line {line_no}: {match.group(0).strip()}')
    return violations


def check_no_literal_secrets_in_mcp_servers(parsed: dict, yaml_str: str) -> list[str]:
    """Reject literal values for sensitive-looking keys under
    ``mcp_servers[].headers`` and ``mcp_servers[].env``.

    ``parsed`` must come from :func:`_parse_yaml_with_secrets`, where every
    ``!secret`` value is already replaced by :data:`SECRET_PLACEHOLDER`.
    """
    violations: list[str] = []
    servers = parsed.get('mcp_servers') or []
    if not isinstance(servers, list):
        return violations
    for entry in servers:
        if not isinstance(entry, dict):
            continue
        alias = entry.get('alias', '<unknown>')
        for block_name in ('headers', 'env'):
            block = entry.get(block_name) or {}
            if not isinstance(block, dict):
                continue
            for key, value in block.items():
                if not isinstance(key, str):
                    continue
                if not _SENSITIVE_KEY_PATTERN.search(key):
                    continue
                if value == SECRET_PLACEHOLDER:
                    continue
                line = _find_key_line(yaml_str, key)
                loc = f' (line {line})' if line else ''
                violations.append(
                    f'mcp_servers[{alias}].{block_name}.{key}{loc}: '
                    'literal value for a sensitive key; use a !secret reference'
                )
    return violations


def _parse_yaml_with_secrets(
    yaml_content: str,
) -> tuple[dict, list[tuple[str, int | None]]]:
    """Parse *yaml_content*, replacing ``!secret`` tags with placeholders.

    Returns ``(parsed_dict, secret_refs)`` where *secret_refs* is a list of
    ``(key, line_number)`` for every ``!secret`` reference found.
    """
    refs: list[tuple[str, int | None]] = []
    loader = yaml.SafeLoader(yaml_content)

    def secret_constructor(loader, node):
        key = loader.construct_scalar(node)
        line = node.start_mark.line + 1 if node.start_mark else None
        refs.append((key, line))
        return SECRET_PLACEHOLDER

    loader.add_constructor('!secret', secret_constructor)
    try:
        data = loader.get_single_data()
    finally:
        loader.dispose()
    return data, refs


def extract_secret_references(yaml_content: str) -> list[tuple[str, int | None]]:
    """Return ``(key, line_number)`` for every ``!secret KEY`` in *yaml_content*."""
    _, refs = _parse_yaml_with_secrets(yaml_content)
    return refs


def check_secret_references(
    yaml_content: str,
    *,
    _refs: list[tuple[str, int | None]] | None = None,
) -> list[str]:
    """Validate that every ``!secret`` reference points to an existing,
    non-empty key in ``secrets.yaml``.

    Returns a (possibly empty) list of human-readable violation strings.
    """
    refs = _refs if _refs is not None else extract_secret_references(yaml_content)
    if not refs:
        return []

    provider = get_secret_provider()
    violations: list[str] = []
    try:
        for key, line in refs:
            error = provider.validate_secret(key)
            if error:
                loc = f'line {line}: ' if line else ''
                violations.append(f'{loc}!secret {key} - {error}')
    except OSError as e:
        return [f'Cannot read secrets file: {e}']
    return violations


def parse_yaml_with_secret_placeholders(yaml_content: str) -> dict:
    data, _ = _parse_yaml_with_secrets(yaml_content)
    return data


def validate_gateway_config(yaml_str: str, *, check_secrets: bool) -> str:
    try:
        parsed, secret_refs = _parse_yaml_with_secrets(yaml_str)
    except yaml.YAMLError as e:
        mark = getattr(e, 'problem_mark', None)
        location = f' (line {mark.line + 1}, column {mark.column + 1})' if mark else ''
        problem = getattr(e, 'problem', None) or str(e)
        raise ProjectConfigValidationError(f'Invalid YAML{location}: {problem}') from e
    if check_secrets:
        violations = check_no_literal_secrets(yaml_str)
        if isinstance(parsed, dict):
            violations += check_no_literal_secrets_in_mcp_servers(parsed, yaml_str)
        if violations:
            raise ProjectConfigValidationError(
                f'Config contains literal secrets: {violations}. Use !secret references instead.'
            )
        secret_violations = check_secret_references(yaml_str, _refs=secret_refs)
        if secret_violations:
            raise ProjectConfigValidationError(
                f'Config references invalid secrets: {"; ".join(secret_violations)}. '
                'Ensure all !secret keys exist and have non-empty values.'
            )
    try:
        GatewayConfig.model_validate(parsed)
    except (ValidationError, KeyError, TypeError) as e:
        if isinstance(e, ValidationError):
            details = '; '.join(
                _format_validation_error(err, yaml_str) for err in e.errors()
            )
            raise ProjectConfigValidationError(
                f'Invalid gateway configuration - {len(e.errors())} error(s): {details}'
            ) from e
        raise ProjectConfigValidationError(f'Invalid gateway configuration: {e}') from e
    return yaml_str


def get_default_config_template() -> str:
    return (
        files('radicalbit_ai_gateway.resources')
        .joinpath('default_config.yaml')
        .read_text()
    )
