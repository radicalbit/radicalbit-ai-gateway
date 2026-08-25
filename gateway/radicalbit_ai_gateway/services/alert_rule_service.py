from enum import Enum
import json
import logging
from uuid import UUID

from radicalbit_ai_gateway.db.dao.alert_rule_dao import AlertRuleDAO
from radicalbit_ai_gateway.db.dao.project_dao import ProjectDAO
from radicalbit_ai_gateway.db.tables.alert_rule_table import AlertRule
from radicalbit_ai_gateway.models.alert_rule_dto import (
    AlertableEventItem,
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

    def _resolve_project_name(self, project_identifier: str) -> str | None:
        if not project_identifier:
            return None
        for p_name, entry in self._project_configs.items():
            p_uuid_str = str(getattr(entry, 'uuid', ''))
            if project_identifier in (p_name, p_uuid_str):
                return p_name
        if self.project_dao is not None:
            try:
                p_uuid = UUID(project_identifier)
                proj = self.project_dao.get_by_uuid(p_uuid)
                if proj and proj.name:
                    return proj.name
            except Exception:
                pass
        return None

    def _to_out(self, rule: AlertRule) -> AlertRuleOut:
        project_name = self._resolve_project_name(rule.project)
        return AlertRuleOut.from_alert_rule(rule, project_name=project_name)

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
        self, project_name: str | None = None, route_name: str | None = None
    ) -> AlertableEventsOut:
        guardrails_items: list[AlertableEventItem] = []
        caching_items: list[AlertableEventItem] = []
        fallback_items: list[AlertableEventItem] = []

        resolved_project = (
            self._resolve_project_name(project_name) if project_name else None
        )
        project_key = resolved_project or project_name

        # Inspect route config if available
        if project_key and route_name and project_key in self._project_configs:
            entry = self._project_configs[project_key]
            if entry and entry.config and entry.config.routes:
                route_cfg = entry.config.routes.get(route_name)
                if route_cfg:
                    # Resolve configured guardrails
                    if getattr(route_cfg, 'guardrails', None):
                        guardrails_by_name = {
                            g.name: g
                            for g in (getattr(entry.config, 'guardrails', None) or [])
                            if hasattr(g, 'name')
                        }
                        for g in route_cfg.guardrails:
                            g_name = (
                                g if isinstance(g, str) else getattr(g, 'name', str(g))
                            )
                            g_def = guardrails_by_name.get(g_name)
                            where_attr = (
                                getattr(g_def, 'where', 'IO') if g_def else 'IO'
                            )
                            where_val = (
                                where_attr.value.upper()
                                if hasattr(where_attr, 'value')
                                else str(where_attr).upper()
                            )

                            if any(k in where_val for k in ('INPUT', 'IO', 'BOTH')):
                                guardrails_items.append(
                                    AlertableEventItem(
                                        event=f'guardrail-input-{g_name}',
                                        label=f'Guardrail: {g_name.upper()} (input)',
                                    )
                                )
                            if any(k in where_val for k in ('OUTPUT', 'IO', 'BOTH')):
                                guardrails_items.append(
                                    AlertableEventItem(
                                        event=f'guardrail-output-{g_name}',
                                        label=f'Guardrail: {g_name.upper()} (output)',
                                    )
                                )

                    # Resolve caching
                    if getattr(route_cfg, 'caching', None):
                        cache_type = str(
                            getattr(route_cfg.caching, 'type', 'exact')
                        ).lower()
                        if cache_type == 'semantic':
                            caching_items.append(
                                AlertableEventItem(
                                    event='cache-semantic',
                                    label='Caching: semantic match',
                                )
                            )
                        else:
                            caching_items.append(
                                AlertableEventItem(
                                    event='cache-exact',
                                    label='Caching: exact match',
                                )
                            )

                    # Resolve fallback
                    if getattr(route_cfg, 'fallback', None):
                        fallback_items.append(
                            AlertableEventItem(
                                event='fallback-triggered',
                                label='Fallback: triggered',
                            )
                        )

        return AlertableEventsOut(
            guardrail=guardrails_items,
            caching=caching_items,
            fallback=fallback_items,
        )

    def _get_valid_events_list(
        self, project_name: str | None, route_name: str | None
    ) -> set[str]:
        events_out = self.get_alertable_events_for_route(project_name, route_name)
        valid_set = set()
        for item in events_out.guardrail + events_out.caching + events_out.fallback:
            valid_set.add(item.event)
        return valid_set

    def create_rule(self, alert_rule_in: AlertRuleIn) -> AlertRuleOut:
        if alert_rule_in.time_aggregation != AlertRuleTimeAggregation.INSTANT:
            raise AlertRuleUnsupportedTimeAggregationError(
                f'Time aggregation "{alert_rule_in.time_aggregation}" is not supported. Only "instant" is supported.'
            )

        valid_events = self._get_valid_events_list(
            alert_rule_in.project, alert_rule_in.route
        )
        if alert_rule_in.event not in valid_events:
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
            valid_events = self._get_valid_events_list(new_project, new_route)
            if new_event not in valid_events:
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

        updated = self.alert_rule_dao.toggle_enabled(
            alert_rule_uuid, enabled, clear_disabled_reason=True
        )
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

    def validate_rules_on_config_change(
        self,
        project_name: str,
        route_name: str | None = None,
        project_uuid: str = '',
    ) -> int:
        """AG-843: Check active rules when config changes.

        Auto-disable any rule whose route no longer exists or whose event is no longer valid.
        """
        resolved_project = (
            self._resolve_project_name(project_name) if project_name else None
        )
        project_key = resolved_project or project_name
        entry = self._project_configs.get(project_key) if project_key else None
        valid_routes = (
            set(entry.config.routes.keys())
            if (entry and entry.config and entry.config.routes)
            else set()
        )

        if route_name:
            active_rules = self.alert_rule_dao.get_active_by_route(
                project_name=project_name,
                route_name=route_name,
                project_uuid=project_uuid,
            )
        else:
            active_rules = self.alert_rule_dao.get_active_by_project(
                project_name=project_name,
                project_uuid=project_uuid,
            )

        if not active_rules:
            return 0

        disabled_count = 0
        for rule in active_rules:
            # 1. Check if the route itself was deleted from the config
            if rule.route not in valid_routes:
                reason = f'The route "{rule.route}" no longer exists in the current project configuration'
                self.alert_rule_dao.auto_disable_rule(rule.uuid, reason)
                disabled_count += 1
                logger.warning(
                    'Auto-disabled alert rule %s (%s) due to deleted route: %s',
                    rule.name,
                    rule.uuid,
                    reason,
                )
                continue

            # 2. Check if the event is no longer valid for the route
            valid_events = self._get_valid_events_list(project_name, rule.route)
            if rule.event not in valid_events:
                reason = f'The event "{rule.event}" is no longer valid for the current route configuration'
                self.alert_rule_dao.auto_disable_rule(rule.uuid, reason)
                disabled_count += 1
                logger.warning(
                    'Auto-disabled alert rule %s (%s) due to config change: %s',
                    rule.name,
                    rule.uuid,
                    reason,
                )

        return disabled_count

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
