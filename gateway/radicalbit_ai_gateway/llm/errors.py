"""What a provider's error says: the status, message and body of the HTTP
error behind it, read from each provider SDK's error type.
"""

from typing import Any

import anthropic
from google.genai import errors as genai_errors
import httpx
import openai


def provider_status(error: BaseException) -> tuple[int, str, Any] | None:
    """Return the HTTP status, message and body of a provider's ``error``.

    None when ``error`` is not a provider's HTTP error. The body is the
    provider's JSON as it sent it, or ``{'error': {'message': ...}}`` when it
    sent none.
    """
    if isinstance(error, openai.APIStatusError | anthropic.APIStatusError):
        return error.status_code, error.message, _json(error.response, error.message)
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code, str(error), _json(error.response, str(error))
    if isinstance(error, genai_errors.APIError):
        body = error.details if isinstance(error.details, dict) else None
        return error.code, error.message, body or {'error': {'message': str(error)}}
    return None


def _json(response: httpx.Response, message: str) -> Any:
    try:
        return response.json()
    except ValueError:
        return {'error': {'message': message}}
