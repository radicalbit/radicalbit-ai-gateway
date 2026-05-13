"""Shared utilities for metrics processing."""

from collections.abc import Callable, Iterable, Sequence
import logging
import threading
import time

logger = logging.getLogger(__name__)


def iter_event_payload(payload: Sequence[dict]) -> Iterable[dict]:
    """Iterate over event payload, handling both single dict and list/tuple of dicts."""
    if isinstance(payload, dict):
        yield payload
        return
    if isinstance(payload, (list, tuple)):
        for item in payload:
            if isinstance(item, dict):
                yield item
            else:
                logger.warning('Skipping non-dict metric payload entry: %s', type(item))
        return
    logger.warning('Unsupported payload type received: %s', type(payload))


class BatchFlushError(Exception):
    """Raised when a synchronous flush triggered by the caller fails."""


class BatchBuffer:
    """Thread-safe batch buffer with time-based and size-based flushing."""

    def __init__(
        self,
        flush_callback: Callable[[list[list]], None],
        max_batch_size: int,
        flush_interval: float,
    ) -> None:
        self._flush_callback = flush_callback
        self._max_batch_size = max_batch_size
        self._flush_interval = flush_interval
        self._rows: list[list] = []
        self._lock = threading.Lock()
        self._last_flush = time.monotonic()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._background_flush, daemon=True)
        self._thread.start()

    def append(self, row: list) -> None:
        """Add a row to the buffer. Triggers immediate flush if batch size is reached."""
        with self._lock:
            self._rows.append(row)
            if len(self._rows) >= self._max_batch_size:
                rows = self._rows
                self._rows = []
                self._last_flush = time.monotonic()
                self._flush(rows, background=False)

    def flush(self, force: bool = False) -> None:
        """Flush buffered rows if interval has elapsed or force=True."""
        with self._lock:
            if not self._rows:
                return
            elapsed = time.monotonic() - self._last_flush
            if not force and elapsed < self._flush_interval:
                return
            rows = self._rows
            self._rows = []
            self._last_flush = time.monotonic()
            self._flush(rows, background=True)

    def stop(self) -> None:
        """Stop the background flush thread and flush remaining rows."""
        self._stop_event.set()
        self._thread.join(timeout=self._flush_interval * 2)
        self.flush(force=True)

    def _background_flush(self) -> None:
        """Background thread that periodically flushes the buffer."""
        while not self._stop_event.wait(self._flush_interval):
            self.flush(force=True)

    def _flush(self, rows: list[list], background: bool) -> None:
        """Execute the flush callback with error handling."""
        try:
            self._flush_callback(rows)
        except Exception as exc:
            if background:
                logger.critical(
                    'Background flush failed, rows will be retried: %s', exc
                )
                with self._lock:
                    self._rows = rows + self._rows
                return
            raise BatchFlushError('Synchronous flush failed') from exc
