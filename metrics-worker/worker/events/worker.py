"""Metrics processing and ClickHouse insertion for regular events."""

from decimal import Decimal
import logging
import threading
import uuid

import clickhouse_connect

from worker.app import celery_app
from worker.base import BatchBuffer, BatchFlushError, iter_event_payload
from worker.config import config

logger = logging.getLogger(__name__)

TABLE_NAME = 'event'

COLUMN_NAMES = [
    'REQUEST_UUID',
    'TIMESTAMP',
    'EVENT_TYPE',
    'ROUTE_NAME',
    'VALUE',
    'ATTRIBUTES',
    'API_KEY_UUID',
    'API_KEY_NAME',
    'GROUP_UUID',
    'GROUP_NAME',
    'COST',
    'PROJECT_UUID',
    'PROJECT_NAME',
    'MODEL_ID',
    'MODEL_TYPE',
    'IS_CACHED_TOKENS',
    'CACHE_TYPE',
    'TARGET',
    'FALLBACK',
    'GUARDRAIL_NAME',
    'GUARDRAIL_TYPE',
    'GUARDRAIL_WHERE',
    'GUARDRAIL_PARAMS',
    'GUARDRAIL_BEHAVIOR',
    'IS_JUDGE',
    'ROUTING_NAME',
    'ROUTING_SELECTED_MODEL_ID',
]


class MetricsWorker:
    """Manages ClickHouse client and batch buffer for metrics processing."""

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
        logger.debug('Flushing %d metric rows', len(rows))
        client.insert(
            TABLE_NAME,
            rows,
            column_names=COLUMN_NAMES,
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


# Singleton instance
_worker = MetricsWorker()


@celery_app.task(
    name='emit_event',
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
    autoretry_for=(BatchFlushError,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
)
def insert_event_record_connect_async(event_payload):
    """Celery task to process and insert event records into ClickHouse via batch buffer."""
    buffer = _worker.get_buffer()
    processed_ids: list[str] = []

    for event_data in iter_event_payload(event_payload):
        try:
            request_uuid = uuid.UUID(event_data['REQUEST_UUID'])
            # Use None for empty UUIDs (Nullable(UUID) in ClickHouse)
            api_key_uuid_str = event_data.get('API_KEY_UUID', '') or ''
            api_key_uuid = uuid.UUID(api_key_uuid_str) if api_key_uuid_str else None
            group_uuid_str = event_data.get('GROUP_UUID', '') or ''
            group_uuid = uuid.UUID(group_uuid_str) if group_uuid_str else None
            project_uuid_str = event_data.get('PROJECT_UUID', '') or ''
            project_uuid = uuid.UUID(project_uuid_str) if project_uuid_str else None
            cost = (
                Decimal(str(event_data['COST']))
                if event_data['COST'] is not None
                else None
            )
        except (KeyError, ValueError) as exc:
            logger.warning('Invalid event payload skipped: %s', exc)
            continue

        data_row = [
            request_uuid,
            event_data['TIMESTAMP'],
            event_data['EVENT_TYPE'],
            event_data['ROUTE_NAME'],
            event_data['VALUE'],
            event_data.get('ATTRIBUTES', {}),
            api_key_uuid,
            event_data['API_KEY_NAME'],
            group_uuid,
            event_data['GROUP_NAME'],
            cost,
            project_uuid,
            event_data.get('PROJECT_NAME', ''),
            event_data.get('MODEL_ID', ''),
            event_data.get('MODEL_TYPE', ''),
            event_data.get('IS_CACHED_TOKENS', False),
            event_data.get('CACHE_TYPE', ''),
            event_data.get('TARGET', ''),
            event_data.get('FALLBACK', ''),
            event_data.get('GUARDRAIL_NAME', ''),
            event_data.get('GUARDRAIL_TYPE', ''),
            event_data.get('GUARDRAIL_WHERE', ''),
            event_data.get('GUARDRAIL_PARAMS', ''),
            event_data.get('GUARDRAIL_BEHAVIOR', ''),
            event_data.get('IS_JUDGE', False),
            event_data.get('ROUTING_NAME', ''),
            event_data.get('ROUTING_SELECTED_MODEL_ID', ''),
        ]

        buffer.append(data_row)
        processed_ids.append(str(request_uuid))

    if not processed_ids:
        logger.warning('Received metric payload without valid events')

    return processed_ids
