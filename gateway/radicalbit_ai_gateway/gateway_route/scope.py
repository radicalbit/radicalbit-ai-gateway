from __future__ import annotations

from typing import TYPE_CHECKING

from radicalbit_ai_gateway.caching.route_cache import Cached, RequestCache
from radicalbit_ai_gateway.guardrails.guardrails import (
    GuardrailFlags,
    RequestGuardrails,
)
from radicalbit_ai_gateway.limiting.limits import RequestLimits
from radicalbit_ai_gateway.models.request_identity import RequestIdentity

if TYPE_CHECKING:
    from radicalbit_ai_gateway.gateway_route.route import GatewayRoute


class RequestScope:
    """One request to a route: who made it, and the route's limits,
    guardrails and cache bound to it.

    As the request goes, it records what the guardrails did (``flags``) and
    what the cache answered (``cached``): the response's headers tell both.

    Not a dataclass: tracing writes the arguments of a traced function to
    its span, and a dataclass is deep-copied field by field, the route and
    its loaded NLP models with it. Tracing records a scope by ``to_json``.
    """

    def __init__(
        self,
        route: GatewayRoute,
        identity: RequestIdentity,
        limits: RequestLimits,
        guardrails: RequestGuardrails,
        cache: RequestCache,
    ) -> None:
        self.route = route
        self.identity = identity
        self.limits = limits
        self.guardrails = guardrails
        self.cache = cache
        self.flags = GuardrailFlags()
        self.cached = Cached()

    def headers(self) -> dict[str, str]:
        """Return the gateway's headers: the cache's, then the guardrails'."""
        return {**self.cached.headers(), **self.flags.headers()}

    def to_json(self) -> str:
        """Return what a span records for the request: the route, by its
        class name, as when the traced functions were the route's methods.
        """
        return type(self.route).__name__
