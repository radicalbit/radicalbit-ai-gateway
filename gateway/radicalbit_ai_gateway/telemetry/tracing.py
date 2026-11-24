"""Trace spans of the gateway's own steps.

``workflow`` and ``task`` wrap a function in a span named ``<name>.workflow``
or ``<name>.task`` that records its input and output. The name of the running
workflow, the path of the running tasks and the request's association
properties travel in the OpenTelemetry context, and every span that starts,
whoever starts it, is stamped with them.

Until ``init_tracing`` is called the decorators only run the function.

The spans, their attributes and the context keys are the ones the OpenLLMetry
SDK (``traceloop-sdk``) produced when the gateway used it: see ``attributes``.
"""

from collections.abc import Callable, Sequence
import contextlib
import dataclasses
from functools import wraps
import inspect
import json
import os
import types
from typing import Any, TypeVar

from opentelemetry import trace
from opentelemetry.context import Context, attach, detach, get_value, set_value
from opentelemetry.instrumentation.threading import ThreadingInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import Span, SpanProcessor, TracerProvider
from opentelemetry.trace import ProxyTracerProvider, Status, StatusCode

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

F = TypeVar('F', bound=Callable[..., Any])

# Context keys. Plugins read ``association_properties`` from the context.
_WORKFLOW_NAME_KEY = 'workflow_name'
_ENTITY_PATH_KEY = 'entity_path'
_ASSOCIATION_PROPERTIES_KEY = 'association_properties'

_WORKFLOW = 'workflow'
_TASK = 'task'

_tracer = trace.get_tracer(TRACER_NAME)
_enabled = False
# The tracer provider that has the context stamp.
_stamped_provider = None


class _ContextStamp(SpanProcessor):
    """Stamp each span that starts with what the context says about it."""

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


def set_association_properties(properties: dict) -> None:
    """Make ``properties`` the association properties of the current context.

    They replace the ones set before. Every span that starts from now on gets
    them, and so does the current span when a workflow is running.
    """
    attach(set_value(_ASSOCIATION_PROPERTIES_KEY, properties))
    if get_value(_WORKFLOW_NAME_KEY) is not None:
        _set_association_attributes(trace.get_current_span(), properties)


def workflow(name: str) -> Callable[[F], F]:
    """Trace the decorated function as the workflow ``name``."""
    return _traced(name, _WORKFLOW)


def task(name: str) -> Callable[[F], F]:
    """Trace the decorated function as the task ``name``."""
    return _traced(name, _TASK)


def entity_name(func: Callable) -> str | None:
    """Return the name ``func`` is traced under, None if it is not traced."""
    return getattr(func, '__traced_entity__', None)


def _set_association_attributes(span: trace.Span, properties: dict) -> None:
    for key, value in properties.items():
        span.set_attribute(f'{ASSOCIATION_PROPERTIES}.{key}', value)


def _traced(name: str, kind: str) -> Callable[[F], F]:
    def decorate(fn: F) -> F:
        if inspect.isasyncgenfunction(fn):

            @wraps(fn)
            async def wrapper(*args, **kwargs):
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

        elif inspect.iscoroutinefunction(fn):

            @wraps(fn)
            async def wrapper(*args, **kwargs):
                if not _enabled:
                    return await fn(*args, **kwargs)
                span, tokens = _open_span(name, kind)
                _record(span, ENTITY_INPUT, {'args': args, 'kwargs': kwargs})
                try:
                    result = await fn(*args, **kwargs)
                except Exception as e:
                    _record_error(span, e)
                    raise
                else:
                    _record(span, ENTITY_OUTPUT, result)
                    return result
                finally:
                    _close_span(span, tokens)

        else:

            @wraps(fn)
            def wrapper(*args, **kwargs):
                if not _enabled:
                    return fn(*args, **kwargs)
                span, tokens = _open_span(name, kind)
                _record(span, ENTITY_INPUT, {'args': args, 'kwargs': kwargs})
                try:
                    result = fn(*args, **kwargs)
                except Exception as e:
                    _record_error(span, e)
                    _close_span(span, tokens)
                    raise
                if isinstance(result, types.GeneratorType):
                    # The span ends with the generator.
                    return _iterate_in_span(span, tokens, result)
                _record(span, ENTITY_OUTPUT, result)
                _close_span(span, tokens)
                return result

        wrapper.__traced_entity__ = name
        return wrapper

    return decorate


def _open_span(name: str, kind: str) -> tuple[trace.Span, tuple]:
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


def _close_span(span: trace.Span, tokens: tuple) -> None:
    span.end()
    _detach_all(tokens)


def _detach_all(tokens: tuple) -> None:
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


def _iterate_in_span(span: trace.Span, tokens: tuple, generator):
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


async def _aiterate_in_span(span: trace.Span, tokens: tuple, generator):
    try:
        async for item in generator:
            yield item
    except Exception as e:
        _record_error(span, e)
        raise
    finally:
        span.end()
        _detach_all(tokens)


def _record(span: trace.Span, attribute: str, value: Any) -> None:
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


class _ContentEncoder(json.JSONEncoder):
    """Encode what JSON cannot: by its own serializer, else as its class name."""

    def default(self, o):
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        if hasattr(o, 'to_json'):
            return o.to_json()
        if hasattr(o, 'model_dump'):
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
