"""StreamingResponse subclass that defers the HTTP status code decision.

A stream that cannot start raises ``StreamRefused`` before its first frame:
the response then answers with the refusal's status, headers and body, so
errors that surface on the very first chunk (e.g. invalid API key) still
produce a non-200 response. Once the first frame is sent, the status is the
response's own.
"""

from collections.abc import Mapping

from starlette.responses import StreamingResponse
from starlette.types import Send
from typing_extensions import override


class StreamRefused(Exception):
    """A stream that failed before its first frame: the HTTP error to answer
    with instead.
    """

    def __init__(
        self, body: str, status_code: int, headers: Mapping[str, str] | None = None
    ) -> None:
        super().__init__(body)
        self.body = body
        self.status_code = status_code
        self.headers = dict(headers or {})


class StreamingResponseWithStatusCode(StreamingResponse):
    """Like ``StreamingResponse``, but a stream that raises ``StreamRefused``
    before its first frame answers with the refusal's status code.
    """

    def _encode(self, chunk: str | bytes | memoryview) -> bytes | memoryview:
        if isinstance(chunk, bytes | memoryview):
            return chunk
        return chunk.encode(self.charset or 'utf-8')

    async def _start(self, send: Send, status_code: int) -> None:
        await send(
            {
                'type': 'http.response.start',
                'status': status_code,
                'headers': self.raw_headers,
            }
        )

    @override
    async def stream_response(self, send: Send) -> None:
        body_iterator = aiter(self.body_iterator)
        try:
            first_chunk = await anext(body_iterator)
        except StopAsyncIteration:
            # An empty stream: headers and an empty body.
            await self._start(send, self.status_code)
            await send({'type': 'http.response.body', 'body': b'', 'more_body': False})
            return
        except StreamRefused as refused:
            # The error is the whole response.
            for name, value in refused.headers.items():
                self.headers[name] = value
            await self._start(send, refused.status_code)
            await send(
                {
                    'type': 'http.response.body',
                    'body': self._encode(refused.body),
                    'more_body': False,
                }
            )
            return

        await self._start(send, self.status_code)
        await send(
            {
                'type': 'http.response.body',
                'body': self._encode(first_chunk),
                'more_body': True,
            }
        )
        async for chunk in body_iterator:
            await send(
                {
                    'type': 'http.response.body',
                    'body': self._encode(chunk),
                    'more_body': True,
                }
            )

        # Final empty body to signal end of stream
        await send({'type': 'http.response.body', 'body': b'', 'more_body': False})
