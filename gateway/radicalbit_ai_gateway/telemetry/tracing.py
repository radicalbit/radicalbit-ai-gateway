"""Trace spans of the gateway's own steps.

``workflow`` and ``task`` wrap a function in a span named ``<name>.workflow``
or ``<name>.task`` that records its input and output. The name of the running
workflow, the path of the running tasks and the request's association
properties travel in the OpenTelemetry context, and every span that starts,
whoever starts it, is stamped with them.

A coroutine that returns a streaming response is not done when it returns:
the response is sent after it. Its span ends when the response is done. That
is when the stream ends, fails or is cut short by the client.

Until ``init_tracing`` is called the decorators only run the function.

The spans, their attributes and the context keys are the ones the OpenLLMetry
SDK (``traceloop-sdk``) produced when the gateway used it: see ``attributes``.
"""

from __future__ import annotations

from collections.abc import (
    AsyncGenerator,
    AsyncIterable,
    AsyncIterator,
    Awaitable,
    Callable,
    Iterator,
    Mapping,
    Sequence,
)
import contextlib
from contextvars import Token
import dataclasses
from functools import wraps
import inspect
import json
import os
from types import CoroutineType
from typing import Any, ParamSpec, Protocol, TypeVar, overload, runtime_checkable
import weakref

from opentelemetry import trace
from opentelemetry.context import (
    Context,
    attach,
    detach,
    get_current,
    get_value,
    set_value,
)
from opentelemetry.instrumentation.threading import ThreadingInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import Span, SpanProcessor, TracerProvider
from opentelemetry.trace import ProxyTracerProvider, Status, StatusCode
from opentelemetry.util.types import AttributeValue
from typing_extensions import override

from radicalbit_ai_gateway.telemetry.attributes import (
    ASSOCIATION_PROPERTIES,
    ENTITY_INPUT,
    ENTITY_NAME,
    ENTITY_OUTPUT,
    ENTITY_PATH,
    SPAN_KIND,
    TRACER_NAME,
    WORKFLOW_NAME,
)

P = ParamSpec('P')
T = TypeVar('T')

# The context tokens of a span, in the order they were attached.
_Tokens = tuple[Token[Context] | None, ...]

# Context keys. Plugins read ``association_properties`` from the context.
_WORKFLOW_NAME_KEY = 'workflow_name'
_ENTITY_PATH_KEY = 'entity_path'
_ASSOCIATION_PROPERTIES_KEY = 'association_properties'

_WORKFLOW = 'workflow'
_TASK = 'task'

_tracer = trace.get_tracer(TRACER_NAME)
_enabled = False
# The tracer provider that has the context stamp.
_stamped_provider: TracerProvider | None = None
# The name each traced function is traced under.
_entity_names: weakref.WeakKeyDictionary[Callable[..., object], str] = (
    weakref.WeakKeyDictionary()
)


class _ContextStamp(SpanProcessor):
    """Stamp each span that starts with what the context says about it."""

    @override
    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        workflow_name = get_value(_WORKFLOW_NAME_KEY)
        if workflow_name is not None:
            span.set_attribute(WORKFLOW_NAME, str(workflow_name))
        entity_path = get_value(_ENTITY_PATH_KEY)
        if entity_path is not None:
            span.set_attribute(ENTITY_PATH, str(entity_path))
        properties = get_value(_ASSOCIATION_PROPERTIES_KEY)
        if isinstance(properties, dict):
            _set_association_attributes(span, properties)


