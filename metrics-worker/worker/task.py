"""Metrics processing and ClickHouse insertion.

This module re-exports components for backward compatibility.
"""

from celery.signals import worker_process_shutdown

from worker.app import celery_app
from worker.base import BatchBuffer, BatchFlushError
from worker.events import _worker, insert_event_record_connect_async
from worker.request_events import _request_event_worker, insert_request_event_record


@worker_process_shutdown.connect
def _cleanup_resources(**kwargs):
    """Cleanup resources when Celery worker process shuts down."""
    _worker.cleanup()
    _request_event_worker.cleanup()


__all__ = [
    'celery_app',
    'BatchBuffer',
    'BatchFlushError',
    'insert_event_record_connect_async',
    'insert_request_event_record',
    '_worker',
    '_request_event_worker',
    '_cleanup_resources',
]
