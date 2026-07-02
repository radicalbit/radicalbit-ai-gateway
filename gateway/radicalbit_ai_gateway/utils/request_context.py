"""Request-scoped route context.

A ``logging.Filter`` only sees the ``LogRecord``, not the FastAPI request. The
handler publishes the resolved route config here right after route resolution so
per-route consumers (e.g. plugins) can read it; ``reset_route_context`` clears it
when the request finishes. The core never interprets the config.
"""

from contextvars import ContextVar
from functools import wraps
from typing import Any

# Route config of the current request, or None when none is resolved. Typed as
# Any to avoid an import cycle with the model.
current_route_config_ctx: ContextVar[Any] = ContextVar(
    'current_route_config', default=None
)


def set_current_route_config(config: Any) -> None:
    current_route_config_ctx.set(config)


def reset_route_context(func):
    """Clear the route context when the handler finishes, including on error."""

    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        finally:
            current_route_config_ctx.set(None)

    return wrapper