def init_tracing(processors: Sequence[SpanProcessor], service_name: str) -> None:
    """Send the gateway's spans to ``processors`` and switch the decorators on.

    The tracer provider is global and cannot be replaced: the first call
    creates it, with ``service_name``, unless one is set already, and a later
    call adds its processors to it.
    """
    global _enabled, _stamped_provider  # noqa: PLW0603
    provider = trace.get_tracer_provider()
    if isinstance(provider, ProxyTracerProvider):
        provider = TracerProvider(
            resource=Resource.create({SERVICE_NAME: service_name})
        )
        trace.set_tracer_provider(provider)
    if not isinstance(provider, TracerProvider):
        msg = f'Tracing needs the SDK tracer provider, not {type(provider).__name__}'
        raise TypeError(msg)
    if provider is not _stamped_provider:
        provider.add_span_processor(_ContextStamp())
        _stamped_provider = provider
    for processor in processors:
        provider.add_span_processor(processor)
    # Carry the trace context into threads.
    threading = ThreadingInstrumentor()
    if not threading.is_instrumented_by_opentelemetry:
        threading.instrument()
    _enabled = True


def disable_tracing() -> None:
    """Make the decorators only run the function again."""
    global _enabled  # noqa: PLW0603
    _enabled = False


def set_association_properties(properties: Mapping[str, AttributeValue]) -> None:
    """Make ``properties`` the association properties of the current context.

    They replace the ones set before. Every span that starts from now on gets
    them, and so does the current span when a workflow is running.
    """
    attach(set_value(_ASSOCIATION_PROPERTIES_KEY, properties))
    if get_value(_WORKFLOW_NAME_KEY) is not None:
        _set_association_attributes(trace.get_current_span(), properties)


def record_error(error: Exception | str) -> None:
    """Mark the current span failed with ``error``, or with that description.

    For an error that is handled where it happens, so it never reaches the
    decorator that would mark the span: a stream that fails after its first
    frame ends with an error frame, not with the error.
    """
    span = trace.get_current_span()
    if isinstance(error, str):
        span.set_status(Status(StatusCode.ERROR, error))
    else:
        _record_error(span, error)


def workflow(name: str) -> _Traced:
    """Trace the decorated function as the workflow ``name``."""
    return _Traced(name, _WORKFLOW)


def task(name: str) -> _Traced:
    """Trace the decorated function as the task ``name``."""
    return _Traced(name, _TASK)


def entity_name(func: Callable[..., object]) -> str | None:
    """Return the name ``func`` is traced under, None if it is not traced.

    A decorator that wraps the traced function with ``functools.wraps`` keeps
    the name: it is looked up along the ``__wrapped__`` chain.
    """
    return _entity_names.get(inspect.unwrap(func, stop=_entity_names.__contains__))


def _set_association_attributes(
    span: trace.Span, properties: Mapping[str, AttributeValue]
) -> None:
    for key, value in properties.items():
        span.set_attribute(f'{ASSOCIATION_PROPERTIES}.{key}', value)


class _Traced:
    """Decorate a function to trace it in a span of its own, whatever its shape:
    a coroutine, an async generator, a generator or a plain function.
    """

    def __init__(self, name: str, kind: str) -> None:
        self._name = name
        self._kind = kind

    @overload
    def __call__(
        self, fn: Callable[P, CoroutineType[Any, Any, T]]
    ) -> Callable[P, CoroutineType[Any, Any, T]]: ...

    @overload
    def __call__(self, fn: Callable[P, T]) -> Callable[P, T]: ...

    def __call__(self, fn: Callable[P, object]) -> Callable[P, object]:
        name, kind = self._name, self._kind
        if inspect.isasyncgenfunction(fn):
            wrapper = _trace_async_generator(fn, name, kind)
        elif inspect.iscoroutinefunction(fn):
            wrapper = _trace_coroutine(fn, name, kind)
        elif inspect.isgeneratorfunction(fn):
            wrapper = _trace_generator(fn, name, kind)
        else:
            wrapper = _trace_function(fn, name, kind)
        _entity_names[wrapper] = name
        return wrapper


def _trace_async_generator(
    fn: Callable[P, AsyncIterator[T]], name: str, kind: str
) -> Callable[P, AsyncIterator[T]]:
    @wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> AsyncIterator[T]:
        if not _enabled:
            async for item in fn(*args, **kwargs):
                yield item
            return
        span, tokens = _open_span(name, kind)
        _record(span, ENTITY_INPUT, {'args': args, 'kwargs': kwargs})
        # ``async for`` does not pass a close on to the inner
        # generator: close it here, so the span ends with this one.
        inner = _aiterate_in_span(span, tokens, fn(*args, **kwargs))
        try:
            async for item in inner:
                yield item
        finally:
            await inner.aclose()

    return wrapper


