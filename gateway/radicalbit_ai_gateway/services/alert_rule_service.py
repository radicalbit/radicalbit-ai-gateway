from collections.abc import Mapping
import logging
from typing import Any
from uuid import UUID

from radicalbit_ai_gateway.alerting.limit_event_names import parse_limit_event
from radicalbit_ai_gateway.db.dao.alert_rule_dao import AlertRuleDAO
from radicalbit_ai_gateway.db.dao.key_dao import KeyDAO
from radicalbit_ai_gateway.db.dao.project_budget_limit_dao import ProjectBudgetLimitDAO
from radicalbit_ai_gateway.db.dao.project_dao import ProjectDAO
from radicalbit_ai_gateway.db.tables.alert_rule_table import AlertRule
from radicalbit_ai_gateway.models.alert_rule_dto import (
    AlertableEventsOut,
    AlertRuleIn,
    AlertRuleOut,
    AlertRuleScope,
    AlertRuleTimeAggregation,
    AlertRuleUpdateIn,
)
from radicalbit_ai_gateway.models.project_entry import ProjectEntry
from radicalbit_ai_gateway.services.alertable_events import AlertableEvents
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import (
    AlertRuleInternalError,
    AlertRuleInvalidEventError,
    AlertRuleInvalidTargetError,
    AlertRuleNotFoundError,
    AlertRuleUnsupportedTimeAggregationError,
)

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)

# Valid, but not dispatched yet: rules using them are refused until they are.
_UNSUPPORTED_SCOPES = {AlertRuleScope.PROJECT, AlertRuleScope.CREDENTIAL}
_UNSUPPORTED_AGGREGATIONS = {AlertRuleTimeAggregation.WINDOW}

# Changing any of these can change which events the rule's target offers.
_EVENT_IDENTITY_FIELDS = {'scope', 'project', 'route', 'credential_uuid', 'event'}


def _rule_fields(rule: AlertRule) -> dict[str, Any]:
    return {
        'scope': rule.scope,
        'project': rule.project,
        'route': rule.route,
        'credential_uuid': rule.credential_uuid,
        'event': rule.event,
        'time_aggregation': rule.time_aggregation,
        'window_size': rule.window_size,
    }


def _check_target(fields: Mapping[str, Any]) -> None:
    """Raise if the scope and its target do not fit together."""
    scope = AlertRuleScope(fields['scope'])
    project, route, credential = (
        fields.get('project'),
        fields.get('route'),
        fields.get('credential_uuid'),
    )
    if scope is AlertRuleScope.ROUTE:
        if not project or not route:
            raise AlertRuleInvalidTargetError(
                'A route rule requires a project and a route'
            )
        if credential:
            raise AlertRuleInvalidTargetError('A route rule takes no credential')
    elif scope is AlertRuleScope.PROJECT:
        if not project:
            raise AlertRuleInvalidTargetError('A project rule requires a project')
        if route or credential:
            raise AlertRuleInvalidTargetError(
                'A project rule takes no route and no credential'
            )
    elif scope is AlertRuleScope.CREDENTIAL:
        if not credential:
            raise AlertRuleInvalidTargetError('A credential rule requires a credential')
        if project or route:
            raise AlertRuleInvalidTargetError(
                'A credential rule takes no project and no route'
            )
    if scope in _UNSUPPORTED_SCOPES:
        raise AlertRuleInvalidTargetError(f'Scope "{scope.value}" is not supported yet')


def _check_aggregation(fields: Mapping[str, Any]) -> None:
    """Raise if the aggregation and the window size do not fit together."""
    aggregation = AlertRuleTimeAggregation(fields['time_aggregation'])
    window_size = fields.get('window_size')
    if aggregation is AlertRuleTimeAggregation.WINDOW and not window_size:
        raise AlertRuleUnsupportedTimeAggregationError(
            'A window size is required with window aggregation'
        )
    if aggregation is not AlertRuleTimeAggregation.WINDOW and window_size:
        raise AlertRuleUnsupportedTimeAggregationError(
            'A window size applies only to window aggregation'
        )
    is_limit_event = parse_limit_event(fields['event']) is not None
    if is_limit_event and aggregation is not AlertRuleTimeAggregation.LIMIT_WINDOW:
        raise AlertRuleUnsupportedTimeAggregationError(
            'Limit and threshold events take only the limit_window aggregation'
        )
    if not is_limit_event and aggregation is AlertRuleTimeAggregation.LIMIT_WINDOW:
        raise AlertRuleUnsupportedTimeAggregationError(
            'The limit_window aggregation applies only to limit and threshold events'
        )
    if aggregation in _UNSUPPORTED_AGGREGATIONS:
        raise AlertRuleUnsupportedTimeAggregationError(
            f'Time aggregation "{aggregation.value}" is not supported yet'
        )


