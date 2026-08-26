from datetime import UTC, datetime
from typing import Any

from radicalbit_ai_gateway.events.buffer import CeleryBuffer
from radicalbit_ai_gateway.models.event_payload import RequestEventPayload
from radicalbit_ai_gateway.utils.app_config import get_app_config

app_config = get_app_config()

# Single buffer instance for request events
_request_events_buffer = CeleryBuffer(
    task_name='emit_request_event', buffer_name='RequestEventsBuffer'
)
_request_events_buffer.register_atexit()


def _create_request_event_dict(
    request_uuid: str,
    route_name: str,
    api_key_uuid: str,
    api_key_name: str,
    group_uuid: str,
    group_name: str,
    project_uuid: str,
    project_name: str,
    request_type: str,
    status: str,
    http_status_code: int,
    duration_ms: float,
    error_type: str | None,
    error_code: str | None,
    is_streaming: bool,
    tags: list[str],
) -> dict[str, Any]:
    """Create a REQUEST event dictionary for the request_event table."""
    return {
        'REQUEST_UUID': request_uuid,
        'TIMESTAMP': datetime.now(tz=UTC),
        'ROUTE_NAME': route_name,
        'API_KEY_UUID': api_key_uuid,
        'API_KEY_NAME': api_key_name,
        'GROUP_UUID': group_uuid,
        'GROUP_NAME': group_name,
        'PROJECT_UUID': project_uuid,
        'PROJECT_NAME': project_name,
        'REQUEST_TYPE': request_type,
        'REQUEST_STATUS': status,
        'HTTP_STATUS_CODE': http_status_code,
        'DURATION_MS': duration_ms,
        'ERROR_TYPE': error_type or '',
        'ERROR_CODE': error_code or '',
        'IS_STREAMING': is_streaming,
        'TAGS': tags,
    }


def emit_request_event(event: RequestEventPayload) -> None:
    """Emit a REQUEST event. Events are buffered and sent in batches."""
    event_dict = _create_request_event_dict(
        request_uuid=event.request_uuid,
        route_name=event.route_name,
        api_key_uuid=event.api_key_uuid,
        api_key_name=event.api_key_name,
        group_uuid=event.group_uuid,
        group_name=event.group_name,
        project_uuid=event.project_uuid,
        project_name=event.project_name,
        request_type=event.request_type,
        status=event.status,
        http_status_code=event.http_status_code,
        duration_ms=event.duration_ms,
        error_type=event.error_type,
        error_code=event.error_code,
        is_streaming=event.is_streaming,
        tags=event.tags,
    )
    _request_events_buffer.add(event_dict)
