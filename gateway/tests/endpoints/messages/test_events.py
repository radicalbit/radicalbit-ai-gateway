import json

from anthropic.types import RawMessageStreamEvent
from pydantic import TypeAdapter

from radicalbit_ai_gateway.endpoints.messages.events import message_events
from radicalbit_ai_gateway.endpoints.messages.output import gateway_message
from radicalbit_ai_gateway.llm.messages_stream import stream_usage

EVENT_ADAPTER = TypeAdapter(RawMessageStreamEvent)

USAGE = {
    'input_tokens': 21,
    'output_tokens': 7,
    'cache_creation_input_tokens': 3,
    'cache_read_input_tokens': 5,
    'cache_creation': {'ephemeral_5m_input_tokens': 3, 'ephemeral_1h_input_tokens': 0},
    'service_tier': 'standard',
}
THINKING = {'type': 'thinking', 'thinking': 'Let me see.', 'signature': 'sig=='}
TOOL_USE = {
    'type': 'tool_use',
    'id': 'toolu_1',
    'name': 'read',
    'input': {'path': 'a.py', 'lines': [1, 2]},
}


def _message(content: list, **fields) -> dict:
    return {
        'id': 'msg_provider_1',
        'type': 'message',
        'role': 'assistant',
        'model': 'assistant',
        'content': content,
        'stop_reason': 'end_turn',
        'stop_sequence': None,
        'usage': USAGE,
        **fields,
    }


def _events(message: dict) -> list[dict]:
    """Return the events of ``message``'s frames, each a valid Messages
    stream event named as its ``type``.
    """
    events = []
    for frame in message_events(message):
        event_line, data_line, *rest = frame.split('\n')
        assert rest == ['', '']
        event = json.loads(data_line.removeprefix('data: '))
        assert event_line == f'event: {event["type"]}'
        EVENT_ADAPTER.validate_python(event)
        events.append(event)
    return events


def _rebuilt(events: list[dict]) -> dict:
    """Rebuild the answer a client reads from ``events``, as an SDK does."""
    message: dict = {}
    partial_json: dict[int, str] = {}
    for event in events:
        if event['type'] == 'message_start':
            message = dict(event['message'])
        elif event['type'] == 'content_block_start':
            assert event['index'] == len(message['content'])
            message['content'] = [*message['content'], dict(event['content_block'])]
        elif event['type'] == 'content_block_delta':
            block = message['content'][event['index']]
            delta = event['delta']
            if delta['type'] == 'text_delta':
                block['text'] += delta['text']
            elif delta['type'] == 'thinking_delta':
                block['thinking'] += delta['thinking']
            elif delta['type'] == 'signature_delta':
                block['signature'] = delta['signature']
            elif delta['type'] == 'citations_delta':
                block['citations'] = [*block['citations'], delta['citation']]
            elif delta['type'] == 'input_json_delta':
                index = event['index']
                partial_json[index] = (
                    partial_json.get(index, '') + delta['partial_json']
                )
        elif event['type'] == 'content_block_stop':
            if event['index'] in partial_json:
                message['content'][event['index']]['input'] = json.loads(
                    partial_json[event['index']]
                )
        elif event['type'] == 'message_delta':
            message.update(event['delta'])
            message['usage'] = {**message['usage'], **event['usage']}
    return message


def test_text_answer_is_streamed_with_its_text_in_one_delta():
    message = _message([{'type': 'text', 'text': 'Hello there'}])

    assert _events(message) == [
        {
            'type': 'message_start',
            'message': {
                **message,
                'content': [],
                'stop_reason': None,
                'stop_sequence': None,
                'usage': {**USAGE, 'output_tokens': 0},
            },
        },
        {
            'type': 'content_block_start',
            'index': 0,
            'content_block': {'type': 'text', 'text': ''},
        },
        {
            'type': 'content_block_delta',
            'index': 0,
            'delta': {'type': 'text_delta', 'text': 'Hello there'},
        },
        {'type': 'content_block_stop', 'index': 0},
        {
            'type': 'message_delta',
            'delta': {'stop_reason': 'end_turn', 'stop_sequence': None},
            'usage': {
                'input_tokens': 21,
                'output_tokens': 7,
                'cache_creation_input_tokens': 3,
                'cache_read_input_tokens': 5,
            },
        },
        {'type': 'message_stop'},
    ]


def test_tool_use_is_streamed_with_its_full_input_in_one_delta():
    message = _message(
        [{'type': 'text', 'text': 'Reading.'}, TOOL_USE], stop_reason='tool_use'
    )

    events = _events(message)

    assert events[4:7] == [
        {
            'type': 'content_block_start',
            'index': 1,
            'content_block': {**TOOL_USE, 'input': {}},
        },
        {
            'type': 'content_block_delta',
            'index': 1,
            'delta': {
                'type': 'input_json_delta',
                'partial_json': '{"path":"a.py","lines":[1,2]}',
            },
        },
        {'type': 'content_block_stop', 'index': 1},
    ]
    assert events[7]['delta'] == {'stop_reason': 'tool_use', 'stop_sequence': None}


