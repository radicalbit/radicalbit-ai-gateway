"""Errors in the shape Anthropic Messages API clients read.

Every error the gateway raises on ``/v1/messages`` reaches the client as
``{"type": "error", "error": {"type": ..., "message": ...}}``, its type taken
from the HTTP status. An upstream's own refusal is relayed as it came.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
import inspect
import json
from typing import Any

from fastapi import status
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from radicalbit_ai_gateway.utils.exceptions import (
    ModelInvokerUpstreamError,
    validation_error_param,
)

MESSAGES_PATH = '/v1/messages'

_ERROR_TYPES = {
    400: 'invalid_request_error',
    401: 'authentication_error',
    403: 'permission_error',
    404: 'not_found_error',
    413: 'request_too_large',
    429: 'rate_limit_error',
}


def error_type(status_code: int) -> str:
    """Return the Anthropic error type of an HTTP status."""
    if status_code >= 500:
        return 'api_error'
    return _ERROR_TYPES.get(status_code, 'invalid_request_error')


def messages_error(status_code: int, message: str) -> dict:
    """Return a Messages API error body."""
    return {
        'type': 'error',
        'error': {'type': error_type(status_code), 'message': message},
    }


def is_messages_request(request: Request) -> bool:
    path = request.url.path
    return path == MESSAGES_PATH or path.startswith(f'{MESSAGES_PATH}/')


def _json_body(response: Response) -> object:
    """Return the parsed JSON body of ``response``, or ``None`` if it has none."""
    try:
        return json.loads(bytes(response.body))
    except (AttributeError, ValueError):
        return None


def _message_of(response: Response) -> str:
    """Return the human-readable message of a gateway error response."""
    body = _json_body(response)
    if isinstance(body, dict):
        error = body.get('error')
        if isinstance(error, dict) and error.get('message'):
            return str(error['message'])
        if isinstance(body.get('detail'), str):
            return body['detail']
    return 'Error'


def is_messages_error_body(body: object) -> bool:
    """Whether ``body`` is already an error in the Messages API shape."""
    return isinstance(body, dict) and body.get('type') == 'error'


def _is_messages_error(response: Response) -> bool:
    return is_messages_error_body(_json_body(response))


def _validation_error(exc: RequestValidationError) -> JSONResponse:
    """Return a request validation error as Messages API clients read it: a 400."""
    errors = exc.errors()
    first = errors[0] if errors else {}
    param = validation_error_param(first)
    message = first.get('msg') or 'Invalid request body'
    code = status.HTTP_400_BAD_REQUEST
    return JSONResponse(
        status_code=code,
        content=messages_error(code, f'{param}: {message}' if param else message),
    )


def with_messages_error_shape(handler: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap an exception handler so it answers ``/v1/messages`` in the Messages shape.

    The status and headers the handler chose are kept. A request validation
    error is a 400, as on Anthropic's API. An upstream's refusal is relayed
    as it came.
    """

    @wraps(handler)
    async def wrapper(request: Request, exc: Exception) -> Response:
        response = handler(request, exc)
        if inspect.isawaitable(response):
            response = await response
        if not is_messages_request(request):
            return response
        if isinstance(exc, RequestValidationError):
            return _validation_error(exc)
        if isinstance(exc, ModelInvokerUpstreamError) or _is_messages_error(response):
            return response
        headers = {
            name: value
            for name, value in response.headers.items()
            if name.lower() not in ('content-length', 'content-type')
        }
        return JSONResponse(
            status_code=response.status_code,
            content=messages_error(response.status_code, _message_of(response)),
            headers=headers,
        )

    return wrapper


def with_messages_error_shapes(
    handlers: dict[Any, Callable[..., Any]],
) -> dict[Any, Callable[..., Any]]:
    """Return ``handlers``, each wrapped by ``with_messages_error_shape``."""
    return {
        key: with_messages_error_shape(handler) for key, handler in handlers.items()
    }
