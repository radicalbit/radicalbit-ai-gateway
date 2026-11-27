"""Sending a stream to the client: what the request's span says of it."""

from collections.abc import AsyncIterator

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from radicalbit_ai_gateway.endpoints.common.streams import serve_stream


async def _fails_after_first_frame() -> AsyncIterator[str]:
    yield 'first'
    raise RuntimeError('upstream gone')


async def test_a_stream_that_fails_after_it_started_marks_the_request_span():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    with provider.get_tracer('test').start_as_current_span('request'):
        frames = [
            frame
            async for frame in serve_stream(
                _fails_after_first_frame(),
                refusal=lambda exc: ('', 500),
                stream_error=lambda exc: f'error: {exc}',
            )
        ]

    # The client gets the error as the stream's last frame...
    assert frames == ['first', 'error: upstream gone']
    # ...and the trace says the request failed.
    (span,) = exporter.get_finished_spans()
    assert span.status.status_code is StatusCode.ERROR
    assert span.status.description == 'upstream gone'
    assert trace.get_current_span() is trace.INVALID_SPAN
