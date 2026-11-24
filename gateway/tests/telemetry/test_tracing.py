"""The spans the gateway's ``workflow`` and ``task`` decorators leave.

The names and attributes asserted here are the wire format the trace queries,
the UI and the enterprise plugins read: they must not change.
"""

from collections.abc import AsyncGenerator, AsyncIterator, Iterable, Iterator, Mapping
import dataclasses
import inspect
import json

from opentelemetry import trace
from opentelemetry.context import get_value
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.trace import StatusCode
from opentelemetry.util.types import AttributeValue
from pydantic import BaseModel
import pytest

from radicalbit_ai_gateway.telemetry.tracing import (
    disable_tracing,
    entity_name,
    init_tracing,
    set_association_properties,
    task,
    workflow,
)


@pytest.fixture
def spans(span_collector):
    span_collector.spans.clear()
    span_collector.on = True
    yield span_collector.spans
    span_collector.on = False


@dataclasses.dataclass(frozen=True)
class _Span:
    """What these tests read of a finished span."""

    span_id: int
    parent_id: int | None
    attributes: Mapping[str, AttributeValue]


def _view(span: ReadableSpan) -> _Span:
    assert span.context is not None
    return _Span(
        span_id=span.context.span_id,
        parent_id=span.parent.span_id if span.parent is not None else None,
        attributes=span.attributes or {},
    )


def _by_name(spans: Iterable[ReadableSpan]) -> dict[str, _Span]:
    return {span.name: _view(span) for span in spans}


async def test_a_workflow_leaves_a_span_with_its_input_and_output(spans):
    @workflow(name='answer')
    async def answer(question, lang='en'):
        return {'text': 'forty-two'}

    assert await answer('why', lang='it') == {'text': 'forty-two'}

    (span,) = spans
    assert span.name == 'answer.workflow'
    assert span.parent is None
    assert span.instrumentation_scope.name == 'traceloop.tracer'
    assert dict(span.attributes) == {
        'traceloop.workflow.name': 'answer',
        'traceloop.span.kind': 'workflow',
        'traceloop.entity.name': 'answer',
        'traceloop.entity.input': '{"args": ["why"], "kwargs": {"lang": "it"}}',
        'traceloop.entity.output': '{"text": "forty-two"}',
    }


async def test_tasks_nest_under_the_workflow_and_chain_their_path(spans):
    @task(name='inner')
    async def inner():
        return 1

    @task(name='outer')
    async def outer():
        return await inner()

    @workflow(name='root')
    async def root():
        return await outer()

    await root()

    by_name = _by_name(spans)
    root_span, outer_span, inner_span = (
        by_name['root.workflow'],
        by_name['outer.task'],
        by_name['inner.task'],
    )
    assert outer_span.parent_id == root_span.span_id
    assert inner_span.parent_id == outer_span.span_id
    assert outer_span.attributes['traceloop.span.kind'] == 'task'
    assert outer_span.attributes['traceloop.entity.name'] == 'outer'
    assert outer_span.attributes['traceloop.workflow.name'] == 'root'
    assert inner_span.attributes['traceloop.workflow.name'] == 'root'
    # A span carries the path of the tasks above it, not its own name.
    assert 'traceloop.entity.path' not in root_span.attributes
    assert 'traceloop.entity.path' not in outer_span.attributes
    assert inner_span.attributes['traceloop.entity.path'] == 'outer'


async def test_the_workflow_name_and_path_do_not_outlive_their_span(spans):
    @task(name='step')
    async def step():
        return None

    @workflow(name='root')
    async def root():
        await step()
        return get_value('entity_path')

    assert await root() is None
    assert get_value('workflow_name') is None


async def test_association_properties_reach_the_current_and_later_spans(spans):
    @task(name='step')
    async def step():
        with trace.get_tracer('plain').start_as_current_span('plain'):
            pass

    @workflow(name='root')
    async def root():
        set_association_properties({'project_uuid': 'p-1', 'tags': 'a,b'})
        await step()
        return get_value('association_properties')

    assert await root() == {'project_uuid': 'p-1', 'tags': 'a,b'}
    for span in spans:
        assert span.attributes['traceloop.association.properties.project_uuid'] == 'p-1'
        assert span.attributes['traceloop.association.properties.tags'] == 'a,b'
    # A span the decorators did not open is stamped too.
    plain = _by_name(spans)['plain']
    assert plain.attributes['traceloop.workflow.name'] == 'root'
    assert plain.attributes['traceloop.entity.path'] == 'step'


async def test_association_properties_outside_a_workflow_only_wait_in_context(spans):
    tracer = trace.get_tracer('plain')
    with tracer.start_as_current_span('before'):
        set_association_properties({'project_uuid': 'p-1'})
        with tracer.start_as_current_span('after'):
            pass

    by_name = _by_name(spans)
    assert 'traceloop.association.properties.project_uuid' not in (
        by_name['before'].attributes
    )
    assert (
        by_name['after'].attributes['traceloop.association.properties.project_uuid']
        == 'p-1'
    )


