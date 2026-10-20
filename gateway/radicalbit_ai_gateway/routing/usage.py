from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from radicalbit_ai_gateway.models.model import Model


@dataclass(frozen=True)
class RoutingUsage:
    """Tokens a router spent on a model of its own to select the route's model.

    The router call is part of the request's spend: the gateway costs it in
    Usage and counts it against the request's limits.
    """

    model: Model
    model_type: str
    latency_ms: float
    input_tokens: int
    output_tokens: int | None = None


OnRoutingUsage = Callable[[RoutingUsage], Awaitable[None]]
