"""Request-scoped route context.

A ``logging.Filter`` only sees the ``LogRecord``, not the FastAPI request. The
handler publishes the resolved route config here right after route resolution so
per-route consumers (e.g. plugins) can read it; ``reset_route_context`` clears it
when the request finishes. The core never interprets the config.

The client-supplied tags live here too: ``emit_event`` is called from deep
inside invokers, guardrails and limits, none of which hold the request.
"""

from collections.abc import AsyncIterable, AsyncIterator
from contextvars import ContextVar
from functools import wraps
import logging
from typing import Any

from starlette.responses import StreamingResponse

from radicalbit_ai_gateway.utils.app_config import get_app_config

logger = logging.getLogger(get_app_config().log_config.logger_name)

# Route config of the current request, or None when none is resolved. Typed as
# Any to avoid an import cycle with the model.
current_route_config_ctx: ContextVar[Any] = ContextVar(
    'current_route_config', default=None
)


def set_current_route_config(config: Any) -> None:
    current_route_config_ctx.set(config)


def _clear_route_context() -> None:
    current_route_config_ctx.set(None)


async def _clear_after(body: AsyncIterable[Any]) -> AsyncIterator[Any]:
    try:
        async for chunk in body:
            yield chunk
    finally:
        _clear_route_context()


def reset_route_context(func):
    """Clear the route context when the handler finishes, including on error.

    A streaming response's body runs after the handler returns and still logs
    for the route: its context is cleared when the body finishes instead.
    """

    @wraps(func)
    async def wrapper(*args, **kwargs):
        response = None
        try:
            response = await func(*args, **kwargs)
            return response
        finally:
            if isinstance(response, StreamingResponse):
                response.body_iterator = _clear_after(response.body_iterator)
            else:
                _clear_route_context()

    return wrapper


# ``key=value`` tags of the current request, or an empty tuple.
current_request_tags_ctx: ContextVar[tuple[str, ...]] = ContextVar(
    'current_request_tags', default=()
)


def set_current_request_tags(tags: tuple[str, ...]) -> None:
    current_request_tags_ctx.set(tags)


def get_current_request_tags() -> tuple[str, ...]:
    return current_request_tags_ctx.get()
