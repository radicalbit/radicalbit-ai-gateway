import json

from openai.types.responses import Response, ResponseStreamEvent
from pydantic import TypeAdapter

from radicalbit_ai_gateway.llm.messages import AIMessage
from radicalbit_ai_gateway.responses.events import response_events
from radicalbit_ai_gateway.responses.output import (
    ResponsesOutput,
    gateway_response,
    message_item,
)
from radicalbit_ai_gateway.responses.serving import serve_stream
from radicalbit_ai_gateway.utils.exceptions import (
    GatewayBadRequest,
    ModelInvokerUpstreamError,
)

EVENT_ADAPTER = TypeAdapter(ResponseStreamEvent)


def events_of(frames: list[str]) -> list[dict]:
    """Parse SSE frames, checking each one's ``event:`` line matches its type."""
    events = []
    for frame in frames:
        event_line, data_line = frame.strip('\n').split('\n')
        event = json.loads(data_line.removeprefix('data: '))
        assert event_line == f'event: {event["type"]}'
        events.append(event)
    return events


def _response(output: list) -> dict:
    response = gateway_response('0000-1111', 'route', {'input': 'Hi'}, '')
    return {**response, 'output': output}


REASONING = {
    'id': 'rs_1',
    'type': 'reasoning',
    'summary': [{'type': 'summary_text', 'text': 'Thinking'}],
    'encrypted_content': 'gAAA',
}
CALL = {
    'id': 'fc_1',
    'type': 'function_call',
    'status': 'completed',
    'call_id': 'call_A',
    'name': 'read',
    'arguments': '{"path":"a.py"}',
}


class TestResponsesOutput:
    def test_each_message_text_reads_as_one_message(self):
        output = ResponsesOutput(_response([REASONING, message_item('Hello'), CALL]))

        assert output.messages() == [AIMessage(content='Hello')]

    def test_changed_text_is_written_back(self):
        response = _response([message_item('My card is 4111')])
        output = ResponsesOutput(response)

        output.write_back([AIMessage(content='My card is <CARD>')])

        assert output.response['output'][0]['content'][0]['text'] == 'My card is <CARD>'
        assert response['output'][0]['content'][0]['text'] == 'My card is 4111'

    def test_changed_text_drops_what_describes_the_old_one(self):
        item = message_item('See example.com')
        item['content'][0]['annotations'] = [
            {
                'type': 'url_citation',
                'start_index': 4,
                'end_index': 15,
                'url': 'https://example.com',
                'title': 'x',
            }
        ]
        item['content'][0]['logprobs'] = [
            {'token': 'See', 'logprob': -0.1, 'bytes': [], 'top_logprobs': []}
        ]
        output = ResponsesOutput(_response([item]))

        output.write_back([AIMessage(content='See <URL>')])

        part = output.response['output'][0]['content'][0]
        assert (part['annotations'], part['logprobs']) == ([], [])


def test_gateway_response_is_a_responses_api_response():
    response = gateway_response(
        'a1b2-c3', 'route', {'input': 'Hi', 'tools': []}, 'Not allowed'
    )

    parsed = Response.model_validate(response)

    assert parsed.id == 'resp_a1b2c3'
    assert parsed.output_text == 'Not allowed'
    assert parsed.model == 'route'


