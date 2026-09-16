"""How each worker manages its ClickHouse client and its buffer.

Both workers hold the same shape: one lazy client, one lazy buffer, and a
cleanup that Celery calls at process shutdown. The tests run over both so the
two cannot drift apart.
"""

import threading

import pytest

from worker.events.worker import COLUMN_NAMES, TABLE_NAME, MetricsWorker
from worker.request_events.worker import (
    REQUEST_COLUMN_NAMES,
    REQUEST_TABLE_NAME,
    RequestEventWorker,
)

WORKERS = [
    pytest.param(
        MetricsWorker, 'worker.events.worker', TABLE_NAME, COLUMN_NAMES, id='events'
    ),
    pytest.param(
        RequestEventWorker,
        'worker.request_events.worker',
        REQUEST_TABLE_NAME,
        REQUEST_COLUMN_NAMES,
        id='request_events',
    ),
]


class _FakeClient:
    def __init__(self):
        self.inserts = []
        self.closed = False

    def insert(self, table, rows, column_names, settings):
        self.inserts.append((table, rows, column_names, settings))

    def close(self):
        self.closed = True


@pytest.fixture
def clickhouse(monkeypatch):
    """Hand every worker the same fake client instead of a real connection."""
    created = []

    def get_client(**kwargs):
        client = _FakeClient()
        client.kwargs = kwargs
        created.append(client)
        return client

    for module in ('worker.events.worker', 'worker.request_events.worker'):
        monkeypatch.setattr(f'{module}.clickhouse_connect.get_client', get_client)
    return created


@pytest.mark.parametrize(('cls', 'module', 'table', 'columns'), WORKERS)
def test_the_client_is_built_once_and_reused(cls, module, table, columns, clickhouse):
    worker = cls()

    first = worker.get_client()
    second = worker.get_client()

    assert first is second
    assert len(clickhouse) == 1


@pytest.mark.parametrize(('cls', 'module', 'table', 'columns'), WORKERS)
def test_the_client_uses_the_configured_connection(
    cls, module, table, columns, clickhouse
):
    worker = cls()

    client = worker.get_client()

    assert set(client.kwargs) == {'host', 'port', 'database', 'username', 'password'}


@pytest.mark.parametrize(('cls', 'module', 'table', 'columns'), WORKERS)
def test_closing_the_client_lets_the_next_call_reconnect(
    cls, module, table, columns, clickhouse
):
    worker = cls()
    first = worker.get_client()

    worker.close_client()
    second = worker.get_client()

    assert first.closed
    assert second is not first


@pytest.mark.parametrize(('cls', 'module', 'table', 'columns'), WORKERS)
def test_closing_a_client_that_was_never_opened_is_a_no_op(
    cls, module, table, columns, clickhouse
):
    cls().close_client()

    assert clickhouse == []


@pytest.mark.parametrize(('cls', 'module', 'table', 'columns'), WORKERS)
def test_a_client_that_fails_to_close_is_still_dropped(
    cls, module, table, columns, clickhouse
):
    """Otherwise a broken connection is reused forever."""
    worker = cls()
    client = worker.get_client()
    client.close = lambda: (_ for _ in ()).throw(RuntimeError('socket gone'))

    with pytest.raises(RuntimeError):
        worker.close_client()

    assert worker.get_client() is not client


@pytest.mark.parametrize(('cls', 'module', 'table', 'columns'), WORKERS)
def test_rows_are_inserted_into_the_right_table_with_its_columns(
    cls, module, table, columns, clickhouse, monkeypatch
):
    monkeypatch.setattr(f'{module}.config.clickhouse.clickhouse_async_insert', False)
    worker = cls()

    worker.insert_rows([['a'], ['b']])

    inserted_table, rows, column_names, settings = clickhouse[0].inserts[0]
    assert inserted_table == table
    assert rows == [['a'], ['b']]
    assert column_names == columns
    assert settings is None


@pytest.mark.parametrize(('cls', 'module', 'table', 'columns'), WORKERS)
def test_async_insert_waits_when_configured_to(
    cls, module, table, columns, clickhouse, monkeypatch
):
    monkeypatch.setattr(f'{module}.config.clickhouse.clickhouse_async_insert', True)
    monkeypatch.setattr(f'{module}.config.clickhouse.clickhouse_wait_for_async', True)
    worker = cls()

    worker.insert_rows([['a']])

    settings = clickhouse[0].inserts[0][3]
    assert settings == {'async_insert': 1, 'wait_for_async_insert': 1}


