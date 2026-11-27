"""The streaming response that defers its status code to the first frame."""

from collections.abc import AsyncIterator, MutableMapping
from typing import Any

from radicalbit_ai_gateway.endpoints.common.streaming_response import (
    StreamingResponseWithStatusCode,
)


async def _sent(response: StreamingResponseWithStatusCode) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []

    async def send(message: MutableMapping[str, Any]) -> None:
        messages.append(dict(message))

    await response.stream_response(send)
    return messages


async def test_bytes_and_memoryview_chunks_are_sent_as_they_are():
    raw = b'data: 1\n\n'
    view = memoryview(b'data: 2\n\n')

    async def frames() -> AsyncIterator[str | bytes | memoryview]:
        yield raw
        yield view
        yield 'data: 3\n\n'

    messages = await _sent(StreamingResponseWithStatusCode(frames()))

    bodies = [m['body'] for m in messages if m['type'] == 'http.response.body']
    assert bodies[0] is raw
    assert bodies[1] is view
    assert bodies[2:] == [b'data: 3\n\n', b'']


async def test_an_empty_stream_sends_its_headers_and_an_empty_body():
    async def frames() -> AsyncIterator[str]:
        return
        yield

    response = StreamingResponseWithStatusCode(
        frames(), status_code=202, headers={'x-trace': 't-1'}
    )
    messages = await _sent(response)

    start, body = messages
    assert start['type'] == 'http.response.start'
    assert start['status'] == 202
    assert (b'x-trace', b't-1') in start['headers']
    assert body == {'type': 'http.response.body', 'body': b'', 'more_body': False}