async def test_an_error_marks_the_span_and_is_raised(spans):
    @task(name='boom')
    async def boom():
        raise ValueError('no good')

    with pytest.raises(ValueError, match='no good'):
        await boom()

    (span,) = spans
    assert span.status.status_code is StatusCode.ERROR
    assert span.status.description == 'no good'
    (event,) = span.events
    assert event.name == 'exception'
    assert event.attributes['exception.type'] == 'ValueError'
    assert 'traceloop.entity.output' not in span.attributes


def test_a_sync_function_is_traced(spans):
    @task(name='add')
    def add(a: int, b: int) -> int:
        return a + b

    assert add(1, 2) == 3

    (span,) = spans
    assert span.name == 'add.task'
    assert span.attributes['traceloop.entity.output'] == '3'


def test_a_sync_generator_span_covers_its_iteration(spans):
    @task(name='count')
    def count() -> Iterator[int]:
        with trace.get_tracer('plain').start_as_current_span('child'):
            yield 1
        yield 2

    generator = count()
    assert spans == []
    assert list(generator) == [1, 2]

    by_name = _by_name(spans)
    assert by_name['child'].parent_id == by_name['count.task'].span_id
    assert 'traceloop.entity.output' not in by_name['count.task'].attributes


async def test_an_async_generator_span_covers_its_iteration(spans):
    @workflow(name='stream')
    async def stream(prefix: str) -> AsyncIterator[str]:
        with trace.get_tracer('plain').start_as_current_span('child'):
            yield f'{prefix}-1'
        yield f'{prefix}-2'

    assert [item async for item in stream('x')] == ['x-1', 'x-2']

    by_name = _by_name(spans)
    span = by_name['stream.workflow']
    assert by_name['child'].parent_id == span.span_id
    assert span.attributes['traceloop.entity.input'] == '{"args": ["x"], "kwargs": {}}'
    assert 'traceloop.entity.output' not in span.attributes
    assert get_value('workflow_name') is None


async def test_closing_an_async_generator_early_ends_its_span(spans):
    @task(name='stream')
    async def stream() -> AsyncGenerator[int]:
        yield 1
        yield 2

    generator = stream()
    assert await anext(generator) == 1
    assert spans == []
    await generator.aclose()

    (span,) = spans
    assert span.name == 'stream.task'


async def test_an_error_in_an_async_generator_marks_the_span(spans):
    @task(name='stream')
    async def stream() -> AsyncIterator[int]:
        yield 1
        raise RuntimeError('cut')

    with pytest.raises(RuntimeError, match='cut'):
        _ = [item async for item in stream()]

    (span,) = spans
    assert span.status.status_code is StatusCode.ERROR
    assert span.status.description == 'cut'


@dataclasses.dataclass
class _Point:
    x: int
    y: int


class _Model(BaseModel):
    name: str


class _Opaque:
    pass


async def test_input_and_output_encode_objects_as_json(spans):
    @task(name='encode')
    async def encode(point, model, opaque):
        return [model, opaque]

    await encode(_Point(1, 2), _Model(name='m'), opaque=_Opaque())

    (span,) = spans
    assert json.loads(span.attributes['traceloop.entity.input']) == {
        'args': [{'x': 1, 'y': 2}, {'name': 'm'}],
        'kwargs': {'opaque': '_Opaque'},
    }
    assert json.loads(span.attributes['traceloop.entity.output']) == [
        {'name': 'm'},
        '_Opaque',
    ]


async def test_content_is_left_out_when_content_tracing_is_off(spans, monkeypatch):
    monkeypatch.setenv('TRACELOOP_TRACE_CONTENT', 'false')

    @task(name='secret')
    async def secret(password):
        return 'token'

    await secret('hunter2')

    (span,) = spans
    assert 'traceloop.entity.input' not in span.attributes
    assert 'traceloop.entity.output' not in span.attributes


async def test_input_and_output_are_cut_at_the_attribute_length_limit(
    spans, monkeypatch
):
    monkeypatch.setenv('OTEL_SPAN_ATTRIBUTE_VALUE_LENGTH_LIMIT', '10')

    @task(name='long')
    async def long():
        return 'x' * 50

    await long()

    (span,) = spans
    assert span.attributes['traceloop.entity.input'] == '{"args": ['
    assert span.attributes['traceloop.entity.output'] == '"xxxxxxxxx'


async def test_decorators_only_run_the_function_while_tracing_is_off(spans):
    @workflow(name='quiet')
    async def quiet():
        set_association_properties({'project_uuid': 'p-1'})
        return trace.get_current_span().is_recording()

    disable_tracing()
    try:
        recording = await quiet()
    finally:
        init_tracing([], service_name='test-gateway')

    assert recording is False
    assert spans == []
    # The plugins read the properties from the context, traced or not.
    assert get_value('association_properties') == {'project_uuid': 'p-1'}


def test_the_entity_name_of_a_decorated_function_can_be_read():
    @task(name='named')
    def named() -> None:
        return None

    def plain() -> None:
        return None

    assert entity_name(named) == 'named'
    assert entity_name(plain) is None
    assert inspect.unwrap(named) is not named
