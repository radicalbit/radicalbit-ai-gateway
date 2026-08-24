"""Tags reach ``event`` rows via the request ContextVar, not the payload."""

from unittest.mock import patch

from radicalbit_ai_gateway.events.events_processor import emit_event
from radicalbit_ai_gateway.models.event_payload import ModelInvocationPayload
from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.utils.request_context import current_request_tags_ctx

BUFFER = 'radicalbit_ai_gateway.events.events_processor._events_buffer'


def _payload() -> ModelInvocationPayload:
    return ModelInvocationPayload(
        request_uuid='11111111-1111-1111-1111-111111111111',
        event_type=EventType.MODEL_INVOCATION,
        route_name='proj/route',
        value=1.0,
        api_key_uuid='22222222-2222-2222-2222-222222222222',
        api_key_name='key',
        group_uuid='33333333-3333-3333-3333-333333333333',
        group_name='group',
        model_id='openai/gpt-4o',
        model_type='chat',
    )


def _emit_and_capture() -> dict:
    with patch(BUFFER) as buffer:
        emit_event(_payload())
    return buffer.add.call_args.args[0]


def test_tags_from_the_context_land_on_the_event_row():
    token = current_request_tags_ctx.set(('cost_center=retail', 'env=prod'))
    try:
        assert _emit_and_capture()['TAGS'] == ['cost_center=retail', 'env=prod']
    finally:
        current_request_tags_ctx.reset(token)


def test_an_untagged_request_produces_an_empty_array():
    token = current_request_tags_ctx.set(())
    try:
        assert _emit_and_capture()['TAGS'] == []
    finally:
        current_request_tags_ctx.reset(token)
