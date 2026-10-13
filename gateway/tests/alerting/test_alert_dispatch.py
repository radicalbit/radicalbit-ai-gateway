"""`emit_event(event)` in; emails and alert records out.

Rules are stored in Postgres. The alert state lives on the Valkey testcontainer
in one class and in process in the other: both run the same tests.
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
        dispatcher = AlertDispatcher(
            alert_rule_dao=AlertRuleDAO(self.db),
            email_service=self.email,
            store=self.make_store(request),
        )
        with (
            patch.object(events_processor, '_alert_dispatcher', dispatcher),
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
        self.rule(time_aggregation='window', window_size='5m')
        self.rule(time_aggregation='limit_window')

        events_processor.emit_event(guardrail_event())

        assert self.email.sent == []
        assert self.buffer.records == []

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
        url = request.getfixturevalue('redis_connection_url')
        Redis.from_url(url).flushdb()
        return RedisAlertStore(Redis.from_url(url), clock=lambda: NOW)


class TestDispatchInProcess(DispatchTests, DatabaseIntegration):
    def make_store(self, request):
        return InProcessAlertStore(clock=lambda: NOW)
