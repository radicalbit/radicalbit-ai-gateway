from datetime import datetime, timezone
from typing import Any

from radicalbit_ai_gateway.events.buffer import CeleryBuffer
from radicalbit_ai_gateway.models.event_payload import EventPayload
from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.utils.request_context import get_current_request_tags

# Single buffer instance for metrics events
_events_buffer = CeleryBuffer(task_name='emit_event', buffer_name='EventsBuffer')
_events_buffer.register_atexit()


def _create_event_dict(
    request_uuid: str,
    event_type: EventType,
    route_name: str,
    value: float,
    api_key_uuid: str,
    api_key_name: str,
    group_uuid: str,
    group_name: str,
    cost: float,
    project_uuid: str,
    project_name: str,
    extra_attributes: dict[str, Any],
    tags: list[str],
) -> dict[str, Any]:
    """Create a standardized event dictionary.

    Note: For backwards compatibility, model_id is stored as model_name in ATTRIBUTES.
    """
    model_id = extra_attributes.get('model_id', '')
    if model_id:
        extra_attributes['model_name'] = model_id
    model_type = extra_attributes.get('model_type', '')
    is_cached_tokens = extra_attributes.get('is_cached_tokens', False)
    cache_type = extra_attributes.get('cache_type', '')
    is_judge = extra_attributes.get('is_judge', False)
    target = extra_attributes.get('target', '')
    fallback = extra_attributes.get('fallback', '')
    guardrail_name = extra_attributes.get('name', '')
    guardrail_type = extra_attributes.get('type', '')
    guardrail_where = extra_attributes.get('where', '')
    guardrail_params = extra_attributes.get('parameters', '')
    guardrail_behavior = extra_attributes.get('behavior', '')
    routing_name = extra_attributes.get('routing_name', '')
    routing_selected_model_id = extra_attributes.get('selected_model_id', '')

    # Convert to strings for ClickHouse Map(LowCardinality(String), String)
    extra_attributes_string = {
        attribute: str(value) for attribute, value in extra_attributes.items()
    }

    return {
        'REQUEST_UUID': request_uuid,
        'TIMESTAMP': datetime.now(tz=timezone.utc),
        'EVENT_TYPE': event_type,
        'ROUTE_NAME': route_name,
        'VALUE': value,
        'API_KEY_UUID': api_key_uuid,
        'API_KEY_NAME': api_key_name,
        'GROUP_UUID': group_uuid,
        'GROUP_NAME': group_name,
        'COST': cost,
        'PROJECT_UUID': project_uuid,
        'PROJECT_NAME': project_name,
        'MODEL_ID': model_id,
        'MODEL_TYPE': model_type,
        'IS_CACHED_TOKENS': is_cached_tokens,
        'CACHE_TYPE': cache_type,
        'TARGET': target,
        'FALLBACK': fallback,
        'GUARDRAIL_NAME': guardrail_name,
        'GUARDRAIL_TYPE': guardrail_type,
        'GUARDRAIL_WHERE': guardrail_where,
        'GUARDRAIL_PARAMS': guardrail_params,
        'GUARDRAIL_BEHAVIOR': guardrail_behavior,
        'IS_JUDGE': is_judge,
        'ROUTING_NAME': routing_name,
        'ROUTING_SELECTED_MODEL_ID': routing_selected_model_id,
        'ATTRIBUTES': extra_attributes_string,
        'TAGS': tags,
    }


def emit_event(event: EventPayload) -> None:
    """Emit a metrics event. Events are buffered and sent in batches."""
    data = event.model_dump(exclude_none=True)

    request_uuid = data.pop('request_uuid')
    event_type = data.pop('event_type')
    project_uuid = data.pop('project_uuid', '')
    project_name = data.pop('project_name', '')
    route_name = data.pop('route_name')
    value = data.pop('value')
    api_key_uuid = data.pop('api_key_uuid')
    api_key_name = data.pop('api_key_name')
    group_uuid = data.pop('group_uuid')
    group_name = data.pop('group_name')
    cost = data.pop('cost', 0.0)

    event_dict = _create_event_dict(
        request_uuid,
        event_type,
        route_name,
        value,
        api_key_uuid,
        api_key_name,
        group_uuid,
        group_name,
        cost,
        project_uuid,
        project_name,
        data,
        # Tags travel out of band via the request context; the rationale
        # lives in utils/request_context.py.
        list(get_current_request_tags()),
    )
    _events_buffer.add(event_dict)
