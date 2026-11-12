"""Sending a stream to the client: what every streaming endpoint shares."""

from collections.abc import AsyncIterator, Callable, Iterable


async def serve_stream(
    frames: AsyncIterator[str],
    *,
    refusal: Callable[[Exception], tuple[str, int]],
    stream_error: Callable[[Exception], str],
) -> AsyncIterator[str | tuple[str, int]]:
    """Send ``frames`` to the client.

    Nothing is sent before the first frame arrives, so a call that fails
    before streaming gets an HTTP error status: ``refusal`` returns its body
    and status, sent as a ``(body, status)`` item (see
    ``StreamingResponseWithStatusCode``). After that, the 200 is sent: an
    error ends the stream with the frame ``stream_error`` returns.

    Both run in the ``except`` block that caught the error.
    """
    try:
        first = await anext(frames)
    except StopAsyncIteration:
        return
    except Exception as exc:
        yield refusal(exc)
        return

    try:
        yield first
        async for frame in frames:
            yield frame
    except Exception as exc:
        yield stream_error(exc)


async def stream_of(items: Iterable) -> AsyncIterator:
    """Return ``items``, known already, as a stream."""
    for item in items:
        yield item