def _trace_coroutine(
    fn: Callable[P, Awaitable[T]], name: str, kind: str
) -> Callable[P, CoroutineType[Any, Any, T]]:
    @wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        if not _enabled:
            return await fn(*args, **kwargs)
        span, tokens = _open_span(name, kind)
        _record(span, ENTITY_INPUT, {'args': args, 'kwargs': kwargs})
        handed_over = False
        try:
            result = await fn(*args, **kwargs)
        except Exception as e:
            _record_error(span, e)
            raise
        else:
            _record(span, ENTITY_OUTPUT, result)
            if isinstance(result, _SentLater):
                # The response is sent after this returns: the span ends
                # when it is done.
                _end_span_when_sent(span, result)
                handed_over = True
            return result
        finally:
            if handed_over:
                _detach_all(tokens)
            else:
                _close_span(span, tokens)

    return wrapper


def _trace_generator(
    fn: Callable[P, Iterator[T]], name: str, kind: str
) -> Callable[P, Iterator[T]]:
    @wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> Iterator[T]:
        if not _enabled:
            return fn(*args, **kwargs)
        span, tokens = _open_span(name, kind)
        _record(span, ENTITY_INPUT, {'args': args, 'kwargs': kwargs})
        try:
            generator = fn(*args, **kwargs)
        except Exception as e:
            _record_error(span, e)
            _close_span(span, tokens)
            raise
        # The span ends with the generator.
        return _iterate_in_span(span, tokens, generator)

    return wrapper


def _trace_function(fn: Callable[P, T], name: str, kind: str) -> Callable[P, T]:
    @wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        if not _enabled:
            return fn(*args, **kwargs)
        span, tokens = _open_span(name, kind)
        _record(span, ENTITY_INPUT, {'args': args, 'kwargs': kwargs})
        try:
            result = fn(*args, **kwargs)
        except Exception as e:
            _record_error(span, e)
            raise
        else:
            _record(span, ENTITY_OUTPUT, result)
            return result
        finally:
            _close_span(span, tokens)

    return wrapper


def _open_span(name: str, kind: str) -> tuple[trace.Span, _Tokens]:
    """Start the span and make it, its workflow name or its path current.

    Return it with the context tokens, in the order they were attached.
    """
    # Attached before the span starts: a workflow span carries its own name.
    name_token = (
        attach(set_value(_WORKFLOW_NAME_KEY, name)) if kind == _WORKFLOW else None
    )
    span = _tracer.start_span(f'{name}.{kind}')
    span_token = attach(trace.set_span_in_context(span))
    # Attached after the span starts: a task span carries the path above it.
    path_token = None
    if kind == _TASK:
        parent_path = get_value(_ENTITY_PATH_KEY)
        path = name if parent_path is None else f'{parent_path}.{name}'
        path_token = attach(set_value(_ENTITY_PATH_KEY, path))
    span.set_attribute(SPAN_KIND, kind)
    span.set_attribute(ENTITY_NAME, name)
    return span, (name_token, span_token, path_token)


def _close_span(span: trace.Span, tokens: _Tokens) -> None:
    span.end()
    _detach_all(tokens)


def _detach_all(tokens: _Tokens) -> None:
    """Detach the tokens, last attached first.

    A generator or a coroutine can resume in another asyncio task or thread
    than the one that attached them, where detaching fails: that context is
    discarded with its task anyway.
    """
    for token in reversed(tokens):
        if token is not None:
            with contextlib.suppress(Exception):
                detach(token)


def _record_error(span: trace.Span, error: Exception) -> None:
    span.set_status(Status(StatusCode.ERROR, str(error)))
    span.record_exception(error)


