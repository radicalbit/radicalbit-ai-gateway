from enum import Enum
import json
import logging
from uuid import UUID

from radicalbit_ai_gateway.db.dao.alert_rule_dao import AlertRuleDAO
from radicalbit_ai_gateway.db.dao.project_dao import ProjectDAO
from radicalbit_ai_gateway.db.tables.alert_rule_table import AlertRule
from radicalbit_ai_gateway.models.alert_rule_dto import (
    AlertableEventsOut,
    AlertRuleIn,
    AlertRuleOut,
    AlertRuleTimeAggregation,
    AlertRuleUpdateIn,
)
from radicalbit_ai_gateway.models.project_entry import ProjectEntry
from radicalbit_ai_gateway.services.alert_email_formatter import (
    build_alert_email_body,
    build_alert_email_subject,
)
from radicalbit_ai_gateway.services.alertable_events import AlertableEvents
from radicalbit_ai_gateway.services.email_service import EmailService
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import (
    AlertRuleInternalError,
    AlertRuleInvalidEventError,
    AlertRuleNotFoundError,
    AlertRuleUnsupportedTimeAggregationError,
)

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)


class AlertRuleService:
    def __init__(
        self,
        alert_rule_dao: AlertRuleDAO,
        project_configs: dict[str, ProjectEntry] | None = None,
        project_dao: ProjectDAO | None = None,
        email_service: EmailService | None = None,
    ):
        self.alert_rule_dao = alert_rule_dao
        self._project_configs = project_configs if project_configs is not None else {}
        self.project_dao = project_dao
        self.email_service = email_service or EmailService()
        self.alertable_events = AlertableEvents(self._project_configs)

    def _resolve_project_name(self, project_uuid: UUID | str | None) -> str | None:
        if not project_uuid:
            return None
        target_uuid_str = str(project_uuid)
        for p_name, entry in self._project_configs.items():
            p_uuid_str = str(getattr(entry, 'uuid', ''))
            if target_uuid_str in (p_name, p_uuid_str):
                return p_name
        if self.project_dao is not None:
            try:
                p_uuid = (
                    UUID(target_uuid_str)
                    if isinstance(project_uuid, str)
                    else project_uuid
                )
                proj = self.project_dao.get_by_uuid(p_uuid)
                if proj and proj.name:
                    return proj.name
            except Exception:
                pass
        return None

    def _to_out(self, rule: AlertRule) -> AlertRuleOut:
        project_name = self._resolve_project_name(rule.project)
        stale_reason = self.alertable_events.stale_reason(
            rule.project, rule.route, rule.event
        )
        return AlertRuleOut.from_alert_rule(
            rule, project_name=project_name, stale_reason=stale_reason
        )

    def get_all_rules(self) -> list[AlertRuleOut]:
        try:
            rules = self.alert_rule_dao.get_all()
            return [self._to_out(rule) for rule in rules]
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
        if alert_rule_in.time_aggregation != AlertRuleTimeAggregation.INSTANT:
            raise AlertRuleUnsupportedTimeAggregationError(
                f'Time aggregation "{alert_rule_in.time_aggregation}" is not supported. Only "instant" is supported.'
            )

        if not self.alertable_events.offers(
            alert_rule_in.project, alert_rule_in.route, alert_rule_in.event
        ):
            raise AlertRuleInvalidEventError(
                f'Event "{alert_rule_in.event}" is not valid for route "{alert_rule_in.route}"'
            )

        try:
            entity = alert_rule_in.to_alert_rule()
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

        if (
            alert_rule_in.time_aggregation is not None
            and alert_rule_in.time_aggregation != AlertRuleTimeAggregation.INSTANT
        ):
            raise AlertRuleUnsupportedTimeAggregationError(
                f'Time aggregation "{alert_rule_in.time_aggregation}" is not supported. Only "instant" is supported.'
            )

        update_dict = alert_rule_in.model_dump(exclude_unset=True)
        if not update_dict:
            return self._to_out(existing)

        for k, v in update_dict.items():
            if isinstance(v, Enum):
                update_dict[k] = v.value

        # Handle recipients serialization if provided
        if 'recipients' in update_dict and isinstance(update_dict['recipients'], list):
            update_dict['recipients'] = json.dumps(update_dict['recipients'])

        # Validate event if route, event or project changes
        new_project = update_dict.get('project', existing.project)
        new_route = update_dict.get('route', existing.route)
        new_event = update_dict.get('event', existing.event)

        if 'route' in update_dict or 'event' in update_dict or 'project' in update_dict:
            if not self.alertable_events.offers(new_project, new_route, new_event):
                raise AlertRuleInvalidEventError(
                    f'Event "{new_event}" is not valid for route "{new_route}"'
                )

        updated = self.alert_rule_dao.update_rule(alert_rule_uuid, update_dict)
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

    def dispatch_event_notification(
        self,
        project_uuid: str,
        route_name: str,
        event_name: str,
        event_details: dict | None = None,
        project_name: str = '',
    ) -> int:
        """AG-844: Send email notifications for triggered events on a route."""
        if not project_uuid and not project_name:
            logger.error(
                'Cannot dispatch alert notification: project identification is missing for route %s',
                route_name,
            )
            return 0

        active_rules = self.alert_rule_dao.get_active_by_route(
            project_uuid=project_uuid,
            route_name=route_name,
            project_name=project_name,
        )

        target_event = event_name.strip().lower()
        matching_rules = [
            r for r in active_rules if r.event.strip().lower() == target_event
        ]

        if not matching_rules:
            return 0

        dispatched_count = 0
        for rule in matching_rules:
            rule_out = AlertRuleOut.from_alert_rule(rule)
            # TODO: Remove this check once time window aggregation (e.g. 'window') is implemented
            if rule_out.time_aggregation != AlertRuleTimeAggregation.INSTANT:
                logger.error(
                    'Time aggregation "%s" is not supported for immediate event dispatch on alert rule "%s" (%s). Only "instant" is supported.',
                    rule_out.time_aggregation.value
                    if isinstance(rule_out.time_aggregation, Enum)
                    else rule_out.time_aggregation,
                    rule.name,
                    rule.uuid,
                )
                continue

            subject = build_alert_email_subject(rule.name, route_name)
            body = build_alert_email_body(
                rule_name=rule.name,
                description=rule.description,
                project_uuid=project_uuid,
                route_name=route_name,
                event_name=event_name,
                event_details=event_details,
            )

            success = self.email_service.send_email(
                recipients=rule_out.recipients,
                subject=subject,
                body=body,
            )
            if success:
                dispatched_count += 1

        return dispatched_count
