from uuid import UUID

from radicalbit_ai_gateway.models.alert_rule_dto import (
    AlertableEventItem,
    AlertableEventsOut,
)
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.models.guardrails import GuardrailWhereType
from radicalbit_ai_gateway.models.project_entry import ProjectEntry

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


def _route_events(
    config: GatewayConfig, route: GatewayRouteConfig
) -> AlertableEventsOut:
    where_by_name = {g.name: g.where for g in config.guardrails or []}
    guardrail = [
        AlertableEventItem(
            event=_guardrail_event(phase, name),
            label=f'Guardrail: {name.upper()} ({phase})',
        )
        for name in route.guardrails or []
        for phase in _PHASES_BY_WHERE[where_by_name.get(name, GuardrailWhereType.IO)]
    ]
    fallback = (
        [AlertableEventItem(event=FALLBACK_EVENT, label='Fallback: triggered')]
        if route.fallback
        else []
    )
    return AlertableEventsOut(guardrail=guardrail, fallback=fallback)


def _event_names(events: AlertableEventsOut) -> set[str]:
    return {item.event for item in events.guardrail + events.fallback}


class AlertableEvents:
    """Which alertable events a target offers, according to what is published now.

    Reads the live `project_configs` mapping on every call, so a publish or an
    unpublish is reflected immediately.
    """

    def __init__(self, project_configs: dict[str, ProjectEntry]):
        self._project_configs = project_configs

    def for_route(self, project: UUID | str, route_name: str) -> AlertableEventsOut:
        published = self._published_route(project, route_name)
        if published is None:
            return AlertableEventsOut()
        return _route_events(*published)

    def offers(self, project: UUID | str, route_name: str, event: str) -> bool:
        published = self._published_route(project, route_name)
        return published is not None and event in _event_names(
            _route_events(*published)
        )

    def stale_reason(
        self, project: UUID | str, route_name: str, event: str
    ) -> str | None:
        """Why a route rule on `event` no longer matches the published configuration.

        Returns None when the rule is not stale.
        """
        published = self._published_route(project, route_name)
        if published is None:
            return f'Route "{route_name}" is not in the published configuration'
        if event in _event_names(_route_events(*published)):
            return None

        _, route = published
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

    def _published_route(
        self, project: UUID | str, route_name: str
    ) -> tuple[GatewayConfig, GatewayRouteConfig] | None:
        entry = self._project_entry(project)
        if entry is None:
            return None
        route = entry.config.routes.get(route_name)
        if route is None:
            return None
        return entry.config, route

    def _project_entry(self, project: UUID | str) -> ProjectEntry | None:
        """Look a project up by name or by uuid: rules may store either."""
        key = str(project)
        if key in self._project_configs:
            return self._project_configs[key]
        return next(
            (e for e in self._project_configs.values() if str(e.uuid) == key), None
        )
