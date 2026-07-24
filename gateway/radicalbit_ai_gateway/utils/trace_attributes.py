from enum import Enum
from functools import wraps

from opentelemetry.context import attach, get_value, set_value
from traceloop.sdk import Traceloop


class OperationCategory(str, Enum):
    ENDPOINT = 'endpoint'
    AUTH = 'auth'
    ROUTING = 'routing'
    PREPROCESSING = 'preprocessing'
    GUARDRAIL_INPUT = 'guardrail_input'
    GUARDRAIL_OUTPUT = 'guardrail_output'
    CACHE = 'cache'
    LIMITING = 'limiting'
    INVOCATION = 'invocation'


def _merge_association_properties(new_properties: dict) -> None:
    """Merge new properties into existing association_properties without losing
    previously-set values. Traceloop.set_association_properties replaces the
    entire dict, so we must read-merge-write.
    """
    existing = get_value('association_properties') or {}
    merged = {**existing, **new_properties}
    attach(set_value('association_properties', merged))
    # Also apply to current span if it's a workflow/task
    Traceloop.set_association_properties(merged)


def set_operation_category(category: OperationCategory) -> None:
    _merge_association_properties({'rb.gateway.operation_category': category.value})


def set_streaming() -> None:
    _merge_association_properties({'rb.gateway.is_streaming': 'true'})


def set_trace_attributes(
    request_uuid: str | None = None,
    route_name: str | None = None,
    api_key_uuid: str | None = None,
    api_key_name: str | None = None,
    group_uuid: str | None = None,
    group_name: str | None = None,
    project_uuid: str | None = None,
    project_name: str | None = None,
) -> None:
    properties = {
        'request_uuid': request_uuid,
        'route_name': route_name,
        'api_key_uuid': api_key_uuid,
        'api_key_name': api_key_name,
        'group_uuid': group_uuid,
        'group_name': group_name,
        'project_uuid': project_uuid,
        'project_name': project_name,
    }
    properties = {k: v for k, v in properties.items() if v is not None}
    if properties:
        _merge_association_properties(properties)


def set_mcp_attributes(
    method: str | None = None,
    alias: str | None = None,
    tool_name: str | None = None,
) -> None:
    properties = {
        'rb.gateway.mcp_method': method,
        'rb.gateway.mcp_alias': alias,
        'rb.gateway.mcp_tool_name': tool_name,
    }
    properties = {k: v for k, v in properties.items() if v is not None}
    if properties:
        _merge_association_properties(properties)


def ensure_endpoint_category(func):
    """Ensure the workflow span always ends with ENDPOINT category.

    When errors occur during request processing (e.g., rate limit exceeded),
    the last set operation category (like LIMITING or AUTH) would remain on the
    workflow span. This decorator resets it to ENDPOINT in a finally block so
    the workflow span category is always correct regardless of errors.
    """

    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        finally:
            set_operation_category(OperationCategory.ENDPOINT)

    return wrapper