class TestResponseEvents:
    def test_events_follow_the_openai_sequence(self):
        response = _response([REASONING, message_item('Hello'), CALL])

        events = events_of(response_events(response))

        for event in events:
            EVENT_ADAPTER.validate_python(event)
        assert [event['sequence_number'] for event in events] == list(
            range(len(events))
        )
        assert [event['type'] for event in events] == [
            'response.created',
            'response.in_progress',
            'response.output_item.added',
            'response.reasoning_summary_part.added',
            'response.reasoning_summary_text.delta',
            'response.reasoning_summary_text.done',
            'response.reasoning_summary_part.done',
            'response.output_item.done',
            'response.output_item.added',
            'response.content_part.added',
            'response.output_text.delta',
            'response.output_text.done',
            'response.content_part.done',
            'response.output_item.done',
            'response.output_item.added',
            'response.function_call_arguments.delta',
            'response.function_call_arguments.done',
            'response.output_item.done',
            'response.completed',
        ]
        assert events[0]['response']['output'] == []
        assert events[-1]['response'] == response
        assert [e['output_index'] for e in events if 'output_index' in e][-1] == 2

    def test_items_are_added_before_their_content(self):
        events = events_of(response_events(_response([message_item('Hello'), CALL])))

        added = [e['item'] for e in events if e['type'] == 'response.output_item.added']
        assert added[0]['content'] == []
        assert added[1]['arguments'] == ''

    def test_tool_calls_stream_their_events(self):
        where = {'status': 'completed'}
        output = [
            {
                'id': 'ctc_1',
                'type': 'custom_tool_call',
                'call_id': 'call_P',
                'name': 'apply_patch',
                'input': '*** Begin Patch',
            },
            {
                'id': 'ws_1',
                'type': 'web_search_call',
                **where,
                'action': {'type': 'search', 'query': 'weather'},
            },
            {'id': 'fs_1', 'type': 'file_search_call', **where, 'queries': ['q']},
            {
                'id': 'ci_1',
                'type': 'code_interpreter_call',
                **where,
                'code': 'print(1)',
                'container_id': 'cntr_1',
                'outputs': [],
            },
            {
                'id': 'ig_1',
                'type': 'image_generation_call',
                **where,
                'result': 'aGk=',
            },
            {'id': 'ml_1', 'type': 'mcp_list_tools', 'server_label': 's', 'tools': []},
            {
                'id': 'mc_1',
                'type': 'mcp_call',
                'status': 'failed',
                'server_label': 's',
                'name': 'n',
                'arguments': '{"a":1}',
            },
        ]

        events = events_of(response_events(_response(output)))

        for event in events:
            EVENT_ADAPTER.validate_python(event)
        types = [e['type'] for e in events]
        for expected in [
            'response.custom_tool_call_input.delta',
            'response.custom_tool_call_input.done',
            'response.web_search_call.searching',
            'response.file_search_call.completed',
            'response.code_interpreter_call_code.done',
            'response.code_interpreter_call.interpreting',
            'response.image_generation_call.generating',
            'response.mcp_list_tools.completed',
            'response.mcp_call_arguments.done',
            'response.mcp_call.failed',
        ]:
            assert expected in types
        added = [e['item'] for e in events if e['type'] == 'response.output_item.added']
        assert added[0]['input'] == ''
        assert added[3]['code'] == ''


async def _collect(source):
    return [item async for item in source]


class TestServeStream:
    async def test_frames_pass_through(self):
        async def frames():
            yield 'event: a\ndata: {}\n\n'
            yield 'event: b\ndata: {}\n\n'

        assert await _collect(serve_stream(frames())) == [
            'event: a\ndata: {}\n\n',
            'event: b\ndata: {}\n\n',
        ]

    async def test_upstream_refusal_before_streaming_is_relayed_as_sent(self):
        body = {'error': {'message': 'context_length_exceeded'}}

        async def frames():
            raise ModelInvokerUpstreamError('too long', 400, body)
            yield

        assert await _collect(serve_stream(frames())) == [(json.dumps(body), 400)]

    async def test_gateway_failure_before_streaming_is_an_http_error(self):
        async def frames():
            raise GatewayBadRequest('nope')
            yield

        ((body, status),) = await _collect(serve_stream(frames()))

        assert status == 400
        assert json.loads(body)['error']['message'] == 'nope'

    async def test_failure_while_streaming_ends_with_an_error_event(self):
        async def frames():
            yield 'event: a\ndata: {"type":"a","sequence_number":0}\n\n'
            yield 'event: b\ndata: {"type":"b","sequence_number":1}\n\n'
            raise RuntimeError('connection reset')

        received = await _collect(serve_stream(frames()))

        (error,) = events_of(received[2:])
        assert error['type'] == 'error'
        # The error continues the stream's sequence
        assert error['sequence_number'] == 2
        EVENT_ADAPTER.validate_python(error)