def _iterate_in_span(
    span: trace.Span, tokens: _Tokens, generator: Iterator[T]
) -> Iterator[T]:
    # The generator body runs in the context of whoever iterates it: make the
    # span current again there.
    span_token = attach(trace.set_span_in_context(span))
    try:
        yield from generator
    except Exception as e:
        _record_error(span, e)
        raise
    finally:
        span.end()
        _detach_all((*tokens, span_token))


async def _aiterate_in_span(
    span: trace.Span, tokens: _Tokens, generator: AsyncIterator[T]
) -> AsyncGenerator[T]:
    try:
        async for item in generator:
            yield item
    except Exception as e:
        _record_error(span, e)
        raise
    finally:
        span.end()
        _detach_all(tokens)


@runtime_checkable
class _SentLater(Protocol):
    """A response sent after the handler returns, that says when it is done
    (``StreamingResponseWithStatusCode``).
    """

    body_iterator: AsyncIterable[Any]

    def when_sent(self, callback: Callable[[], Awaitable[None]]) -> None: ...


def _end_span_when_sent(span: trace.Span, response: _SentLater) -> None:
    """Iterate the body of ``response`` with ``span`` current. End ``span``
    when the response is done.

    Call it while ``span`` is current: the body is iterated in this context,
    so the body's spans are its children.
    """
    context = get_current()
    body = response.body_iterator

    async def iterate() -> AsyncGenerator[Any]:
        token = attach(context)
        try:
            async for chunk in body:
                yield chunk
        except Exception as e:
            _record_error(span, e)
            raise
        finally:
            _detach_all((token,))

    iterating = iterate()
    response.body_iterator = iterating

    async def end() -> None:
        # A client that leaves can leave the body open. Close it, so its own
        # spans end before this one.
        try:
            await iterating.aclose()
            aclose = getattr(body, 'aclose', None)
            if aclose is not None:
                await aclose()
        finally:
            span.end()

    response.when_sent(end)


def _record(span: trace.Span, attribute: str, value: object) -> None:
    """Set ``value`` as JSON on the span, unless content tracing is off."""
    if not _content_tracing_enabled():
        return
    try:
        content = json.dumps(value, cls=_ContentEncoder)
    except TypeError:
        return
    span.set_attribute(attribute, _cut_to_length_limit(content))


def _content_tracing_enabled() -> bool:
    return (os.getenv('TRACELOOP_TRACE_CONTENT') or 'true').lower() == 'true'


def _cut_to_length_limit(content: str) -> str:
    """Cut ``content`` at OTEL_SPAN_ATTRIBUTE_VALUE_LENGTH_LIMIT, if it is set.

    What is left may not be valid JSON.
    """
    try:
        limit = int(os.getenv('OTEL_SPAN_ATTRIBUTE_VALUE_LENGTH_LIMIT') or 0)
    except ValueError:
        return content
    return content[:limit] if limit > 0 else content


@runtime_checkable
class _ToJson(Protocol):
    def to_json(self) -> object: ...


@runtime_checkable
class _ModelDump(Protocol):
    def model_dump(self) -> object: ...


class _ContentEncoder(json.JSONEncoder):
    """Encode what JSON cannot: by its own serializer, else as its class name."""

    @override
    def default(self, o: object) -> object:
        if dataclasses.is_dataclass(o) and not isinstance(o, type):
            return dataclasses.asdict(o)
        if isinstance(o, _ToJson):
            return o.to_json()
        if isinstance(o, _ModelDump):
            return o.model_dump()
        for serializer_name in ('dict', 'json'):
            serializer = getattr(o, serializer_name, None)
            if not callable(serializer) or inspect.iscoroutinefunction(serializer):
                continue
            result = serializer()
            if inspect.iscoroutine(result):
                result.close()
                continue
            if serializer_name == 'json' and isinstance(result, str):
                # A JSON string: parse it, not to encode it twice.
                try:
                    return json.loads(result)
                except (ValueError, TypeError):
                    return result
            return result
        return o.__class__.__name__
