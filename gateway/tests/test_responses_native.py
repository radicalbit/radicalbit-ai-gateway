"""Responses API: the provider call and the invoker's fallbacks.

The request and event shapes follow a recorded opencode session against the
OpenAI Responses API (``store: false``, encrypted reasoning sent back, ``phase``
on assistant messages, parallel function calls).
"""

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
from httpx_aiohttp import HttpxAiohttpClient
import openai
import pytest

from tests.common.provider_recorder import CannedResponse, ProviderRecorder

from radicalbit_ai_gateway.invocation.chat_model_invoker import ChatModelInvoker
from radicalbit_ai_gateway.llm.chat_model import ChatModel
from radicalbit_ai_gateway.llm.factory import init_chat_model
from radicalbit_ai_gateway.llm.messages import AIMessageChunk
from radicalbit_ai_gateway.llm.providers._openai_responses import iter_sse_events
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.utils.exceptions import (
    ModelInvokerBadRequest,
    ModelInvokerInternalError,
    ModelInvokerUpstreamError,
)
from radicalbit_ai_gateway.utils.responses_native import NativeResponsesEvent
from radicalbit_ai_gateway.utils.streaming_utils import StreamingUtils

# A turn as opencode sends it back: reasoning only the model can resume, a
# commentary message, two parallel calls and their outputs.
OPENCODE_TURN = [
    {
        'type': 'message',
        'role': 'user',
        'content': [{'type': 'input_text', 'text': 'Implement the task'}],
    },
    {
        'type': 'reasoning',
        'id': 'rs_0095a',
        'summary': [],
        'encrypted_content': 'gAAAAABq301x',
    },
    {
        'type': 'message',
        'id': 'msg_0095a',
        'role': 'assistant',
        'status': 'completed',
        'content': [{'type': 'output_text', 'text': 'I will read the files first.'}],
        'phase': 'commentary',
    },
    {
        'type': 'function_call',
        'id': 'fc_0095a',
        'call_id': 'call_A',
        'name': 'read',
        'arguments': '{"path":"a.py"}',
    },
    {
        'type': 'function_call',
        'id': 'fc_0095b',
        'call_id': 'call_B',
        'name': 'glob',
        'arguments': '{"pattern":"**/*.py"}',
    },
    {'type': 'function_call_output', 'call_id': 'call_A', 'output': 'print(1)'},
    {'type': 'function_call_output', 'call_id': 'call_B', 'output': 'a.py'},
]

UPSTREAM_EVENTS = [
    {
        'type': 'response.created',
        'response': {'id': 'resp_1', 'model': 'gpt-6-luna', 'status': 'in_progress'},
    },
    {
        'type': 'response.output_text.delta',
        'item_id': 'msg_1',
        'output_index': 0,
        'content_index': 0,
        'delta': 'Hi',
        'logprobs': [],
        'obfuscation': 'xY',
    },
    {
        'type': 'response.completed',
        'response': {
            'id': 'resp_1',
            'model': 'gpt-6-luna',
            'status': 'completed',
            'usage': {
                'input_tokens': 100,
                'input_tokens_details': {'cached_tokens': 40, 'cache_write_tokens': 0},
                'output_tokens': 7,
                'output_tokens_details': {'reasoning_tokens': 0},
                'total_tokens': 107,
            },
        },
    },
]


async def _collect(source):
    return [item async for item in source]


# ── Provider ──────────────────────────────────────────────────────────────


def _openai(**kwargs):
    return init_chat_model(
        'openai:gpt-6-luna',
        api_key='sk',
        http_async_client=HttpxAiohttpClient(),
        **kwargs,
    )


class TestOpenAIResponses:
    def test_only_the_official_endpoint_serves_responses(self):
        assert _openai().supports_native_responses()
        assert not _openai(base_url='http://vllm:8000/v1').supports_native_responses()

    async def test_stream_forwards_the_body_and_relays_events(self):
        chat_model = _openai(temperature=0.2, reasoning_effort='low')
        body = {
            'model': 'my-route',
            'input': OPENCODE_TURN,
            'stream': True,
            'store': False,
            'include': ['reasoning.encrypted_content'],
            'reasoning': {'summary': 'auto'},
            'text': {'verbosity': 'low'},
            'prompt_cache_key': 'ses_1',
        }
        canned = CannedResponse(sse_events=UPSTREAM_EVENTS, sse_format='anthropic')

        with ProviderRecorder([canned]) as recorder:
            events = await _collect(chat_model.astream_native_responses(body))

        sent = recorder.requests[0]
        assert sent['url'] == 'https://api.openai.com/v1/responses'
        assert sent['body'] == {
            **body,
            'model': 'gpt-6-luna',
            # Configured settings fill what the client left out
            'temperature': 0.2,
            'reasoning': {'effort': 'low', 'summary': 'auto'},
        }
        assert [event for event, _ in events] == [e['type'] for e in UPSTREAM_EVENTS]
        assert [json.loads(data) for _, data in events] == UPSTREAM_EVENTS

    async def test_non_streaming_returns_the_response_object(self):
        upstream = UPSTREAM_EVENTS[2]['response']

        with ProviderRecorder([CannedResponse(json_body=upstream)]) as recorder:
            result = await _openai().ainvoke_native_responses({'input': 'Hi'})

        assert result == upstream
        assert recorder.requests[0]['body'] == {'input': 'Hi', 'model': 'gpt-6-luna'}


