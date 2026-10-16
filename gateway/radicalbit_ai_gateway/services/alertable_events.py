from collections.abc import Callable, Iterable
from uuid import UUID

from radicalbit_ai_gateway.alerting.limit_event_names import (
    AUDIO_DURATION_LIMIT,
    BUDGET_LIMIT,
    CATEGORY_LABELS,
    RATE_LIMIT,
    TOKEN_INPUT_LIMIT,
    TOKEN_OUTPUT_LIMIT,
    exceeded_event,
    parse_limit_event,
    threshold_event,
    window_name,
)
from radicalbit_ai_gateway.limiter.window_config import parse_window
from radicalbit_ai_gateway.models.alert_rule_dto import (
    AlertableEventAggregation,
    AlertableEventItem,
    AlertableEventsOut,
)
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.models.guardrails import GuardrailWhereType
from radicalbit_ai_gateway.models.limiting import Limiting
from radicalbit_ai_gateway.models.project_entry import ProjectEntry
from radicalbit_ai_gateway.utils.app_config import get_app_config

FALLBACK_EVENT = 'fallback-triggered'
_GUARDRAIL_PREFIX = 'guardrail-'
_CACHE_PREFIX = 'cache-'

_PHASES_BY_WHERE = {
    GuardrailWhereType.INPUT: ('input',),
    GuardrailWhereType.OUTPUT: ('output',),
    GuardrailWhereType.IO: ('input', 'output'),
}


def _guardrail_event(phase: str, name: str) -> str:
    return f'{_GUARDRAIL_PREFIX}{phase}-{name}'


def allows_window_aggregation(event: str) -> bool:
    """Whether a rule on `event` may use window aggregation instead of instant."""
    return event == FALLBACK_EVENT or event.startswith(_GUARDRAIL_PREFIX)


def _window_seconds(limit: Limiting) -> int:
    size = limit.window_size
    return parse_window(size) if isinstance(size, str) else size


def _route_limits(route: GatewayRouteConfig, with_budget: bool) -> dict[str, int]:
    """Map each limit of the route that rules can watch to its window seconds.

    A project budget limit replaces the route budget, so `with_budget` is False
    when the project has one.
    """
    tokens = route.token_limiting
    limits = {
        RATE_LIMIT: route.rate_limiting,
        TOKEN_INPUT_LIMIT: tokens.input if tokens else None,
        TOKEN_OUTPUT_LIMIT: tokens.output if tokens else None,
        BUDGET_LIMIT: route.budget_limiting if with_budget else None,
        AUDIO_DURATION_LIMIT: route.duration_limiting,
    }
    return {
        category: _window_seconds(limit)
        for category, limit in limits.items()
        if limit is not None
    }


def _limit_item(event: str, label: str) -> AlertableEventItem:
    return AlertableEventItem(
        event=event, label=label, aggregation=AlertableEventAggregation.LIMIT_WINDOW
    )


def _route_events(
    config: GatewayConfig, route: GatewayRouteConfig, with_budget: bool
) -> AlertableEventsOut:
    where_by_name = {g.name: g.where for g in config.guardrails or []}
    guardrail = [
        AlertableEventItem(
            event=_guardrail_event(phase, name),
            label=f'Guardrail: {name.upper()} ({phase})',
            aggregation=AlertableEventAggregation.SELECTABLE,
        )
        for name in route.guardrails or []
        for phase in _PHASES_BY_WHERE[where_by_name.get(name, GuardrailWhereType.IO)]
    ]
    fallback = (
        [
            AlertableEventItem(
                event=FALLBACK_EVENT,
                label='Fallback: triggered',
                aggregation=AlertableEventAggregation.SELECTABLE,
            )
        ]
        if route.fallback
        else []
    )
    limit, threshold = _limit_groups(_route_limits(route, with_budget).items())
    return AlertableEventsOut(
        guardrail=guardrail, fallback=fallback, limit=limit, threshold=threshold
    )


def _limit_groups(
    limits: Iterable[tuple[str, int]],
) -> tuple[list[AlertableEventItem], list[AlertableEventItem]]:
    """Build the exceeded and threshold events of each (category, seconds) limit."""
    limits = list(limits)
    percentages = get_app_config().alert_config.alert_threshold_percentages
    limit = [
        _limit_item(
            exceeded_event(category, seconds),
            f'{CATEGORY_LABELS[category]}: exceeded ({window_name(seconds)})',
        )
        for category, seconds in limits
    ]
    threshold = [
        _limit_item(
            threshold_event(category, pct, seconds),
            f'{CATEGORY_LABELS[category]}: {pct}% ({window_name(seconds)})',
        )
        for category, seconds in limits
        for pct in percentages
    ]
    return limit, threshold


def _project_events(budget_windows: Iterable[int]) -> AlertableEventsOut:
    limit, threshold = _limit_groups(
        # Limits on the same window, by algorithm or spelling, share their events.
        (BUDGET_LIMIT, seconds)
        for seconds in sorted(set(budget_windows))
    )
    return AlertableEventsOut(limit=limit, threshold=threshold)


