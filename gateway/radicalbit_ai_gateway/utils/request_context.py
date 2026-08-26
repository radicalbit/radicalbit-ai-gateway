"""Request-scoped route context.

A ``logging.Filter`` only sees the ``LogRecord``, not the FastAPI request. The
handler publishes the resolved route config here right after route resolution so
per-route consumers (e.g. plugins) can read it; ``reset_route_context`` clears it
when the request finishes. The core never interprets the config.

The client-supplied tags live here too: ``emit_event`` is called from deep
inside invokers, guardrails and limiters, none of which hold the request.
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


# ``key=value`` tags of the current request, or an empty tuple.
current_request_tags_ctx: ContextVar[tuple[str, ...]] = ContextVar(
    'current_request_tags', default=()
)


def set_current_request_tags(tags: tuple[str, ...]) -> None:
    current_request_tags_ctx.set(tags)


def get_current_request_tags() -> tuple[str, ...]:
    return current_request_tags_ctx.get()