def test_thinking_is_streamed_with_its_text_then_its_signature():
    events = _events(_message([THINKING, {'type': 'text', 'text': 'Hi'}]))

    assert events[1:5] == [
        {
            'type': 'content_block_start',
            'index': 0,
            'content_block': {'type': 'thinking', 'thinking': '', 'signature': ''},
        },
        {
            'type': 'content_block_delta',
            'index': 0,
            'delta': {'type': 'thinking_delta', 'thinking': 'Let me see.'},
        },
        {
            'type': 'content_block_delta',
            'index': 0,
            'delta': {'type': 'signature_delta', 'signature': 'sig=='},
        },
        {'type': 'content_block_stop', 'index': 0},
    ]


def test_thinking_with_no_text_is_streamed_with_its_signature_only():
    omitted = {'type': 'thinking', 'thinking': '', 'signature': 'sig=='}

    events = _events(_message([omitted]))

    assert [event['type'] for event in events[1:-2]] == [
        'content_block_start',
        'content_block_delta',
        'content_block_stop',
    ]
    assert events[2]['delta'] == {'type': 'signature_delta', 'signature': 'sig=='}


def test_redacted_thinking_is_streamed_whole_with_no_delta():
    redacted = {'type': 'redacted_thinking', 'data': 'opaque'}

    events = _events(_message([redacted]))

    assert events[1:-2] == [
        {'type': 'content_block_start', 'index': 0, 'content_block': redacted},
        {'type': 'content_block_stop', 'index': 0},
    ]


def test_text_citations_are_streamed_after_the_text():
    citation = {
        'type': 'char_location',
        'cited_text': 'The sky is blue.',
        'document_index': 0,
        'document_title': 'Sky',
        'start_char_index': 0,
        'end_char_index': 16,
        'file_id': None,
    }
    block = {'type': 'text', 'text': 'Blue.', 'citations': [citation]}

    events = _events(_message([block]))

    assert events[1]['content_block'] == {'type': 'text', 'text': '', 'citations': []}
    assert [event['delta'] for event in events[2:4]] == [
        {'type': 'text_delta', 'text': 'Blue.'},
        {'type': 'citations_delta', 'citation': citation},
    ]


def test_server_tool_blocks_are_streamed_as_the_upstream_streams_them():
    server_tool_use = {
        'type': 'server_tool_use',
        'id': 'srvtoolu_1',
        'name': 'web_search',
        'input': {'query': 'weather'},
    }
    result = {
        'type': 'web_search_tool_result',
        'tool_use_id': 'srvtoolu_1',
        'content': [
            {
                'type': 'web_search_result',
                'title': 'Weather',
                'url': 'https://example.com',
                'encrypted_content': 'abc',
                'page_age': None,
            }
        ],
    }

    events = _events(_message([server_tool_use, result]))

    assert events[1]['content_block'] == {**server_tool_use, 'input': {}}
    assert events[2]['delta'] == {
        'type': 'input_json_delta',
        'partial_json': '{"query":"weather"}',
    }
    assert events[4:6] == [
        {'type': 'content_block_start', 'index': 1, 'content_block': result},
        {'type': 'content_block_stop', 'index': 1},
    ]


def test_a_client_rebuilds_the_same_answer_from_the_events():
    message = _message(
        [THINKING, {'type': 'text', 'text': 'Reading.'}, TOOL_USE],
        stop_reason='tool_use',
    )

    assert _rebuilt(_events(message)) == message


def test_the_events_carry_the_usage_the_gateway_counts():
    usage: dict = {}
    for frame in message_events(_message([{'type': 'text', 'text': 'Hi'}])):
        event, data = frame.strip().split('\n')
        usage = stream_usage(
            event.removeprefix('event: '), data.removeprefix('data: '), usage
        )

    assert usage == USAGE


def test_built_answer_is_streamed_as_a_valid_stream():
    message = gateway_message('0000-1111', 'assistant', 'I cannot help with that.')

    events = _events(message)

    assert [event['type'] for event in events] == [
        'message_start',
        'content_block_start',
        'content_block_delta',
        'content_block_stop',
        'message_delta',
        'message_stop',
    ]
    assert _rebuilt(events) == message


def test_text_is_not_escaped_in_the_frames():
    frames = message_events(_message([{'type': 'text', 'text': 'Perché no'}]))

    assert '"text":"Perché no"' in frames[2]


def test_answer_with_no_content_or_usage_is_still_a_stream():
    events = _events(_message(None, usage=None))

    assert [event['type'] for event in events] == [
        'message_start',
        'message_delta',
        'message_stop',
    ]
    assert events[0]['message']['usage'] == {'input_tokens': 0, 'output_tokens': 0}
    assert events[1]['usage'] == {'output_tokens': 0}
