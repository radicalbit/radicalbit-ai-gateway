"""Talking HTTP with an Anthropic Messages API client."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
import json
import logging

import anthropic
from fastapi import status

from radicalbit_ai_gateway.messages.errors import is_messages_error_body, messages_error
from radicalbit_ai_gateway.messages.events import sse
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import AppError, ModelInvokerUpstreamError

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)

# The client's headers that go upstream with its request. Its credential never does.
FORWARDED_HEADERS = ('anthropic-version', 'anthropic-beta')


def anthropic_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Return the client's headers to forward upstream."""
    return {name: headers[name] for name in FORWARDED_HEADERS if headers.get(name)}


def _error_body(exc: Exception) -> tuple[dict, int]:
    """Return the error body and HTTP status of a failed stream."""
    if isinstance(exc, ModelInvokerUpstreamError):
        return exc.body, exc.status_code
    if isinstance(exc, AppError):
        return messages_error(exc.status_code, exc.client_message), exc.status_code
    logger.error('Unhandled error during streaming', exc_info=exc)
    code = status.HTTP_500_INTERNAL_SERVER_ERROR
    return messages_error(code, 'Unhandled error during streaming'), code


async def serve_messages_stream(
    frames: AsyncIterator[str],
) -> AsyncIterator[str | tuple[str, int]]:
    """Send a Messages stream to the client.

    Nothing is sent before the first frame arrives, so a call that fails before
    streaming gets an HTTP error status (a ``(body, status)`` item, see
    ``StreamingResponseWithStatusCode``). After that, an error ends the stream
    with an ``error`` event.
    """
    try:
        first = await anext(frames)
    except StopAsyncIteration:
        return
    except Exception as exc:
        body, status_code = _error_body(exc)
        yield json.dumps(body), status_code
        return

    try:
        yield first
        async for frame in frames:
            yield frame
    except Exception as exc:
        logger.warning('Messages stream failed after it started', exc_info=exc)
        yield sse('error', json.dumps(_error_event_body(exc)))


def _error_event_body(exc: Exception) -> dict:
    """Return the body of the ``error`` event that ends a started stream.

    An upstream Messages API error keeps its own type and message. Any other
    error is an ``api_error`` that says nothing of the gateway's internals.
    """
    upstream = (anthropic.APIStatusError, ModelInvokerUpstreamError)
    if isinstance(exc, upstream) and is_messages_error_body(exc.body):
        return exc.body
    return messages_error(
        status.HTTP_500_INTERNAL_SERVER_ERROR, 'Internal server error'
    )
