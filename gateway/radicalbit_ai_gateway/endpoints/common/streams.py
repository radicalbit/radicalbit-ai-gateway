"""Sending a stream to the client: what every streaming endpoint shares."""

from collections.abc import AsyncIterator, Callable, Iterable
from typing import TypeVar

from radicalbit_ai_gateway.endpoints.common.streaming_response import StreamRefused
from radicalbit_ai_gateway.utils.exceptions import limit_scope_headers

T = TypeVar('T')


async def serve_stream(
    frames: AsyncIterator[str],
    *,
    refusal: Callable[[Exception], tuple[str, int]],
    stream_error: Callable[[Exception], str],
) -> AsyncIterator[str]:
    """Send ``frames`` to the client.

    Nothing is sent before the first frame arrives, so a call that fails
    before streaming gets an HTTP error status: ``refusal`` returns its body
    and status, raised as ``StreamRefused`` (see
    ``StreamingResponseWithStatusCode``) with headers that name the limit
    scope that blocked, if a limit did. After that, the 200 is sent: an
    error ends the stream with the frame ``stream_error`` returns.

    Both run in the ``except`` block that caught the error.
    """
    try:
        first = await anext(frames)
    except StopAsyncIteration:
        return
    except Exception as exc:
        raise StreamRefused(*refusal(exc), limit_scope_headers(exc)) from exc

    try:
        yield first
        async for frame in frames:
            yield frame
    except Exception as exc:
        yield stream_error(exc)


async def stream_of(items: Iterable[T]) -> AsyncIterator[T]:
    """Return ``items``, known already, as a stream."""
    for item in items:
        yield item
