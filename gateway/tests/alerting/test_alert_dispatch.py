"""`emit_event(event)` in; emails and alert records out.

Rules are stored in Postgres. The alert state lives in process: what the stores
themselves do, on Redis and in process alike, is tested in `test_alert_store`.
Only the dispatchers that share one Redis run on the Valkey testcontainer.
Windows are closed by calling the scheduler's tick, `close_windows`, directly.
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
    LimitEventPayload,
    LimitScope,
)
from radicalbit_ai_gateway.models.event_type import EventType

PROJECT_UUID = str(uuid.uuid4())
CREDENTIAL_UUID = str(uuid.uuid4())
NOW = datetime(2026, 10, 13, 9, 30, tzinfo=UTC)
RESET = int(datetime(2026, 10, 13, 9, 31, tzinfo=UTC).timestamp())


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


def guardrail_event(where: str = 'INPUT'):
    return GuardrailEventPayload(
        request_uuid=str(uuid.uuid4()),
        route_name='chat',
        value=1,
        api_key_uuid=str(uuid.uuid4()),
        api_key_name='billing-service',
        group_uuid=str(uuid.uuid4()),
        group_name='finance',
        project_uuid=PROJECT_UUID,
        project_name='acme',
        event_type=EventType.GUARDRAIL,
        name='pii',
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


def cache_hit_event():
    return CacheEventPayload(
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


def limit_event(
    window_id: str | None = 'w1',
    reset_time: int = RESET,
    threshold_percentage: int | None = None,
    event_type: EventType = EventType.RATE_LIMIT,
    category: str = 'request_rate',
    consumption: float = 11,
    maximum: float = 10,
    **update,
):
    """Build a route limit event; `update` overrides any other field."""
    if threshold_percentage is not None:
        event_type = EventType.LIMIT_THRESHOLD
    return LimitEventPayload(
        request_uuid=str(uuid.uuid4()),
        route_name='chat',
        value=1,
        api_key_uuid=str(uuid.uuid4()),
        api_key_name='billing-service',
        group_uuid=str(uuid.uuid4()),
        group_name='finance',
        project_uuid=PROJECT_UUID,
        project_name='acme',
        event_type=event_type,
        limit_scope=LimitScope.ROUTE,
        category=category,
        window_seconds=60,
        maximum=maximum,
        consumption=consumption,
        reset_time=reset_time,
        window_id=window_id,
        threshold_percentage=threshold_percentage,
    ).model_copy(update=update)


def project_budget_event(threshold_percentage: int | None = None, **fields):
    return limit_event(
        category='budget',
        threshold_percentage=threshold_percentage,
        limit_scope=LimitScope.PROJECT,
        **fields,
    ).model_copy(
        update={
            'event_type': EventType.PROJECT_BUDGET_LIMIT
            if threshold_percentage is None
            else EventType.LIMIT_THRESHOLD
        }
    )


def credential_event(credential_uuid: str = CREDENTIAL_UUID, **fields):
    return limit_event(
        limit_scope=LimitScope.CREDENTIAL,
        api_key_uuid=credential_uuid,
        route_name='*',
        **fields,
    )


def limit_rule(event: str = 'rate_limit-exceeded-1m', **columns) -> dict:
    return {'event': event, 'time_aggregation': 'limit_window', **columns}


def project_rule(event: str = 'budget_limit-exceeded-1m', **columns) -> dict:
    return limit_rule(event, scope='project', route=None, **columns)


def credential_rule(event: str = 'rate_limit-exceeded-1m') -> dict:
    return limit_rule(
        event,
        scope='credential',
        project=None,
        route=None,
        credential_uuid=uuid.UUID(CREDENTIAL_UUID),
    )


def window_rule(size: str = '5m', **columns) -> dict:
    return {'time_aggregation': 'window', 'window_size': size, **columns}


@pytest.fixture(scope='module')
def db():
    class Schema(DatabaseIntegration):
        pass

    Schema.setUpClass()
    yield Schema.db
    Schema.tearDownClass()


class DispatcherHarness:
    @pytest.fixture(autouse=True)
    def _wire(self, request, db):
        self.db = db
        self.email = FakeEmailService()
        self.buffer = FakeBuffer()
        self.clock = FakeClock()
        self.dispatcher = AlertDispatcher(
            alert_rule_dao=AlertRuleDAO(db),
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
        with db.begin_session() as session:
            session.query(AlertRule).delete()

    def make_store(self, request):
        return InProcessAlertStore(clock=self.clock)

    def rule(self, event: str = 'guardrail-input-pii', **columns) -> AlertRule:
        rule = AlertRule(
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
        with self.db.begin_session() as session:
            session.add(rule)
            session.flush()
            return rule

    def close_at(self, hour: int, minute: int, second: int = 0) -> None:
        self.clock.set(hour, minute, second)
        self.dispatcher.close_windows()


def repeat(event, *variants):
    return [lambda v=v: event(**v) for v in variants]


class TestDispatch(DispatcherHarness):
    # --- instant and limit-window matching ---

    @pytest.mark.parametrize(
        ('rules', 'events', 'sent_after_each'),
        [
            pytest.param(
                [{}],
                [guardrail_event, guardrail_event],
                [1, 2],
                id='instant-sends-per-event',
            ),
            pytest.param(
                [{'event': 'fallback-triggered'}], [fallback_event], [1], id='fallback'
            ),
            pytest.param(
                [{'event': 'guardrail-output-pii'}],
                [guardrail_event],
                [0],
                id='another-event',
            ),
            pytest.param(
                [{'route': 'summarise'}], [guardrail_event], [0], id='another-route'
            ),
            pytest.param(
                [{'project': str(uuid.uuid4())}],
                [guardrail_event],
                [0],
                id='another-project',
            ),
            pytest.param(
                [{'project': 'acme'}],
                [guardrail_event],
                [0],
                id='project-name-is-not-its-uuid',
            ),
            pytest.param(
                [{'enabled': False}, {'deleted': True}],
                [guardrail_event],
                [0],
                id='disabled-and-deleted',
            ),
            pytest.param(
                [{'event': 'cache-exact'}],
                [cache_hit_event],
                [0],
                id='cache-hit-not-alertable',
            ),
            pytest.param(
                [limit_rule()],
                repeat(
                    limit_event,
                    {'window_id': 'w1'},
                    {'window_id': 'w1'},
                    {'window_id': 'w2'},
                ),
                [1, 1, 2],
                id='limit-once-per-window',
            ),
            pytest.param(
                [limit_rule()],
                repeat(
                    limit_event,
                    {'window_id': None},
                    {'window_id': None},
                    {'window_id': None, 'reset_time': RESET + 60},
                ),
                [1, 1, 2],
                id='reset-time-names-the-window',
            ),
            pytest.param(
                [limit_rule(name='first'), limit_rule(name='second')],
                [limit_event],
                [2],
                id='each-limit-rule-has-its-window',
            ),
            pytest.param(
                [limit_rule('rate_limit-75pct-1m')],
                repeat(
                    limit_event,
                    {'threshold_percentage': 98},
                    {'threshold_percentage': 75},
                ),
                [0, 1],
                id='threshold-on-its-percentage-only',
            ),
            pytest.param(
                [limit_rule()],
                repeat(limit_event, {'threshold_percentage': 75}),
                [0],
                id='threshold-not-the-exceeded-rule',
            ),
            pytest.param(
                [
                    limit_rule('rate_limit-exceeded-1h'),
                    limit_rule('token_input_limit-exceeded-1m'),
                ],
                [limit_event],
                [0],
                id='category-and-window-must-match',
            ),
            pytest.param(
                [
                    limit_rule(f'{c}-exceeded-1m', name=c)
                    for c in (
                        'token_input_limit',
                        'token_output_limit',
                        'budget_limit',
                        'audio_duration_limit',
                    )
                ],
                repeat(
                    limit_event,
                    {
                        'event_type': EventType.TOKEN_INPUT_LIMIT,
                        'category': 'token_input',
                    },
                    {
                        'event_type': EventType.TOKEN_OUTPUT_LIMIT,
                        'category': 'token_output',
                    },
                    {'event_type': EventType.BUDGET_LIMIT, 'category': 'budget'},
                    {
                        'event_type': EventType.AUDIO_DURATION_LIMIT,
                        'category': 'audio_duration',
                    },
                ),
                [1, 2, 3, 4],
                id='each-limit-category',
            ),
            pytest.param(
                [limit_rule()],
                repeat(limit_event, {'limit_scope': LimitScope.PROJECT}),
                [0],
                id='project-limit-not-a-route-rule',
            ),
            pytest.param(
                [project_rule()],
                repeat(
                    project_budget_event,
                    {'window_id': 'w1'},
                    {'window_id': 'w1'},
                    {'window_id': 'w2'},
                ),
                [1, 1, 2],
                id='project-once-per-window',
            ),
            pytest.param(
                [project_rule(project=str(uuid.uuid4()))],
                [project_budget_event],
                [0],
                id='project-rule-only-its-project',
            ),
            pytest.param(
                [project_rule()],
                repeat(
                    limit_event,
                    {'category': 'budget', 'event_type': EventType.BUDGET_LIMIT},
                ),
                [0],
                id='route-budget-not-a-project-rule',
            ),
            pytest.param(
                [credential_rule()],
                repeat(
                    credential_event,
                    {'window_id': 'w1'},
                    {'window_id': 'w1'},
                    {'window_id': 'w2'},
                ),
                [1, 1, 2],
                id='credential-once-per-window',
            ),
            pytest.param(
                [credential_rule('rate_limit-98pct-1m')],
                repeat(credential_event, {'threshold_percentage': 98}),
                [1],
                id='credential-threshold',
            ),
            pytest.param(
                [credential_rule()],
                repeat(credential_event, {'credential_uuid': str(uuid.uuid4())}),
                [0],
                id='credential-rule-only-its-credential',
            ),
            pytest.param(
                [credential_rule()],
                repeat(limit_event, {'api_key_uuid': CREDENTIAL_UUID}),
                [0],
                id='route-limit-not-a-credential-rule',
            ),
            pytest.param(
                [credential_rule()],
                repeat(credential_event, {'credential_uuid': ''}),
                [0],
                id='credential-event-without-credential',
            ),
        ],
    )
    def test_a_rule_sends_on_each_event_it_matches(
        self, rules, events, sent_after_each
    ):
        for columns in rules:
            self.rule(**columns)

        sent = []
        for event in events:
            events_processor.emit_event(event())
            sent.append(len(self.email.sent))

        assert sent == sent_after_each
        assert len(self.buffer.records) == sent_after_each[-1]
        assert all(e['recipients'] == ['ops@example.com'] for e in self.email.sent)

    def test_every_matching_rule_sends(self):
        self.rule(name='first')
        self.rule(name='second')

        events_processor.emit_event(guardrail_event())

        subjects = [e['subject'] for e in self.email.sent]
        assert len(subjects) == 2
        assert any('first' in s for s in subjects)
        assert any('second' in s for s in subjects)

    @pytest.mark.parametrize(
        ('columns', 'event', 'subject', 'expected'),
        [
            pytest.param(
                {},
                guardrail_event,
                None,
                {
                    'RULE_NAME': 'PII watch',
                    'SCOPE': 'route',
                    'PROJECT_UUID': PROJECT_UUID,
                    'ROUTE_NAME': 'chat',
                    'CREDENTIAL_UUID': None,
                    'EVENT': 'guardrail-input-pii',
                    'AGGREGATION': 'instant',
                    'COUNT': 1,
                    'WINDOW_START': None,
                    'WINDOW_END': None,
                },
                id='instant',
            ),
            pytest.param(
                limit_rule(),
                limit_event,
                None,
                {
                    'EVENT': 'rate_limit-exceeded-1m',
                    'AGGREGATION': 'limit_window',
                    'COUNT': 1,
                    'WINDOW_START': NOW,
                    'WINDOW_END': NOW.replace(minute=31),
                },
                id='limit-window',
            ),
            pytest.param(
                project_rule(),
                project_budget_event,
                '[Alert] PII watch: budget_limit-exceeded-1m on acme',
                {'SCOPE': 'project', 'PROJECT_UUID': PROJECT_UUID, 'ROUTE_NAME': None},
                id='project',
            ),
            pytest.param(
                credential_rule(),
                repeat(
                    credential_event, {'event_type': EventType.CREDENTIAL_RATE_LIMIT}
                )[0],
                '[Alert] PII watch: rate_limit-exceeded-1m on billing-service',
                {
                    'SCOPE': 'credential',
                    'CREDENTIAL_UUID': CREDENTIAL_UUID,
                    'PROJECT_UUID': None,
                },
                id='credential',
            ),
        ],
    )
    def test_an_alert_is_recorded_as_sent_with_its_rule_and_target(
        self, columns, event, subject, expected
    ):
        rule = self.rule(**columns)

        events_processor.emit_event(event())

        [email] = self.email.sent
        if subject is not None:
            assert email['subject'] == subject
        [record] = self.buffer.records
        assert record['RULE_UUID'] == str(rule.uuid)
        assert record['STATUS'] == 'sent'
        assert {k: record[k] for k in expected} == expected

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

    # --- email content ---

    def test_a_limit_email_shows_consumption_maximum_and_reset_time(self):
        self.rule(**limit_rule())

        events_processor.emit_event(limit_event(consumption=11, maximum=10))

        body = self.email.sent[0]['body']
        for expected in ('Consumption', '>11<', 'Maximum', '>10<'):
            assert expected in body
        assert '2026-10-13 09:31:00 UTC' in body

    @pytest.mark.parametrize(
        ('columns', 'event'),
        [
            pytest.param(limit_rule('rate_limit-75pct-1m'), limit_event, id='route'),
            pytest.param(
                project_rule('budget_limit-75pct-1m'),
                project_budget_event,
                id='project-budget',
            ),
        ],
    )
    def test_a_threshold_email_also_shows_the_percentage(self, columns, event):
        self.rule(**columns)

        events_processor.emit_event(event(threshold_percentage=75, consumption=7.5))

        [email] = self.email.sent
        assert '>75%<' in email['body']
        assert '>7.5<' in email['body']

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

    # --- window ---

    def test_a_closed_window_sends_one_alert_with_the_count_once(self):
        self.rule(**window_rule('5m'))

        for _ in range(3):
            events_processor.emit_event(guardrail_event())
        self.close_at(9, 35)
        self.close_at(9, 36)

        [email] = self.email.sent
        assert email['recipients'] == ['ops@example.com']
        assert 'PII watch' in email['subject']
        assert 'acme / chat' in email['subject']
        assert 'Events' in email['body']
        assert '>3<' in email['body']
        assert '2026-10-13 09:30:00 UTC → 2026-10-13 09:35:00 UTC' in email['body']

    @pytest.mark.parametrize(
        ('size', 'event_at', 'closed_at', 'start', 'end'),
        [
            pytest.param(
                '15m',
                NOW,
                NOW.replace(minute=45),
                NOW,
                NOW.replace(minute=45),
                id='15m',
            ),
            pytest.param(
                '1h',
                NOW.replace(minute=41),
                NOW.replace(hour=10, minute=0),
                NOW.replace(minute=0),
                NOW.replace(hour=10, minute=0),
                id='1h-aligned-to-the-utc-clock',
            ),
            pytest.param(
                '24h',
                NOW,
                datetime(2026, 10, 14, tzinfo=UTC),
                datetime(2026, 10, 13, tzinfo=UTC),
                datetime(2026, 10, 14, tzinfo=UTC),
                id='day-from-midnight-to-midnight-utc',
            ),
        ],
    )
    def test_a_window_alert_is_recorded_with_its_count_and_utc_aligned_interval(
        self, size, event_at, closed_at, start, end
    ):
        rule = self.rule(**window_rule(size, event='fallback-triggered'))

        self.clock.now = event_at
        events_processor.emit_event(fallback_event())
        events_processor.emit_event(fallback_event())
        self.clock.now = closed_at
        self.dispatcher.close_windows()

        [record] = self.buffer.records
        assert record['RULE_UUID'] == str(rule.uuid)
        assert record['EVENT'] == 'fallback-triggered'
        assert record['AGGREGATION'] == 'window'
        assert record['COUNT'] == 2
        assert record['WINDOW_START'] == start
        assert record['WINDOW_END'] == end
        assert record['STATUS'] == 'sent'

    def test_an_event_counted_after_its_window_closed_sends_no_second_alert(self):
        self.rule(**window_rule('5m'))

        events_processor.emit_event(guardrail_event())
        self.close_at(9, 35)
        # A replica whose clock lags still counts into the closed window.
        self.clock.set(9, 34, 59)
        events_processor.emit_event(guardrail_event())
        self.close_at(9, 35, 30)

        assert len(self.email.sent) == 1

    def test_events_in_consecutive_windows_send_one_alert_each(self):
        self.rule(**window_rule('5m'))

        events_processor.emit_event(guardrail_event())
        self.clock.set(9, 36)
        events_processor.emit_event(guardrail_event())
        events_processor.emit_event(guardrail_event())
        self.close_at(9, 40)

        counts = sorted(r['COUNT'] for r in self.buffer.records)
        assert counts == [1, 2]

    def test_each_window_rule_counts_on_its_own(self):
        self.rule(**window_rule('5m', name='first'))
        self.rule(**window_rule('5m', name='second'))

        events_processor.emit_event(guardrail_event())
        self.close_at(9, 35)

        assert sorted(r['RULE_NAME'] for r in self.buffer.records) == [
            'first',
            'second',
        ]

    @pytest.mark.parametrize(
        ('emitted', 'change', 'closed_at'),
        [
            pytest.param(1, None, (9, 34, 59), id='window-still-open'),
            pytest.param(0, None, (9, 35), id='empty-window'),
            pytest.param(
                1,
                lambda dao, rule: dao.toggle_enabled(rule.uuid, False),
                (9, 35),
                id='rule-disabled',
            ),
            pytest.param(
                1,
                lambda dao, rule: dao.soft_delete_by_uuid(rule.uuid),
                (9, 35),
                id='rule-deleted',
            ),
            pytest.param(
                1,
                lambda dao, rule: dao.update_rule(
                    rule.uuid, {'time_aggregation': 'instant', 'window_size': None}
                ),
                (9, 35),
                id='rule-switched-to-instant',
            ),
            pytest.param(
                1,
                lambda dao, rule: dao.update_rule(rule.uuid, {'window_size': '1h'}),
                (9, 35),
                id='rule-resized',
            ),
        ],
    )
    def test_a_window_sends_nothing_while_open_empty_or_after_its_rule_changed(
        self, emitted, change, closed_at
    ):
        rule = self.rule(**window_rule('5m'))

        for _ in range(emitted):
            events_processor.emit_event(guardrail_event())
        if change:
            change(AlertRuleDAO(self.db), rule)
        self.close_at(*closed_at)

        assert self.email.sent == []
        assert self.buffer.records == []

    def test_a_dropped_window_is_not_sent_later(self):
        rule = self.rule(**window_rule('5m'))

        events_processor.emit_event(guardrail_event())
        dao = AlertRuleDAO(self.db)
        dao.toggle_enabled(rule.uuid, False)
        self.close_at(9, 35)
        dao.toggle_enabled(rule.uuid, True)
        self.close_at(9, 36)

        assert self.email.sent == []

    def test_a_failed_window_send_is_recorded_as_failed(self):
        self.rule(**window_rule('5m'))
        self.email.outcomes = [RuntimeError('smtp down')]

        events_processor.emit_event(guardrail_event())
        self.close_at(9, 35)

        assert [r['STATUS'] for r in self.buffer.records] == ['failed']


class TestDispatchersSharingOneRedis(DispatcherHarness):
    def make_store(self, request):
        self.redis_url = request.getfixturevalue('redis_connection_url')
        Redis.from_url(self.redis_url).flushdb()
        return self.redis_store()

    def redis_store(self):
        return RedisAlertStore(Redis.from_url(self.redis_url), clock=self.clock)

    def replica(self):
        return AlertDispatcher(
            alert_rule_dao=AlertRuleDAO(self.db),
            email_service=self.email,
            store=self.redis_store(),
        )

    def test_two_dispatchers_on_the_same_redis_send_one_alert_per_window(self):
        self.rule(**window_rule('5m'))
        replica = self.replica()

        self.dispatcher.dispatch(guardrail_event())
        replica.dispatch(guardrail_event())
        replica.dispatch(guardrail_event())
        self.clock.set(9, 35)
        replica.close_windows()
        self.dispatcher.close_windows()

        assert len(self.email.sent) == 1
        [record] = self.buffer.records
        assert record['COUNT'] == 3

    def test_two_dispatchers_on_the_same_redis_send_one_limit_alert(self):
        self.rule(**limit_rule())
        replica = self.replica()

        self.dispatcher.dispatch(limit_event())
        replica.dispatch(limit_event())

        assert len(self.email.sent) == 1
