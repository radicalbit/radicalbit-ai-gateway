"""The trace of POST /v1/messages through a real route.

The routes are built from a project config and served on the real app
(``open_gateway``). The Anthropic provider and its SDK are real; Anthropic is
mocked over HTTP with pook. The tests read the spans the request leaves.
"""

import json

import pytest

from tests.common import provider_responses as canned
from tests.common.gateway_harness import open_gateway
from tests.common.messages_api import (
    CLAUDE,
    messages_routes,
    mock_anthropic,
    mock_anthropic_stream,
    send,
    send_stream,
)

from radicalbit_ai_gateway.db.dao.otel_traces_dao import request_type_of_root_span
from radicalbit_ai_gateway.models.request_event_type import RequestType

LLM_SPAN = 'ChatAnthropic.chat'
CONTENT_KEYS = (
    'gen_ai.input.messages',
    'gen_ai.output.messages',
    'gen_ai.system_instructions',
)


@pytest.fixture
def gateway():
    with open_gateway(messages_routes(CLAUDE), use_pook=True) as gateway:
        yield gateway


def _spans_of(span_collector, request) -> list:
    """Return the spans a request leaves; ``request`` sends it and reads it all."""
    span_collector.spans.clear()
    span_collector.on = True
    try:
        response = request()
    finally:
        span_collector.on = False
    assert response.status_code == 200
    return list(span_collector.spans)


def _root(spans: list):
    (root,) = [span for span in spans if span.parent is None]
    return root


def _llm_span(spans: list):
    (span,) = [span for span in spans if span.name == LLM_SPAN]
    return span


# ── The root span ───────────────────────────────────────────────────────────


def test_the_root_span_is_a_chat_trace_and_carries_the_entry_endpoint(
    gateway, span_collector
):
    mock_anthropic()

    spans = _spans_of(span_collector, lambda: send(gateway))

    root = _root(spans)
    assert root.name == 'messages.workflow'
    assert request_type_of_root_span(root.name) is RequestType.CHAT_COMPLETIONS
    assert root.attributes['gateway.entry_endpoint'] == '/v1/messages'
    # Only the root span says where the request came in.
    assert [s.name for s in spans if 'gateway.entry_endpoint' in s.attributes] == [
        'messages.workflow'
    ]


def test_a_streaming_request_has_the_same_root_span(gateway, span_collector):
    mock_anthropic_stream()

    spans = _spans_of(span_collector, lambda: send_stream(gateway))

    root = _root(spans)
    assert root.name == 'messages.workflow'
    assert root.attributes['gateway.entry_endpoint'] == '/v1/messages'


# ── The model call span ─────────────────────────────────────────────────────


def test_the_llm_span_records_provider_model_tokens_cost_and_stop_reason(
    gateway, span_collector
):
    mock_anthropic(
        canned.anthropic_message(
            input_tokens=21, output_tokens=7, cache_read=4, cache_5m=5
        ).json_body
    )

    spans = _spans_of(span_collector, lambda: send(gateway))

    span = _llm_span(spans)
    attributes = dict(span.attributes)
    assert attributes['gen_ai.provider.name'] == 'anthropic'
    assert attributes['gen_ai.operation.name'] == 'chat'
    assert attributes['gen_ai.request.model'] == 'claude-sonnet-4-5'
    assert attributes['gen_ai.response.model'] == 'claude-sonnet-4-5-20250929'
    assert attributes['gen_ai.request.max_tokens'] == 1024
    # The input counts the cache reads and writes, as a chat span's does.
    assert attributes['gen_ai.usage.input_tokens'] == 30
    assert attributes['gen_ai.usage.output_tokens'] == 7
    assert attributes['gen_ai.usage.total_tokens'] == 37
    assert attributes['gen_ai.usage.cache_read.input_tokens'] == 4
    assert attributes['gen_ai.usage.cache_creation.input_tokens'] == 5
    # 21 input at 3, 4 read at 0.30, 5 written at 3.75 and 7 output at 15
    # dollars per million tokens.
    assert attributes['gen_ai.usage.cost'] == pytest.approx(0.00018795)
    assert attributes['gen_ai.response.finish_reasons'] == ('stop',)
    # It belongs to the request's trace.
    assert span.context.trace_id == _root(spans).context.trace_id


def test_the_llm_span_of_a_stream_records_the_same(gateway, span_collector):
    mock_anthropic_stream(
        canned.anthropic_stream(
            input_tokens=21, output_tokens=7, cache_read=4, cache_5m=5
        ).sse_text()
    )

    spans = _spans_of(span_collector, lambda: send_stream(gateway))

    span = _llm_span(spans)
    attributes = dict(span.attributes)
    assert attributes['gen_ai.request.stream'] is True
    assert attributes['gen_ai.response.model'] == 'claude-sonnet-4-5-20250929'
    assert attributes['gen_ai.usage.input_tokens'] == 30
    assert attributes['gen_ai.usage.output_tokens'] == 7
    assert attributes['gen_ai.usage.cache_read.input_tokens'] == 4
    assert attributes['gen_ai.usage.cache_creation.input_tokens'] == 5
    assert attributes['gen_ai.usage.cost'] == pytest.approx(0.00018795)
    assert attributes['gen_ai.response.finish_reasons'] == ('stop',)
    assert span.context.trace_id == _root(spans).context.trace_id


def test_the_llm_span_carries_the_prompt_and_the_answer(gateway, span_collector):
    mock_anthropic()

    spans = _spans_of(span_collector, lambda: send(gateway))

    attributes = _llm_span(spans).attributes
    assert json.loads(attributes['gen_ai.system_instructions']) == [
        {'type': 'text', 'content': 'You are terse.'}
    ]
    assert json.loads(attributes['gen_ai.input.messages']) == [
        {'role': 'user', 'parts': [{'type': 'text', 'content': 'Hi'}]}
    ]
    assert json.loads(attributes['gen_ai.output.messages']) == [
        {
            'role': 'assistant',
            'parts': [{'type': 'text', 'content': 'Hello from the model'}],
            'finish_reason': 'stop',
        }
    ]


def test_the_llm_span_carries_no_content_when_content_tracing_is_off(
    gateway, span_collector, monkeypatch
):
    monkeypatch.setenv('TRACELOOP_TRACE_CONTENT', 'false')
    mock_anthropic()

    spans = _spans_of(span_collector, lambda: send(gateway))

    attributes = _llm_span(spans).attributes
    assert not [key for key in CONTENT_KEYS if key in attributes]
    assert attributes['gen_ai.usage.output_tokens'] == 7
