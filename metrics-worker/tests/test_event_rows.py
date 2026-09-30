"""What the metrics worker inserts for an event dictionary.

The insert names its columns explicitly. A column the gateway sends but the
worker does not build is the failure to watch for. These tests are that check.
"""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import uuid

import pytest

from worker.events.worker import (
    COLUMN_NAMES,
    _worker,
    insert_event_record_connect_async,
)


class _FakeBuffer:
    def __init__(self):
        self.rows = []

    def append(self, row):
        self.rows.append(row)


@pytest.fixture
def buffer(monkeypatch) -> _FakeBuffer:
    fake = _FakeBuffer()
    monkeypatch.setattr(_worker, 'get_buffer', lambda: fake)
    return fake


def _event(**overrides) -> dict:
    event = {
        'REQUEST_UUID': str(uuid.uuid4()),
        'TIMESTAMP': datetime.now(tz=UTC),
        'EVENT_TYPE': 'MCP_INVOCATION',
        'ROUTE_NAME': 'my-route',
        'VALUE': 1.0,
        'ATTRIBUTES': {},
        'API_KEY_UUID': str(uuid.uuid4()),
        'API_KEY_NAME': 'my-key',
        'GROUP_UUID': str(uuid.uuid4()),
        'GROUP_NAME': 'team-a',
        'COST': 0.0,
        'PROJECT_UUID': str(uuid.uuid4()),
        'PROJECT_NAME': 'my-project',
        'TAGS': ['env=prod'],
    }
    event.update(overrides)
    return event


def _row(buffer: _FakeBuffer) -> dict:
    """Return the single inserted row, read back by column name."""
    (row,) = buffer.rows
    assert len(row) == len(COLUMN_NAMES), (
        'the row builder and COLUMN_NAMES have drifted apart'
    )
    return dict(zip(COLUMN_NAMES, row, strict=True))


def test_an_mcp_invocation_writes_its_method_alias_and_target(buffer):
    insert_event_record_connect_async(
        [_event(MCP_METHOD='tools/call', MCP_ALIAS='github', MCP_TARGET='get_issue')]
    )

    row = _row(buffer)
    assert row['MCP_METHOD'] == 'tools/call'
    assert row['MCP_ALIAS'] == 'github'
    assert row['MCP_TARGET'] == 'get_issue'


def test_an_unresolved_server_writes_an_empty_alias_and_target(buffer):
    insert_event_record_connect_async(
        [_event(MCP_METHOD='tools/call', MCP_ALIAS='', MCP_TARGET='')]
    )

    row = _row(buffer)
    assert row['MCP_ALIAS'] == ''
    assert row['MCP_TARGET'] == ''


def test_an_event_without_the_mcp_fields_writes_the_empty_default(buffer):
    """Every other event type, and anything emitted by an older gateway."""
    insert_event_record_connect_async([_event(EVENT_TYPE='MODEL_INVOCATION')])

    row = _row(buffer)
    assert row['MCP_METHOD'] == ''
    assert row['MCP_ALIAS'] == ''
    assert row['MCP_TARGET'] == ''


def test_the_envelope_survives_the_round_trip(buffer):
    event = _event(MCP_METHOD='prompts/get', MCP_ALIAS='jira')

    insert_event_record_connect_async([event])

    row = _row(buffer)
    assert str(row['API_KEY_UUID']) == event['API_KEY_UUID']
    assert str(row['GROUP_UUID']) == event['GROUP_UUID']
    assert str(row['PROJECT_UUID']) == event['PROJECT_UUID']
    assert row['ROUTE_NAME'] == 'my-route'
    assert row['TAGS'] == ['env=prod']


def test_the_task_returns_the_ids_it_processed(buffer):
    events = [_event(), _event()]

    processed = insert_event_record_connect_async(events)

    assert processed == [e['REQUEST_UUID'] for e in events]


def test_a_single_dict_payload_is_accepted(buffer):
    insert_event_record_connect_async(_event())

    assert len(buffer.rows) == 1


def test_an_event_without_a_request_uuid_is_skipped(buffer):
    event = _event()
    del event['REQUEST_UUID']

    assert insert_event_record_connect_async([event]) == []
    assert buffer.rows == []


def test_an_event_with_an_unparseable_uuid_is_skipped(buffer):
    assert insert_event_record_connect_async([_event(REQUEST_UUID='nope')]) == []
    assert buffer.rows == []


def test_one_bad_event_does_not_drop_the_good_ones(buffer):
    """A single malformed event must not cost the whole batch."""
    good = _event()

    processed = insert_event_record_connect_async([_event(REQUEST_UUID='nope'), good])

    assert processed == [good['REQUEST_UUID']]
    assert len(buffer.rows) == 1


def test_a_non_numeric_cost_takes_down_the_whole_batch(buffer):
    """Known bug, pinned so that fixing it is a deliberate change.

    The guard catches KeyError and ValueError. Decimal raises
    InvalidOperation, which is an ArithmeticError and neither of those, so a
    COST that is not a number escapes the per-event skip and fails the task.
    Celery then retries the same payload until it gives up, and the good
    events batched with it never land.

    The fix is to add InvalidOperation to the caught exceptions.
    """
    with pytest.raises(InvalidOperation):
        insert_event_record_connect_async([_event(COST='free'), _event()])

    assert buffer.rows == []


def test_an_empty_payload_processes_nothing(buffer):
    assert insert_event_record_connect_async([]) == []


@pytest.mark.parametrize('column', ['API_KEY_UUID', 'GROUP_UUID', 'PROJECT_UUID'])
@pytest.mark.parametrize('empty', ['', None])
def test_an_absent_uuid_becomes_null_not_an_empty_string(buffer, column, empty):
    """The ClickHouse column is Nullable(UUID). '' would not parse."""
    insert_event_record_connect_async([_event(**{column: empty})])

    assert _row(buffer)[column] is None


def test_an_absent_cost_stays_null(buffer):
    insert_event_record_connect_async([_event(COST=None)])

    assert _row(buffer)['COST'] is None


def test_a_cost_is_carried_as_a_decimal(buffer):
    """Float rounding on money is the bug this avoids."""
    insert_event_record_connect_async([_event(COST=0.1)])

    assert _row(buffer)['COST'] == Decimal('0.1')
