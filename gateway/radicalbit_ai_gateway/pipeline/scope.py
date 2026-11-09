from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from radicalbit_ai_gateway.caching.route_cache import Cached, RequestCache
from radicalbit_ai_gateway.guardrails.guardrails import (
    GuardrailFlags,
    RequestGuardrails,
)
from radicalbit_ai_gateway.limiting.limits import RequestLimits
from radicalbit_ai_gateway.models.request_identity import RequestIdentity

if TYPE_CHECKING:
    from radicalbit_ai_gateway.ai_gateway import GatewayRoute


@dataclass
class RequestScope:
    """One request to a route: who made it, and the route's limits,
    guardrails and cache bound to it.

    As the request goes, it records what the guardrails did (``flags``) and
    what the cache answered (``cached``): the response's headers tell both.
    """

    route: GatewayRoute
    identity: RequestIdentity
    limits: RequestLimits
    guardrails: RequestGuardrails
    cache: RequestCache
    flags: GuardrailFlags = field(default_factory=GuardrailFlags)
    cached: Cached = field(default_factory=Cached)

    def headers(self) -> dict[str, str]:
        """Return the gateway's headers: the cache's, then the guardrails'."""
        return {**self.cached.headers(), **self.flags.headers()}
