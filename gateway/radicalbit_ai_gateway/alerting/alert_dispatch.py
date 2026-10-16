"""Turn gateway events into alerts.

Every event from `emit_event` reaches `AlertDispatcher.dispatch` off the
request path. The dispatcher names the alertable event, finds the enabled rules
watching its target, and lets each rule's time aggregation decide what to send.

Window rules only count at dispatch. `AlertDispatcher.close_windows`, ticked by
the scheduler, sends one alert per closed window that saw at least one event.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
import logging
from uuid import UUID

from radicalbit_ai_gateway.alerting.alert_store import AlertStore
from radicalbit_ai_gateway.alerting.limit_event_names import (
    CATEGORY_BY_SCENARIO,
    exceeded_event,
    threshold_event,
)
from radicalbit_ai_gateway.db.dao.alert_rule_dao import AlertRuleDAO
from radicalbit_ai_gateway.db.tables.alert_rule_table import AlertRule
from radicalbit_ai_gateway.events.alerts_processor import AlertStatus, emit_alert
from radicalbit_ai_gateway.models.alert_rule_dto import (
    AlertRuleOut,
    AlertRuleScope,
    AlertRuleTimeAggregation,
    AlertRuleWindowSize,
)
from radicalbit_ai_gateway.models.event_payload import (
    EventPayload,
    FallbackEventPayload,
    GuardrailEventPayload,
    LimitEventPayload,
    LimitScope,
)
from radicalbit_ai_gateway.services.alert_email_formatter import (
    build_alert_email_body,
    build_alert_email_subject,
)
from radicalbit_ai_gateway.services.email_service import EmailService
from radicalbit_ai_gateway.utils.app_config import get_app_config

logger = logging.getLogger(get_app_config().log_config.logger_name)

FALLBACK_EVENT = 'fallback-triggered'

_WINDOW_SECONDS = {
    AlertRuleWindowSize.FIVE_MINUTES: 5 * 60,
    AlertRuleWindowSize.FIFTEEN_MINUTES: 15 * 60,
    AlertRuleWindowSize.ONE_HOUR: 60 * 60,
    AlertRuleWindowSize.SIX_HOURS: 6 * 60 * 60,
    AlertRuleWindowSize.ONE_DAY: 24 * 60 * 60,
}

# How long a window's counter and closed mark outlive the window.
_WINDOW_GRACE_SECONDS = 60 * 60
_TIME_FORMAT = '%Y-%m-%d %H:%M:%S UTC'

# How long a limit window's claim outlives the window's reset.
_LIMIT_WINDOW_MARGIN_SECONDS = 60 * 60


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
    if isinstance(event, LimitEventPayload):
        # Rules on credential limits are not dispatched yet.
        if event.limit_scope is LimitScope.CREDENTIAL:
            return None
        category = CATEGORY_BY_SCENARIO.get(event.category)
        if category is None:
            return None
        if event.threshold_percentage is None:
            key = exceeded_event(category, event.window_seconds)
        else:
            key = threshold_event(
                category, event.threshold_percentage, event.window_seconds
            )
        return AlertEvent(key=key, scope=AlertRuleScope(event.limit_scope.value))
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


@dataclass(frozen=True)
class _Window:
    """One tumbling window of one rule, as registered in the open windows."""

    rule_uuid: str
    size: AlertRuleWindowSize
    start: datetime
    target: str

    @staticmethod
    def containing(
        rule_uuid: str, size: AlertRuleWindowSize, at: datetime, target: str
    ) -> '_Window':
        seconds = _WINDOW_SECONDS[size]
        epoch = int(at.timestamp()) // seconds * seconds
        return _Window(
            rule_uuid=rule_uuid,
            size=size,
            start=datetime.fromtimestamp(epoch, tz=UTC),
            target=target,
        )

    @property
    def end(self) -> datetime:
        return self.start + timedelta(seconds=self.seconds)

    @property
    def seconds(self) -> int:
        return _WINDOW_SECONDS[self.size]

    @property
    def counter_key(self) -> str:
        start = int(self.start.timestamp())
        return f'alert:window:{self.rule_uuid}:{self.size.value}:{start}'

    @property
    def closed_key(self) -> str:
        return f'{self.counter_key}:closed'

    def encode(self) -> str:
        """Name the window in the open windows, the same way on every replica."""
        return json.dumps(
            {
                'rule': self.rule_uuid,
                'size': self.size.value,
                'start': int(self.start.timestamp()),
                'target': self.target,
            },
            sort_keys=True,
        )

    @staticmethod
    def decode(member: str) -> '_Window':
        data = json.loads(member)
        return _Window(
            rule_uuid=data['rule'],
            size=AlertRuleWindowSize(data['size']),
            start=datetime.fromtimestamp(data['start'], tz=UTC),
            target=data['target'],
        )


def _format_quantity(value: float) -> str:
    return str(int(value)) if value == int(value) else f'{value:g}'


def _limit_details(event: LimitEventPayload, reset: datetime) -> list[tuple[str, str]]:
    details = [
        ('Consumption', _format_quantity(event.consumption)),
        ('Maximum', _format_quantity(event.maximum)),
    ]
    if event.threshold_percentage is not None:
        details.append(('Threshold', f'{event.threshold_percentage}%'))
    details.append(('Reset time', reset.strftime(_TIME_FORMAT)))
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
        ] = {
            AlertRuleTimeAggregation.INSTANT: self._send_instant,
            AlertRuleTimeAggregation.LIMIT_WINDOW: self._send_once_per_limit_window,
            AlertRuleTimeAggregation.WINDOW: self._count_in_window,
        }

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

    def close_windows(self) -> None:
        """Send the alert of every window that has closed by now.

        Each window is claimed once, by one replica. An event counted after its
        window was claimed registers the window again, and the next tick drops
        it: the window has had its alert. A window whose rule is gone, disabled
        or no longer on that window is dropped.
        """
        for member in self._store.windows_due(self._store.now()):
            self._store.close_window(member)
            try:
                self._close_window(_Window.decode(member))
            except Exception:
                logger.exception('Failed to close alert window %s', member)

    def _close_window(self, window: _Window) -> None:
        ttl_seconds = window.seconds + _WINDOW_GRACE_SECONDS
        if not self._store.claim(window.closed_key, ttl_seconds=ttl_seconds):
            return
        count = self._store.take(window.counter_key)
        if count == 0:
            return
        rule = self._alert_rule_dao.get_by_uuid(UUID(window.rule_uuid))
        if (
            rule is None
            or not rule.enabled
            or rule.time_aggregation != AlertRuleTimeAggregation.WINDOW.value
            or rule.window_size != window.size.value
        ):
            return
        interval = (
            f'{window.start.strftime(_TIME_FORMAT)} → '
            f'{window.end.strftime(_TIME_FORMAT)}'
        )
        self._send(
            rule,
            AlertEvent(key=rule.event, scope=AlertRuleScope(rule.scope)),
            target=window.target,
            time=window.end,
            details=[('Events', str(count)), ('Window', interval)],
            count=count,
            window_start=window.start,
            window_end=window.end,
        )

    def _count_in_window(
        self, rule: AlertRule, matched: AlertEvent, event: EventPayload
    ) -> None:
        try:
            size = AlertRuleWindowSize(rule.window_size)
        except ValueError:
            logger.warning(
                'Alert rule %s has window size "%s", which is not dispatched',
                rule.uuid,
                rule.window_size,
            )
            return
        window = _Window.containing(
            str(rule.uuid), size, self._store.now(), _target(matched.scope, event)
        )
        self._store.increment(
            window.counter_key, ttl_seconds=window.seconds + _WINDOW_GRACE_SECONDS
        )
        self._store.open_window(window.encode(), closes_at=window.end)

    def _send_instant(
        self, rule: AlertRule, matched: AlertEvent, event: EventPayload
    ) -> None:
        self._send(
            rule,
            matched,
            target=_target(matched.scope, event),
            time=self._store.now(),
            details=_instant_details(event),
        )

    def _send_once_per_limit_window(
        self, rule: AlertRule, matched: AlertEvent, event: EventPayload
    ) -> None:
        """Send the first time the rule fires in the limit's current window.

        The window is the limiter's `window_id`, or its reset time when the
        limiter had no window open. Only the replica that claims it sends.
        """
        if not isinstance(event, LimitEventPayload):
            return
        window = event.window_id or str(event.reset_time)
        now = int(self._store.now().timestamp())
        ttl = max(event.reset_time - now, 0) + _LIMIT_WINDOW_MARGIN_SECONDS
        if not self._store.claim(f'alert:limit:{rule.uuid}:{window}', ttl):
            return
        reset = datetime.fromtimestamp(event.reset_time, tz=UTC)
        self._send(
            rule,
            matched,
            target=_target(matched.scope, event),
            time=self._store.now(),
            details=_limit_details(event, reset),
            window_start=reset - timedelta(seconds=event.window_seconds),
            window_end=reset,
        )

    def _send(
        self,
        rule: AlertRule,
        matched: AlertEvent,
        *,
        target: str,
        time: datetime,
        details: list[tuple[str, str]],
        count: int = 1,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
    ) -> None:
        subject = build_alert_email_subject(rule.name, matched.key, target)
        body = build_alert_email_body(
            rule_name=rule.name,
            description=rule.description,
            scope=matched.scope.value,
            target=target,
            event=matched.key,
            time=time,
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
            count=count,
            window_start=window_start,
            window_end=window_end,
        )
