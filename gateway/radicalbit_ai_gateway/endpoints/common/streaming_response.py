"""StreamingResponse subclass that defers the HTTP status code decision.

A stream that cannot start raises ``StreamRefused`` before its first frame:
the response then answers with the refusal's status, headers and body, so
errors that surface on the very first chunk (e.g. invalid API key) still
produce a non-200 response. Once the first frame is sent, the status is the
response's own.

``when_sent`` runs a callback once the response is done, however it ends.
"""

from collections.abc import Awaitable, Callable, Mapping

from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send
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

    _when_sent: tuple[Callable[[], Awaitable[None]], ...] = ()

    def when_sent(self, callback: Callable[[], Awaitable[None]]) -> None:
        """Call ``callback`` once the response is done.

        It runs when the stream ends, fails or is cut short by the client.
        It runs even if the client left before the stream started.
        """
        self._when_sent = (*self._when_sent, callback)

    @override
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            for callback in self._when_sent:
                await callback()

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
