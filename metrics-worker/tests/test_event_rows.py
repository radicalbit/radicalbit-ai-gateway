"""What the metrics worker inserts for an event dictionary.

The insert names its columns explicitly and builds each row positionally, so a
new column added to the gateway but not here fails silently: events flow, the
insert succeeds, and the column is empty. These tests are that check.
"""

from datetime import UTC, datetime
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


def test_an_mcp_invocation_writes_its_method_and_alias(buffer):
    insert_event_record_connect_async(
        [_event(MCP_METHOD='tools/call', MCP_ALIAS='github')]
    )

    row = _row(buffer)
    assert row['MCP_METHOD'] == 'tools/call'
    assert row['MCP_ALIAS'] == 'github'


def test_an_unresolved_server_writes_an_empty_alias(buffer):
    insert_event_record_connect_async([_event(MCP_METHOD='tools/call', MCP_ALIAS='')])

    assert _row(buffer)['MCP_ALIAS'] == ''


def test_an_event_without_the_mcp_fields_writes_the_empty_default(buffer):
    """Every other event type, and anything emitted by an older gateway."""
    insert_event_record_connect_async([_event(EVENT_TYPE='MODEL_INVOCATION')])

    row = _row(buffer)
    assert row['MCP_METHOD'] == ''
    assert row['MCP_ALIAS'] == ''


def test_the_envelope_survives_the_round_trip(buffer):
    event = _event(MCP_METHOD='prompts/get', MCP_ALIAS='jira')

    insert_event_record_connect_async([event])

    row = _row(buffer)
    assert str(row['API_KEY_UUID']) == event['API_KEY_UUID']
    assert str(row['GROUP_UUID']) == event['GROUP_UUID']
    assert str(row['PROJECT_UUID']) == event['PROJECT_UUID']
    assert row['ROUTE_NAME'] == 'my-route'
    assert row['TAGS'] == ['env=prod']
