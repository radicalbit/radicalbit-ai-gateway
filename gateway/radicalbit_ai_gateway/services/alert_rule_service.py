import json
import logging
from uuid import UUID

from radicalbit_ai_gateway.db.dao.alert_rule_dao import AlertRuleDAO
from radicalbit_ai_gateway.db.tables.alert_rule_table import AlertRule
from radicalbit_ai_gateway.models.alert_rule_dto import (
    AlertableEventItem,
    AlertableEventsOut,
    AlertRuleIn,
    AlertRuleOut,
    AlertRuleUpdateIn,
)
from radicalbit_ai_gateway.models.project_entry import ProjectEntry
from radicalbit_ai_gateway.services.email_service import EmailService
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import (
    AlertRuleInternalError,
    AlertRuleNotFoundError,
)

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)


class AlertRuleService:
    def __init__(
        self,
        alert_rule_dao: AlertRuleDAO,
        project_configs: dict[str, ProjectEntry] | None = None,
        email_service: EmailService | None = None,
    ):
        self.alert_rule_dao = alert_rule_dao
        self._project_configs = project_configs if project_configs is not None else {}
        self.email_service = email_service or EmailService()

    def _resolve_project_name(self, project_identifier: str) -> str:
        if not project_identifier:
            return project_identifier
        for key, entry in self._project_configs.items():
            if (
                str(key) == project_identifier
                or getattr(entry, 'project_uuid', None) == project_identifier
            ):
                if entry.config and getattr(entry.config, 'project_name', None):
                    return entry.config.project_name
        return project_identifier

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
        caching_items: list[AlertableEventItem] = [
            AlertableEventItem(event='cache-exact', label='Caching: exact match'),
            AlertableEventItem(event='cache-semantic', label='Caching: semantic match'),
        ]
        fallback_items: list[AlertableEventItem] = [
            AlertableEventItem(event='fallback-triggered', label='Fallback: triggered'),
        ]

        # Inspect route config if available
        if project_name and route_name and project_name in self._project_configs:
            entry = self._project_configs[project_name]
            route_cfg = (
                entry.config.routes.get(route_name) if entry and entry.config else None
            )
            if route_cfg:
                # Add input guardrails if any
                if getattr(route_cfg, 'guardrails', None):
                    for g in route_cfg.guardrails:
                        g_name = getattr(g, 'name', 'pii')
                        guardrails_items.append(
                            AlertableEventItem(
                                event=f'guardrail-input-{g_name}',
                                label=f'Guardrail: {g_name.upper()} (input)',
                            )
                        )
                        guardrails_items.append(
                            AlertableEventItem(
                                event=f'guardrail-output-{g_name}',
                                label=f'Guardrail: {g_name.upper()} (output)',
                            )
                        )

        # Default fallback items if no specific guardrails were derived
        if not guardrails_items:
            guardrails_items = [
                AlertableEventItem(
                    event='guardrail-input-pii', label='Guardrail: PII (input)'
                ),
                AlertableEventItem(
                    event='guardrail-input-toxicity',
                    label='Guardrail: Toxicity (input)',
                ),
                AlertableEventItem(
                    event='guardrail-output-pii', label='Guardrail: PII (output)'
                ),
                AlertableEventItem(
                    event='guardrail-output-toxicity',
                    label='Guardrail: Toxicity (output)',
                ),
            ]

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
        try:
            # Validate event against route alertable events
            valid_events = self._get_valid_events_list(
                alert_rule_in.project, alert_rule_in.route
            )
            if alert_rule_in.event not in valid_events:
                logger.info(
                    'Event %s is not in route %s alertable events %s, proceeding with creation',
                    alert_rule_in.event,
                    alert_rule_in.route,
                    valid_events,
                )

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

        update_dict = alert_rule_in.model_dump(exclude_unset=True)
        if not update_dict:
            return self._to_out(existing)

        # Handle recipients serialization if provided
        if 'recipients' in update_dict and isinstance(update_dict['recipients'], list):
            update_dict['recipients'] = json.dumps(update_dict['recipients'])

        # Validate event if route or event changes
        new_project = update_dict.get('project', existing.project)
        new_route = update_dict.get('route', existing.route)
        new_event = update_dict.get('event', existing.event)

        if 'route' in update_dict or 'event' in update_dict:
            valid_events = self._get_valid_events_list(new_project, new_route)
            if new_event not in valid_events:
                logger.info(
                    'Updated event %s is not in route %s alertable events',
                    new_event,
                    new_route,
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
        self, project_name: str, route_name: str
    ) -> int:
        """AG-843: Check active rules for a route when config changes.

        Auto-disable any rule whose event is no longer valid for the route.
        """
        active_rules = self.alert_rule_dao.get_active_by_route(project_name, route_name)
        if not active_rules:
            return 0

        valid_events = self._get_valid_events_list(project_name, route_name)
        disabled_count = 0

        for rule in active_rules:
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

    @staticmethod
    def _build_alert_email_body(
        rule_name: str,
        description: str | None,
        project_uuid: str,
        route_name: str,
        event_name: str,
        event_details: dict | None = None,
    ) -> str:
        details = event_details or {}
        req_uuid = details.get('request_uuid', 'N/A')
        project_name = details.get('project_name', 'N/A')
        api_key_name = details.get('api_key_name', 'N/A')
        group_name = details.get('group_name', 'N/A')

        g_name = details.get('name', 'N/A')
        g_type = details.get('type', 'N/A')
        g_where = details.get('where', 'N/A')
        g_behavior = details.get('behavior', 'N/A')
        g_params = details.get('parameters', 'N/A')

        cache_type = details.get('cache_type')
        fallback_target = details.get('target')
        fallback_dest = details.get('fallback')

        extra_rows = ''
        if g_name != 'N/A':
            extra_rows += (
                f"<tr><td style='padding: 8px; font-weight: bold;'>Guardrail Name:</td>"
                f"<td style='padding: 8px;'>{g_name}</td></tr>"
                f"<tr><td style='padding: 8px; font-weight: bold;'>Guardrail Type:</td>"
                f"<td style='padding: 8px;'>{g_type}</td></tr>"
                f"<tr><td style='padding: 8px; font-weight: bold;'>Phase (Where):</td>"
                f"<td style='padding: 8px;'>{g_where}</td></tr>"
                f"<tr><td style='padding: 8px; font-weight: bold;'>Behavior:</td>"
                f"<td style='padding: 8px;'>{g_behavior}</td></tr>"
                f"<tr><td style='padding: 8px; font-weight: bold;'>Parameters:</td>"
                f"<td style='padding: 8px; font-family: monospace;'>{g_params}</td></tr>"
            )
        if cache_type:
            extra_rows += (
                f"<tr><td style='padding: 8px; font-weight: bold;'>Cache Type:</td>"
                f"<td style='padding: 8px;'>{cache_type}</td></tr>"
            )
        if fallback_target:
            extra_rows += (
                f"<tr><td style='padding: 8px; font-weight: bold;'>Fallback:</td>"
                f"<td style='padding: 8px;'>{fallback_target} &rarr; {fallback_dest}</td></tr>"
            )

        return f"""
        <div style="font-family: Arial, sans-serif; max-width: 650px; border: 1px solid #e0e0e0; border-radius: 8px; padding: 20px; color: #333; background-color: #ffffff;">
            <h2 style="color: #e53e3e; margin-top: 0;">🚨 Alert Notification</h2>
            <p style="font-size: 14px; color: #555;">An alert rule has been triggered on your Radicalbit AI Gateway.</p>

            <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">
                <tr style="background-color: #f7fafc;"><td style="padding: 10px; font-weight: bold; border-bottom: 1px solid #e2e8f0; width: 35%;">Rule Name:</td><td style="padding: 10px; border-bottom: 1px solid #e2e8f0;">{rule_name}</td></tr>
                <tr><td style="padding: 10px; font-weight: bold; border-bottom: 1px solid #e2e8f0;">Description:</td><td style="padding: 10px; border-bottom: 1px solid #e2e8f0;">{description or 'N/A'}</td></tr>
                <tr style="background-color: #f7fafc;"><td style="padding: 10px; font-weight: bold; border-bottom: 1px solid #e2e8f0;">Project:</td><td style="padding: 10px; border-bottom: 1px solid #e2e8f0;">{project_name} <span style="font-size: 12px; color: #718096;">({project_uuid})</span></td></tr>
                <tr><td style="padding: 10px; font-weight: bold; border-bottom: 1px solid #e2e8f0;">Route:</td><td style="padding: 10px; border-bottom: 1px solid #e2e8f0;">{route_name}</td></tr>
                <tr style="background-color: #f7fafc;"><td style="padding: 10px; font-weight: bold; border-bottom: 1px solid #e2e8f0;">Event:</td><td style="padding: 10px; border-bottom: 1px solid #e2e8f0; color: #c53030; font-weight: bold;">{event_name}</td></tr>
            </table>

            <h3 style="color: #2d3748; border-bottom: 2px solid #edf2f7; padding-bottom: 8px; margin-top: 25px;">Event Details</h3>
            <table style="width: 100%; border-collapse: collapse; background-color: #f8fafc; border-radius: 6px; border: 1px solid #e2e8f0;">
                <tr><td style="padding: 8px; font-weight: bold; width: 35%;">Request UUID:</td><td style="padding: 8px; font-family: monospace;">{req_uuid}</td></tr>
                <tr><td style="padding: 8px; font-weight: bold;">API Key:</td><td style="padding: 8px;">{api_key_name}</td></tr>
                <tr><td style="padding: 8px; font-weight: bold;">Group:</td><td style="padding: 8px;">{group_name}</td></tr>
                {extra_rows}
            </table>

            <div style="margin-top: 25px; padding-top: 15px; border-top: 1px solid #e2e8f0; text-align: center; font-size: 12px; color: #a0aec0;">
                Radicalbit AI Gateway &bull; Alerting System
            </div>
        </div>
        """

    def dispatch_event_notification(
        self,
        project_uuid: str,
        route_name: str,
        event_name: str,
        event_details: dict | None = None,
    ) -> int:
        """AG-844: Send email notifications for triggered events on a route."""
        if not project_uuid:
            logger.error(
                'Cannot dispatch alert notification: project_uuid is missing for route %s',
                route_name,
            )
            return 0

        active_rules = self.alert_rule_dao.get_active_by_route(
            project_uuid=project_uuid,
            route_name=route_name,
        )

        candidate_events = {event_name.lower()}
        if any(k in event_name.lower() for k in ('presidio', 'pii', 'personal_id')):
            if 'input' in event_name.lower():
                candidate_events.add('guardrail-input-pii')
            elif 'output' in event_name.lower():
                candidate_events.add('guardrail-output-pii')
        if 'toxicity' in event_name.lower():
            if 'input' in event_name.lower():
                candidate_events.add('guardrail-input-toxicity')
            elif 'output' in event_name.lower():
                candidate_events.add('guardrail-output-toxicity')

        matching_rules = [
            r for r in active_rules if r.event.lower() in candidate_events
        ]

        if not matching_rules:
            return 0

        dispatched_count = 0
        for rule in matching_rules:
            rule_out = AlertRuleOut.from_alert_rule(rule)
            subject = f'[Alert Notification] {rule.name} triggered on {route_name}'
            body = self._build_alert_email_body(
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