def _event_names(events: AlertableEventsOut) -> set[str]:
    return {
        item.event
        for item in events.guardrail + events.fallback + events.limit + events.threshold
    }


def _limit_stale_reason(
    route_name: str, route: GatewayRouteConfig, event: str, with_budget: bool
) -> str | None:
    name = parse_limit_event(event)
    if name is None:
        return None
    label = name.label.lower()
    if name.category == BUDGET_LIMIT and not with_budget:
        return f'The project budget limit replaces the budget limit of route "{route_name}"'
    seconds = _route_limits(route, with_budget).get(name.category)
    if seconds is None:
        return f'Route "{route_name}" no longer has a {label}'
    if window_name(seconds) != name.window:
        return (
            f'The {label} of route "{route_name}" no longer has a {name.window} window'
        )
    if name.percentage is not None:
        return f'Threshold {name.percentage}% is no longer configured'
    return f'Event "{event}" is not offered by route "{route_name}"'


class AlertableEvents:
    """Which alertable events a target offers, according to what is published now.

    Reads the live `project_configs` mapping on every call, so a publish or an
    unpublish is reflected immediately.
    """

    def __init__(
        self,
        project_configs: dict[str, ProjectEntry],
        project_budget_windows: Callable[[str], list[int]] = lambda _: [],
        project_exists: Callable[[str], bool] = lambda _: False,
    ):
        """`project_budget_windows` gives the window seconds of each budget limit
        stored for a project; `project_exists` says whether it is still there.
        """
        self._project_configs = project_configs
        self._project_budget_windows = project_budget_windows
        self._project_exists = project_exists

    def for_project(self, project: UUID | str | None) -> AlertableEventsOut:
        """List the project's budget events, read from the stored budget limits."""
        if not self._project_exists(str(project)):
            return AlertableEventsOut()
        return _project_events(self._project_budget_windows(str(project)))

    def offers_project(self, project: UUID | str | None, event: str) -> bool:
        return event in _event_names(self.for_project(project))

    def project_stale_reason(
        self, project: UUID | str | None, event: str
    ) -> str | None:
        """Why a project rule on `event` no longer matches the stored budget limits.

        Returns None when the rule is not stale.
        """
        if not self._project_exists(str(project)):
            return 'The project no longer exists'
        if self.offers_project(project, event):
            return None
        limit_event = parse_limit_event(event)
        if limit_event is None or limit_event.category != BUDGET_LIMIT:
            return f'Event "{event}" is not offered by the project'
        windows = {window_name(s) for s in self._project_budget_windows(str(project))}
        if limit_event.window not in windows:
            return f'The project has no budget limit with a {limit_event.window} window'
        return f'Threshold {limit_event.percentage}% is no longer configured'

    def for_route(
        self, project: UUID | str | None, route_name: str | None
    ) -> AlertableEventsOut:
        published = self._published_route(project, route_name)
        if published is None:
            return AlertableEventsOut()
        return _route_events(*published, self._with_budget(project))

    def offers(
        self, project: UUID | str | None, route_name: str | None, event: str
    ) -> bool:
        published = self._published_route(project, route_name)
        return published is not None and event in _event_names(
            _route_events(*published, self._with_budget(project))
        )

    def stale_reason(
        self, project: UUID | str | None, route_name: str | None, event: str
    ) -> str | None:
        """Why a route rule on `event` no longer matches the published configuration.

        Returns None when the rule is not stale.
        """
        published = self._published_route(project, route_name)
        if published is None:
            return f'Route "{route_name}" is not in the published configuration'
        with_budget = self._with_budget(project)
        if event in _event_names(_route_events(*published, with_budget)):
            return None

        _, route = published
        limit_reason = _limit_stale_reason(route_name, route, event, with_budget)
        if limit_reason is not None:
            return limit_reason
        if event.startswith(_CACHE_PREFIX):
            return 'Cache hits no longer trigger alerts'
        if event == FALLBACK_EVENT:
            return f'Route "{route_name}" no longer has a fallback'
        if event.startswith(_GUARDRAIL_PREFIX):
            phase, _, name = event.removeprefix(_GUARDRAIL_PREFIX).partition('-')
            if name not in (route.guardrails or []):
                return (
                    f'Guardrail "{name}" is no longer applied to route "{route_name}"'
                )
            return (
                f'Guardrail "{name}" no longer runs on {phase} of route "{route_name}"'
            )
        return f'Event "{event}" is not offered by route "{route_name}"'

    def _with_budget(self, project: UUID | str | None) -> bool:
        """Whether the route budget counts: not when the project has a budget."""
        return not self._project_budget_windows(str(project))

    def _published_route(
        self, project: UUID | str | None, route_name: str | None
    ) -> tuple[GatewayConfig, GatewayRouteConfig] | None:
        entry = self._project_entry(project)
        if entry is None:
            return None
        route = entry.config.routes.get(route_name)
        if route is None:
            return None
        return entry.config, route

    def _project_entry(self, project: UUID | str | None) -> ProjectEntry | None:
        """Look a project up by uuid. A rule still holding a project name finds none."""
        key = str(project)
        return next(
            (e for e in self._project_configs.values() if str(e.uuid) == key), None
        )