async def test_sse_events_without_event_lines_take_the_data_type():
    async def lines():
        for line in ['data: {"type":"a"}', '', 'event: b', 'data: {"type":"b"}', '']:
            yield line

    assert await _collect(iter_sse_events(lines())) == [
        ('a', '{"type":"a"}'),
        ('b', '{"type":"b"}'),
    ]


def test_native_event_reports_the_route_as_model():
    created = json.dumps(UPSTREAM_EVENTS[0], separators=(',', ':'))
    delta = json.dumps(UPSTREAM_EVENTS[1], separators=(',', ':'))

    created_event = NativeResponsesEvent.parse('response.created', created)
    delta_event = NativeResponsesEvent.parse('response.output_text.delta', delta)

    created_frame = created_event.to_sse('r')
    assert json.loads(created_frame.split('data: ')[1])['response']['model'] == 'r'
    # The upstream response stays as sent, for accounting and the cache
    assert created_event.response['model'] == 'gpt-6-luna'
    # Other events pass byte for byte
    assert delta_event.to_sse('r') == (
        f'event: response.output_text.delta\ndata: {delta}\n\n'
    )


# ── Invoker ───────────────────────────────────────────────────────────────


class FakeChatModel(ChatModel):
    def __init__(self, native=True, events=(), error=None, fail_after=None):
        self.native = native
        self.events = events
        self.error = error
        self.fail_after = fail_after
        self.bodies = []

    def supports_native_responses(self):
        return self.native

    async def astream_native_responses(self, body):
        self.bodies.append(body)
        if self.error:
            raise self.error
        for i, event in enumerate(self.events):
            if i == self.fail_after:
                raise RuntimeError('connection reset')
            yield event['type'], json.dumps(event)

    async def ainvoke_native_responses(self, body):
        self.bodies.append(body)
        if self.error:
            raise self.error
        return self.events[-1]['response']

    async def _agenerate(self, messages, **kwargs):
        raise NotImplementedError

    async def _astream(self, messages, **kwargs):
        raise NotImplementedError
        yield


def _invoker(primary, *fallbacks) -> ChatModelInvoker:
    invoker = ChatModelInvoker.__new__(ChatModelInvoker)
    models = [
        Model(model_id=f'm{i}', model='openai/x') for i in range(len(fallbacks) + 1)
    ]
    invoker.model_map = {
        'm0': (models[0], primary, list(zip(models[1:], fallbacks, strict=True)))
    }
    invoker._record_metrics = MagicMock()
    return invoker


CALL = {
    'request_uuid': 'r',
    'api_key_uuid': 'k',
    'group_uuid': 'g',
    'api_key_name': 'k',
    'group_name': 'g',
    'route_name': 'route',
    'model_id': 'm0',
}


async def _stream(invoker, body, **kwargs):
    return await _collect(invoker.stream_responses(**CALL, body=body, **kwargs))


def _status_error(status: int, body: dict):
    request = httpx.Request('POST', 'https://api.openai.com/v1/responses')
    response = httpx.Response(status, json=body, request=request)
    return openai.APIStatusError(body['error']['message'], response=response, body=body)


