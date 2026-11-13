"""The message object built from the events of a Messages API stream."""

import json

from tests.common import provider_responses as canned

from radicalbit_ai_gateway.llm.messages_stream import MessageBuilder

CITATION = {'type': 'char_location', 'cited_text': 'Rome', 'document_index': 0}


def _built(events: list[dict]) -> MessageBuilder:
    builder = MessageBuilder()
    for event in events:
        builder.add(event['type'], json.dumps(event))
    return builder


def _block(start: dict, *deltas: dict) -> list[dict]:
    """Return the events of one content block, the first of its message."""
    return [
        {'type': 'content_block_start', 'index': 0, 'content_block': start},
        *({'type': 'content_block_delta', 'index': 0, 'delta': d} for d in deltas),
        {'type': 'content_block_stop', 'index': 0},
    ]


def _stream(*block: dict) -> list[dict]:
    """Return the canned stream with ``block`` as its only content block."""
    events = canned.anthropic_stream([]).sse_events
    return [events[0], *block, *events[1:]]


def test_a_stream_builds_its_message_with_the_usage_of_both_ends():
    builder = _built(
        canned.anthropic_stream(
            ['Hello', ' there'], tool_use=[canned.ANTHROPIC_WEATHER_TOOL_USE]
        ).sse_events
    )

    message = builder.message()
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

    assert _built(events).message()['content'] == [
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

    assert _built(events).message()['content'] == [
        {'type': 'text', 'text': 'In Rome.', 'citations': [CITATION]}
    ]


def test_a_tool_input_cut_half_way_is_left_out():
    tool_use = {'type': 'tool_use', 'id': 'toolu_1', 'name': 'read', 'input': {}}
    events = _stream(
        *_block(tool_use, {'type': 'input_json_delta', 'partial_json': '{"path": "/tm'})
    )

    builder = _built(events)

    assert builder.has_cut_off_input
    assert builder.message()['content'] == [tool_use]


def test_a_stream_is_complete_once_it_gave_its_stop_reason():
    events = canned.anthropic_stream().sse_events

    before_the_stop_reason = _built(events[:-2])
    without_message_stop = _built(events[:-1])

    assert not before_the_stop_reason.complete
    assert before_the_stop_reason.message()['content'] == [
        {'type': 'text', 'text': 'Hello from the model'}
    ]
    assert without_message_stop.complete


def test_no_message_is_built_before_message_start():
    builder = _built([{'type': 'ping'}])

    assert builder.message() is None
    assert not builder.complete


def test_an_error_event_is_kept_as_it_came():
    error = {'type': 'error', 'error': {'type': 'overloaded_error', 'message': 'busy'}}

    assert json.loads(_built([error]).error) == error
