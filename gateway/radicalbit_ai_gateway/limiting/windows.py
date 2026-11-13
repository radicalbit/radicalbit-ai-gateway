"""Limit windows: one counter each, owned by a route, a credential or a project."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from radicalbit_ai_gateway.limiter import (
    AlignedFixedWindowLimiter,
    BaseFixedWindowLimiter,
    FixedWindowLimiter,
    ScenarioType,
    Storage,
    WindowConfig,
)
from radicalbit_ai_gateway.models.event_payload import LimitScope
from radicalbit_ai_gateway.models.limiting import LimitingAlgorithmType
from radicalbit_ai_gateway.utils import BUDGET_MULTIPLIER

if TYPE_CHECKING:
    from radicalbit_ai_gateway.models.credential_limiting import CredentialLimitOut
    from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
    from radicalbit_ai_gateway.models.project_budget_limiting import (
        ProjectBudgetLimitOut,
    )


class Category(StrEnum):
    """What a window counts. The values are the counters' Redis key segments."""

    REQUESTS = ScenarioType.REQUEST_RATE.value
    INPUT_TOKENS = ScenarioType.TOKEN_INPUT.value
    OUTPUT_TOKENS = ScenarioType.TOKEN_OUTPUT.value
    COST = ScenarioType.BUDGET.value
    AUDIO_SECONDS = ScenarioType.AUDIO_DURATION.value


# Every route, credential and project limit a request may meet sits on one of
# these: the route slot of a credential or project key is '*'.
_ANY_ROUTE = '*'


@dataclass(frozen=True)
class Window:
    """One limit and the counter it is checked against.

    ``config`` holds the maximum in counter units (a budget in billionths of
    a dollar) and the parts of the counter's key. ``shown_value`` and
    ``shown_window`` are the limit as configured, for the messages.
    """

    scope: LimitScope
    category: Category
    config: WindowConfig
    aligned: bool
    shown_value: Any
    shown_window: str | int

    def limiter(self, storage: Storage) -> BaseFixedWindowLimiter:
        if self.aligned:
            return AlignedFixedWindowLimiter(storage)
        return FixedWindowLimiter(storage)

    @property
    def key(self) -> str:
        return self.limiter(storage=None)._build_key(self.config)


def _window(
    scope: LimitScope,
    category: Category,
    *,
    maximum: int,
    algorithm: str,
    window_size: str | int,
    owner_uuid: str,
    route_name: str,
    shown_value: Any,
) -> Window:
    return Window(
        scope=scope,
        category=category,
        config=WindowConfig.from_parts(
            limit=maximum,
            window=window_size,
            project_uuid=owner_uuid,
            route_name=route_name,
            scenario_type=ScenarioType(category.value),
        ),
        aligned=algorithm == LimitingAlgorithmType.ALIGNED_FIXED_WINDOW,
        shown_value=shown_value,
        shown_window=window_size,
    )


def route_windows(config: GatewayRouteConfig, project_uuid: str) -> tuple[Window, ...]:
    """Return a route's windows. Route names are unique only within a
    project: the project's uuid keeps two projects' routes apart.
    """
    token_limiting = config.token_limiting
    limits = (
        (Category.REQUESTS, config.rate_limiting, 'max_requests'),
        (Category.INPUT_TOKENS, token_limiting and token_limiting.input, 'max_tokens'),
        (
            Category.OUTPUT_TOKENS,
            token_limiting and token_limiting.output,
            'max_tokens',
        ),
        (Category.COST, config.budget_limiting, 'max_budget'),
        (Category.AUDIO_SECONDS, config.duration_limiting, 'max_duration_seconds'),
    )
    windows = []
    for category, limiting, field in limits:
        if limiting is None:
            continue
        shown_value = getattr(limiting, field)
        if category is Category.COST:
            maximum = limiting.max_budget_in_units
        elif category is Category.AUDIO_SECONDS:
            maximum = round(shown_value)
        else:
            maximum = shown_value
        windows.append(
            _window(
                LimitScope.ROUTE,
                category,
                maximum=maximum,
                algorithm=limiting.algorithm,
                window_size=limiting.window_size,
                owner_uuid=project_uuid,
                route_name=config.route_name,
                shown_value=shown_value,
            )
        )
    return tuple(windows)


def credential_window(
    credential_uuid: str,
    category: str,
    algorithm: str,
    window_size: str,
    value: float = 0,
) -> Window:
    """Return a credential's window: it counts across every route it calls."""
    category = Category(category)
    maximum = (
        int(value * BUDGET_MULTIPLIER) if category is Category.COST else int(value)
    )
    return _window(
        LimitScope.CREDENTIAL,
        category,
        maximum=maximum,
        algorithm=algorithm,
        window_size=window_size,
        owner_uuid=credential_uuid,
        route_name=_ANY_ROUTE,
        shown_value=value,
    )


def credential_windows(
    credential_uuid: str, limits: list[CredentialLimitOut]
) -> tuple[Window, ...]:
    return tuple(
        credential_window(
            credential_uuid,
            limit.category.value,
            limit.algorithm,
            limit.window_size,
            limit.value,
        )
        for limit in limits
    )


def project_window(
    project_uuid: str, algorithm: str, window_size: str, value: float = 0
) -> Window:
    """Return a project's budget window: it counts across all its routes."""
    return _window(
        LimitScope.PROJECT,
        Category.COST,
        maximum=int(value * BUDGET_MULTIPLIER),
        algorithm=algorithm,
        window_size=window_size,
        owner_uuid=project_uuid,
        route_name=_ANY_ROUTE,
        shown_value=value,
    )


def project_windows(
    project_uuid: str, limits: list[ProjectBudgetLimitOut]
) -> tuple[Window, ...]:
    return tuple(
        project_window(project_uuid, limit.algorithm, limit.window_size, limit.value)
        for limit in limits
    )
