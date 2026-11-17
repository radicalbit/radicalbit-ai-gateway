"""Typed errors of the SDK, one class per kind of failure.

The gateway answers errors in two shapes (``models.ErrorOut`` and
``models.HTTPValidationError``):
- ``{"error": {"message", "type", "param", "code", "details"?}}``: every error
  but the 422;
- ``{"detail": [{"loc", "msg", "type"}, ...]}``: 422, request validation.
A body in neither shape (e.g. from a proxy) is kept as it came, in ``body``.

When no answer arrives at all, the error is an ``APIConnectionError`` (an
``APITimeoutError`` when the time ran out), with ``status`` None. So one
``except GatewayError`` catches every failure of a call.
"""

import json
from typing import Any

CONFIG_VALIDATION_CODE = 'project_config_validation_error'


class GatewayError(Exception):
    """A call to the gateway failed.

    ``status`` is the HTTP status (None when no answer arrived), ``code`` the
    gateway's machine-readable code (None in the 422 shape), ``body`` the
    decoded body (or the raw text).
    """

    def __init__(self, status: int | None, code: str | None, message: str, body: Any):
        if status is None:
            text = message
        else:
            text = f'{status}: {message}' if message else str(status)
        super().__init__(text)
        self.status = status
        self.code = code
        self.message = message
        self.body = body


class APIConnectionError(GatewayError):
    """No answer: the gateway could not be reached, or the connection broke.

    Raised after the retries (``max_retries``) ran out; ``__cause__`` is the
    network error.
    """

    def __init__(self, message: str = 'Could not reach the gateway'):
        super().__init__(None, None, message, None)


class APITimeoutError(APIConnectionError):
    """No answer within the timeout (``timeout`` of the client)."""

    def __init__(self, message: str = 'The gateway did not answer in time'):
        super().__init__(message)


class AuthenticationError(GatewayError):
    """401: missing or invalid credentials."""


class AuthorizationError(GatewayError):
    """403: the caller may not do this."""


class ValidationError(GatewayError):
    """400 on an invalid gateway configuration, or 422 on an invalid request.

    ``details`` lists the problems as ``{"loc", "msg", "type"}`` dicts.
    """

    def __init__(
        self,
        status: int,
        code: str | None,
        message: str,
        body: Any,
        details: list[dict[str, Any]] | None = None,
    ):
        super().__init__(status, code, message, body)
        self.details = details or []


class NotFoundError(GatewayError):
    """404: the resource does not exist."""


class ConflictError(GatewayError):
    """409: the resource is not in a state that allows the action."""


_BY_STATUS: dict[int, type[GatewayError]] = {
    401: AuthenticationError,
    403: AuthorizationError,
    404: NotFoundError,
    409: ConflictError,
    422: ValidationError,
}


def error_from_response(status: int, content: bytes) -> GatewayError:
    """The typed error for an error response."""
    try:
        body: Any = json.loads(content)
    except ValueError:
        body = content.decode(errors='replace')

    code: str | None = None
    message = ''
    details: list[dict[str, Any]] = []
    if isinstance(body, dict) and isinstance(body.get('error'), dict):
        error = body['error']
        code = None if error.get('code') is None else str(error['code'])
        message = str(error.get('message') or '')
        details = list(error.get('details') or [])
    elif isinstance(body, dict) and isinstance(body.get('detail'), list):
        details = [
            {'loc': d.get('loc'), 'msg': d.get('msg'), 'type': d.get('type')}
            for d in body['detail']
            if isinstance(d, dict)
        ]
        message = '; '.join(str(d['msg']) for d in details)
    elif isinstance(body, str):
        message = body

    if status == 400 and code == CONFIG_VALIDATION_CODE:
        cls: type[GatewayError] = ValidationError
    else:
        cls = _BY_STATUS.get(status, GatewayError)
    if cls is ValidationError:
        return ValidationError(status, code, message, body, details)
    return cls(status, code, message, body)


__all__ = [
    'APIConnectionError',
    'APITimeoutError',
    'AuthenticationError',
    'AuthorizationError',
    'ConflictError',
    'GatewayError',
    'NotFoundError',
    'ValidationError',
    'error_from_response',
]
