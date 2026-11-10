"""Talking HTTP with an Anthropic Messages API client."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
import json
import logging

from fastapi import status

from radicalbit_ai_gateway.endpoints.common import streams
from radicalbit_ai_gateway.endpoints.messages.errors import (
    is_messages_error_body,
    messages_error,
)
from radicalbit_ai_gateway.endpoints.messages.events import sse
from radicalbit_ai_gateway.llm.errors import provider_status
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


def serve_stream(
    frames: AsyncIterator[str],
) -> AsyncIterator[str | tuple[str, int]]:
    """Send a Messages stream to the client (see ``streams.serve_stream``):
    an error after the first frame ends the stream with an ``error`` event.
    """
    return streams.serve_stream(frames, refusal=_refusal, stream_error=_stream_error)


def _refusal(exc: Exception) -> tuple[str, int]:
    body, status_code = _error_body(exc)
    return json.dumps(body), status_code


def _stream_error(exc: Exception) -> str:
    logger.warning('Messages stream failed after it started', exc_info=exc)
    return sse('error', json.dumps(_error_event_body(exc)))


def _error_event_body(exc: Exception) -> dict:
    """Return the body of the ``error`` event that ends a started stream.

    An upstream Messages API error keeps its own type and message. Any other
    error is an ``api_error`` that says nothing of the gateway's internals.
    """
    if isinstance(exc, ModelInvokerUpstreamError):
        body = exc.body
    else:
        refusal = provider_status(exc)
        body = refusal[2] if refusal else None
    if is_messages_error_body(body):
        return body
    return messages_error(
        status.HTTP_500_INTERNAL_SERVER_ERROR, 'Internal server error'
    )
