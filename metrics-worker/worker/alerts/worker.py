"""ClickHouse insertion for alert records."""

import logging
import threading
import uuid

import clickhouse_connect

from worker.app import celery_app
from worker.base import BatchBuffer, BatchFlushError, iter_event_payload
from worker.config import config

logger = logging.getLogger(__name__)

ALERT_TABLE_NAME = 'alert'

ALERT_COLUMN_NAMES = [
    'ALERT_UUID',
    'TIMESTAMP',
    'RULE_UUID',
    'RULE_NAME',
    'SCOPE',
    'PROJECT_UUID',
    'ROUTE_NAME',
    'CREDENTIAL_UUID',
    'EVENT',
    'AGGREGATION',
    'COUNT',
    'WINDOW_START',
    'WINDOW_END',
    'STATUS',
]


def _optional_uuid(column: str, value: str | None) -> uuid.UUID | None:
    """Parse a Nullable(UUID) target. A malformed one is stored as null, so the
    alert itself still reaches the history.
    """
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        logger.warning('Invalid %s %r stored as null', column, value)
        return None


class AlertWorker:
    """Manages ClickHouse client and batch buffer for alert records."""

    def __init__(self):
        self._lock = threading.Lock()
        self._client = None
        self._buffer = None

    def get_client(self):
        """Get or create ClickHouse client (thread-safe)."""
        if self._client is None:
            with self._lock:
                if self._client is None:
                    self._client = clickhouse_connect.get_client(
                        host=config.clickhouse.clickhouse_host,
                        port=config.clickhouse.clickhouse_port,
                        database=config.clickhouse.clickhouse_database,
                        username=config.clickhouse.clickhouse_user,
                        password=config.clickhouse.clickhouse_password,
                    )
        return self._client

    def close_client(self) -> None:
        """Close ClickHouse client (thread-safe)."""
        with self._lock:
            if self._client is not None:
                try:
                    self._client.close()
                finally:
                    self._client = None

    def insert_rows(self, rows: list[list]) -> None:
        """Insert rows into ClickHouse with optional async insert settings."""
        client = self.get_client()
        settings = {}
        if config.clickhouse.clickhouse_async_insert:
            settings['async_insert'] = 1
            settings['wait_for_async_insert'] = (
                1 if config.clickhouse.clickhouse_wait_for_async else 0
            )
        logger.debug('Flushing %d alert rows', len(rows))
        client.insert(
            ALERT_TABLE_NAME,
            rows,
            column_names=ALERT_COLUMN_NAMES,
            settings=settings or None,
        )

    def get_buffer(self) -> BatchBuffer:
        """Get or create batch buffer (thread-safe)."""
        if self._buffer is None:
            with self._lock:
                if self._buffer is None:
                    self._buffer = BatchBuffer(
                        flush_callback=self.insert_rows,
                        max_batch_size=config.metrics.metrics_batch_size,
                        flush_interval=config.metrics.flush_interval_sec,
                    )
        return self._buffer

    def close_buffer(self) -> None:
        """Stop batch buffer (thread-safe)."""
        with self._lock:
            if self._buffer is not None:
                self._buffer.stop()
                self._buffer = None

    def cleanup(self) -> None:
        """Cleanup all resources."""
        self.close_buffer()
        self.close_client()


# Singleton instance for alert records
_alert_worker = AlertWorker()


@celery_app.task(
    name='emit_alert',
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
    autoretry_for=(BatchFlushError,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
)
def insert_alert_record(alert_payload):
    """Celery task to insert alert records into ClickHouse via batch buffer."""
    buffer = _alert_worker.get_buffer()
    processed_ids: list[str] = []

    for alert_data in iter_event_payload(alert_payload):
        try:
            alert_uuid = uuid.UUID(alert_data['ALERT_UUID'])
            rule_uuid = uuid.UUID(alert_data['RULE_UUID'])
        except (KeyError, ValueError) as exc:
            logger.warning('Invalid alert payload skipped: %s', exc)
            continue

        project_uuid = _optional_uuid('PROJECT_UUID', alert_data.get('PROJECT_UUID'))
        credential_uuid = _optional_uuid(
            'CREDENTIAL_UUID', alert_data.get('CREDENTIAL_UUID')
        )

        data_row = [
            alert_uuid,
            alert_data['TIMESTAMP'],
            rule_uuid,
            alert_data.get('RULE_NAME', ''),
            alert_data.get('SCOPE') or None,
            project_uuid,
            alert_data.get('ROUTE_NAME') or None,
            credential_uuid,
            alert_data.get('EVENT', ''),
            alert_data.get('AGGREGATION', ''),
            alert_data.get('COUNT', 1),
            alert_data.get('WINDOW_START'),
            alert_data.get('WINDOW_END'),
            alert_data.get('STATUS', ''),
        ]

        buffer.append(data_row)
        processed_ids.append(str(alert_uuid))

    if not processed_ids:
        logger.warning('Received alert payload without valid alerts')

    return processed_ids