class AlertRuleService:
    def __init__(
        self,
        alert_rule_dao: AlertRuleDAO,
        project_configs: dict[str, ProjectEntry] | None = None,
        project_dao: ProjectDAO | None = None,
        key_dao: KeyDAO | None = None,
        project_budget_limit_dao: ProjectBudgetLimitDAO | None = None,
    ):
        self.alert_rule_dao = alert_rule_dao
        self._project_configs = project_configs if project_configs is not None else {}
        self.project_dao = project_dao
        self.key_dao = key_dao
        self.project_budget_limit_dao = project_budget_limit_dao
        self.alertable_events = AlertableEvents(
            self._project_configs, project_has_budget=self._project_has_budget
        )

    def _project_has_budget(self, project_uuid: str) -> bool:
        if self.project_budget_limit_dao is None:
            return False
        return bool(
            self.project_budget_limit_dao.get_by_project_uuid(UUID(project_uuid))
        )

    def _resolve_project_name(self, project_uuid: str | None) -> str | None:
        if not project_uuid:
            return None
        for p_name, entry in self._project_configs.items():
            if str(entry.uuid) == project_uuid:
                return p_name
        if self.project_dao is not None:
            try:
                proj = self.project_dao.get_by_uuid(UUID(project_uuid))
                if proj and proj.name:
                    return proj.name
            except Exception:
                pass
        return None

    def _credential_names(self, rules: list[AlertRule]) -> dict[UUID, str]:
        uuids = [r.credential_uuid for r in rules if r.credential_uuid]
        if not uuids or self.key_dao is None:
            return {}
        return self.key_dao.get_names_by_uuids(uuids)

    def _stale_reason(self, rule: AlertRule) -> str | None:
        if AlertRuleScope(rule.scope) is not AlertRuleScope.ROUTE:
            return None
        return self.alertable_events.stale_reason(rule.project, rule.route, rule.event)

    def _to_out(
        self, rule: AlertRule, credential_names: Mapping[UUID, str] | None = None
    ) -> AlertRuleOut:
        if credential_names is None:
            credential_names = self._credential_names([rule])
        return AlertRuleOut.from_alert_rule(
            rule,
            project_name=self._resolve_project_name(rule.project),
            credential_name=credential_names.get(rule.credential_uuid),
            stale_reason=self._stale_reason(rule),
        )

    def _check_event(self, fields: Mapping[str, Any]) -> None:
        if not self.alertable_events.offers(
            fields['project'], fields['route'], fields['event']
        ):
            raise AlertRuleInvalidEventError(
                f'Event "{fields["event"]}" is not valid for route "{fields["route"]}"'
            )

    def get_all_rules(self) -> list[AlertRuleOut]:
        try:
            rules = list(self.alert_rule_dao.get_all())
            credential_names = self._credential_names(rules)
            return [self._to_out(rule, credential_names) for rule in rules]
        except Exception as e:
            logger.exception('Failed to fetch alert rules')
            raise AlertRuleInternalError(f'Failed to fetch alert rules: {e}') from e

    def get_rule_by_uuid(self, alert_rule_uuid: UUID) -> AlertRuleOut:
        rule = self.alert_rule_dao.get_by_uuid(alert_rule_uuid)
        if not rule:
            raise AlertRuleNotFoundError(
                f'Alert rule with UUID {alert_rule_uuid} not found'
            )
        return self._to_out(rule)

    def get_alertable_events_for_route(
        self, project_uuid: UUID | str, route_name: str
    ) -> AlertableEventsOut:
        return self.alertable_events.for_route(project_uuid, route_name)

    def create_rule(self, alert_rule_in: AlertRuleIn) -> AlertRuleOut:
        entity = alert_rule_in.to_alert_rule()
        fields = _rule_fields(entity)
        _check_target(fields)
        _check_aggregation(fields)
        self._check_event(fields)

        try:
            inserted = self.alert_rule_dao.insert(entity)
            logger.info('Created alert rule %s (%s)', inserted.name, inserted.uuid)
            return self._to_out(inserted)
        except Exception as e:
            logger.exception('Failed to create alert rule')
            raise AlertRuleInternalError(f'Failed to create alert rule: {e}') from e

    def update_rule(
        self, alert_rule_uuid: UUID, alert_rule_in: AlertRuleUpdateIn
    ) -> AlertRuleOut:
        existing = self.alert_rule_dao.get_by_uuid(alert_rule_uuid)
        if not existing:
            raise AlertRuleNotFoundError(
                f'Alert rule with UUID {alert_rule_uuid} not found'
            )

        update_fields = alert_rule_in.to_update_fields()
        if not update_fields:
            return self._to_out(existing)

        merged = {**_rule_fields(existing), **update_fields}
        _check_target(merged)
        _check_aggregation(merged)
        # A stale rule can still be renamed: the event is checked only when the
        # client changes what it identifies.
        if _EVENT_IDENTITY_FIELDS & update_fields.keys():
            self._check_event(merged)

        updated = self.alert_rule_dao.update_rule(alert_rule_uuid, update_fields)
        if not updated:
            raise AlertRuleNotFoundError(
                f'Alert rule with UUID {alert_rule_uuid} not found'
            )

        logger.info('Updated alert rule %s (%s)', updated.name, updated.uuid)
        return self._to_out(updated)

    def toggle_rule_enabled(self, alert_rule_uuid: UUID, enabled: bool) -> AlertRuleOut:
        existing = self.alert_rule_dao.get_by_uuid(alert_rule_uuid)
        if not existing:
            raise AlertRuleNotFoundError(
                f'Alert rule with UUID {alert_rule_uuid} not found'
            )

        updated = self.alert_rule_dao.toggle_enabled(alert_rule_uuid, enabled)
        if not updated:
            raise AlertRuleNotFoundError(
                f'Alert rule with UUID {alert_rule_uuid} not found'
            )

        logger.info('Toggled alert rule %s enabled to %s', alert_rule_uuid, enabled)
        return self._to_out(updated)

    def delete_rule(self, alert_rule_uuid: UUID) -> AlertRuleOut:
        deleted = self.alert_rule_dao.soft_delete_by_uuid(alert_rule_uuid)
        if not deleted:
            raise AlertRuleNotFoundError(
                f'Alert rule with UUID {alert_rule_uuid} not found'
            )

        logger.info('Soft deleted alert rule %s', alert_rule_uuid)
        return self._to_out(deleted)
