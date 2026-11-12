"""Sending a Responses API stream to the client."""

from __future__ import annotations

from collections.abc import AsyncIterator
import json
import logging
import re

from radicalbit_ai_gateway.endpoints.common import streams
from radicalbit_ai_gateway.endpoints.responses.events import sse
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import AppError, ModelInvokerUpstreamError

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)


def _error_body(exc: Exception) -> tuple[str, int]:
    """Return the HTTP error body and status of a request that failed before streaming."""
    if isinstance(exc, ModelInvokerUpstreamError):
        return json.dumps(exc.body), exc.status_code
    if isinstance(exc, AppError):
        error = {
            'message': exc.client_message,
            'type': 'model_invoker_error',
            'param': None,
            'code': exc.code or exc.status_code,
        }
        return json.dumps({'error': error}), exc.status_code
    logger.error('Unhandled error during streaming', exc_info=exc)
    error = {
        'message': 'Unhandled error during streaming',
        'type': 'internal_error',
        'param': None,
        'code': 500,
    }
    return json.dumps({'error': error}), 500


def _error_event(exc: Exception, sequence_number: int) -> str:
    body, status_code = _error_body(exc)
    error = json.loads(body).get('error') or {}
    return sse(
        {
            'type': 'error',
            'code': str(error.get('code') or status_code),
            'message': error.get('message') or 'Error during streaming',
            'param': error.get('param'),
            'sequence_number': sequence_number,
        }
    )


_SEQUENCE_NUMBER = re.compile(r'"sequence_number":\s*(\d+)')


def _next_sequence_number(frame: str, current: int) -> int:
    """Return the sequence number after ``frame``'s, read without parsing it."""
    numbers = _SEQUENCE_NUMBER.findall(frame)
    return int(numbers[-1]) + 1 if numbers else current


def serve_stream(
    frames: AsyncIterator[str],
) -> AsyncIterator[str | tuple[str, int, dict[str, str]]]:
    """Send a Responses stream to the client (see ``streams.serve_stream``):
    an error after the first frame ends the stream with an ``error`` event
    that follows the last frame's sequence number.
    """
    sequence_number = 0

    async def numbered() -> AsyncIterator[str]:
        nonlocal sequence_number
        async for frame in frames:
            sequence_number = _next_sequence_number(frame, sequence_number)
            yield frame

    def stream_error(exc: Exception) -> str:
        logger.warning('Responses stream failed after it started: %s', exc)
        return _error_event(exc, sequence_number)

    return streams.serve_stream(
        numbered(), refusal=_error_body, stream_error=stream_error
    )
