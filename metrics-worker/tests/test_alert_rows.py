"""What the worker inserts for an alert record.

This insert is positional against ALERT_COLUMN_NAMES. These tests read the
row back by name so a row built one slot out of line fails loudly.
"""

from datetime import UTC, datetime, timedelta
import uuid

import pytest

from worker.alerts.worker import ALERT_COLUMN_NAMES, _alert_worker, insert_alert_record


class _FakeBuffer:
    def __init__(self):
        self.rows = []

    def append(self, row):
        self.rows.append(row)


@pytest.fixture
def buffer(monkeypatch) -> _FakeBuffer:
    fake = _FakeBuffer()
    monkeypatch.setattr(_alert_worker, 'get_buffer', lambda: fake)
    return fake


def _alert(**overrides) -> dict:
    alert = {
        'ALERT_UUID': str(uuid.uuid4()),
        'TIMESTAMP': datetime.now(tz=UTC),
        'RULE_UUID': str(uuid.uuid4()),
        'RULE_NAME': 'my-rule',
        'SCOPE': 'route',
        'PROJECT_UUID': str(uuid.uuid4()),
        'ROUTE_NAME': 'my-route',
        'CREDENTIAL_UUID': str(uuid.uuid4()),
        'EVENT': 'fallback-triggered',
        'AGGREGATION': 'instant',
        'COUNT': 1,
        'WINDOW_START': None,
        'WINDOW_END': None,
        'STATUS': 'sent',
    }
    alert.update(overrides)
    return alert


def _row(buffer: _FakeBuffer) -> dict:
    """Return the single inserted row, read back by column name."""
    (row,) = buffer.rows
    assert len(row) == len(ALERT_COLUMN_NAMES), (
        'the row builder and ALERT_COLUMN_NAMES have drifted apart'
    )
    return dict(zip(ALERT_COLUMN_NAMES, row, strict=True))


def test_the_record_survives_the_round_trip(buffer):
    alert = _alert(STATUS='failed')

    insert_alert_record([alert])

    row = _row(buffer)
    assert row['ALERT_UUID'] == uuid.UUID(alert['ALERT_UUID'])
    assert row['TIMESTAMP'] == alert['TIMESTAMP']
    assert row['RULE_UUID'] == uuid.UUID(alert['RULE_UUID'])
    assert row['RULE_NAME'] == 'my-rule'
    assert row['SCOPE'] == 'route'
    assert row['PROJECT_UUID'] == uuid.UUID(alert['PROJECT_UUID'])
    assert row['ROUTE_NAME'] == 'my-route'
    assert row['CREDENTIAL_UUID'] == uuid.UUID(alert['CREDENTIAL_UUID'])
    assert row['EVENT'] == 'fallback-triggered'
    assert row['AGGREGATION'] == 'instant'
    assert row['COUNT'] == 1
    assert row['STATUS'] == 'failed'


def test_a_windowed_alert_keeps_its_window(buffer):
    end = datetime.now(tz=UTC)
    start = end - timedelta(minutes=5)

    insert_alert_record(
        [_alert(AGGREGATION='window', COUNT=7, WINDOW_START=start, WINDOW_END=end)]
    )

    row = _row(buffer)
    assert row['COUNT'] == 7
    assert row['WINDOW_START'] == start
    assert row['WINDOW_END'] == end


def test_an_instant_alert_has_no_window(buffer):
    insert_alert_record([_alert()])

    row = _row(buffer)
    assert row['WINDOW_START'] is None
    assert row['WINDOW_END'] is None


@pytest.mark.parametrize('column', ['PROJECT_UUID', 'CREDENTIAL_UUID'])
@pytest.mark.parametrize('empty', ['', None])
def test_an_absent_uuid_becomes_null_not_an_empty_string(buffer, column, empty):
    """The ClickHouse column is Nullable(UUID). '' would not parse."""
    insert_alert_record([_alert(**{column: empty})])

    assert _row(buffer)[column] is None


@pytest.mark.parametrize('column', ['SCOPE', 'ROUTE_NAME'])
@pytest.mark.parametrize('empty', ['', None])
def test_an_absent_scope_or_route_becomes_null(buffer, column, empty):
    insert_alert_record([_alert(**{column: empty})])

    assert _row(buffer)[column] is None


def test_the_task_returns_the_ids_it_processed(buffer):
    alerts = [_alert(), _alert()]

    processed = insert_alert_record(alerts)

    assert processed == [a['ALERT_UUID'] for a in alerts]


def test_a_single_dict_payload_is_accepted(buffer):
    insert_alert_record(_alert())

    assert len(buffer.rows) == 1


@pytest.mark.parametrize('column', ['ALERT_UUID', 'RULE_UUID'])
def test_an_alert_without_a_required_uuid_is_skipped(buffer, column):
    alert = _alert()
    del alert[column]

    assert insert_alert_record([alert]) == []
    assert buffer.rows == []


@pytest.mark.parametrize('column', ['ALERT_UUID', 'RULE_UUID'])
def test_an_alert_with_an_unparseable_required_uuid_is_skipped(buffer, column):
    assert insert_alert_record([_alert(**{column: 'not-a-uuid'})]) == []
    assert buffer.rows == []


@pytest.mark.parametrize('column', ['PROJECT_UUID', 'CREDENTIAL_UUID'])
def test_an_unparseable_target_uuid_becomes_null_and_keeps_the_alert(buffer, column):
    """The history must not lose an alert over a malformed target."""
    insert_alert_record([_alert(**{column: 'not-a-uuid'})])

    assert _row(buffer)[column] is None


def test_one_bad_alert_does_not_drop_the_good_ones(buffer):
    good = _alert()

    processed = insert_alert_record([_alert(ALERT_UUID='nope'), good])

    assert processed == [good['ALERT_UUID']]
    assert len(buffer.rows) == 1


def test_an_empty_payload_processes_nothing(buffer):
    assert insert_alert_record([]) == []
