"""`emit_event(event)` in; emails and alert records out.

Rules are stored in Postgres. The alert state lives on the Valkey testcontainer
in one class and in process in the other: both run the same tests. Windows are
closed by calling the scheduler's tick, `close_windows`, directly.
"""

from datetime import UTC, datetime
import json
from unittest.mock import patch
import uuid

import pytest
from redis import Redis

from tests.common.db_integration import DatabaseIntegration

from radicalbit_ai_gateway.alerting.alert_dispatch import AlertDispatcher
from radicalbit_ai_gateway.alerting.alert_store import (
    InProcessAlertStore,
    RedisAlertStore,
)
from radicalbit_ai_gateway.db.dao.alert_rule_dao import AlertRuleDAO
from radicalbit_ai_gateway.db.tables.alert_rule_table import AlertRule
from radicalbit_ai_gateway.events import events_processor
from radicalbit_ai_gateway.models.event_payload import (
    CacheEventPayload,
    FallbackEventPayload,
    GuardrailEventPayload,
)
from radicalbit_ai_gateway.models.event_type import EventType

PROJECT_UUID = str(uuid.uuid4())
NOW = datetime(2026, 10, 13, 9, 30, tzinfo=UTC)


class FakeEmailService:
    def __init__(self):
        self.sent: list[dict] = []
        self.outcomes: list[bool | Exception] = []

    def send_email(self, recipients: list[str], subject: str, body: str) -> bool:
        self.sent.append({'recipients': recipients, 'subject': subject, 'body': body})
        outcome = self.outcomes.pop(0) if self.outcomes else True
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeBuffer:
    def __init__(self):
        self.records: list[dict] = []

    def add(self, record: dict) -> None:
        self.records.append(record)


class FakeClock:
    def __init__(self, now: datetime = NOW):
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def set(self, hour: int, minute: int, second: int = 0) -> None:
        self.now = self.now.replace(hour=hour, minute=minute, second=second)


class InlineExecutor:
    """Runs the alert dispatch on the caller's thread, so a test can see it."""

    def submit(self, fn, *args):
        fn(*args)


def guardrail_event(
    name: str = 'pii', where: str = 'INPUT', project_uuid: str = PROJECT_UUID
):
    return GuardrailEventPayload(
        request_uuid=str(uuid.uuid4()),
        route_name='chat',
        value=1,
        api_key_uuid=str(uuid.uuid4()),
        api_key_name='billing-service',
        group_uuid=str(uuid.uuid4()),
        group_name='finance',
        project_uuid=project_uuid,
        project_name='acme',
        event_type=EventType.GUARDRAIL,
        name=name,
        type='CONTAINS',
        where=where,
        parameters="{'values': ['top-secret-parameter']}",
        behavior='BLOCK',
    )


def fallback_event():
    return FallbackEventPayload(
        request_uuid=str(uuid.uuid4()),
        route_name='chat',
        value=1,
        api_key_uuid=str(uuid.uuid4()),
        api_key_name='billing-service',
        group_uuid=str(uuid.uuid4()),
        group_name='finance',
        project_uuid=PROJECT_UUID,
        project_name='acme',
        event_type=EventType.FALLBACK,
        target='gpt-4',
        fallback='gpt-3.5',
    )


