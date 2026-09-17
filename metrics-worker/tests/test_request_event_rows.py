"""What the worker inserts for a request event.

This insert is positional against REQUEST_COLUMN_NAMES. Every column is a
string or a number, so a row built one slot out of line still inserts, just
into the wrong columns. These tests read the row back by name.
"""

from datetime import UTC, datetime
import uuid

import pytest

from worker.request_events.worker import (
    REQUEST_COLUMN_NAMES,
    _request_event_worker,
    insert_request_event_record,
)


class _FakeBuffer:
    def __init__(self):
        self.rows = []

    def append(self, row):
        self.rows.append(row)


@pytest.fixture
def buffer(monkeypatch) -> _FakeBuffer:
    fake = _FakeBuffer()
    monkeypatch.setattr(_request_event_worker, 'get_buffer', lambda: fake)
    return fake


def _event(**overrides) -> dict:
    event = {
        'REQUEST_UUID': str(uuid.uuid4()),
        'TIMESTAMP': datetime.now(tz=UTC),
        'ROUTE_NAME': 'my-route',
        'API_KEY_UUID': str(uuid.uuid4()),
        'API_KEY_NAME': 'my-key',
        'GROUP_UUID': str(uuid.uuid4()),
        'GROUP_NAME': 'team-a',
        'PROJECT_UUID': str(uuid.uuid4()),
        'PROJECT_NAME': 'my-project',
    }
    event.update(overrides)
    return event


def _row(buffer: _FakeBuffer) -> dict:
    """Return the single inserted row, read back by column name."""
    (row,) = buffer.rows
    assert len(row) == len(REQUEST_COLUMN_NAMES), (
        'the row builder and REQUEST_COLUMN_NAMES have drifted apart'
    )
    return dict(zip(REQUEST_COLUMN_NAMES, row, strict=True))


def test_the_envelope_survives_the_round_trip(buffer):
    event = _event()

    insert_request_event_record([event])

    row = _row(buffer)
    assert str(row['REQUEST_UUID']) == event['REQUEST_UUID']
    assert str(row['API_KEY_UUID']) == event['API_KEY_UUID']
    assert str(row['GROUP_UUID']) == event['GROUP_UUID']
    assert str(row['PROJECT_UUID']) == event['PROJECT_UUID']
    assert row['ROUTE_NAME'] == 'my-route'
    assert row['API_KEY_NAME'] == 'my-key'
    assert row['GROUP_NAME'] == 'team-a'
    assert row['PROJECT_NAME'] == 'my-project'


def test_the_request_outcome_is_recorded(buffer):
    insert_request_event_record(
        [
            _event(
                REQUEST_TYPE='chat',
                REQUEST_STATUS='error',
                HTTP_STATUS_CODE=429,
                DURATION_MS=12.5,
                ERROR_TYPE='rate_limit',
                ERROR_CODE='too_many_requests',
                IS_STREAMING=True,
                TAGS=['env=prod'],
            )
        ]
    )

    row = _row(buffer)
    assert row['REQUEST_TYPE'] == 'chat'
    assert row['REQUEST_STATUS'] == 'error'
    assert row['HTTP_STATUS_CODE'] == 429
    assert row['DURATION_MS'] == 12.5
    assert row['ERROR_TYPE'] == 'rate_limit'
    assert row['ERROR_CODE'] == 'too_many_requests'
    assert row['IS_STREAMING'] is True
    assert row['TAGS'] == ['env=prod']


def test_a_successful_request_writes_the_empty_defaults(buffer):
    insert_request_event_record([_event()])

    row = _row(buffer)
    assert row['REQUEST_TYPE'] == ''
    assert row['REQUEST_STATUS'] == ''
    assert row['HTTP_STATUS_CODE'] == 0
    assert row['DURATION_MS'] == 0.0
    assert row['ERROR_TYPE'] == ''
    assert row['ERROR_CODE'] == ''
    assert row['IS_STREAMING'] is False
    assert row['TAGS'] == []


@pytest.mark.parametrize('column', ['API_KEY_UUID', 'GROUP_UUID', 'PROJECT_UUID'])
@pytest.mark.parametrize('empty', ['', None])
def test_an_absent_uuid_becomes_null_not_an_empty_string(buffer, column, empty):
    """The ClickHouse column is Nullable(UUID). '' would not parse."""
    insert_request_event_record([_event(**{column: empty})])

    assert _row(buffer)[column] is None


def test_the_task_returns_the_ids_it_processed(buffer):
    events = [_event(), _event()]

    processed = insert_request_event_record(events)

    assert processed == [e['REQUEST_UUID'] for e in events]


def test_a_single_dict_payload_is_accepted(buffer):
    insert_request_event_record(_event())

    assert len(buffer.rows) == 1


def test_an_event_without_a_request_uuid_is_skipped(buffer):
    event = _event()
    del event['REQUEST_UUID']

    assert insert_request_event_record([event]) == []
    assert buffer.rows == []


def test_an_event_with_an_unparseable_uuid_is_skipped(buffer):
    assert insert_request_event_record([_event(REQUEST_UUID='not-a-uuid')]) == []
    assert buffer.rows == []


def test_one_bad_event_does_not_drop_the_good_ones(buffer):
    """A single malformed event must not cost the whole batch."""
    good = _event()

    processed = insert_request_event_record([_event(REQUEST_UUID='nope'), good])

    assert processed == [good['REQUEST_UUID']]
    assert len(buffer.rows) == 1


def test_an_empty_payload_processes_nothing(buffer):
    assert insert_request_event_record([]) == []
