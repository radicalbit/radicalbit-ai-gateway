"""The routing flag lands in its own column, not in the attributes map."""

from unittest.mock import patch

from radicalbit_ai_gateway.events.events_processor import emit_event
from radicalbit_ai_gateway.models.event_payload import InputTokenProcessedPayload
from radicalbit_ai_gateway.models.event_type import EventType

BUFFER = 'radicalbit_ai_gateway.events.events_processor._events_buffer'


def _payload(**overrides) -> InputTokenProcessedPayload:
    fields = {
        'request_uuid': '11111111-1111-1111-1111-111111111111',
        'event_type': EventType.INPUT_TOKEN_PROCESSED,
        'route_name': 'proj/route',
        'value': 7.0,
        'api_key_uuid': '22222222-2222-2222-2222-222222222222',
        'api_key_name': 'key',
        'group_uuid': '33333333-3333-3333-3333-333333333333',
        'group_name': 'group',
        'model_id': 'emb',
        'model_type': 'embeddings',
    }
    return InputTokenProcessedPayload(**{**fields, **overrides})


def _emit_and_capture(payload: InputTokenProcessedPayload) -> dict:
    with patch(BUFFER) as buffer:
        emit_event(payload)
    return buffer.add.call_args.args[0]


def test_a_routing_call_is_flagged_in_its_own_column():
    row = _emit_and_capture(_payload(is_routing=True))

    assert row['IS_ROUTING'] is True
    assert row['IS_JUDGE'] is False


def test_any_other_call_is_not_flagged_as_routing():
    row = _emit_and_capture(_payload())

    assert row['IS_ROUTING'] is False


def test_the_routing_flag_does_not_leak_into_the_attributes_map():
    row = _emit_and_capture(_payload(is_routing=True))

    assert 'is_routing' not in row['ATTRIBUTES']