class DispatchTests:
    """The behaviour every alert store must give. Subclasses build the store."""

    @pytest.fixture(autouse=True)
    def _wire(self, request):
        self.email = FakeEmailService()
        self.buffer = FakeBuffer()
        self.clock = FakeClock()
        self.dispatcher = AlertDispatcher(
            alert_rule_dao=AlertRuleDAO(self.db),
            email_service=self.email,
            store=self.make_store(request),
        )
        with (
            patch.object(events_processor, '_alert_dispatcher', self.dispatcher),
            patch.object(events_processor, '_alert_executor', InlineExecutor()),
            patch.object(events_processor, '_events_buffer'),
            patch(
                'radicalbit_ai_gateway.events.alerts_processor._alerts_buffer',
                self.buffer,
            ),
        ):
            yield
        with self.db.begin_session() as session:
            session.query(AlertRule).delete()

    def make_store(self, request):
        raise NotImplementedError

    def rule(self, event: str = 'guardrail-input-pii', **columns) -> AlertRule:
        return self.insert(
            AlertRule(
                **{
                    'name': 'PII watch',
                    'description': 'Watches PII',
                    'scope': 'route',
                    'project': PROJECT_UUID,
                    'route': 'chat',
                    'event': event,
                    'time_aggregation': 'instant',
                    'channel': 'email',
                    'recipients': json.dumps(['ops@example.com']),
                    'enabled': True,
                    'deleted': False,
                    'created_at': NOW,
                    'updated_at': NOW,
                    **columns,
                }
            )
        )

    # --- instant ---

    def test_an_instant_rule_sends_one_email_per_event(self):
        self.rule()

        events_processor.emit_event(guardrail_event())
        events_processor.emit_event(guardrail_event())

        assert len(self.email.sent) == 2
        assert self.email.sent[0]['recipients'] == ['ops@example.com']

    def test_a_fallback_rule_sends_on_a_fallback(self):
        self.rule('fallback-triggered')

        events_processor.emit_event(fallback_event())

        assert len(self.email.sent) == 1

    def test_every_matching_rule_sends(self):
        self.rule(name='first')
        self.rule(name='second')

        events_processor.emit_event(guardrail_event())

        subjects = [e['subject'] for e in self.email.sent]
        assert len(subjects) == 2
        assert any('first' in s for s in subjects)
        assert any('second' in s for s in subjects)

    def test_an_instant_alert_is_recorded_as_sent(self):
        rule = self.rule()

        events_processor.emit_event(guardrail_event())

        [record] = self.buffer.records
        assert record['RULE_UUID'] == str(rule.uuid)
        assert record['RULE_NAME'] == 'PII watch'
        assert record['SCOPE'] == 'route'
        assert record['PROJECT_UUID'] == PROJECT_UUID
        assert record['ROUTE_NAME'] == 'chat'
        assert record['CREDENTIAL_UUID'] is None
        assert record['EVENT'] == 'guardrail-input-pii'
        assert record['AGGREGATION'] == 'instant'
        assert record['COUNT'] == 1
        assert record['WINDOW_START'] is None
        assert record['WINDOW_END'] is None
        assert record['STATUS'] == 'sent'

    def test_each_alert_is_recorded_with_its_own_uuid(self):
        self.rule()

        events_processor.emit_event(guardrail_event())
        events_processor.emit_event(guardrail_event())

        first, second = self.buffer.records
        assert first['ALERT_UUID'] != second['ALERT_UUID']

    def test_a_failed_send_is_recorded_as_failed(self):
        self.rule()
        self.email.outcomes = [False]

        events_processor.emit_event(guardrail_event())

        assert [r['STATUS'] for r in self.buffer.records] == ['failed']

    def test_a_send_that_raises_is_recorded_as_failed_and_the_next_rule_still_runs(
        self,
    ):
        self.rule(name='first', created_at=NOW)
        self.rule(name='second', created_at=NOW)
        self.email.outcomes = [RuntimeError('smtp down'), True]

        events_processor.emit_event(guardrail_event())

        assert sorted(r['STATUS'] for r in self.buffer.records) == ['failed', 'sent']

    # --- matching ---

    def test_a_rule_on_another_event_does_not_send(self):
        self.rule('guardrail-output-pii')

        events_processor.emit_event(guardrail_event(where='INPUT'))

        assert self.email.sent == []

    def test_a_rule_on_another_route_does_not_send(self):
        self.rule(route='summarise')

        events_processor.emit_event(guardrail_event())

        assert self.email.sent == []

    def test_a_rule_on_another_project_does_not_send(self):
        self.rule(project=str(uuid.uuid4()))

        events_processor.emit_event(guardrail_event())

        assert self.email.sent == []

    def test_a_rule_is_matched_by_project_uuid_not_by_project_name(self):
        self.rule(project='acme')

        events_processor.emit_event(guardrail_event())

        assert self.email.sent == []

    def test_disabled_and_deleted_rules_do_not_send(self):
        self.rule(enabled=False)
        self.rule(deleted=True)

        events_processor.emit_event(guardrail_event())

        assert self.email.sent == []
        assert self.buffer.records == []

    def test_a_cache_hit_is_not_alertable(self):
        self.rule('cache-exact')

        events_processor.emit_event(
            CacheEventPayload(
                request_uuid='r1',
                route_name='chat',
                value=1,
                api_key_uuid='k1',
                api_key_name='key',
                group_uuid='g1',
                group_name='group',
                project_uuid=PROJECT_UUID,
                project_name='acme',
                event_type=EventType.CACHE_HIT,
                cache_type='exact',
                model_id='gpt-4',
            )
        )

        assert self.email.sent == []

    def test_aggregations_not_built_yet_send_nothing(self):
        self.rule(time_aggregation='limit_window')

        events_processor.emit_event(guardrail_event())

        assert self.email.sent == []
        assert self.buffer.records == []

    # --- window ---

    def window_rule(self, size: str = '5m', **columns) -> AlertRule:
        return self.rule(time_aggregation='window', window_size=size, **columns)

    def test_a_window_rule_sends_nothing_while_its_window_is_open(self):
        self.window_rule('5m')

        events_processor.emit_event(guardrail_event())
        self.clock.set(9, 34, 59)
        self.dispatcher.close_windows()

        assert self.email.sent == []
        assert self.buffer.records == []

    def test_a_closed_window_sends_one_alert_with_the_count(self):
        self.window_rule('5m')

        for _ in range(3):
            events_processor.emit_event(guardrail_event())
        self.clock.set(9, 35)
        self.dispatcher.close_windows()

        [email] = self.email.sent
        assert email['recipients'] == ['ops@example.com']
        assert 'PII watch' in email['subject']
        assert 'acme / chat' in email['subject']
        assert 'Events' in email['body']
        assert '>3<' in email['body']
        assert '2026-10-13 09:30:00 UTC → 2026-10-13 09:35:00 UTC' in email['body']

    def test_a_closed_window_is_sent_once(self):
        self.window_rule('5m')

        events_processor.emit_event(guardrail_event())
        self.clock.set(9, 35)
        self.dispatcher.close_windows()
        self.clock.set(9, 36)
        self.dispatcher.close_windows()

        assert len(self.email.sent) == 1

    def test_a_window_alert_is_recorded_with_its_count_and_interval(self):
        rule = self.window_rule('15m', event='fallback-triggered')

        events_processor.emit_event(fallback_event())
        events_processor.emit_event(fallback_event())
        self.clock.set(9, 45)
        self.dispatcher.close_windows()

        [record] = self.buffer.records
        assert record['RULE_UUID'] == str(rule.uuid)
        assert record['EVENT'] == 'fallback-triggered'
        assert record['AGGREGATION'] == 'window'
        assert record['COUNT'] == 2
        assert record['WINDOW_START'] == datetime(2026, 10, 13, 9, 30, tzinfo=UTC)
        assert record['WINDOW_END'] == datetime(2026, 10, 13, 9, 45, tzinfo=UTC)
        assert record['STATUS'] == 'sent'

    def test_windows_are_aligned_to_the_utc_clock(self):
        self.window_rule('1h')

        self.clock.set(9, 41)
        events_processor.emit_event(guardrail_event())
        self.clock.set(10, 0)
        self.dispatcher.close_windows()

        [record] = self.buffer.records
        assert record['WINDOW_START'] == datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
        assert record['WINDOW_END'] == datetime(2026, 10, 13, 10, 0, tzinfo=UTC)

    def test_a_day_window_runs_from_midnight_to_midnight_utc(self):
        self.window_rule('24h')

        events_processor.emit_event(guardrail_event())
        self.clock.now = datetime(2026, 10, 14, tzinfo=UTC)
        self.dispatcher.close_windows()

        [record] = self.buffer.records
        assert record['WINDOW_START'] == datetime(2026, 10, 13, tzinfo=UTC)
        assert record['WINDOW_END'] == datetime(2026, 10, 14, tzinfo=UTC)

    def test_an_event_counted_after_its_window_closed_sends_no_second_alert(self):
        self.window_rule('5m')

        events_processor.emit_event(guardrail_event())
        self.clock.set(9, 35)
        self.dispatcher.close_windows()
        # A replica whose clock lags still counts into the closed window.
        self.clock.set(9, 34, 59)
        events_processor.emit_event(guardrail_event())
        self.clock.set(9, 35, 30)
        self.dispatcher.close_windows()

        assert len(self.email.sent) == 1

    def test_events_in_consecutive_windows_send_one_alert_each(self):
        self.window_rule('5m')

        events_processor.emit_event(guardrail_event())
        self.clock.set(9, 36)
        events_processor.emit_event(guardrail_event())
        events_processor.emit_event(guardrail_event())
        self.clock.set(9, 40)
        self.dispatcher.close_windows()

        counts = sorted(r['COUNT'] for r in self.buffer.records)
        assert counts == [1, 2]

    def test_an_empty_window_sends_nothing(self):
        self.window_rule('5m')

        self.clock.set(9, 35)
        self.dispatcher.close_windows()

        assert self.email.sent == []
        assert self.buffer.records == []

    def test_each_window_rule_counts_on_its_own(self):
        self.window_rule('5m', name='first')
        self.window_rule('5m', name='second')

        events_processor.emit_event(guardrail_event())
        self.clock.set(9, 35)
        self.dispatcher.close_windows()

        assert sorted(r['RULE_NAME'] for r in self.buffer.records) == [
            'first',
            'second',
        ]

    def test_a_rule_disabled_before_close_sends_nothing(self):
        rule = self.window_rule('5m')

        events_processor.emit_event(guardrail_event())
        AlertRuleDAO(self.db).toggle_enabled(rule.uuid, False)
        self.clock.set(9, 35)
        self.dispatcher.close_windows()

        assert self.email.sent == []
        assert self.buffer.records == []

    def test_a_rule_deleted_before_close_sends_nothing(self):
        rule = self.window_rule('5m')

        events_processor.emit_event(guardrail_event())
        AlertRuleDAO(self.db).soft_delete_by_uuid(rule.uuid)
        self.clock.set(9, 35)
        self.dispatcher.close_windows()

        assert self.email.sent == []

    def test_a_rule_switched_away_from_its_window_before_close_sends_nothing(self):
        to_instant = self.window_rule('5m', name='to instant')
        resized = self.window_rule('5m', name='resized')

        events_processor.emit_event(guardrail_event())
        dao = AlertRuleDAO(self.db)
        dao.update_rule(
            to_instant.uuid, {'time_aggregation': 'instant', 'window_size': None}
        )
        dao.update_rule(resized.uuid, {'window_size': '1h'})
        self.clock.set(9, 35)
        self.dispatcher.close_windows()

        assert self.email.sent == []

    def test_a_dropped_window_is_not_sent_later(self):
        rule = self.window_rule('5m')

        events_processor.emit_event(guardrail_event())
        dao = AlertRuleDAO(self.db)
        dao.toggle_enabled(rule.uuid, False)
        self.clock.set(9, 35)
        self.dispatcher.close_windows()
        dao.toggle_enabled(rule.uuid, True)
        self.clock.set(9, 36)
        self.dispatcher.close_windows()

        assert self.email.sent == []

    def test_a_failed_window_send_is_recorded_as_failed(self):
        self.window_rule('5m')
        self.email.outcomes = [RuntimeError('smtp down')]

        events_processor.emit_event(guardrail_event())
        self.clock.set(9, 35)
        self.dispatcher.close_windows()

        assert [r['STATUS'] for r in self.buffer.records] == ['failed']

    # --- email content ---

    def test_the_email_names_rule_scope_target_event_and_time(self):
        self.rule()

        events_processor.emit_event(guardrail_event())

        [email] = self.email.sent
        assert 'PII watch' in email['subject']
        assert 'guardrail-input-pii' in email['subject']
        assert 'acme / chat' in email['subject']
        body = email['body']
        for expected in (
            'PII watch',
            'route',
            'acme / chat',
            'guardrail-input-pii',
            '2026-10-13 09:30:00 UTC',
        ):
            assert expected in body

    def test_an_instant_email_carries_the_event_details(self):
        self.rule('fallback-triggered')

        events_processor.emit_event(fallback_event())

        body = self.email.sent[0]['body']
        assert 'billing-service' in body
        assert 'finance' in body
        assert 'gpt-4 → gpt-3.5' in body

    def test_an_instant_guardrail_email_carries_type_and_behaviour_but_no_parameters(
        self,
    ):
        self.rule()

        events_processor.emit_event(guardrail_event())

        body = self.email.sent[0]['body']
        assert 'CONTAINS' in body
        assert 'BLOCK' in body
        assert 'top-secret-parameter' not in body


class TestDispatchOnRedis(DispatchTests, DatabaseIntegration):
    def make_store(self, request):
        self.redis_url = request.getfixturevalue('redis_connection_url')
        Redis.from_url(self.redis_url).flushdb()
        return RedisAlertStore(Redis.from_url(self.redis_url), clock=self.clock)

    def test_two_dispatchers_on_the_same_redis_send_one_alert_per_window(self):
        self.window_rule('5m')
        replica = AlertDispatcher(
            alert_rule_dao=AlertRuleDAO(self.db),
            email_service=self.email,
            store=RedisAlertStore(Redis.from_url(self.redis_url), clock=self.clock),
        )

        self.dispatcher.dispatch(guardrail_event())
        replica.dispatch(guardrail_event())
        replica.dispatch(guardrail_event())
        self.clock.set(9, 35)
        replica.close_windows()
        self.dispatcher.close_windows()

        assert len(self.email.sent) == 1
        [record] = self.buffer.records
        assert record['COUNT'] == 3


class TestDispatchInProcess(DispatchTests, DatabaseIntegration):
    def make_store(self, request):
        return InProcessAlertStore(clock=self.clock)
