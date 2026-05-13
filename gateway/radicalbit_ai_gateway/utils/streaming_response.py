"""StreamingResponse subclass that defers the HTTP status code decision.

The generator can yield plain ``str`` content (normal chunks) or a
``(str, int)`` tuple where the second element is the desired HTTP status
code.  The status code from the **first** yielded item is used for the
``http.response.start`` ASGI message, so errors that surface on the very
first chunk (e.g. invalid API key) still produce a non-200 response.
"""

from collections.abc import AsyncIterable
import logging

from starlette.responses import StreamingResponse
from starlette.types import Send

from radicalbit_ai_gateway.utils.app_config import get_app_config

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)


class StreamingResponseWithStatusCode(StreamingResponse):
    """Like ``StreamingResponse`` but lets the generator choose the status code."""

    async def stream_response(self, send: Send) -> None:
        body_iterator: AsyncIterable[str | bytes | memoryview[int]] = self.body_iterator

        first_chunk_content: str | bytes | memoryview[int]
        status_code = self.status_code

        async for chunk in body_iterator:
            if isinstance(chunk, tuple):
                first_chunk_content, status_code = chunk
            else:
                first_chunk_content = chunk

            # Send the response start with the resolved status code
            await send(
                {
                    'type': 'http.response.start',
                    'status': status_code,
                    'headers': self.raw_headers,
                }
            )

            # Send the first chunk body
            await send(
                {
                    'type': 'http.response.body',
                    'body': first_chunk_content
                    if isinstance(first_chunk_content, bytes | memoryview)
                    else first_chunk_content.encode(self.charset or 'utf-8'),
                    'more_body': status_code < 400,
                }
            )

            # For error responses, stop after the first (error) chunk
            if status_code >= 400:
                return

            break
        else:
            # Empty iterator — send headers + empty body
            await send(
                {
                    'type': 'http.response.start',
                    'status': status_code,
                    'headers': self.raw_headers,
                }
            )
            await send(
                {
                    'type': 'http.response.body',
                    'body': b'',
                    'more_body': False,
                }
            )
            return

        # Stream remaining chunks (all plain strings at this point)
        async for chunk in body_iterator:
            if isinstance(chunk, tuple):
                # Shouldn't happen after the first chunk, but handle gracefully
                chunk = chunk[0]
            await send(
                {
                    'type': 'http.response.body',
                    'body': chunk
                    if isinstance(chunk, bytes | memoryview)
                    else chunk.encode(self.charset or 'utf-8'),
                    'more_body': True,
                }
            )

        # Final empty body to signal end of stream
        await send(
            {
                'type': 'http.response.body',
                'body': b'',
                'more_body': False,
            }
        )
