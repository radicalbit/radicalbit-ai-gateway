"""The CLIENT span every chat model call emits (``llm/tracing.py``).

The tests swap the module's tracer and histograms for ones backed by an
in-memory exporter and metric reader (``monkeypatch`` restores them), so no
global OpenTelemetry or Traceloop state is touched.
"""

from collections.abc import AsyncIterator
import dataclasses
import datetime
import json
from typing import Any

import httpx2
from httpx_aiohttp import HttpxAiohttpClient
import openai
from opentelemetry import context as context_api, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.sampling import ALWAYS_OFF
from opentelemetry.trace import SpanKind, StatusCode
from pydantic import BaseModel
import pytest

from tests.common import provider_responses as canned
from tests.common.provider_recorder import ProviderRecorder

from radicalbit_ai_gateway.llm import tracing
from radicalbit_ai_gateway.llm.chat_model import ChatModel
from radicalbit_ai_gateway.llm.factory import init_chat_model
from radicalbit_ai_gateway.llm.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    FunctionMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    tool_call_chunk,
)
from radicalbit_ai_gateway.llm.providers.openai import _langchain_error_type
from radicalbit_ai_gateway.models.model import MockGatewayChatModel


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


class _LlmOutputModel(_Model):
    """A model reporting LangChain's ``llm_output`` (model, id, raw usage)."""

    def __init__(self, llm_output: dict, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.llm_output = llm_output

    def _llm_output(self, message: AIMessage) -> dict | None:
        return self.llm_output


@pytest.fixture
def spans(monkeypatch) -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(tracing, '_tracer', provider.get_tracer('test'))
    return exporter


@pytest.fixture
def metrics(monkeypatch):
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    meter = provider.get_meter('test')
    monkeypatch.setattr(
        tracing,
        '_duration_histogram',
        meter.create_histogram('gen_ai.client.operation.duration', unit='s'),
    )
    monkeypatch.setattr(
        tracing,
        '_token_histogram',
        meter.create_histogram('gen_ai.client.token.usage', unit='token'),
    )
    yield reader
    provider.shutdown()


@pytest.fixture
def content_tracing_off(monkeypatch):
    monkeypatch.setenv('TRACELOOP_TRACE_CONTENT', 'false')


MESSAGES = [SystemMessage('Be terse.'), HumanMessage('Hi')]
CONTENT_KEYS = (
    'gen_ai.input.messages',
    'gen_ai.output.messages',
    'gen_ai.system_instructions',
)


def _only_span(exporter: InMemorySpanExporter):
    (span,) = exporter.get_finished_spans()
    return span


def _points(reader: InMemoryMetricReader) -> dict[str, list[tuple[dict, int, float]]]:
    """Each histogram's points as ``(attributes, count, sum)``."""
    data = reader.get_metrics_data()
    points: dict[str, list] = {}
    for resource_metrics in data.resource_metrics if data else []:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                points[metric.name] = [
                    (dict(p.attributes), p.count, p.sum)
                    for p in metric.data.data_points
                ]
    return points


def _token_points(reader: InMemoryMetricReader) -> dict[str, tuple[str, str, int]]:
    """Return the token usage histogram as ``{token type: (provider, model, sum)}``."""
    return {
        attributes['gen_ai.token.type']: (
            attributes['gen_ai.provider.name'],
            attributes['gen_ai.response.model'],
            total,
        )
        for attributes, _, total in _points(reader).get('gen_ai.client.token.usage', [])
    }


def _input_messages(span) -> list[dict]:
    return json.loads(span.attributes['gen_ai.input.messages'])


def _output(span) -> dict:
    (output,) = json.loads(span.attributes['gen_ai.output.messages'])
    return output


async def _collect(stream: AsyncIterator[AIMessageChunk]) -> list[AIMessageChunk]:
    return [chunk async for chunk in stream]


# ── Reply spans ──────────────────────────────────────────────────────────────


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


async def test_span_is_a_client_child_of_the_current_span(spans):
    with tracing._tracer.start_as_current_span('llm_complete.task') as parent:
        await _Model(AIMessage('ok'), model='m').ainvoke(MESSAGES)

    span = next(s for s in spans.get_finished_spans() if s.name == '_Model.chat')
    attributes = dict(span.attributes)
    assert span.kind == SpanKind.CLIENT
    assert span.parent.span_id == parent.get_span_context().span_id
    assert span.context.trace_id == parent.get_span_context().trace_id
    assert span.status.status_code == StatusCode.UNSET
    assert attributes['gen_ai.operation.name'] == 'chat'
    assert attributes['traceloop.workflow.name'] == ''
    assert attributes['traceloop.entity.path'] == ''
    assert 'gen_ai.task.status' not in attributes


async def test_usage_and_response_model_reach_the_metrics(spans, metrics):
    model = _Model(
        AIMessage(
            'Hello',
            response_metadata={'model_name': 'm-1'},
            usage_metadata={'input_tokens': 3, 'output_tokens': 2, 'total_tokens': 5},
        ),
        model='m',
    )
    await model.ainvoke(MESSAGES)

    attributes = _only_span(spans).attributes
    # Without an llm_output the span keeps the request model as response model.
    assert attributes['gen_ai.response.model'] == 'm'
    assert attributes['gen_ai.usage.total_tokens'] == 5
    assert 'gen_ai.usage.cache_read.input_tokens' not in attributes
    assert _token_points(metrics) == {
        'input': ('fake', 'm-1', 3),
        'output': ('fake', 'm-1', 2),
    }
    ((duration_attributes, count, seconds),) = _points(metrics)[
        'gen_ai.client.operation.duration'
    ]
    assert duration_attributes == {
        'gen_ai.provider.name': 'fake',
        'gen_ai.response.model': 'm-1',
    }
    assert count == 1
    assert seconds >= 0


async def test_zero_usage_sets_no_usage_attributes_nor_token_metrics(spans, metrics):
    zero = {'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0}
    await _Model(AIMessage('ok', usage_metadata=zero), model='m').ainvoke(MESSAGES)

    attributes = _only_span(spans).attributes
    assert not any(key.startswith('gen_ai.usage.') for key in attributes)
    assert 'gen_ai.client.token.usage' not in _points(metrics)
    assert _points(metrics)['gen_ai.client.operation.duration'][0][0] == {
        'gen_ai.provider.name': 'fake',
        'gen_ai.response.model': 'm',
    }


async def test_only_output_tokens_are_recorded_when_input_is_zero(spans, metrics):
    usage = {'input_tokens': 0, 'output_tokens': 4, 'total_tokens': 4}
    await _Model(AIMessage('ok', usage_metadata=usage), model='m').ainvoke(MESSAGES)

    assert _only_span(spans).attributes['gen_ai.usage.input_tokens'] == 0
    assert _token_points(metrics) == {'output': ('fake', 'm', 4)}


async def test_cache_tokens_from_usage_details(spans):
    usage = {
        'input_tokens': 10,
        'output_tokens': 2,
        'total_tokens': 12,
        'input_token_details': {'cache_read': 6, 'cache_creation': 3},
    }
    await _Model(AIMessage('ok', usage_metadata=usage), model='m').ainvoke(MESSAGES)

    attributes = _only_span(spans).attributes
    assert attributes['gen_ai.usage.cache_read.input_tokens'] == 6
    assert attributes['gen_ai.usage.cache_creation.input_tokens'] == 3
    assert attributes['gen_ai.usage.total_tokens'] == 12


async def test_cache_tokens_alone_are_reported(spans):
    usage = {
        'input_tokens': 0,
        'output_tokens': 0,
        'total_tokens': 0,
        'input_token_details': {'cache_read': 0},
    }
    await _Model(AIMessage('ok', usage_metadata=usage), model='m').ainvoke(MESSAGES)

    attributes = _only_span(spans).attributes
    assert attributes['gen_ai.usage.cache_read.input_tokens'] == 0
    assert attributes['gen_ai.usage.input_tokens'] == 0
    assert 'gen_ai.usage.cache_creation.input_tokens' not in attributes


async def test_llm_output_gives_response_model_id_and_raw_usage(spans, metrics):
    llm_output = {
        'model_name': 'm-2',
        'id': 'resp-1',
        'token_usage': {'prompt_tokens': 4, 'completion_tokens': 6},
    }
    model = _LlmOutputModel(llm_output, AIMessage('ok'), model='m')
    await model.ainvoke(MESSAGES)

    attributes = _only_span(spans).attributes
    assert attributes['gen_ai.request.model'] == 'm'
    assert attributes['gen_ai.response.model'] == 'm-2'
    assert attributes['gen_ai.response.id'] == 'resp-1'
    assert attributes['gen_ai.usage.input_tokens'] == 4
    assert attributes['gen_ai.usage.output_tokens'] == 6
    # Missing from the raw usage: the sum.
    assert attributes['gen_ai.usage.total_tokens'] == 10
    assert _token_points(metrics) == {
        'input': ('fake', 'm-2', 4),
        'output': ('fake', 'm-2', 6),
    }


async def test_usage_metadata_overrides_llm_output_usage_on_the_span(spans, metrics):
    llm_output = {
        'model_name': 'm-2',
        'usage': {'input_tokens': 4, 'output_tokens': 6, 'total_tokens': 99},
    }
    reply = AIMessage(
        'ok',
        usage_metadata={'input_tokens': 5, 'output_tokens': 7, 'total_tokens': 12},
    )
    await _LlmOutputModel(llm_output, reply, model='m').ainvoke(MESSAGES)

    attributes = _only_span(spans).attributes
    assert attributes['gen_ai.usage.input_tokens'] == 5
    assert attributes['gen_ai.usage.total_tokens'] == 12
    # The metrics count the raw usage once, not the usage metadata again.
    assert _token_points(metrics) == {
        'input': ('fake', 'm-2', 4),
        'output': ('fake', 'm-2', 6),
    }


async def test_llm_output_model_is_the_request_model_when_none_was_set(spans, metrics):
    llm_output = {'model_id': 'm-3', 'id': None}
    await _LlmOutputModel(llm_output, AIMessage('ok')).ainvoke(MESSAGES)

    attributes = _only_span(spans).attributes
    assert attributes['gen_ai.request.model'] == 'm-3'
    assert attributes['gen_ai.response.model'] == 'm-3'
    assert 'gen_ai.response.id' not in attributes
    assert _points(metrics)['gen_ai.client.operation.duration'][0][0] == {
        'gen_ai.provider.name': 'fake',
        'gen_ai.response.model': 'm-3',
    }


async def test_llm_output_without_model_falls_back_to_the_reply_metadata(
    spans, metrics
):
    reply = AIMessage('ok', response_metadata={'model_name': 'm-1'})
    await _LlmOutputModel({'id': 'resp-1'}, reply).ainvoke(MESSAGES)

    attributes = _only_span(spans).attributes
    assert attributes['gen_ai.request.model'] == 'unknown'
    assert attributes['gen_ai.response.model'] == 'unknown'
    assert attributes['gen_ai.response.id'] == 'resp-1'
    duration_attributes = _points(metrics)['gen_ai.client.operation.duration'][0][0]
    assert duration_attributes['gen_ai.response.model'] == 'm-1'


@pytest.mark.parametrize(
    ('raw', 'reported'),
    [
        ('stop', 'stop'),
        ('length', 'length'),
        ('tool_calls', 'tool_call'),
        ('function_call', 'tool_call'),
        ('content_filter', 'content_filter'),
        ('end_turn', 'stop'),
        ('stop_sequence', 'stop'),
        ('tool_use', 'tool_call'),
        ('max_tokens', 'length'),
        ('SAFETY', 'SAFETY'),
    ],
)
async def test_finish_reason_mapping(spans, raw, reported):
    reply = AIMessage('ok', response_metadata={'finish_reason': raw})
    await _Model(reply, model='m').ainvoke(MESSAGES)

    span = _only_span(spans)
    assert span.attributes['gen_ai.response.finish_reasons'] == (reported,)
    assert _output(span)['finish_reason'] == reported


async def test_no_finish_reason(spans):
    await _Model(AIMessage('ok'), model='m').ainvoke(MESSAGES)

    span = _only_span(spans)
    assert 'gen_ai.response.finish_reasons' not in span.attributes
    assert _output(span)['finish_reason'] == ''


# ── Request params ───────────────────────────────────────────────────────────


async def test_constructor_params_win_over_call_params(spans):
    model = _Model(AIMessage('ok'), model='m', max_tokens=100)
    await model.ainvoke(MESSAGES, max_tokens=5)

    assert _only_span(spans).attributes['gen_ai.request.max_tokens'] == 100


async def test_call_params_are_reported_when_the_model_has_none(spans, metrics):
    await _Model(AIMessage('ok')).ainvoke(
        MESSAGES, model_id='m-call', max_new_tokens=7, temperature=0.1, stop=['x']
    )

    attributes = _only_span(spans).attributes
    assert attributes['gen_ai.request.max_tokens'] == 7
    assert attributes['gen_ai.request.temperature'] == 0.1
    assert 'gen_ai.request.top_p' not in attributes
    # As with LangChain, constructor params without a model reset the span's
    # request model; the call's model still names the reply in the metrics.
    assert attributes['gen_ai.request.model'] == 'unknown'
    duration_attributes = _points(metrics)['gen_ai.client.operation.duration'][0][0]
    assert duration_attributes['gen_ai.response.model'] == 'm-call'


async def test_unknown_request_model(spans):
    await _Model(AIMessage('ok')).ainvoke(MESSAGES)

    attributes = _only_span(spans).attributes
    assert attributes['gen_ai.request.model'] == 'unknown'
    assert attributes['gen_ai.response.model'] == 'unknown'


async def test_nested_constructor_params(spans):
    class _Nested(_Model):
        def _serialized_kwargs(self) -> dict:
            return {'model_name': 'm-n', 'params': {'top_p': 0.3, 'max_tokens': 9}}

    await _Nested(AIMessage('ok')).ainvoke(MESSAGES, top_p=0.9)

    attributes = _only_span(spans).attributes
    assert attributes['gen_ai.request.model'] == 'm-n'
    assert attributes['gen_ai.request.top_p'] == 0.3
    assert attributes['gen_ai.request.max_tokens'] == 9


async def test_tool_and_function_definitions(spans):
    tools = [
        {
            'type': 'function',
            'function': {
                'name': 'get_weather',
                'description': 'Get the weather.',
                'parameters': {'type': 'object'},
            },
        },
        {'name': 'lookup', 'input_schema': {'type': 'object', 'required': ['q']}},
    ]
    await _Model(AIMessage('ok'), model='m').ainvoke(MESSAGES, tools=tools)
    functions = [{'name': 'legacy', 'description': '', 'parameters': {}}]
    await _Model(AIMessage('ok'), model='m').ainvoke(MESSAGES, functions=functions)

    tools_span, functions_span = spans.get_finished_spans()
    assert json.loads(tools_span.attributes['gen_ai.tool.definitions']) == [
        {
            'name': 'get_weather',
            'description': 'Get the weather.',
            'parameters': {'type': 'object'},
        },
        {'name': 'lookup', 'parameters': {'type': 'object', 'required': ['q']}},
    ]
    assert json.loads(functions_span.attributes['gen_ai.tool.definitions']) == [
        {'name': 'legacy'}
    ]


# ── Input messages ───────────────────────────────────────────────────────────


async def test_system_instructions_are_split_from_input_messages(spans):
    messages = [
        SystemMessage('One.'),
        SystemMessage([{'type': 'text', 'text': 'Two.'}]),
        HumanMessage('Hi'),
    ]
    await _Model(AIMessage('ok'), model='m').ainvoke(messages)

    span = _only_span(spans)
    assert json.loads(span.attributes['gen_ai.system_instructions']) == [
        {'type': 'text', 'content': 'One.'},
        {'type': 'text', 'content': 'Two.'},
    ]
    assert _input_messages(span) == [
        {'role': 'user', 'parts': [{'type': 'text', 'content': 'Hi'}]}
    ]


async def test_no_system_instructions_nor_empty_input(spans):
    await _Model(AIMessage('ok'), model='m').ainvoke([SystemMessage('')])

    attributes = _only_span(spans).attributes
    assert 'gen_ai.system_instructions' not in attributes
    assert 'gen_ai.input.messages' not in attributes


async def test_tool_calls_and_tool_results_in_input_messages(spans):
    messages = [
        HumanMessage('Weather in Paris?'),
        AIMessage(
            '',
            tool_calls=[{'name': 'get_weather', 'args': {'city': 'Paris'}, 'id': 'c1'}],
        ),
        ToolMessage('sunny', tool_call_id='c1'),
        ToolMessage([{'type': 'text', 'text': 'warm'}], tool_call_id='c2'),
        FunctionMessage('{"t": 20}', name='get_weather'),
        HumanMessage(
            'legacy',
            additional_kwargs={
                'tool_calls': [
                    {
                        'id': 'c3',
                        'function': {'name': 'f', 'arguments': '{"a": 1}'},
                    },
                    {'id': 'c4', 'function': {'name': 'g', 'arguments': 'not json'}},
                    {'id': 'c5', 'function': {'name': 'h'}},
                ]
            },
        ),
    ]
    await _Model(AIMessage('ok'), model='m').ainvoke(messages)

    assert _input_messages(_only_span(spans)) == [
        {'role': 'user', 'parts': [{'type': 'text', 'content': 'Weather in Paris?'}]},
        {
            'role': 'assistant',
            'parts': [
                {
                    'type': 'tool_call',
                    'id': 'c1',
                    'name': 'get_weather',
                    'arguments': {'city': 'Paris'},
                }
            ],
        },
        {
            'role': 'tool',
            'parts': [{'type': 'tool_call_response', 'id': 'c1', 'response': 'sunny'}],
        },
        {
            'role': 'tool',
            'parts': [
                {
                    'type': 'tool_call_response',
                    'id': 'c2',
                    'response': '[{"type": "text", "text": "warm"}]',
                }
            ],
        },
        # A function result has no tool call id: its content is reported.
        {'role': 'tool', 'parts': [{'type': 'text', 'content': '{"t": 20}'}]},
        {
            'role': 'user',
            'parts': [
                {'type': 'text', 'content': 'legacy'},
                {'type': 'tool_call', 'id': 'c3', 'name': 'f', 'arguments': {'a': 1}},
                {'type': 'tool_call', 'id': 'c4', 'name': 'g', 'arguments': 'not json'},
                {'type': 'tool_call', 'id': 'c5', 'name': 'h'},
            ],
        },
    ]


async def test_multimodal_content_parts(spans):
    content = [
        'plain',
        '',
        {'type': 'text', 'text': 'look'},
        {'type': 'text', 'text': ''},
        {'type': 'image_url', 'image_url': {'url': 'https://x/cat.png'}},
        {'type': 'image_url', 'image_url': {}},
        # Standard data blocks, converted as LangChain did for tracing.
        {'type': 'image', 'base64': 'AAA', 'mime_type': 'image/png'},
        {'type': 'image', 'url': 'https://x/dog.png'},
        {'type': 'image', 'file_id': 'file-1'},
        {'type': 'file', 'base64': 'BBB', 'mime_type': 'application/pdf'},
        # A provider-native image block.
        {'type': 'image', 'media_type': 'image/jpeg', 'data': 'CCC'},
        {'input_audio': {'data': 'DDD'}},
        {'type': 'custom', 'value': 1},
    ]
    await _Model(AIMessage('ok'), model='m').ainvoke([HumanMessage(content)])

    (message,) = _input_messages(_only_span(spans))
    assert message['role'] == 'user'
    assert message['parts'] == [
        {'type': 'text', 'content': 'plain'},
        {'type': 'text', 'content': 'look'},
        {'type': 'uri', 'modality': 'image', 'uri': 'https://x/cat.png'},
        {'type': 'uri', 'modality': 'image', 'uri': 'data:image/png;base64,AAA'},
        {'type': 'uri', 'modality': 'image', 'uri': 'https://x/dog.png'},
        {'type': 'blob', 'modality': 'image', 'mime_type': '', 'content': ''},
        {
            'type': 'text',
            'content': json.dumps(
                {
                    'type': 'file',
                    'mime_type': 'application/pdf',
                    'data': 'BBB',
                    'source_type': 'base64',
                }
            ),
        },
        {
            'type': 'blob',
            'modality': 'image',
            'mime_type': 'image/jpeg',
            'content': 'CCC',
        },
        {
            'type': 'text',
            'content': json.dumps(
                {'type': 'input_audio', 'input_audio': {'data': 'DDD'}}
            ),
        },
        {'type': 'text', 'content': json.dumps({'type': 'custom', 'value': 1})},
    ]


@dataclasses.dataclass
class _Point:
    x: int


class _Shape(BaseModel):
    sides: int


class _Serializable:
    def to_json(self) -> dict:
        return {'kind': 'serializable'}


class _Opaque:
    def __str__(self) -> str:
        return 'opaque'


class _Unprintable:
    def __str__(self) -> str:
        raise RuntimeError('no')


async def test_unknown_block_values_are_serialized(spans):
    block = {
        'type': 'custom',
        'point': _Point(1),
        'shape': _Shape(sides=3),
        'serializable': _Serializable(),
        'at': datetime.datetime(2026, 1, 2, 3, 4, 5),
        'opaque': _Opaque(),
        'unprintable': _Unprintable(),
    }
    await _Model(AIMessage('ok'), model='m').ainvoke([HumanMessage([block])])

    ((part,),) = [m['parts'] for m in _input_messages(_only_span(spans))]
    assert json.loads(part['content']) == {
        'type': 'custom',
        'point': {'x': 1},
        'shape': {'sides': 3},
        'serializable': {'kind': 'serializable'},
        'at': '2026-01-02T03:04:05',
        'opaque': 'opaque',
        'unprintable': '',
    }


# ── Output message ───────────────────────────────────────────────────────────


async def test_output_tool_calls_and_function_call(spans):
    reply = AIMessage(
        '',
        tool_calls=[{'name': 'get_weather', 'args': {'city': 'Paris'}, 'id': 'c1'}],
        additional_kwargs={
            'function_call': {'name': 'legacy', 'arguments': '{"a": 1}'},
        },
        response_metadata={'finish_reason': 'tool_calls'},
    )
    await _Model(reply, model='m').ainvoke(MESSAGES)

    assert _output(_only_span(spans)) == {
        'role': 'assistant',
        'parts': [
            {'type': 'tool_call', 'id': '', 'name': 'legacy', 'arguments': {'a': 1}},
            {
                'type': 'tool_call',
                'id': 'c1',
                'name': 'get_weather',
                'arguments': {'city': 'Paris'},
            },
        ],
        'finish_reason': 'tool_call',
    }


async def test_output_function_call_with_unparsable_arguments(spans):
    reply = AIMessage(
        '', additional_kwargs={'function_call': {'name': 'f', 'arguments': '{oops'}}
    )
    await _Model(reply, model='m').ainvoke(MESSAGES)

    assert _output(_only_span(spans))['parts'] == [
        {'type': 'tool_call', 'id': '', 'name': 'f', 'arguments': '{oops'}
    ]


async def test_output_text_of_typed_and_legacy_blocks(spans):
    typed = AIMessage(
        [
            {'type': 'text', 'text': 'Hel'},
            {'type': 'reasoning', 'reasoning': '...'},
            {'type': 'text', 'text': 'lo'},
        ]
    )
    legacy = AIMessage(
        [{'text': 'Hel'}, 'lo', {'type': 'text', 'text': '!'}, {'type': 'other'}]
    )
    await _Model(typed, model='m').ainvoke(MESSAGES)
    await _Model(legacy, model='m').ainvoke(MESSAGES)

    typed_span, legacy_span = spans.get_finished_spans()
    assert _output(typed_span)['parts'] == [{'type': 'text', 'content': 'Hello'}]
    assert _output(legacy_span)['parts'] == [{'type': 'text', 'content': 'Hello!'}]


async def test_output_without_text_reports_its_content_parts(spans):
    reply = AIMessage([{'type': 'image_url', 'image_url': {'url': 'https://x/i.png'}}])
    await _Model(reply, model='m').ainvoke(MESSAGES)

    assert _output(_only_span(spans))['parts'] == [
        {'type': 'uri', 'modality': 'image', 'uri': 'https://x/i.png'}
    ]


# ── Content tracing switch ───────────────────────────────────────────────────


async def test_content_tracing_switch(spans, content_tracing_off):
    reply = AIMessage('secret', response_metadata={'finish_reason': 'stop'})
    await _Model(reply, model='m').ainvoke(MESSAGES)

    attributes = _only_span(spans).attributes
    assert not set(CONTENT_KEYS) & set(attributes)
    assert attributes['gen_ai.response.finish_reasons'] == ('stop',)
    assert attributes['gen_ai.request.model'] == 'm'


async def test_content_tracing_switch_for_streams(spans, content_tracing_off):
    chunks = [AIMessageChunk('sec'), AIMessageChunk('ret')]
    await _collect(_Model(chunks=chunks, model='m').astream(MESSAGES))

    assert not set(CONTENT_KEYS) & set(_only_span(spans).attributes)


async def test_content_tracing_switch_hides_function_definitions(
    spans, content_tracing_off
):
    await _Model(AIMessage('ok'), model='m').ainvoke(
        MESSAGES, functions=[{'name': 'f'}]
    )

    assert 'gen_ai.tool.definitions' not in _only_span(spans).attributes


async def test_content_tracing_context_override(spans, content_tracing_off):
    token = context_api.attach(
        context_api.set_value('override_enable_content_tracing', True)
    )
    try:
        await _Model(AIMessage('shown'), model='m').ainvoke(MESSAGES)
    finally:
        context_api.detach(token)

    span = _only_span(spans)
    assert set(CONTENT_KEYS) <= set(span.attributes)
    assert _output(span)['parts'] == [{'type': 'text', 'content': 'shown'}]


# ── Streams ──────────────────────────────────────────────────────────────────


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


async def test_stream_usage_is_summed_across_chunks(spans, metrics):
    chunks = [
        AIMessageChunk(
            'a',
            usage_metadata={
                'input_tokens': 10,
                'output_tokens': 1,
                'total_tokens': 11,
                'input_token_details': {'cache_read': 4},
            },
        ),
        AIMessageChunk('b'),
        AIMessageChunk(
            'c',
            usage_metadata={
                'input_tokens': 0,
                'output_tokens': 5,
                'total_tokens': 5,
                'input_token_details': {'cache_read': 0, 'cache_creation': 2},
            },
        ),
    ]
    await _collect(_Model(chunks=chunks, model='m').astream(MESSAGES))

    attributes = _only_span(spans).attributes
    assert attributes['gen_ai.usage.input_tokens'] == 10
    assert attributes['gen_ai.usage.output_tokens'] == 6
    assert attributes['gen_ai.usage.total_tokens'] == 16
    assert attributes['gen_ai.usage.cache_read.input_tokens'] == 4
    assert attributes['gen_ai.usage.cache_creation.input_tokens'] == 2
    # A stream has no llm_output: the metrics come from the merged usage.
    assert _token_points(metrics) == {
        'input': ('fake', 'm', 10),
        'output': ('fake', 'm', 6),
    }


async def test_stream_usage_from_a_later_chunk_only(spans):
    chunks = [
        AIMessageChunk('a'),
        AIMessageChunk(
            'b',
            usage_metadata={'input_tokens': 2, 'output_tokens': 3, 'total_tokens': 5},
        ),
    ]
    await _collect(_Model(chunks=chunks, model='m').astream(MESSAGES))

    attributes = _only_span(spans).attributes
    assert attributes['gen_ai.usage.input_tokens'] == 2
    assert attributes['gen_ai.usage.output_tokens'] == 3


async def test_single_chunk_stream(spans, metrics):
    chunk = AIMessageChunk(
        'whole',
        response_metadata={'finish_reason': 'length', 'model_name': 'm-1'},
        usage_metadata={'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2},
    )
    received = await _collect(_Model(chunks=[chunk], model='m').astream(MESSAGES))

    assert [c.content for c in received] == ['whole', '']
    span = _only_span(spans)
    assert span.attributes['gen_ai.response.finish_reasons'] == ('length',)
    assert _output(span) == {
        'role': 'unknown',
        'parts': [{'type': 'text', 'content': 'whole'}],
        'finish_reason': 'length',
    }
    assert _token_points(metrics)['input'] == ('fake', 'm-1', 1)


async def test_stream_generation_infos_are_merged(spans):
    class _InfoModel(_Model):
        def _generation_info(self, message: AIMessage) -> dict | None:
            return message.additional_kwargs.get('info')

    chunks = [
        AIMessageChunk('a', additional_kwargs={'info': {'logprobs': None}}),
        AIMessageChunk('b'),
        AIMessageChunk('c', additional_kwargs={'info': {'finish_reason': 'stop'}}),
    ]
    await _collect(_InfoModel(chunks=chunks, model='m').astream(MESSAGES))

    span = _only_span(spans)
    assert span.attributes['gen_ai.response.finish_reasons'] == ('stop',)
    assert _output(span)['finish_reason'] == 'stop'


async def test_stream_content_blocks_are_merged(spans):
    chunks = [
        AIMessageChunk('Intro '),
        AIMessageChunk([{'type': 'text', 'text': 'one', 'index': 0}]),
        AIMessageChunk([{'type': 'text', 'text': ' two', 'index': 0}]),
        AIMessageChunk([{'type': 'text', 'text': 'tail'}]),
        AIMessageChunk(''),
        AIMessageChunk(
            [{'type': 'non_standard', 'index': 1, 'value': {'type': 'x', 'a': 1}}]
        ),
        AIMessageChunk(
            [{'type': 'non_standard', 'index': 1, 'value': {'type': 'x', 'b': 2}}]
        ),
        AIMessageChunk(
            [{'type': 'non_standard', 'index': 0, 'value': {'type': 'y', 'c': 3}}]
        ),
    ]
    await _collect(_Model(chunks=chunks, model='m').astream(MESSAGES))

    assert _output(_only_span(spans))['parts'] == [
        {'type': 'text', 'content': 'Intro one twotail'}
    ]


async def test_stream_string_after_blocks_is_appended(spans):
    chunks = [
        AIMessageChunk([{'type': 'image_url', 'image_url': {'url': 'u'}}]),
        AIMessageChunk('more'),
        AIMessageChunk(' text'),
    ]
    await _collect(_Model(chunks=chunks, model='m').astream(MESSAGES))

    assert _output(_only_span(spans))['parts'] == [
        {'type': 'text', 'content': 'more text'}
    ]


async def test_stream_response_metadata_is_merged(spans, metrics):
    chunks = [
        AIMessageChunk(
            'a',
            response_metadata={
                'id': 'r1',
                'model_name': 'm-1',
                'model_provider': 'p',
                'index': 'lc_0',
                'created': 1,
                'count': 1,
                'flag': True,
                'nested': {'n': 1},
                'items': ['x'],
                'empty': None,
            },
        ),
        AIMessageChunk(
            'b',
            response_metadata={
                'id': 'r1',
                'model_name': '-x',
                'model_provider': 'p',
                'index': 'lc_1',
                'created': 2,
                'count': 2,
                'flag': True,
                'nested': {'n': 1},
                'items': [{'no': 'index'}],
                'empty': 'filled',
                'skipped': None,
            },
        ),
    ]
    await _collect(_Model(chunks=chunks, model='m').astream(MESSAGES))

    # The merged metadata's model name: concatenated, as LangChain did.
    duration_attributes = _points(metrics)['gen_ai.client.operation.duration'][0][0]
    assert duration_attributes['gen_ai.response.model'] == 'm-1-x'
    assert _only_span(spans).attributes['gen_ai.response.model'] == 'm'


async def test_stream_with_unmergeable_metadata_still_streams(spans):
    chunks = [
        AIMessageChunk('a', response_metadata={'score': 0.1}),
        AIMessageChunk('b', response_metadata={'score': 0.2}),
    ]
    received = await _collect(_Model(chunks=chunks, model='m').astream(MESSAGES))

    # Tracing never fails the call: the reply is streamed in full.
    assert [c.content for c in received] == ['a', 'b', '']


async def test_stream_with_mismatched_metadata_types_still_streams(spans):
    chunks = [
        AIMessageChunk('a', response_metadata={'model_name': 'm-1'}),
        AIMessageChunk('b', response_metadata={'model_name': 2}),
    ]
    received = await _collect(_Model(chunks=chunks, model='m').astream(MESSAGES))

    assert [c.content for c in received] == ['a', 'b', '']


async def test_stream_with_unaddable_usage_still_streams(spans):
    usage = {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}
    chunks = [
        AIMessageChunk('a', usage_metadata={**usage, 'service_tier': 'standard'}),
        AIMessageChunk('b', usage_metadata={**usage, 'service_tier': 'flex'}),
    ]
    received = await _collect(_Model(chunks=chunks, model='m').astream(MESSAGES))

    assert [c.content for c in received] == ['a', 'b', '']


# ── Failures ─────────────────────────────────────────────────────────────────


def _assert_error_span(span, error_type: str, message: str) -> None:
    assert span.kind == SpanKind.CLIENT
    assert span.status.status_code == StatusCode.ERROR
    assert span.status.description == message
    assert span.attributes['error.type'] == error_type
    assert span.attributes['gen_ai.task.status'] == 'failure'
    assert 'gen_ai.output.messages' not in span.attributes
    (event,) = span.events
    assert event.name == 'exception'
    assert event.attributes['exception.type'] == error_type


async def test_failed_call_is_an_error_span(spans, metrics):
    model = _Model(error=RuntimeError('boom'), model='m')
    with pytest.raises(RuntimeError):
        await model.ainvoke(MESSAGES)

    span = _only_span(spans)
    _assert_error_span(span, 'RuntimeError', 'boom')
    assert span.attributes['gen_ai.input.messages']
    # Failed calls record no metrics.
    assert _points(metrics) == {}


async def test_failed_stream_is_an_error_span(spans, metrics):
    chunks = [AIMessageChunk('partial')]
    model = _Model(chunks=chunks, error=ConnectionError('dropped'), model='m')
    stream = model.astream(MESSAGES)
    first = await anext(stream)
    with pytest.raises(ConnectionError):
        await anext(stream)

    assert first.content == 'partial'
    _assert_error_span(_only_span(spans), 'ConnectionError', 'dropped')
    assert _points(metrics) == {}


async def test_stream_stopped_by_the_consumer_is_an_error_span(spans):
    chunks = [AIMessageChunk('a'), AIMessageChunk('b')]
    stream = _Model(chunks=chunks, model='m').astream(MESSAGES)
    first = await anext(stream)
    await stream.aclose()

    assert first.content == 'a'
    _assert_error_span(_only_span(spans), 'GeneratorExit', '')


async def test_empty_stream_is_an_error_span(spans):
    with pytest.raises(ValueError, match='No generation chunks'):
        [chunk async for chunk in _Model(model='m').astream(MESSAGES)]

    _assert_error_span(
        _only_span(spans), 'ValueError', 'No generation chunks were returned'
    )


async def test_openai_errors_keep_langchain_names_on_the_span(spans):
    chat_model = init_chat_model(
        'openai:gpt-4o-mini',
        api_key='sk',
        max_retries=0,
        http_async_client=HttpxAiohttpClient(),
    )
    with (
        ProviderRecorder([canned.error(400, 'bad request')]),
        pytest.raises(openai.BadRequestError),
    ):
        await chat_model.ainvoke(MESSAGES)
    with (
        ProviderRecorder([canned.error(400, 'bad request')]),
        pytest.raises(openai.BadRequestError),
    ):
        await _collect(chat_model.astream(MESSAGES))

    invoke_span, stream_span = spans.get_finished_spans()
    for span in (invoke_span, stream_span):
        assert span.status.status_code == StatusCode.ERROR
        assert span.attributes['error.type'] == 'OpenAIInvalidRequestError'
        assert span.attributes['gen_ai.provider.name'] == 'openai'


def test_openai_errors_keep_langchain_names():
    request = httpx2.Request('POST', 'https://x')
    response = httpx2.Response(400, request=request)
    error = openai.BadRequestError('bad', response=response, body=None)

    assert _langchain_error_type(error) == 'OpenAIInvalidRequestError'
    assert _langchain_error_type(ValueError()) == 'ValueError'


# ── Tracing off or broken ────────────────────────────────────────────────────


@pytest.fixture
def unsampled(monkeypatch) -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = TracerProvider(sampler=ALWAYS_OFF)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(tracing, '_tracer', provider.get_tracer('test'))
    return exporter


@pytest.mark.parametrize('tracer', ['unsampled', 'no-op'])
async def test_nothing_is_recorded_when_the_span_is_not_recording(
    unsampled, metrics, monkeypatch, tracer
):
    if tracer == 'no-op':
        monkeypatch.setattr(tracing, '_tracer', trace.NoOpTracer())
    reply = AIMessage(
        'ok', usage_metadata={'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}
    )
    model = _Model(reply, chunks=[AIMessageChunk('a'), AIMessageChunk('b')], model='m')

    assert (await model.ainvoke(MESSAGES)).content == 'ok'
    received = await _collect(model.astream(MESSAGES))

    assert [c.content for c in received] == ['a', 'b', '']
    assert unsampled.get_finished_spans() == ()
    assert _points(metrics) == {}


async def test_a_broken_tracing_hook_does_not_fail_the_call(spans):
    class _Broken(_Model):
        def _invocation_params(self, stop=None, **kwargs: Any) -> dict:
            raise RuntimeError('hook')

    model = _Broken(AIMessage('ok'), chunks=[AIMessageChunk('a')], model='m')

    assert (await model.ainvoke(MESSAGES)).content == 'ok'
    assert [c.content for c in await _collect(model.astream(MESSAGES))] == ['a', '']
    with pytest.raises(KeyError):
        await _Broken(error=KeyError('k'), model='m').ainvoke(MESSAGES)


# ── Providers ────────────────────────────────────────────────────────────────

AZURE = {
    'api_key': 'sk',
    'api_version': '2024-10-21',
    'azure_endpoint': 'https://res.openai.azure.com',
}
USAGE = {
    'gen_ai.usage.input_tokens': 21,
    'gen_ai.usage.output_tokens': 7,
    'gen_ai.usage.total_tokens': 28,
}


def _openai(**kwargs):
    return init_chat_model(
        'openai:gpt-4o-mini',
        api_key='sk',
        http_async_client=HttpxAiohttpClient(),
        **kwargs,
    )


PROVIDER_REPLIES = {
    'openai': (
        _openai,
        canned.openai_completion,
        {
            'name': 'ChatOpenAI.chat',
            'gen_ai.provider.name': 'openai',
            'gen_ai.request.model': 'gpt-4o-mini',
            'gen_ai.response.model': 'gpt-4o-mini-2024-07-18',
            'gen_ai.response.id': 'chatcmpl-provider-1',
            'gen_ai.response.finish_reasons': ('stop',),
            'gen_ai.usage.cache_read.input_tokens': 0,
            **USAGE,
        },
    ),
    'openai-responses': (
        lambda: _openai(use_responses_api=True),
        canned.openai_response,
        {
            'name': 'ChatOpenAI.chat',
            'gen_ai.provider.name': 'openai',
            'gen_ai.request.model': 'gpt-4o-mini',
            # Responses API replies had no llm_output nor finish reason.
            'gen_ai.response.model': 'gpt-4o-mini',
            'gen_ai.response.id': None,
            'gen_ai.response.finish_reasons': None,
            'gen_ai.usage.cache_read.input_tokens': 4,
            **USAGE,
        },
    ),
    'azure': (
        lambda: init_chat_model(
            'azure_openai:gpt-4o-mini', http_async_client=HttpxAiohttpClient(), **AZURE
        ),
        canned.openai_completion,
        {
            'name': 'AzureChatOpenAI.chat',
            'gen_ai.provider.name': 'azure.ai.openai',
            'gen_ai.request.model': 'gpt-4o-mini',
            'gen_ai.response.model': 'gpt-4o-mini-2024-07-18',
            'gen_ai.response.finish_reasons': ('stop',),
            **USAGE,
        },
    ),
    'deepseek': (
        lambda: init_chat_model(
            'deepseek:deepseek-chat',
            api_key='sk',
            http_async_client=HttpxAiohttpClient(),
        ),
        lambda: canned.openai_completion(model='deepseek-chat'),
        {
            'name': 'GatewayDeepSeekChatModel.chat',
            'gen_ai.provider.name': 'deepseek',
            'gen_ai.request.model': 'deepseek-chat',
            'gen_ai.response.model': 'deepseek-chat',
            'gen_ai.response.id': 'chatcmpl-provider-1',
            'gen_ai.response.finish_reasons': ('stop',),
            **USAGE,
        },
    ),
    'anthropic': (
        lambda: init_chat_model('anthropic:claude-sonnet-4-5', api_key='sk'),
        lambda: canned.anthropic_message(input_tokens=330, cache_read=1000),
        {
            'name': 'ChatAnthropic.chat',
            'gen_ai.provider.name': 'anthropic',
            'gen_ai.request.model': 'claude-sonnet-4-5',
            'gen_ai.request.max_tokens': 64000,
            'gen_ai.response.model': 'claude-sonnet-4-5-20250929',
            'gen_ai.response.id': 'msg_provider_1',
            'gen_ai.usage.input_tokens': 1330,
            'gen_ai.usage.output_tokens': 7,
            'gen_ai.usage.total_tokens': 1337,
            'gen_ai.usage.cache_read.input_tokens': 1000,
            'gen_ai.usage.cache_creation.input_tokens': 0,
        },
    ),
    'gemini': (
        lambda: init_chat_model('google-genai:gemini-2.5-flash', api_key='sk'),
        canned.gemini_response,
        {
            'name': 'ChatGoogleGenerativeAI.chat',
            'gen_ai.provider.name': 'gcp.gen_ai',
            'gen_ai.request.model': 'gemini-2.5-flash',
            'gen_ai.request.temperature': 0.7,
            'gen_ai.response.model': 'gemini-2.5-flash',
            # Not one of the mapped finish reasons: reported as is.
            'gen_ai.response.finish_reasons': ('STOP',),
            'gen_ai.usage.cache_read.input_tokens': 0,
            **USAGE,
        },
    ),
    'mistral': (
        lambda: init_chat_model('mistralai:mistral-small-latest', api_key='sk'),
        canned.mistral_completion,
        {
            'name': 'ChatMistralAI.chat',
            'gen_ai.provider.name': 'mistral_ai',
            'gen_ai.request.model': 'mistral-small-latest',
            'gen_ai.request.temperature': 0.7,
            'gen_ai.request.top_p': 1,
            'gen_ai.response.model': 'mistral-small-latest',
            'gen_ai.response.finish_reasons': ('stop',),
            **USAGE,
        },
    ),
}


def _span_view(span, expected: dict) -> dict:
    return {
        key: span.name if key == 'name' else span.attributes.get(key)
        for key in expected
    }


@pytest.mark.parametrize('provider', list(PROVIDER_REPLIES))
async def test_provider_reply_span(spans, provider):
    build, response, expected = PROVIDER_REPLIES[provider]
    with ProviderRecorder([response()]):
        await build().ainvoke(
            [SystemMessage('You are terse.'), HumanMessage('Say hello.')]
        )

    span = _only_span(spans)
    assert _span_view(span, expected) == expected
    assert span.kind == SpanKind.CLIENT
    assert json.loads(span.attributes['gen_ai.system_instructions']) == [
        {'type': 'text', 'content': 'You are terse.'}
    ]
    assert _input_messages(span) == [
        {'role': 'user', 'parts': [{'type': 'text', 'content': 'Say hello.'}]}
    ]
    output = _output(span)
    assert output['role'] == 'assistant'
    assert output['parts'] == [{'type': 'text', 'content': 'Hello from the model'}]


PROVIDER_STREAMS = {
    'openai': (
        _openai,
        canned.openai_stream,
        {
            'name': 'ChatOpenAI.chat',
            'gen_ai.response.model': 'gpt-4o-mini',
            'gen_ai.response.finish_reasons': ('stop',),
            'gen_ai.usage.cache_read.input_tokens': 0,
            **USAGE,
        },
    ),
    'anthropic': (
        lambda: init_chat_model('anthropic:claude-sonnet-4-5', api_key='sk'),
        canned.anthropic_stream,
        {
            'name': 'ChatAnthropic.chat',
            'gen_ai.response.model': 'claude-sonnet-4-5',
            'gen_ai.response.finish_reasons': None,
            'gen_ai.usage.output_tokens': 7,
        },
    ),
    'gemini': (
        lambda: init_chat_model('google-genai:gemini-2.5-flash', api_key='sk'),
        canned.gemini_stream,
        {
            'name': 'ChatGoogleGenerativeAI.chat',
            'gen_ai.response.model': 'gemini-2.5-flash',
            'gen_ai.response.finish_reasons': ('STOP',),
        },
    ),
    'mistral': (
        lambda: init_chat_model('mistralai:mistral-small-latest', api_key='sk'),
        canned.mistral_stream,
        {
            'name': 'ChatMistralAI.chat',
            'gen_ai.response.model': 'mistral-small-latest',
            # Mistral stream chunks carried no generation info.
            'gen_ai.response.finish_reasons': None,
            **USAGE,
        },
    ),
}


@pytest.mark.parametrize('provider', list(PROVIDER_STREAMS))
async def test_provider_stream_span(spans, metrics, provider):
    build, response, expected = PROVIDER_STREAMS[provider]
    with ProviderRecorder([response()]):
        await _collect(build().astream([HumanMessage('Say hello.')]))

    span = _only_span(spans)
    assert _span_view(span, expected) == expected
    output = _output(span)
    assert output['role'] == 'unknown'
    assert output['parts'] == [{'type': 'text', 'content': 'Hello from the model'}]
    assert _points(metrics)['gen_ai.client.operation.duration'][0][1] == 1


async def test_openai_tool_call_reply(spans):
    tool = {
        'type': 'function',
        'function': {
            'name': 'get_weather',
            'description': 'Get the weather for a city.',
            'parameters': {'type': 'object', 'properties': {}},
        },
    }
    response = canned.openai_completion(
        None, tool_calls=[canned.WEATHER_TOOL_CALL], finish_reason='tool_calls'
    )
    with ProviderRecorder([response]):
        await _openai().bind_tools([tool]).ainvoke([HumanMessage('Weather?')])

    span = _only_span(spans)
    assert json.loads(span.attributes['gen_ai.tool.definitions']) == [tool['function']]
    assert span.attributes['gen_ai.response.finish_reasons'] == ('tool_call',)
    assert _output(span)['parts'] == [
        {
            'type': 'tool_call',
            'id': 'call_weather_1',
            'name': 'get_weather',
            'arguments': {'city': 'Paris', 'unit': 'c'},
        }
    ]


async def test_mock_model_spans(spans, metrics):
    model = MockGatewayChatModel('echo', 0, 'mocked answer')
    await model.ainvoke([HumanMessage('Say hello.')])
    await _collect(model.astream([HumanMessage('Say hello.')]))

    invoke_span, stream_span = spans.get_finished_spans()
    for span in (invoke_span, stream_span):
        assert span.name == 'MockGatewayChatModel.chat'
        assert span.attributes['gen_ai.provider.name'] == 'mock'
        assert span.attributes['gen_ai.request.model'] == 'echo'
        assert span.attributes['gen_ai.response.model'] == 'echo'
        assert _output(span)['finish_reason'] == ''
    # The mock reports zero usage on replies, the word count on streams.
    assert not any(k.startswith('gen_ai.usage.') for k in invoke_span.attributes)
    assert stream_span.attributes['gen_ai.usage.output_tokens'] == 2
    assert _token_points(metrics) == {'output': ('mock', 'echo', 2)}


# ── Native Responses API ─────────────────────────────────────────────────────


class _ResponsesModel(_Model):
    """A model serving the Responses API with canned events or a response."""

    def __init__(self, response=None, events=(), error=None, **settings: Any):
        super().__init__(error=error, **settings)
        self.response = response
        self.events = list(events)

    async def _ainvoke_native_responses(self, body: dict) -> dict:
        if self.error:
            raise self.error
        return self.response

    async def _astream_native_responses(
        self, body: dict
    ) -> AsyncIterator[tuple[str, str]]:
        for event in self.events:
            yield event['type'], json.dumps(event)
        if self.error:
            raise self.error


RESPONSES_BODY = {
    'instructions': 'Be terse.',
    'input': [
        {'role': 'developer', 'content': 'Use tools.'},
        {'role': 'user', 'content': [{'type': 'input_text', 'text': 'Weather?'}]},
        {
            'type': 'reasoning',
            'id': 'rs_1',
            'summary': [{'type': 'summary_text', 'text': 'Need a tool.'}],
            'encrypted_content': 'gAAAA',
        },
        {
            'type': 'function_call',
            'call_id': 'call_1',
            'name': 'weather',
            'arguments': '{"city":"Paris"}',
        },
        {'type': 'function_call_output', 'call_id': 'call_1', 'output': 'rainy'},
    ],
    'tools': [
        {
            'type': 'function',
            'name': 'weather',
            'description': 'The weather',
            'parameters': {'type': 'object'},
        },
        {'type': 'web_search'},
    ],
    'temperature': 0.5,
}

RESPONSE = {
    'id': 'resp_1',
    'model': 'gpt-6-luna-2026',
    'status': 'completed',
    'output': [
        {'type': 'reasoning', 'id': 'rs_2', 'summary': [], 'encrypted_content': 'x'},
        {'type': 'web_search_call', 'id': 'ws_1', 'status': 'completed'},
        {
            'type': 'message',
            'role': 'assistant',
            'content': [{'type': 'output_text', 'text': 'Rainy.'}],
        },
        {
            'type': 'function_call',
            'call_id': 'call_2',
            'name': 'weather',
            'arguments': '{"city":"Rome"}',
        },
    ],
    'usage': {
        'input_tokens': 100,
        'input_tokens_details': {'cached_tokens': 40, 'cache_write_tokens': 0},
        'output_tokens': 7,
        'output_tokens_details': {'reasoning_tokens': 3},
        'total_tokens': 107,
    },
}


def _stream_events(response: dict) -> list[dict]:
    final = {
        'completed': 'response.completed',
        'incomplete': 'response.incomplete',
        'failed': 'response.failed',
    }[response['status']]
    return [
        {'type': 'response.created', 'response': {**response, 'status': 'in_progress'}},
        {'type': 'response.output_text.delta', 'delta': 'Rainy.'},
        {'type': final, 'response': response},
    ]


async def test_responses_reply_span(spans, metrics):
    model = _ResponsesModel(RESPONSE, model_name='gpt-6-luna', temperature=0.2)

    assert await model.ainvoke_native_responses(RESPONSES_BODY) == RESPONSE

    span = _only_span(spans)
    assert span.name == '_ResponsesModel.chat'
    assert span.kind == SpanKind.CLIENT
    attributes = dict(span.attributes)
    assert attributes['gen_ai.provider.name'] == 'fake'
    assert attributes['gen_ai.operation.name'] == 'chat'
    assert attributes['gen_ai.request.model'] == 'gpt-6-luna'
    assert attributes['gen_ai.response.model'] == 'gpt-6-luna-2026'
    assert attributes['gen_ai.response.id'] == 'resp_1'
    # The client's value wins over the model's setting.
    assert attributes['gen_ai.request.temperature'] == 0.5
    assert attributes['gen_ai.usage.input_tokens'] == 100
    assert attributes['gen_ai.usage.output_tokens'] == 7
    assert attributes['gen_ai.usage.total_tokens'] == 107
    assert attributes['gen_ai.usage.cache_read.input_tokens'] == 40
    assert attributes['gen_ai.usage.reasoning.output_tokens'] == 3
    assert 'gen_ai.usage.cache_creation.input_tokens' not in attributes
    assert attributes['gen_ai.response.finish_reasons'] == ('tool_call',)
    assert json.loads(attributes['gen_ai.tool.definitions']) == [
        {
            'name': 'weather',
            'description': 'The weather',
            'parameters': {'type': 'object'},
        },
        {'name': 'web_search'},
    ]
    assert json.loads(attributes['gen_ai.system_instructions']) == [
        {'type': 'text', 'content': 'Be terse.'},
        {'type': 'text', 'content': 'Use tools.'},
    ]
    assert _input_messages(span) == [
        {'role': 'user', 'parts': [{'type': 'text', 'content': 'Weather?'}]},
        {
            'role': 'assistant',
            'parts': [
                {'type': 'reasoning', 'content': 'Need a tool.'},
                {
                    'type': 'tool_call',
                    'id': 'call_1',
                    'name': 'weather',
                    'arguments': {'city': 'Paris'},
                },
            ],
        },
        {
            'role': 'tool',
            'parts': [
                {'type': 'tool_call_response', 'id': 'call_1', 'response': 'rainy'}
            ],
        },
    ]
    assert _output(span) == {
        'role': 'assistant',
        'parts': [
            {'type': 'web_search_call', 'id': 'ws_1', 'status': 'completed'},
            {'type': 'text', 'content': 'Rainy.'},
            {
                'type': 'tool_call',
                'id': 'call_2',
                'name': 'weather',
                'arguments': {'city': 'Rome'},
            },
        ],
        'finish_reason': 'tool_call',
    }
    assert _token_points(metrics) == {
        'input': ('fake', 'gpt-6-luna-2026', 100),
        'output': ('fake', 'gpt-6-luna-2026', 7),
    }
    (duration,) = _points(metrics)['gen_ai.client.operation.duration']
    assert duration[0] == {
        'gen_ai.provider.name': 'fake',
        'gen_ai.response.model': 'gpt-6-luna-2026',
    }


async def test_responses_settings_fill_what_the_client_left_out(spans):
    response = {'id': 'r', 'status': 'completed', 'output': []}
    model = _ResponsesModel(response, model_name='m', max_tokens=50, top_p=0.9)

    await model.ainvoke_native_responses({'input': 'Hi', 'max_output_tokens': 10})

    attributes = _only_span(spans).attributes
    assert attributes['gen_ai.request.max_tokens'] == 10
    assert attributes['gen_ai.request.top_p'] == 0.9
    # No model in the response: the request model stands.
    assert attributes['gen_ai.response.model'] == 'm'
    assert attributes['gen_ai.response.finish_reasons'] == ('stop',)
    assert _input_messages(_only_span(spans)) == [
        {'role': 'user', 'parts': [{'type': 'text', 'content': 'Hi'}]}
    ]


async def test_responses_image_and_other_input_blocks(spans):
    response = {'id': 'r', 'status': 'completed', 'output': []}
    content = [
        {'type': 'input_text', 'text': 'What is it?'},
        {'type': 'input_image', 'image_url': 'https://example.com/cat.png'},
        {'type': 'input_file', 'file_id': 'file_1'},
    ]

    await _ResponsesModel(response, model_name='m').ainvoke_native_responses(
        {'input': [{'role': 'user', 'content': content}]}
    )

    assert _input_messages(_only_span(spans)) == [
        {
            'role': 'user',
            'parts': [
                {'type': 'text', 'content': 'What is it?'},
                {
                    'type': 'uri',
                    'modality': 'image',
                    'uri': 'https://example.com/cat.png',
                },
                # Any other block is reported as its JSON.
                {
                    'type': 'text',
                    'content': '{"type": "input_file", "file_id": "file_1"}',
                },
            ],
        }
    ]


async def test_responses_stream_span_reads_the_final_response(spans, metrics):
    model = _ResponsesModel(events=_stream_events(RESPONSE), model_name='gpt-6-luna')

    events = await _collect(model.astream_native_responses(RESPONSES_BODY))

    assert len(events) == 3
    span = _only_span(spans)
    assert span.status.status_code == StatusCode.UNSET
    assert span.attributes['gen_ai.response.id'] == 'resp_1'
    assert span.attributes['gen_ai.usage.output_tokens'] == 7
    assert _output(span)['finish_reason'] == 'tool_call'
    assert _token_points(metrics)['output'] == ('fake', 'gpt-6-luna-2026', 7)


async def test_responses_incomplete_reason_is_the_finish_reason(spans):
    response = {
        'id': 'r',
        'status': 'incomplete',
        'incomplete_details': {'reason': 'max_output_tokens'},
        'output': [],
    }
    model = _ResponsesModel(events=_stream_events(response), model_name='m')

    await _collect(model.astream_native_responses({'input': 'Hi'}))

    assert _only_span(spans).attributes['gen_ai.response.finish_reasons'] == ('length',)


async def test_responses_failed_response_fails_the_span(spans):
    response = {
        'id': 'r',
        'status': 'failed',
        'error': {'code': 'server_error', 'message': 'Upstream broke'},
        'output': [],
    }
    model = _ResponsesModel(events=_stream_events(response), model_name='m')

    await _collect(model.astream_native_responses({'input': 'Hi'}))

    span = _only_span(spans)
    assert span.status.status_code == StatusCode.ERROR
    assert span.status.description == 'Upstream broke'
    assert span.attributes['error.type'] == 'server_error'


async def test_responses_error_event_fails_the_span(spans):
    error = {'type': 'error', 'code': 'rate_limit_exceeded', 'message': 'Slow down'}
    model = _ResponsesModel(events=[error], model_name='m')

    await _collect(model.astream_native_responses({'input': 'Hi'}))

    span = _only_span(spans)
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes['error.type'] == 'rate_limit_exceeded'


async def test_responses_call_error_fails_the_span(spans):
    model = _ResponsesModel(error=ValueError('boom'), model_name='m')

    with pytest.raises(ValueError, match='boom'):
        await model.ainvoke_native_responses({'input': 'Hi'})

    span = _only_span(spans)
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes['error.type'] == 'ValueError'
    assert span.attributes['gen_ai.task.status'] == 'failure'


async def test_responses_stream_stopped_early_fails_the_span(spans):
    model = _ResponsesModel(events=_stream_events(RESPONSE), model_name='m')

    stream = model.astream_native_responses({'input': 'Hi'})
    await anext(stream)
    await stream.aclose()

    span = _only_span(spans)
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes['error.type'] == 'GeneratorExit'


async def test_responses_content_tracing_switch(spans, content_tracing_off):
    model = _ResponsesModel(RESPONSE, model_name='m')

    await model.ainvoke_native_responses(RESPONSES_BODY)

    attributes = _only_span(spans).attributes
    assert not any(key in attributes for key in CONTENT_KEYS)
    assert 'gen_ai.tool.definitions' in attributes


# ── Stream and server attributes ─────────────────────────────────────────────


class _ServerModel(_ResponsesModel):
    def __init__(self, url, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.url = url

    def _server_url(self) -> str | None:
        return self.url


@pytest.mark.parametrize(
    ('url', 'address', 'port'),
    [
        ('https://api.openai.com/v1/', 'api.openai.com', 443),
        ('http://vllm:8000/v1', 'vllm', 8000),
        ('http://ollama/v1', 'ollama', 80),
    ],
)
async def test_server_of_the_call(spans, url, address, port):
    model = _ServerModel(url, reply=AIMessage('Hi'), model='m')

    await model.ainvoke(MESSAGES)

    attributes = _only_span(spans).attributes
    assert attributes['server.address'] == address
    assert attributes['server.port'] == port


async def test_no_server_when_the_model_has_none(spans):
    await _Model(reply=AIMessage('Hi'), model='m').ainvoke(MESSAGES)

    attributes = _only_span(spans).attributes
    assert 'server.address' not in attributes
    assert 'server.port' not in attributes


async def test_a_failing_server_hook_does_not_stop_the_trace(spans):
    class _Broken(_Model):
        def _server_url(self) -> str | None:
            raise RuntimeError('no client')

    await _Broken(reply=AIMessage('Hi'), model='m').ainvoke(MESSAGES)

    assert 'server.address' not in _only_span(spans).attributes


async def test_streams_report_stream_and_time_to_first_chunk(spans):
    chunks = [AIMessageChunk('a'), AIMessageChunk('b')]
    await _Model(reply=AIMessage('Hi'), model='m').ainvoke(MESSAGES)
    await _collect(_Model(chunks=chunks, model='m').astream(MESSAGES))
    await _ResponsesModel(RESPONSE, model_name='m').ainvoke_native_responses(
        {'input': 'Hi'}
    )
    await _collect(
        _ResponsesModel(
            events=_stream_events(RESPONSE), model_name='m'
        ).astream_native_responses({'input': 'Hi'})
    )

    reply, stream, responses_reply, responses_stream = spans.get_finished_spans()
    for span in (reply, responses_reply):
        assert 'gen_ai.request.stream' not in span.attributes
        assert 'gen_ai.response.time_to_first_chunk' not in span.attributes
    for span in (stream, responses_stream):
        assert span.attributes['gen_ai.request.stream'] is True
        assert 0 <= span.attributes['gen_ai.response.time_to_first_chunk'] < 1


async def test_responses_request_state_and_reasoning(spans):
    body = {
        'input': 'Hi',
        'previous_response_id': 'resp_0',
        'conversation': {'id': 'conv_1'},
        'reasoning': {'summary': 'auto'},
    }
    model = _ResponsesModel(RESPONSE, model_name='m', reasoning_effort='low')

    await model.ainvoke_native_responses(body)
    await model.ainvoke_native_responses(
        {'input': 'Hi', 'conversation': 'conv_2', 'reasoning': {'effort': 'high'}}
    )

    first, second = spans.get_finished_spans()
    assert first.attributes['gen_ai.request.previous_response.id'] == 'resp_0'
    assert first.attributes['gen_ai.conversation.id'] == 'conv_1'
    # The model's setting, as the client sent none.
    assert first.attributes['gen_ai.request.reasoning.level'] == 'low'
    assert 'gen_ai.request.previous_response.id' not in second.attributes
    assert second.attributes['gen_ai.conversation.id'] == 'conv_2'
    assert second.attributes['gen_ai.request.reasoning.level'] == 'high'


@pytest.mark.parametrize(
    ('spec', 'settings', 'url'),
    [
        ('openai:gpt-6-luna', {}, 'https://api.openai.com/v1/'),
        ('openai:m', {'base_url': 'http://vllm:8000/v1'}, 'http://vllm:8000/v1/'),
        ('deepseek:deepseek-chat', {}, 'https://api.deepseek.com/v1/'),
        ('anthropic:claude-x', {}, 'https://api.anthropic.com'),
        ('mistralai:m', {}, 'https://api.mistral.ai/v1'),
        ('google_genai:gemini-x', {}, 'https://generativelanguage.googleapis.com/'),
    ],
)
def test_provider_server_urls(monkeypatch, spec, settings, url):
    for name in ('OPENAI_API_BASE', 'ANTHROPIC_API_URL', 'ANTHROPIC_BASE_URL'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv('MISTRAL_BASE_URL', raising=False)
    model = init_chat_model(
        spec, api_key='sk', http_async_client=HttpxAiohttpClient(), **settings
    )

    assert model._server_url() == url


async def test_responses_stream_stopped_after_its_final_event_succeeds(spans, metrics):
    # A client that closes the connection once it has response.completed
    # cancels the stream before the upstream closes it.
    model = _ResponsesModel(events=_stream_events(RESPONSE), model_name='m')

    stream = model.astream_native_responses({'input': 'Hi'})
    async for event, _ in stream:
        if event == 'response.completed':
            break
    await stream.aclose()

    span = _only_span(spans)
    assert span.status.status_code == StatusCode.UNSET
    assert 'error.type' not in span.attributes
    assert span.attributes['gen_ai.response.id'] == 'resp_1'
    assert span.attributes['gen_ai.usage.output_tokens'] == 7
    assert _token_points(metrics)['output'] == ('fake', 'gpt-6-luna-2026', 7)
