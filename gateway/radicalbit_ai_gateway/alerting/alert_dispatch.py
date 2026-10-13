"""Turn gateway events into alerts.

Every event from `emit_event` reaches `AlertDispatcher.dispatch` off the
request path. The dispatcher names the alertable event, finds the enabled rules
watching its target, and lets each rule's time aggregation decide what to send.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import logging
from uuid import UUID

from radicalbit_ai_gateway.alerting.alert_store import AlertStore
from radicalbit_ai_gateway.db.dao.alert_rule_dao import AlertRuleDAO
from radicalbit_ai_gateway.db.tables.alert_rule_table import AlertRule
from radicalbit_ai_gateway.events.alerts_processor import AlertStatus, emit_alert
from radicalbit_ai_gateway.models.alert_rule_dto import (
    AlertRuleOut,
    AlertRuleScope,
    AlertRuleTimeAggregation,
)
from radicalbit_ai_gateway.models.event_payload import (
    EventPayload,
    FallbackEventPayload,
    GuardrailEventPayload,
)
from radicalbit_ai_gateway.services.alert_email_formatter import (
    build_alert_email_body,
    build_alert_email_subject,
)
from radicalbit_ai_gateway.services.email_service import EmailService
from radicalbit_ai_gateway.utils.app_config import get_app_config

logger = logging.getLogger(get_app_config().log_config.logger_name)

FALLBACK_EVENT = 'fallback-triggered'


@dataclass(frozen=True)
class AlertEvent:
    """An event as alert rules see it: the key they match and the scope they watch."""

    key: str
    scope: AlertRuleScope


def alert_event(event: EventPayload) -> AlertEvent | None:
    """Name the alertable event behind `event`, or None if it is not alertable."""
    if isinstance(event, GuardrailEventPayload):
        key = f'guardrail-{event.where}-{event.name}'.lower()
        return AlertEvent(key=key, scope=AlertRuleScope.ROUTE)
    if isinstance(event, FallbackEventPayload):
        return AlertEvent(key=FALLBACK_EVENT, scope=AlertRuleScope.ROUTE)
    return None


def _target(scope: AlertRuleScope, event: EventPayload) -> str:
    if scope is AlertRuleScope.ROUTE:
        return f'{event.project_name} / {event.route_name}'
    if scope is AlertRuleScope.PROJECT:
        return event.project_name
    return event.api_key_name


def _instant_details(event: EventPayload) -> list[tuple[str, str]]:
    details = [('Credential', event.api_key_name), ('Group', event.group_name)]
    if isinstance(event, GuardrailEventPayload):
        details += [
            ('Guardrail type', event.type),
            ('Guardrail behaviour', event.behavior),
        ]
    if isinstance(event, FallbackEventPayload):
        details.append(('Fallback', f'{event.target} → {event.fallback}'))
    return details


class AlertDispatcher:
    """Send the alerts an event triggers, according to each rule's aggregation.

    Each time aggregation has one handler. Instant sends at once; the window and
    limit-window handlers keep their state in the alert store.
    """

    def __init__(
        self,
        alert_rule_dao: AlertRuleDAO,
        email_service: EmailService,
        store: AlertStore,
    ):
        self._alert_rule_dao = alert_rule_dao
        self._email_service = email_service
        self._store = store
        self._handlers: dict[
            AlertRuleTimeAggregation,
            Callable[[AlertRule, AlertEvent, EventPayload], None],
        ] = {AlertRuleTimeAggregation.INSTANT: self._send_instant}

    def dispatch(self, event: EventPayload) -> None:
        """Hand `event` to every enabled rule watching its target and event."""
        matched = alert_event(event)
        if matched is None:
            return
        for rule in self._candidate_rules(matched.scope, event):
            if rule.event.strip().lower() != matched.key:
                continue
            try:
                aggregation = AlertRuleTimeAggregation(rule.time_aggregation)
            except ValueError:
                aggregation = None
            handler = self._handlers.get(aggregation) if aggregation else None
            if handler is None:
                logger.warning(
                    'Alert rule %s uses time aggregation "%s", which is not dispatched',
                    rule.uuid,
                    rule.time_aggregation,
                )
                continue
            handler(rule, matched, event)

    def _candidate_rules(
        self, scope: AlertRuleScope, event: EventPayload
    ) -> Sequence[AlertRule]:
        if scope is AlertRuleScope.ROUTE:
            if not event.project_uuid:
                return []
            return self._alert_rule_dao.get_enabled_route_rules(
                event.project_uuid, event.route_name
            )
        if scope is AlertRuleScope.PROJECT:
            if not event.project_uuid:
                return []
            return self._alert_rule_dao.get_enabled_project_rules(event.project_uuid)
        return self._alert_rule_dao.get_enabled_credential_rules(
            UUID(event.api_key_uuid)
        )

    def _send_instant(
        self, rule: AlertRule, matched: AlertEvent, event: EventPayload
    ) -> None:
        self._send(rule, matched, event, details=_instant_details(event))

    def _send(
        self,
        rule: AlertRule,
        matched: AlertEvent,
        event: EventPayload,
        details: list[tuple[str, str]],
    ) -> None:
        target = _target(matched.scope, event)
        subject = build_alert_email_subject(rule.name, matched.key, target)
        body = build_alert_email_body(
            rule_name=rule.name,
            description=rule.description,
            scope=matched.scope.value,
            target=target,
            event=matched.key,
            time=self._store.now(),
            details=details,
        )
        recipients = AlertRuleOut.from_alert_rule(rule).recipients
        try:
            sent = self._email_service.send_email(
                recipients=recipients, subject=subject, body=body
            )
        except Exception:
            logger.exception(
                'Failed to send alert for rule "%s" (%s)', rule.name, rule.uuid
            )
            sent = False
        emit_alert(
            rule_uuid=str(rule.uuid),
            rule_name=rule.name,
            scope=matched.scope.value,
            project_uuid=rule.project,
            route_name=rule.route,
            credential_uuid=str(rule.credential_uuid) if rule.credential_uuid else None,
            event=matched.key,
            aggregation=rule.time_aggregation,
            status=AlertStatus.SENT if sent else AlertStatus.FAILED,
        )
