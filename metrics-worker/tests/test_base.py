"""What the shared batching layer does with rows and with failures.

Every worker row goes through `BatchBuffer`. A flush that fails in the
background must not lose the rows, and one that fails on the caller's thread
must be visible to Celery. These tests pin both.
"""

import threading
import time

import pytest

from worker.base import BatchBuffer, BatchFlushError, iter_event_payload

# Long enough that the background thread never fires mid-test.
NEVER = 3600.0


class _Sink:
    """Records every batch handed to it. Can be told to fail."""

    def __init__(self, fail_times: int = 0):
        self.batches: list[list] = []
        self._fail_times = fail_times
        self.calls = 0

    def __call__(self, rows: list[list]) -> None:
        self.calls += 1
        if self.calls <= self._fail_times:
            raise RuntimeError('clickhouse is down')
        self.batches.append(rows)


@pytest.fixture
def sink() -> _Sink:
    return _Sink()


@pytest.fixture
def make_buffer():
    """Build buffers and stop their background threads when the test ends."""
    built: list[BatchBuffer] = []

    def build(
        flush_callback, max_batch_size: int = 100, flush_interval: float = NEVER
    ) -> BatchBuffer:
        buffer = BatchBuffer(flush_callback, max_batch_size, flush_interval)
        built.append(buffer)
        return buffer

    yield build

    for buffer in built:
        buffer._stop_event.set()
        buffer._thread.join(timeout=5)


def test_a_single_dict_payload_yields_itself():
    assert list(iter_event_payload({'a': 1})) == [{'a': 1}]


def test_a_list_payload_yields_each_entry():
    assert list(iter_event_payload([{'a': 1}, {'b': 2}])) == [{'a': 1}, {'b': 2}]


def test_a_tuple_payload_yields_each_entry():
    assert list(iter_event_payload(({'a': 1},))) == [{'a': 1}]


def test_non_dict_entries_are_dropped_not_raised():
    assert list(iter_event_payload([{'a': 1}, 'nonsense', None])) == [{'a': 1}]


def test_an_unsupported_payload_type_yields_nothing():
    assert list(iter_event_payload('nonsense')) == []


def test_rows_stay_buffered_until_something_flushes(sink, make_buffer):
    buffer = make_buffer(sink)

    buffer.append([1])
    buffer.append([2])

    assert sink.batches == []


def test_reaching_the_batch_size_flushes_at_once(sink, make_buffer):
    buffer = make_buffer(sink, max_batch_size=2)

    buffer.append([1])
    buffer.append([2])

    assert sink.batches == [[[1], [2]]]


def test_a_forced_flush_sends_what_is_buffered(sink, make_buffer):
    buffer = make_buffer(sink)
    buffer.append([1])

    buffer.flush(force=True)

    assert sink.batches == [[[1]]]


def test_an_empty_buffer_flushes_nothing(sink, make_buffer):
    buffer = make_buffer(sink)

    buffer.flush(force=True)

    assert sink.calls == 0


def test_an_unforced_flush_waits_for_the_interval(sink, make_buffer):
    """The Celery task calls flush() often. It must not insert one row at a time."""
    buffer = make_buffer(sink)
    buffer.append([1])

    buffer.flush()

    assert sink.calls == 0


def test_an_unforced_flush_sends_once_the_interval_has_elapsed(sink, make_buffer):
    buffer = make_buffer(sink, flush_interval=0.0)
    buffer.append([1])

    buffer.flush()

    assert sink.batches == [[[1]]]


def test_the_background_thread_flushes_on_its_own(sink, make_buffer):
    buffer = make_buffer(sink, flush_interval=0.05)

    buffer.append([1])
    deadline = time.monotonic() + 5
    while not sink.batches and time.monotonic() < deadline:
        time.sleep(0.01)

    assert sink.batches == [[[1]]]


def test_stop_drains_the_buffer(sink, make_buffer):
    buffer = make_buffer(sink, flush_interval=0.05)
    buffer.append([1])

    buffer.stop()

    assert sink.batches == [[[1]]]
    assert not buffer._thread.is_alive()


def test_a_failed_background_flush_deadlocks_the_buffer(make_buffer):
    """Known bug, pinned so that fixing it is a deliberate change.

    flush() holds _lock, then the requeue inside _flush() takes _lock again.
    It is a plain Lock, so the thread waits on itself and never returns. The
    buffer is dead from then on: every later append blocks too, and the rows
    it was holding never reach ClickHouse. One bad minute from ClickHouse
    stops all metrics until the worker restarts.

    The fix is to drop that second acquire, since both callers of _flush()
    already hold the lock. Once fixed, replace this with tests that the rows
    are kept, retried, and stay in order.
    """
    failing = _Sink(fail_times=1)
    buffer = make_buffer(failing)
    buffer.append([1])

    finished = threading.Event()
    threading.Thread(
        target=lambda: (buffer.flush(force=True), finished.set()), daemon=True
    ).start()

    assert not finished.wait(timeout=2), 'the requeue deadlock looks fixed'


def test_a_failed_synchronous_flush_raises_for_celery_to_retry(make_buffer):
    failing = _Sink(fail_times=1)
    buffer = make_buffer(failing, max_batch_size=1)

    with pytest.raises(BatchFlushError):
        buffer.append([1])


def test_appends_from_many_threads_all_land(sink, make_buffer):
    buffer = make_buffer(sink, max_batch_size=1000)

    def append_ten(start: int) -> None:
        for i in range(10):
            buffer.append([start + i])

    threads = [threading.Thread(target=append_ten, args=(n * 10,)) for n in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    buffer.flush(force=True)

    assert sorted(row[0] for row in sink.batches[0]) == list(range(50))
