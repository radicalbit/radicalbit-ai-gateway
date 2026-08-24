"""Middleware package for Radicalbit AI Gateway."""

# RequestEventMiddleware is deliberately not re-exported here. It imports
# utils.exceptions, which imports RequestEventContext from this package, so an
# eager import would make the package circular. Import it from
# radicalbit_ai_gateway.middleware.request_event_middleware instead, as
# server.py does.
from radicalbit_ai_gateway.middleware.request_event_context import (
    RequestEventContext,
)

__all__ = [
    'RequestEventContext',
]
