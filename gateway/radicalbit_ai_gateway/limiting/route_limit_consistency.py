"""Credential limits looser than the routes their group reaches (AG-947).

A request through a route counts against both the route limit and the
credential limit, so a credential limit that allows more than the route does is
never reached there: the route blocks first. That is worth a warning when the
limit is saved, not an error.
"""

from collections.abc import Iterable, Mapping
from typing import NamedTuple

from radicalbit_ai_gateway.limiter.window_config import format_window, parse_window
from radicalbit_ai_gateway.models.credential_limiting import (
    CATEGORY_TO_LIMITING_FIELD,
    CredentialLimitCategory,
    CredentialLimitIn,
    RouteLimitConsistencyWarning,
)
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.models.limiting import Limiting, LimitingAlgorithmType


class LimitMax(NamedTuple):
    category: CredentialLimitCategory
    algorithm: LimitingAlgorithmType
    window_size: str
    value: float

    @staticmethod
    def of(limit_in: CredentialLimitIn) -> 'LimitMax':
        return LimitMax(
            limit_in.category,
            limit_in.algorithm,
            str(limit_in.window_size),
            limit_in.value,
        )


def route_limit_warnings(
    limits: Iterable[LimitMax], routes: Mapping[str, GatewayRouteConfig]
) -> list[RouteLimitConsistencyWarning]:
    """One warning per route and limit where the limit allows more per second."""
    limits = list(limits)
    warnings: list[RouteLimitConsistencyWarning] = []
    for route_name, route in routes.items():
        for limit in limits:
            route_limiting = _route_limiting(route, limit.category)
            if route_limiting is None:
                continue
            route_value = getattr(
                route_limiting, CATEGORY_TO_LIMITING_FIELD[limit.category]
            )
            if route_value is None:
                continue
            route_seconds = _seconds(route_limiting.window_size)
            credential_seconds = _seconds(limit.window_size)
            # value / seconds compared without dividing, so equal rates stay equal
            if limit.value * route_seconds > route_value * credential_seconds:
                warnings.append(
                    RouteLimitConsistencyWarning(
                        category=limit.category,
                        algorithm=limit.algorithm,
                        route_name=route_name,
                        credential_value=limit.value,
                        credential_window_size=limit.window_size,
                        route_value=route_value,
                        route_window_size=format_window(route_seconds),
                    )
                )
    return warnings


def _route_limiting(
    route: GatewayRouteConfig, category: CredentialLimitCategory
) -> Limiting | None:
    if category == CredentialLimitCategory.RATE:
        return route.rate_limiting
    if category == CredentialLimitCategory.BUDGET:
        return route.budget_limiting
    if route.token_limiting is None:
        return None
    if category == CredentialLimitCategory.TOKEN_INPUT:
        return route.token_limiting.input
    return route.token_limiting.output


def _seconds(window_size: int | str) -> int:
    return parse_window(window_size) if isinstance(window_size, str) else window_size
