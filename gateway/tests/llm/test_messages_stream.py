"""The message object built from the events of a Messages API stream."""

import json
from typing import Any

from tests.common import provider_responses as canned
from tests.common.provider_recorder import CannedResponse

from radicalbit_ai_gateway.llm.messages_stream import MessageBuilder

CITATION = {'type': 'char_location', 'cited_text': 'Rome', 'document_index': 0}


def _built(events: list[dict[str, Any]]) -> MessageBuilder:
    builder = MessageBuilder()
    for event in events:
        builder.add(event['type'], json.dumps(event))
    return builder


def _sse_events(response: CannedResponse) -> list[dict[str, Any]]:
    assert response.sse_events is not None
    return response.sse_events


def _message(builder: MessageBuilder) -> dict[str, Any]:
    message = builder.message()
    assert message is not None
    return message


def _block(start: dict[str, Any], *deltas: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the events of one content block, the first of its message."""
    return [
        {'type': 'content_block_start', 'index': 0, 'content_block': start},
        *({'type': 'content_block_delta', 'index': 0, 'delta': d} for d in deltas),
        {'type': 'content_block_stop', 'index': 0},
    ]


def _stream(*block: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the canned stream with ``block`` as its only content block."""
    events = _sse_events(canned.anthropic_stream([]))
    return [events[0], *block, *events[1:]]


def test_a_stream_builds_its_message_with_the_usage_of_both_ends():
    builder = _built(
        _sse_events(
            canned.anthropic_stream(
                ['Hello', ' there'], tool_use=[canned.ANTHROPIC_WEATHER_TOOL_USE]
            )
        )
    )

    message = _message(builder)
    assert builder.complete
    assert not builder.has_cut_off_input
    assert message['content'] == [
        {'type': 'text', 'text': 'Hello there'},
        {'type': 'tool_use', **canned.ANTHROPIC_WEATHER_TOOL_USE},
    ]
    assert message['stop_reason'] == 'tool_use'
    assert message['usage']['input_tokens'] == 21
    assert message['usage']['output_tokens'] == 7
    assert message['usage'] == builder.usage


def test_thinking_keeps_its_signature():
    events = _stream(
        *_block(
            {'type': 'thinking', 'thinking': '', 'signature': ''},
            {'type': 'thinking_delta', 'thinking': 'Let me see.'},
            {'type': 'signature_delta', 'signature': 'sig=='},
        )
    )

    assert _message(_built(events))['content'] == [
        {'type': 'thinking', 'thinking': 'Let me see.', 'signature': 'sig=='}
    ]


def test_text_keeps_its_citations():
    events = _stream(
        *_block(
            {'type': 'text', 'text': '', 'citations': []},
            {'type': 'text_delta', 'text': 'In Rome.'},
            {'type': 'citations_delta', 'citation': CITATION},
        )
    )

    assert _message(_built(events))['content'] == [
        {'type': 'text', 'text': 'In Rome.', 'citations': [CITATION]}
    ]


def test_a_tool_input_cut_half_way_is_left_out():
    tool_use = {'type': 'tool_use', 'id': 'toolu_1', 'name': 'read', 'input': {}}
    events = _stream(
        *_block(tool_use, {'type': 'input_json_delta', 'partial_json': '{"path": "/tm'})
    )

    builder = _built(events)

    assert builder.has_cut_off_input
    assert _message(builder)['content'] == [tool_use]


def test_a_stream_is_complete_once_it_gave_its_stop_reason():
    events = _sse_events(canned.anthropic_stream())

    before_the_stop_reason = _built(events[:-2])
    without_message_stop = _built(events[:-1])

    assert not before_the_stop_reason.complete
    assert _message(before_the_stop_reason)['content'] == [
        {'type': 'text', 'text': 'Hello from the model'}
    ]
    assert without_message_stop.complete


def test_no_message_is_built_before_message_start():
    builder = _built([{'type': 'ping'}])

    assert builder.message() is None
    assert not builder.complete


def test_an_error_event_is_kept_as_it_came():
    error = {'type': 'error', 'error': {'type': 'overloaded_error', 'message': 'busy'}}

    built_error = _built([error]).error
    assert built_error is not None
    assert json.loads(built_error) == error


def test_an_error_event_is_described_by_its_type_and_message():
    error = {'type': 'error', 'error': {'type': 'overloaded_error', 'message': 'busy'}}

    assert _built([error]).error_description() == 'overloaded_error: busy'


def test_an_error_that_is_not_an_anthropic_error_is_described_as_it_came():
    builder = MessageBuilder()
    builder.add('error', 'upstream gone')

    assert builder.error_description() == 'upstream gone'


def test_a_stream_without_an_error_has_no_error_description():
    events = _sse_events(canned.anthropic_stream())

    assert _built(events).error_description() is None