@pytest.mark.parametrize(('cls', 'module', 'table', 'columns'), WORKERS)
def test_async_insert_does_not_wait_by_default(
    cls, module, table, columns, clickhouse, monkeypatch
):
    monkeypatch.setattr(f'{module}.config.clickhouse.clickhouse_async_insert', True)
    monkeypatch.setattr(f'{module}.config.clickhouse.clickhouse_wait_for_async', False)
    worker = cls()

    worker.insert_rows([['a']])

    settings = clickhouse[0].inserts[0][3]
    assert settings == {'async_insert': 1, 'wait_for_async_insert': 0}


@pytest.mark.parametrize(('cls', 'module', 'table', 'columns'), WORKERS)
def test_the_buffer_is_built_once_and_reused(cls, module, table, columns, clickhouse):
    worker = cls()
    try:
        assert worker.get_buffer() is worker.get_buffer()
    finally:
        worker.close_buffer()


@pytest.mark.parametrize(('cls', 'module', 'table', 'columns'), WORKERS)
def test_the_buffer_flushes_through_this_worker(
    cls, module, table, columns, clickhouse, monkeypatch
):
    """The wiring that turns a buffered row into an insert."""
    monkeypatch.setattr(f'{module}.config.clickhouse.clickhouse_async_insert', False)
    worker = cls()
    try:
        worker.get_buffer().append(['a'])
        worker.get_buffer().flush(force=True)
    finally:
        worker.close_buffer()

    assert clickhouse[0].inserts[0][1] == [['a']]


@pytest.mark.parametrize(('cls', 'module', 'table', 'columns'), WORKERS)
def test_closing_the_buffer_drains_it(
    cls, module, table, columns, clickhouse, monkeypatch
):
    """Shutdown must not drop the last batch."""
    monkeypatch.setattr(f'{module}.config.clickhouse.clickhouse_async_insert', False)
    worker = cls()
    worker.get_client()  # warm, see the deadlock test below
    worker.get_buffer().append(['a'])

    worker.close_buffer()

    assert clickhouse[0].inserts[0][1] == [['a']]


@pytest.mark.parametrize(('cls', 'module', 'table', 'columns'), WORKERS)
def test_closing_a_cold_buffer_deadlocks_the_shutdown(
    cls, module, table, columns, clickhouse, monkeypatch
):
    """Known bug, pinned so that fixing it is a deliberate change.

    close_buffer() holds _lock while it drains, and the drain reaches
    get_client(). get_client() only takes _lock when the client is missing,
    so under load it returns early and nothing goes wrong. When the shutdown
    flush is the first flush, it takes _lock a second time on the same thread
    and hangs. That is a worker that booted, buffered a few rows and stopped
    before any timed flush fired: short-lived workers, low traffic, or a
    container restart just after boot. Celery's shutdown hook never returns
    and the batch never lands.

    The fix is threading.RLock in __init__. Once fixed, this test should go
    and test_closing_the_buffer_drains_it should drop its warm-up line.
    """
    monkeypatch.setattr(f'{module}.config.clickhouse.clickhouse_async_insert', False)
    worker = cls()
    worker.get_buffer().append(['a'])

    finished = threading.Event()
    threading.Thread(
        target=lambda: (worker.close_buffer(), finished.set()), daemon=True
    ).start()

    assert not finished.wait(timeout=2), 'the shutdown deadlock looks fixed'
    assert clickhouse == [], 'nothing was inserted, the batch is lost'


@pytest.mark.parametrize(('cls', 'module', 'table', 'columns'), WORKERS)
def test_closing_a_buffer_that_was_never_built_is_a_no_op(
    cls, module, table, columns, clickhouse
):
    cls().close_buffer()

    assert clickhouse == []


@pytest.mark.parametrize(('cls', 'module', 'table', 'columns'), WORKERS)
def test_cleanup_drains_the_buffer_then_closes_the_client(
    cls, module, table, columns, clickhouse, monkeypatch
):
    """Order matters. Closing first would drop the last batch."""
    monkeypatch.setattr(f'{module}.config.clickhouse.clickhouse_async_insert', False)
    worker = cls()
    worker.get_client()  # see test_closing_a_cold_buffer_deadlocks_the_shutdown
    worker.get_buffer().append(['a'])

    worker.cleanup()

    client = clickhouse[0]
    assert client.inserts[0][1] == [['a']]
    assert client.closed
