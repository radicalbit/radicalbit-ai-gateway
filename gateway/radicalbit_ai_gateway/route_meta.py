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
