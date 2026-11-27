"""What a Responses API stream event says of a failed stream."""

import json

from radicalbit_ai_gateway.llm.responses_stream import NativeResponsesEvent


def _event(payload: dict[str, object]) -> NativeResponsesEvent:
    return NativeResponsesEvent.parse(str(payload['type']), json.dumps(payload))


def test_an_error_event_fails_the_stream_with_its_code_and_message():
    event = _event({'type': 'error', 'code': 'server_error', 'message': 'busy'})

    assert event.failure == 'server_error: busy'


def test_a_failed_final_response_fails_the_stream_with_its_error():
    event = _event(
        {
            'type': 'response.failed',
            'response': {
                'status': 'failed',
                'error': {'code': 'rate_limit_exceeded', 'message': 'slow down'},
            },
        }
    )

    assert event.failure == 'rate_limit_exceeded: slow down'


def test_a_failure_without_its_error_object_is_only_an_error():
    event = _event(
        {'type': 'response.failed', 'response': {'status': 'failed', 'error': None}}
    )

    assert event.failure == 'error'


def test_other_events_do_not_fail_the_stream():
    completed = _event(
        {'type': 'response.completed', 'response': {'status': 'completed'}}
    )
    delta = _event({'type': 'response.output_text.delta', 'delta': 'Hi'})

    assert completed.failure is None
    assert delta.failure is None
