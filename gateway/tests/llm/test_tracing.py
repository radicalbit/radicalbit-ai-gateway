"""The CLIENT span every chat model call emits (``llm/tracing.py``)."""

from collections.abc import AsyncIterator
import json
from typing import Any

import httpx2
import openai
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
import pytest

from radicalbit_ai_gateway.llm import tracing
from radicalbit_ai_gateway.llm.chat_model import ChatModel
from radicalbit_ai_gateway.llm.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    tool_call_chunk,
)
from radicalbit_ai_gateway.llm.providers.openai import _langchain_error_type


class _Model(ChatModel):
    _gen_ai_provider = 'fake'

    def __init__(self, reply=None, chunks=(), error=None, **settings: Any):
        self.reply = reply
        self.chunks = list(chunks)
        self.error = error
        for name, value in settings.items():
            setattr(self, name, value)

    async def _agenerate(self, messages: list[BaseMessage], **kwargs: Any) -> AIMessage:
        if self.error:
            raise self.error
        return self.reply

    async def _astream(
        self, messages: list[BaseMessage], **kwargs: Any
    ) -> AsyncIterator[AIMessageChunk]:
        for chunk in self.chunks:
            yield chunk
        if self.error:
            raise self.error

    def _generation_info(self, message: AIMessage) -> dict | None:
        if reason := message.response_metadata.get('finish_reason'):
            return {'finish_reason': reason}
        return None


@pytest.fixture
def spans(monkeypatch) -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(tracing, '_tracer', provider.get_tracer('test'))
    return exporter


MESSAGES = [SystemMessage('Be terse.'), HumanMessage('Hi')]


def _only_span(exporter: InMemorySpanExporter):
    (span,) = exporter.get_finished_spans()
    return span


async def test_reply_span(spans):
    model = _Model(
        AIMessage(
            'Hello',
            response_metadata={'finish_reason': 'stop', 'model_name': 'm-1'},
            usage_metadata={'input_tokens': 3, 'output_tokens': 2, 'total_tokens': 5},
        ),
        model='m',
        temperature=0.5,
    )
    await model.ainvoke(MESSAGES, top_p=0.9)

    span = _only_span(spans)
    attributes = dict(span.attributes)
    assert span.name == '_Model.chat'
    assert attributes['gen_ai.provider.name'] == 'fake'
    assert attributes['gen_ai.request.model'] == 'm'
    assert attributes['gen_ai.request.temperature'] == 0.5
    assert attributes['gen_ai.request.top_p'] == 0.9
    assert attributes['gen_ai.usage.input_tokens'] == 3
    assert attributes['gen_ai.response.finish_reasons'] == ('stop',)
    assert json.loads(attributes['gen_ai.system_instructions']) == [
        {'type': 'text', 'content': 'Be terse.'}
    ]
    assert json.loads(attributes['gen_ai.output.messages']) == [
        {
            'role': 'assistant',
            'parts': [{'type': 'text', 'content': 'Hello'}],
            'finish_reason': 'stop',
        }
    ]


async def test_constructor_params_win_over_call_params(spans):
    model = _Model(AIMessage('ok'), model='m', max_tokens=100)
    await model.ainvoke(MESSAGES, max_tokens=5)

    assert _only_span(spans).attributes['gen_ai.request.max_tokens'] == 100


async def test_stream_is_reported_merged(spans):
    chunks = [
        AIMessageChunk('Hel', response_metadata={'model_name': 'm-1'}),
        AIMessageChunk(
            'lo',
            tool_call_chunks=[tool_call_chunk(name='f', args='{"a"', id='c1', index=0)],
        ),
        AIMessageChunk(
            '',
            tool_call_chunks=[tool_call_chunk(args=': 1}', index=0)],
            response_metadata={'finish_reason': 'tool_calls'},
            usage_metadata={'input_tokens': 3, 'output_tokens': 2, 'total_tokens': 5},
        ),
    ]
    model = _Model(chunks=chunks, model='m')
    received = [chunk async for chunk in model.astream(MESSAGES)]

    assert received[-1].chunk_position == 'last'
    attributes = dict(_only_span(spans).attributes)
    assert attributes['gen_ai.response.model'] == 'm'
    assert attributes['gen_ai.usage.output_tokens'] == 2
    assert json.loads(attributes['gen_ai.output.messages']) == [
        {
            'role': 'unknown',
            'parts': [
                {'type': 'text', 'content': 'Hello'},
                {'type': 'tool_call', 'id': 'c1', 'name': 'f', 'arguments': {'a': 1}},
            ],
            'finish_reason': 'tool_call',
        }
    ]


async def test_failed_call_is_an_error_span(spans):
    model = _Model(error=RuntimeError('boom'), model='m')
    with pytest.raises(RuntimeError):
        await model.ainvoke(MESSAGES)

    span = _only_span(spans)
    assert span.status.status_code.name == 'ERROR'
    assert span.attributes['error.type'] == 'RuntimeError'


async def test_empty_stream_is_an_error_span(spans):
    with pytest.raises(ValueError, match='No generation chunks'):
        [chunk async for chunk in _Model(model='m').astream(MESSAGES)]

    assert _only_span(spans).attributes['error.type'] == 'ValueError'


async def test_content_tracing_switch(spans, monkeypatch):
    monkeypatch.setenv('TRACELOOP_TRACE_CONTENT', 'false')
    reply = AIMessage('secret', response_metadata={'finish_reason': 'stop'})
    await _Model(reply, model='m').ainvoke(MESSAGES)

    attributes = _only_span(spans).attributes
    assert 'gen_ai.input.messages' not in attributes
    assert 'gen_ai.output.messages' not in attributes
    assert attributes['gen_ai.response.finish_reasons'] == ('stop',)


def test_openai_errors_keep_langchain_names():
    request = httpx2.Request('POST', 'https://x')
    response = httpx2.Response(400, request=request)
    error = openai.BadRequestError('bad', response=response, body=None)

    assert _langchain_error_type(error) == 'OpenAIInvalidRequestError'
    assert _langchain_error_type(ValueError()) == 'ValueError'
