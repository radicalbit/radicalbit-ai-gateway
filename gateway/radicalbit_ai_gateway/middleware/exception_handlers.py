"""Registering an exception handler for one exception class, typed.

Starlette types a handler as taking any ``Exception``: it cannot tell that
the handler registered for a class only ever gets instances of it. A
handler written for its class (``(Request, GatewayError) -> Response``) is
then not a valid argument of ``add_exception_handler``.
``add_exception_handler`` here takes the class and a handler of that class,
and registers a handler of any ``Exception`` that narrows to the class.
"""

from collections.abc import Awaitable, Callable
from typing import TypeVar

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response

E = TypeVar('E', bound=Exception)


def add_exception_handler(
    app: Starlette,
    exc_class: type[E],
    handler: Callable[[Request, E], Response | Awaitable[Response]],
) -> None:
    """Register ``handler`` for ``exc_class`` and its subclasses on ``app``.

    The handler is called on the event loop, its result awaited when it is
    awaitable: as the gateway's app calls every handler (see
    ``with_messages_error_shape``).
    """

    async def handle(request: Request, exc: Exception) -> Response:
        # Starlette picks the handler by the exception's class (its MRO): an
        # exception of another class never gets here.
        if not isinstance(exc, exc_class):
            raise exc
        response = handler(request, exc)
        if isinstance(response, Response):
            return response
        return await response

    app.add_exception_handler(exc_class, handle)
