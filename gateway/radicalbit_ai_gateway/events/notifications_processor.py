from datetime import datetime, timezone
from typing import Any

from radicalbit_ai_gateway.events.buffer import CeleryBuffer

# Single buffer instance for notifications
_notifications_buffer = CeleryBuffer(
    task_name='emit_notification', buffer_name='NotificationsBuffer'
)
_notifications_buffer.register_atexit()


def _create_notification_dict(
    route_name: str,
    direction: str,
    window_size: int,
    max_tokens: int,
    current_usage: int,
    reset_time: int,
    window_id: str,
) -> dict[str, Any]:
    """Create a standardized notification dictionary with window state."""
    return {
        'TIMESTAMP': datetime.now(tz=timezone.utc),
        'ROUTE_NAME': route_name,
        'DIRECTION': direction,
        'WINDOW_SIZE': window_size,
        'MAX_TOKENS': max_tokens,
        'CURRENT_USAGE': current_usage,
        'RESET_TIME': reset_time,
        'WINDOW_ID': window_id,
    }


def emit_notification(
    route_name: str,
    direction: str,
    window_size: int,
    max_tokens: int,
    current_usage: int,
    reset_time: int,
    window_id: str,
) -> None:
    """Emit a token window state notification."""
    notification = _create_notification_dict(
        route_name,
        direction,
        window_size,
        max_tokens,
        current_usage,
        reset_time,
        window_id,
    )
    _notifications_buffer.add(notification)
