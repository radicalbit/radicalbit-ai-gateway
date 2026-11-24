from collections.abc import Callable
from typing import Any, TypeVar

F = TypeVar('F', bound=Callable[..., Any])


def route_meta(**kwargs: Any) -> Callable[[F], F]:
    """Attach arbitrary metadata to a route handler.

    No-op at runtime. Consumers read the ``_route_meta`` dict from the
    wrapped function.
    """

    def decorator(func: F) -> F:
        func.__dict__['_route_meta'] = kwargs
        return func

    return decorator


def read_route_meta(func: Callable[..., Any]) -> dict[str, Any] | None:
    """Return the metadata ``route_meta`` attached to ``func``, or None."""
    meta = getattr(func, '_route_meta', None)
    return meta if isinstance(meta, dict) else None
