from datetime import UTC, datetime
from enum import Enum
from typing import Any
import uuid

from radicalbit_ai_gateway.events.buffer import CeleryBuffer

# Single buffer instance for alert records
_alerts_buffer = CeleryBuffer(task_name='emit_alert', buffer_name='AlertsBuffer')
_alerts_buffer.register_atexit()


class AlertStatus(str, Enum):
    SENT = 'sent'
    FAILED = 'failed'


def emit_alert(
    rule_uuid: str,
    rule_name: str,
    scope: str | None,
    project_uuid: str | None,
    route_name: str | None,
    credential_uuid: str | None,
    event: str,
    aggregation: str,
    status: AlertStatus,
    count: int = 1,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> None:
    """Record one alert send attempt. Records are buffered and sent in batches."""
    record: dict[str, Any] = {
        'ALERT_UUID': str(uuid.uuid4()),
        'TIMESTAMP': datetime.now(tz=UTC),
        'RULE_UUID': rule_uuid,
        'RULE_NAME': rule_name,
        'SCOPE': scope,
        'PROJECT_UUID': project_uuid,
        'ROUTE_NAME': route_name,
        'CREDENTIAL_UUID': credential_uuid,
        'EVENT': event,
        'AGGREGATION': aggregation,
        'COUNT': count,
        'WINDOW_START': window_start,
        'WINDOW_END': window_end,
        'STATUS': status.value,
    }
    _alerts_buffer.add(record)
