import atexit
from collections.abc import Sequence
import logging
import threading
from typing import Any

from celery import Celery

from radicalbit_ai_gateway.utils.app_config import get_app_config

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)

# Shared Celery app for all event types
celery_app = Celery('events_app', broker=app_config.celery_config.celery_broker_url)
celery_app.conf.update(
    task_send_sent_event=False,
    broker_pool_limit=app_config.celery_config.celery_broker_pool_limit,
    task_ignore_result=True,
)


class CeleryBuffer:
    """Thread-safe buffer that batches items before sending to Celery."""

    def __init__(self, task_name: str, buffer_name: str = 'buffer'):
        self._task_name = task_name
        self._buffer_name = buffer_name
        self._buffer: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._batch_size = app_config.celery_config.celery_events_batch_size
        self._flush_interval = app_config.celery_config.celery_events_flush_ms / 1000
        self._closed = False

    def add(self, item: dict[str, Any]) -> None:
        """Add item to buffer, flush if batch is full."""
        if self._closed:
            logger.warning('%s is closed, dropping item', self._buffer_name)
            return

        items_to_send: list[dict[str, Any]] | None = None

        with self._lock:
            self._buffer.append(item)

            if len(self._buffer) >= self._batch_size:
                items_to_send = self._take_all_unlocked()
            elif self._timer is None:
                self._start_timer_unlocked()

        if items_to_send:
            self._send_batch(items_to_send)

    def _take_all_unlocked(self) -> list[dict[str, Any]]:
        """Take all items (must hold lock)."""
        items = self._buffer.copy()
        self._buffer.clear()
        self._cancel_timer_unlocked()
        return items

    def _start_timer_unlocked(self) -> None:
        """Start flush timer (must hold lock)."""
        self._timer = threading.Timer(self._flush_interval, self._on_timer)
        self._timer.daemon = True
        self._timer.start()

    def _cancel_timer_unlocked(self) -> None:
        """Cancel timer if running (must hold lock)."""
        if self._timer:
            self._timer.cancel()
            self._timer = None

    def _on_timer(self) -> None:
        """Timer callback - flush buffer."""
        if self._closed:
            return

        with self._lock:
            self._timer = None
            if not self._buffer:
                return
            items_to_send = self._take_all_unlocked()

        self._send_batch(items_to_send)

    def _send_batch(self, items: Sequence[dict[str, Any]]) -> None:
        """Send batch to Celery."""
        if not items:
            return

        try:
            celery_app.send_task(
                self._task_name, args=[list(items)], ignore_result=True
            )
        except Exception:
            logger.exception(
                'Failed to send %d items to Celery task %s',
                len(items),
                self._task_name,
            )
            with self._lock:
                self._buffer[:0] = list(items)

    def flush(self) -> None:
        """Force flush all buffered items."""
        with self._lock:
            if not self._buffer:
                return
            items_to_send = self._take_all_unlocked()

        self._send_batch(items_to_send)

    def close(self) -> None:
        """Flush and close the buffer."""
        self._closed = True
        self.flush()

    def register_atexit(self) -> None:
        """Register close() to be called on program exit."""
        atexit.register(self.close)