class TestStreamResponses:
    async def test_streams_the_events_and_records_usage(self):
        invoker = _invoker(FakeChatModel(events=UPSTREAM_EVENTS))

        events = await _stream(invoker, {'input': OPENCODE_TURN})

        assert [event.event for event in events] == [e['type'] for e in UPSTREAM_EVENTS]
        metrics = invoker._record_metrics.call_args.kwargs
        assert metrics['token_input_count'] == 60
        assert metrics['cached_token_count'] == 40
        assert metrics['token_output_count'] == 7
        assert metrics['fallback_triggered'] is False

    async def test_fallback_gets_no_reasoning(self):
        primary = FakeChatModel(error=RuntimeError('503'))
        fallback = FakeChatModel(events=UPSTREAM_EVENTS)
        invoker = _invoker(primary, fallback)

        await _stream(invoker, {'input': OPENCODE_TURN})

        assert primary.bodies[0]['input'] == OPENCODE_TURN
        assert 'reasoning' not in [item['type'] for item in fallback.bodies[0]['input']]
        assert invoker._record_metrics.call_args.kwargs['fallback_triggered'] is True

    async def test_fallbacks_without_responses_api_are_skipped(self):
        primary = FakeChatModel(error=RuntimeError('503'))
        deepseek = FakeChatModel(native=False, events=UPSTREAM_EVENTS)
        openai_fallback = FakeChatModel(events=UPSTREAM_EVENTS)

        await _stream(_invoker(primary, deepseek, openai_fallback), {'input': 'Hi'})

        assert deepseek.bodies == []
        assert len(openai_fallback.bodies) == 1

    async def test_no_fallback_for_stored_state(self):
        primary = FakeChatModel(error=RuntimeError('503'))
        fallback = FakeChatModel(events=UPSTREAM_EVENTS)

        with pytest.raises(ModelInvokerInternalError):
            await _stream(
                _invoker(primary, fallback),
                {'input': 'Hi', 'previous_response_id': 'resp_0'},
                allow_fallback=False,
            )
        assert fallback.bodies == []

    async def test_model_without_responses_api_is_refused(self):
        with pytest.raises(ModelInvokerBadRequest):
            await _stream(_invoker(FakeChatModel(native=False)), {'input': 'Hi'})

    async def test_failure_after_streaming_started_is_not_retried(self):
        primary = FakeChatModel(events=UPSTREAM_EVENTS, fail_after=2)
        fallback = FakeChatModel(events=UPSTREAM_EVENTS)

        with pytest.raises(RuntimeError, match='connection reset'):
            await _stream(_invoker(primary, fallback), {'input': 'Hi'})
        assert fallback.bodies == []

    async def test_upstream_refusal_reaches_the_client_as_sent(self):
        body = {'error': {'message': 'context_length_exceeded', 'code': 'x'}}
        primary = FakeChatModel(error=_status_error(400, body))

        with pytest.raises(ModelInvokerUpstreamError) as raised:
            await _stream(_invoker(primary), {'input': 'Hi'})

        assert raised.value.status_code == 400
        assert raised.value.body == body

    async def test_other_failures_are_internal_errors(self):
        primary = FakeChatModel(error=RuntimeError('boom'))

        with pytest.raises(ModelInvokerInternalError):
            await _stream(_invoker(primary), {'input': 'Hi'})


class TestCompleteResponses:
    async def test_returns_the_upstream_response(self):
        invoker = _invoker(FakeChatModel(events=UPSTREAM_EVENTS))

        result, model = await invoker.complete_responses(
            **CALL, body={'input': OPENCODE_TURN}
        )

        assert result == UPSTREAM_EVENTS[2]['response']
        assert model.model_id == 'm0'
        assert invoker._record_metrics.call_args.kwargs['token_input_count'] == 60

    async def test_fallback_answers_without_reasoning(self):
        primary = FakeChatModel(error=RuntimeError('503'))
        fallback = FakeChatModel(events=UPSTREAM_EVENTS)
        invoker = _invoker(primary, fallback)

        _, model = await invoker.complete_responses(
            **CALL, body={'input': OPENCODE_TURN}
        )

        assert model.model_id == 'm1'
        assert 'reasoning' not in [item['type'] for item in fallback.bodies[0]['input']]
        assert invoker._record_metrics.call_args.kwargs['fallback_triggered'] is True

    async def test_no_fallback_for_stored_state(self):
        primary = FakeChatModel(error=RuntimeError('503'))
        fallback = FakeChatModel(events=UPSTREAM_EVENTS)

        with pytest.raises(ModelInvokerInternalError):
            await _invoker(primary, fallback).complete_responses(
                **CALL, body={'input': 'Hi'}, allow_fallback=False
            )
        assert fallback.bodies == []

    async def test_upstream_refusal_is_relayed(self):
        body = {'error': {'message': 'rate limited', 'code': 'rate_limit'}}
        primary = FakeChatModel()
        primary.ainvoke_native_responses = AsyncMock(
            side_effect=_status_error(429, body)
        )

        with pytest.raises(ModelInvokerUpstreamError) as raised:
            await _invoker(primary).complete_responses(**CALL, body={'input': 'Hi'})

        assert raised.value.status_code == 429


# ── Chat chunks (/v1/chat/completions) ────────────────────────────────────


class TestChatChunkConversion:
    def test_parallel_calls_keep_their_index(self):
        chunk = AIMessageChunk(
            content='',
            tool_call_chunks=[
                {'index': 1, 'id': 'call_B', 'name': 'glob', 'args': '{'}
            ],
        )

        converted = StreamingUtils.to_openai_chat_completion_chunk(chunk, 'r')

        assert converted.choices[0].delta.tool_calls[0].index == 1

    def test_reasoning_content_is_streamed(self):
        chunk = AIMessageChunk(
            content='', additional_kwargs={'reasoning_content': 'Thinking'}
        )

        converted = StreamingUtils.to_openai_chat_completion_chunk(chunk, 'r')

        assert converted.choices[0].delta.model_extra['reasoning_content'] == 'Thinking'
        assert '"reasoning_content":"Thinking"' in converted.model_dump_json()
