import datetime
import json
from types import SimpleNamespace
from unittest.mock import patch
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
import yaml

from tests.common import db_mock  # noqa: F401  (registers every table Key relates to)
from tests.common.db_integration import DatabaseIntegration
from tests.common.db_mock import get_sample_key_limit

from radicalbit_ai_gateway.db.dao.alert_rule_dao import AlertRuleDAO
from radicalbit_ai_gateway.db.dao.key_dao import KeyDAO
from radicalbit_ai_gateway.db.dao.key_limit_dao import KeyLimitDAO
from radicalbit_ai_gateway.db.tables.alert_rule_table import AlertRule
from radicalbit_ai_gateway.db.tables.key_table import Key
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.project_entry import ProjectEntry
from radicalbit_ai_gateway.routes.alert_rule_route import AlertRuleRoute
from radicalbit_ai_gateway.services.alert_rule_service import AlertRuleService
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import (
    AlertRuleInternalError,
    AlertRuleInvalidEventError,
    AlertRuleInvalidTargetError,
    AlertRuleNotFoundError,
    AlertRuleUnsupportedTimeAggregationError,
    alert_rule_exception_handler,
)

PROJECT_NAME = 'acme'
PROJECT_UUID = uuid.uuid4()

MODELS = """
chat_models:
  - model_id: gpt-4
    model: openai/gpt-4
  - model_id: gpt-3.5
    model: openai/gpt-3.5
transcription_models:
  - model_id: whisper
    model: openai/whisper-1
"""


def route_config(
    guardrails: dict[str, str] | None = None,
    fallback: bool = False,
    caching: bool = False,
    pii_values: tuple[str, ...] = ('secret',),
    limits: dict | None = None,
) -> GatewayConfig:
    """Build a published configuration with one route, `chat`.

    `guardrails` maps each guardrail attached to the route to its phase.
    `limits` holds the route's limiting sections, as in the YAML.
    """
    raw = yaml.safe_load(MODELS)
    route: dict = {'chat_models': ['gpt-4', 'gpt-3.5']}
    if guardrails:
        raw['guardrails'] = [
            {
                'name': name,
                'type': 'contains',
                'where': where,
                'parameters': {'values': list(pii_values)},
            }
            for name, where in guardrails.items()
        ]
        route['guardrails'] = list(guardrails)
    if fallback:
        route['fallback'] = [{'target': 'gpt-4', 'fallbacks': ['gpt-3.5']}]
    if caching:
        raw['cache'] = {'redis_host': 'localhost', 'redis_port': 6379}
        route['caching'] = {'type': 'exact', 'ttl': 60}
    route.update(limits or {})
    raw['routes'] = {'chat': route}
    return GatewayConfig.model_validate(raw)


def rate_limit(window_size='1 minute', max_requests=10) -> dict:
    return {'rate_limiting': {'window_size': window_size, 'max_requests': max_requests}}


EVERY_LIMIT = {
    'rate_limiting': {'window_size': '1 minute', 'max_requests': 10},
    'token_limiting': {
        'input': {'window_size': '1 hour', 'max_token': 1000},
        'output': {'window_size': '1 day', 'max_token': 500},
    },
    'budget_limiting': {'window_size': '1 month', 'max_budget': 5.0},
    'duration_limiting': {'window_size': '90 minutes', 'max_duration_seconds': 600},
    'transcription_models': ['whisper'],
}


class FakeProjectBudgets:
    """The project budget limits stored in the DB, by project uuid."""

    def __init__(self):
        self.limits: dict[str, list[SimpleNamespace]] = {}

    def add(self, project_uuid, window_size: str, max_value: float = 10.0) -> None:
        self.limits.setdefault(str(project_uuid), []).append(
            SimpleNamespace(window_size=window_size, max_value=max_value)
        )

    def get_by_project_uuid(self, project_uuid):
        return list(self.limits.get(str(project_uuid), []))


class FakeProjects:
    """The projects that are not deleted, by uuid."""

    def __init__(self):
        self.names: dict[str, str] = {}

    def get_by_uuid(self, project_uuid):
        name = self.names.get(str(project_uuid))
        return SimpleNamespace(name=name) if name else None


LIMIT_LABELS = {
    'rate_limit': 'Rate limit',
    'token_input_limit': 'Token input limit',
    'token_output_limit': 'Token output limit',
    'budget_limit': 'Budget limit',
    'audio_duration_limit': 'Audio duration limit',
}


def selectable(event: str, label: str) -> dict:
    return {'event': event, 'label': label, 'aggregation': 'selectable'}


def no_events(*limits: tuple[str, str], percentages=(75, 98)) -> dict:
    """List the alertable events of `limits`, as (category, window name), alone."""

    def item(event, label):
        return {'event': event, 'label': label, 'aggregation': 'limit_window'}

    return {
        'guardrail': [],
        'fallback': [],
        'limit': [
            item(f'{c}-exceeded-{w}', f'{LIMIT_LABELS[c]}: exceeded ({w})')
            for c, w in limits
        ],
        'threshold': [
            item(f'{c}-{pct}pct-{w}', f'{LIMIT_LABELS[c]}: {pct}% ({w})')
            for c, w in limits
            for pct in percentages
        ],
    }


def route_rule(event: str, **fields) -> dict:
    """Describe a rule `TestAlertRuleRoute.create` makes, minus generated fields."""
    return {
        'name': 'rule',
        'description': None,
        'scope': 'route',
        'project': str(PROJECT_UUID),
        'projectName': PROJECT_NAME,
        'route': 'chat',
        'credentialUuid': None,
        'credentialName': None,
        'event': event,
        'timeAggregation': 'instant',
        'windowSize': None,
        'channel': 'email',
        'recipients': ['ops@example.com'],
        'enabled': True,
        'stale': False,
        'staleReason': None,
        **fields,
    }


class TestAlertRuleRoute(DatabaseIntegration):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project_configs: dict[str, ProjectEntry] = {}
        cls.project_budgets = FakeProjectBudgets()
        cls.projects = FakeProjects()
        service = AlertRuleService(
            alert_rule_dao=AlertRuleDAO(cls.db),
            project_configs=cls.project_configs,
            project_dao=cls.projects,
            key_dao=KeyDAO(cls.db),
            project_budget_limit_dao=cls.project_budgets,
            key_limit_dao=KeyLimitDAO(cls.db),
        )
        app = FastAPI()
        for err in (
            AlertRuleNotFoundError,
            AlertRuleInvalidEventError,
            AlertRuleInvalidTargetError,
            AlertRuleUnsupportedTimeAggregationError,
            AlertRuleInternalError,
        ):
            app.add_exception_handler(err, alert_rule_exception_handler)
        app.include_router(AlertRuleRoute.get_alert_rule_router(service))
        cls.client = TestClient(app)

    def setUp(self):
        self.project_configs.clear()
        self.project_budgets.limits.clear()
        self.projects.names = {str(PROJECT_UUID): PROJECT_NAME}

    def publish(self, config: GatewayConfig) -> None:
        self.project_configs[PROJECT_NAME] = ProjectEntry(
            uuid=PROJECT_UUID, config=config
        )

    def unpublish(self) -> None:
        self.project_configs.pop(PROJECT_NAME, None)

    def create(self, event: str, route: str = 'chat', **overrides):
        payload = {
            'name': 'rule',
            'project': str(PROJECT_UUID),
            'route': route,
            'event': event,
            'recipients': ['ops@example.com'],
            'enabled': True,
            **overrides,
        }
        return self.client.post('/rule', json=payload)

    def rejected(self, response) -> str:
        assert response.status_code == 400, response.text
        return response.json()['error']['message']

    def created(self, event: str, **overrides) -> dict:
        response = self.create(event, **overrides)
        assert response.status_code == 201, response.text
        return response.json()

    def insert_rule(self, event: str, route: str = 'chat', **columns) -> AlertRule:
        """Store a rule bypassing validation, as an older release could have."""
        now = datetime.datetime.now(tz=datetime.UTC)
        return self.insert(
            AlertRule(
                **{
                    'name': 'legacy',
                    'project': str(PROJECT_UUID),
                    'route': route,
                    'scope': 'route',
                    'event': event,
                    'time_aggregation': 'instant',
                    'channel': 'email',
                    'recipients': json.dumps(['ops@example.com']),
                    'enabled': True,
                    'deleted': False,
                    'created_at': now,
                    'updated_at': now,
                    **columns,
                }
            )
        )

    def insert_credential(self, name: str) -> Key:
        now = datetime.datetime.now(tz=datetime.UTC)
        return self.insert(
            Key(
                name=name,
                hashed_key=uuid.uuid4().hex,
                obscured_key='sk-...abcd',
                created_at=now,
                updated_at=now,
            )
        )

    def listed(self, rule_uuid) -> dict:
        response = self.client.get('/rule')
        assert response.status_code == 200
        return next(r for r in response.json() if r['uuid'] == str(rule_uuid))

    def fetched(self, rule_uuid) -> dict:
        response = self.client.get(f'/rule/{rule_uuid}')
        assert response.status_code == 200
        return response.json()

    def alertable_events(self, route: str = 'chat') -> dict:
        response = self.client.get(
            f'/projects/{PROJECT_UUID}/routes/{route}/alertable-events'
        )
        assert response.status_code == 200
        return response.json()

    def body(self, rule: dict) -> dict:
        """Drop the fields the server generates."""
        return {
            k: v for k, v in rule.items() if k not in ('uuid', 'createdAt', 'updatedAt')
        }

    def assert_stale(self, rule_uuid, reason: str | None) -> None:
        listed = self.listed(rule_uuid)
        assert (listed['stale'], listed['staleReason']) == (reason is not None, reason)

    def patched(self, rule_uuid, **fields):
        return self.client.patch(f'/rule/{rule_uuid}', json=fields)

    # --- alertable events ---

    def test_alertable_events_lists_guardrails_by_phase_and_fallback(self):
        self.publish(
            route_config(
                guardrails={'pii': 'input', 'toxicity': 'io', 'format': 'output'},
                fallback=True,
            )
        )

        assert self.alertable_events() == {
            'guardrail': [
                selectable('guardrail-input-pii', 'Guardrail: PII (input)'),
                selectable('guardrail-input-toxicity', 'Guardrail: TOXICITY (input)'),
                selectable('guardrail-output-toxicity', 'Guardrail: TOXICITY (output)'),
                selectable('guardrail-output-format', 'Guardrail: FORMAT (output)'),
            ],
            'fallback': [selectable('fallback-triggered', 'Fallback: triggered')],
            'limit': [],
            'threshold': [],
        }

    def test_alertable_events_are_empty_without_offered_events(self):
        cases = [
            ('cache events are never offered', route_config(caching=True), 'chat'),
            ('unpublished route', route_config(fallback=True), 'missing'),
        ]
        for case, config, route in cases:
            with self.subTest(case):
                self.publish(config)

                assert self.alertable_events(route=route) == no_events()

    def test_alertable_events_offer_every_route_limit(self):
        self.publish(route_config(limits=EVERY_LIMIT))

        assert self.alertable_events() == no_events(
            ('rate_limit', '1m'),
            ('token_input_limit', '1h'),
            ('token_output_limit', '1d'),
            ('budget_limit', '1mo'),
            ('audio_duration_limit', '90m'),
        )

    def test_alertable_events_offer_one_threshold_per_global_percentage(self):
        self.publish(route_config(limits=rate_limit()))

        with patch.object(
            get_app_config().alert_config, 'alert_threshold_percentages', [50, 90]
        ):
            events = self.alertable_events()

        assert events == no_events(('rate_limit', '1m'), percentages=(50, 90))

    def test_the_window_is_named_by_the_largest_unit_that_divides_it(self):
        cases = [
            (rate_limit('1 month'), '1mo'),
            (rate_limit('30 days'), '1mo'),
            (rate_limit('2 weeks'), '2w'),
            (rate_limit('14 days'), '2w'),
            (rate_limit('8 days'), '8d'),
            (rate_limit('90 minutes'), '90m'),
            (rate_limit('120 minutes'), '2h'),
            (rate_limit('45 seconds'), '45s'),
            (rate_limit(3600), '1h'),
            # The algorithm is not part of the name
            (
                {
                    'rate_limiting': {
                        'algorithm': 'ALIGNED_FIXED_WINDOW',
                        'window_size': '1 hour',
                        'max_requests': 10,
                    }
                },
                '1h',
            ),
        ]
        for limits, name in cases:
            with self.subTest(limits=limits):
                self.publish(route_config(limits=limits))

                [exceeded] = self.alertable_events()['limit']

                assert exceeded['event'] == f'rate_limit-exceeded-{name}'

    def test_route_budget_is_not_offered_when_the_project_has_a_budget(self):
        self.publish(route_config(limits=EVERY_LIMIT))
        self.project_budgets.add(PROJECT_UUID, '1 day')

        assert self.alertable_events() == no_events(
            ('rate_limit', '1m'),
            ('token_input_limit', '1h'),
            ('token_output_limit', '1d'),
            ('audio_duration_limit', '90m'),
        )

    # --- create / update validation ---

    def test_create_a_route_rule_disabled_by_default(self):
        self.publish(route_config(guardrails={'pii': 'input'}))

        response = self.client.post(
            '/rule',
            json={
                'name': 'rule',
                'project': str(PROJECT_UUID),
                'route': 'chat',
                'event': 'guardrail-input-pii',
                'recipients': ['ops@example.com'],
            },
        )

        assert response.status_code == 201, response.text
        assert self.body(response.json()) == route_rule(
            'guardrail-input-pii', enabled=False
        )

    def test_create_a_rule_on_a_limit_event_with_limit_window(self):
        self.publish(route_config(limits=rate_limit()))
        for event in ('rate_limit-exceeded-1m', 'rate_limit-75pct-1m'):
            with self.subTest(event):
                rule = self.created(event, timeAggregation='limit_window')

                assert self.body(rule) == route_rule(
                    event, timeAggregation='limit_window'
                )

    def test_create_rejects_an_invalid_rule(self):
        fallback = route_config(fallback=True)
        project = {'scope': 'project', 'route': None}
        project_window = {**project, 'timeAggregation': 'limit_window'}
        credential = {'scope': 'credential', 'project': None, 'route': None}
        not_for_route = 'Event "{}" is not valid for route "chat"'
        not_for_project = f'Event "{{}}" is not valid for project "{PROJECT_UUID}"'
        limit_only = 'Limit and threshold events take only the limit_window aggregation'
        # (published config, project budget window, event, overrides, error)
        cases = [
            (rate_limit(), None, 'rate_limit-exceeded-1m', {}, limit_only),
            (
                fallback,
                None,
                'fallback-triggered',
                {'timeAggregation': 'limit_window'},
                'The limit_window aggregation applies only to limit and threshold events',
            ),
            (
                route_config(guardrails={'pii': 'input'}),
                None,
                'guardrail-output-pii',
                {},
                not_for_route,
            ),
            (route_config(caching=True), None, 'cache-exact', {}, not_for_route),
            (
                fallback,
                None,
                'fallback-triggered',
                {'route': None},
                'A route rule requires a project and a route',
            ),
            (
                fallback,
                None,
                'fallback-triggered',
                {'project': None},
                'A route rule requires a project and a route',
            ),
            (
                fallback,
                None,
                'fallback-triggered',
                {'credential': str(uuid.uuid4())},
                'A route rule takes no credential',
            ),
            (
                fallback,
                None,
                'fallback-triggered',
                {'project': PROJECT_NAME},
                not_for_route,
            ),
            (
                None,
                None,
                'budget_limit-exceeded-1mo',
                {**project, 'project': None},
                'A project rule requires a project',
            ),
            (
                None,
                None,
                'budget_limit-exceeded-1mo',
                {'scope': 'project'},
                'A project rule takes no route and no credential',
            ),
            (
                None,
                None,
                'rate_limit-exceeded-1m',
                credential,
                'A credential rule requires a credential',
            ),
            (
                None,
                None,
                'rate_limit-exceeded-1m',
                {'scope': 'credential', 'credential': str(uuid.uuid4())},
                'A credential rule takes no project and no route',
            ),
            (
                fallback,
                None,
                'fallback-triggered',
                {'timeAggregation': 'window'},
                'A window size is required with window aggregation',
            ),
            (
                fallback,
                None,
                'fallback-triggered',
                {'windowSize': '5m'},
                'A window size applies only to window aggregation',
            ),
            (
                fallback,
                None,
                'fallback-triggered',
                {'timeAggregation': 'window', 'windowSize': '10m'},
                422,
            ),
            (
                None,
                None,
                'budget_limit-exceeded-1mo',
                {**project, 'timeAggregation': 'window', 'windowSize': '1h'},
                'Window aggregation applies only to guardrail and fallback events',
            ),
            (
                None,
                '1 day',
                'budget_limit-exceeded-1h',
                project_window,
                not_for_project,
            ),
            (None, '1 day', 'rate_limit-exceeded-1d', project_window, not_for_project),
            (
                None,
                '1 day',
                'budget_limit-exceeded-1d',
                {**project, 'timeAggregation': 'instant'},
                limit_only,
            ),
        ]
        for config, budget_window, event, overrides, error in cases:
            with self.subTest(event=event, overrides=overrides):
                self.setUp()
                if config:
                    self.publish(config)
                if budget_window:
                    self.project_budgets.add(PROJECT_UUID, budget_window)

                response = self.create(event, **overrides)

                if error == 422:
                    assert response.status_code == 422, response.text
                else:
                    assert self.rejected(response) == error.format(event)

    def test_update_rejects_an_invalid_rule(self):
        self.publish(
            route_config(
                guardrails={'pii': 'input'}, fallback=True, limits=rate_limit()
            )
        )
        rule = self.created('fallback-triggered')
        limit_rule = self.created(
            'rate_limit-exceeded-1m', timeAggregation='limit_window'
        )
        cases = [
            (
                rule,
                {'event': 'guardrail-output-pii'},
                'Event "guardrail-output-pii" is not valid for route "chat"',
            ),
            (
                rule,
                {'scope': 'credential', 'credential': str(uuid.uuid4())},
                'A credential rule takes no project and no route',
            ),
            (
                rule,
                {'windowSize': '1h'},
                'A window size applies only to window aggregation',
            ),
            (
                limit_rule,
                {'timeAggregation': 'instant'},
                'Limit and threshold events take only the limit_window aggregation',
            ),
        ]
        for target, fields, error in cases:
            with self.subTest(fields=fields):
                response = self.patched(target['uuid'], **fields)

                assert self.rejected(response) == error

    def test_update_moves_a_rule_between_events_and_aggregations(self):
        self.publish(route_config(guardrails={'pii': 'input'}, fallback=True))
        fallback = self.create(
            'fallback-triggered', timeAggregation='window', windowSize='15m'
        )
        assert fallback.status_code == 201, fallback.text
        assert self.body(fallback.json()) == route_rule(
            'fallback-triggered', timeAggregation='window', windowSize='15m'
        )
        rule = self.created(
            'guardrail-input-pii', timeAggregation='window', windowSize='24h'
        )
        steps = [
            (
                {'event': 'fallback-triggered'},
                {'timeAggregation': 'window', 'windowSize': '24h'},
            ),
            ({'timeAggregation': 'instant', 'windowSize': None}, {}),
            (
                {'timeAggregation': 'window', 'windowSize': '6h'},
                {'timeAggregation': 'window', 'windowSize': '6h'},
            ),
        ]
        for fields, expected in steps:
            with self.subTest(fields=fields):
                response = self.patched(rule['uuid'], **fields)

                assert response.status_code == 200, response.text
                assert self.body(response.json()) == route_rule(
                    'fallback-triggered', **expected
                )

    # --- staleness ---

    def test_a_route_rule_is_stale_when_the_published_route_no_longer_offers_it(self):
        limit_window = {'timeAggregation': 'limit_window'}
        # (published config, event, overrides, change, stale reason)
        cases = [
            (
                route_config(limits=rate_limit()),
                'rate_limit-exceeded-1m',
                limit_window,
                lambda: self.publish(route_config()),
                'Route "chat" no longer has a rate limit',
            ),
            (
                route_config(limits=rate_limit('1 minute')),
                'rate_limit-exceeded-1m',
                limit_window,
                lambda: self.publish(route_config(limits=rate_limit('1 hour'))),
                'The rate limit of route "chat" no longer has a 1m window',
            ),
            (
                route_config(limits=rate_limit(max_requests=10)),
                'rate_limit-75pct-1m',
                limit_window,
                lambda: self.publish(route_config(limits=rate_limit(max_requests=99))),
                None,
            ),
            (
                route_config(limits=EVERY_LIMIT),
                'budget_limit-exceeded-1mo',
                limit_window,
                lambda: self.project_budgets.add(PROJECT_UUID, '1 day'),
                'The project budget limit replaces the budget limit of route "chat"',
            ),
            (
                route_config(guardrails={'pii': 'input'}),
                'guardrail-input-pii',
                {},
                self.unpublish,
                'Route "chat" is not in the published configuration',
            ),
            (
                route_config(guardrails={'pii': 'input'}),
                'guardrail-input-pii',
                {},
                lambda: self.publish(route_config(guardrails={'pii_v2': 'input'})),
                'Guardrail "pii" is no longer applied to route "chat"',
            ),
            (
                route_config(guardrails={'pii': 'input'}),
                'guardrail-input-pii',
                {},
                lambda: self.publish(route_config(guardrails={'pii': 'output'})),
                'Guardrail "pii" no longer runs on input of route "chat"',
            ),
            (
                route_config(fallback=True),
                'fallback-triggered',
                {},
                lambda: self.publish(route_config()),
                'Route "chat" no longer has a fallback',
            ),
            (
                route_config(guardrails={'pii': 'io'}, pii_values=('secret',)),
                'guardrail-output-pii',
                {},
                lambda: self.publish(
                    route_config(guardrails={'pii': 'io'}, pii_values=('password',))
                ),
                None,
            ),
        ]
        for config, event, overrides, change, reason in cases:
            with self.subTest(event=event, reason=reason):
                self.setUp()
                self.publish(config)
                rule = self.created(event, **overrides)

                change()

                self.assert_stale(rule['uuid'], reason)
                assert self.listed(rule['uuid'])['enabled'] is True

    def test_a_threshold_rule_is_stale_when_its_percentage_is_dropped(self):
        self.publish(route_config(limits=rate_limit()))
        route_rule_ = self.created(
            'rate_limit-75pct-1m', timeAggregation='limit_window'
        )
        credential = self.insert_credential('billing-service')
        self.add_credential_limit(credential, 'request_rate', '1 minute')
        credential_rule = self.created_credential_rule(
            credential, 'rate_limit-75pct-1m'
        )

        with patch.object(
            get_app_config().alert_config, 'alert_threshold_percentages', [90]
        ):
            for rule in (route_rule_, credential_rule):
                self.assert_stale(rule['uuid'], 'Threshold 75% is no longer configured')

    def test_a_legacy_rule_the_validation_would_reject_is_stale(self):
        self.publish(route_config(caching=True, fallback=True))
        credential = self.insert_credential('billing-service')
        credential_rule = {'scope': 'credential', 'project': None, 'route': None}
        cases = [
            ('cache-exact', {}, 'Cache hits no longer trigger alerts'),
            (
                'fallback-triggered',
                {'project': PROJECT_NAME},
                'Route "chat" is not in the published configuration',
            ),
            (
                'rate_limit-exceeded-1m',
                {
                    **credential_rule,
                    'credential_uuid': None,
                    'time_aggregation': 'limit_window',
                },
                'The credential no longer exists',
            ),
            (
                'fallback-triggered',
                {**credential_rule, 'credential_uuid': credential.uuid},
                'Event "fallback-triggered" is not offered by the credential',
            ),
        ]
        for event, columns, reason in cases:
            with self.subTest(event=event, columns=columns):
                rule = self.insert_rule(event, **columns)

                self.assert_stale(rule.uuid, reason)

    def test_a_rule_still_holding_a_project_name_can_be_renamed(self):
        self.publish(route_config(fallback=True))
        rule = self.insert_rule('fallback-triggered', project=PROJECT_NAME)

        response = self.patched(rule.uuid, name='renamed')

        assert response.status_code == 200, response.text
        assert response.json()['name'] == 'renamed'

    def test_republishing_clears_the_warning(self):
        self.publish(route_config(fallback=True))
        rule = self.created('fallback-triggered')
        self.unpublish()
        assert self.listed(rule['uuid'])['stale'] is True

        self.publish(route_config(fallback=True))

        self.assert_stale(rule['uuid'], None)

    def test_get_rule_carries_staleness(self):
        self.publish(route_config(fallback=True))
        rule = self.created('fallback-triggered')
        assert self.body(self.fetched(rule['uuid'])) == route_rule('fallback-triggered')

        self.publish(route_config())

        assert self.body(self.fetched(rule['uuid'])) == route_rule(
            'fallback-triggered',
            stale=True,
            staleReason='Route "chat" no longer has a fallback',
        )

    # --- list / toggle / delete ---

    def test_list_returns_newest_rules_first(self):
        self.publish(route_config(guardrails={'pii': 'io'}, fallback=True))
        first = self.created('guardrail-input-pii')
        second = self.created('guardrail-output-pii')
        third = self.created('fallback-triggered')

        response = self.client.get('/rule')

        assert response.status_code == 200
        assert [r['uuid'] for r in response.json()] == [
            third['uuid'],
            second['uuid'],
            first['uuid'],
        ]

    def test_toggle_leaves_staleness_to_the_published_configuration(self):
        self.publish(route_config(fallback=True))
        rule = self.created('fallback-triggered')
        self.publish(route_config())

        disabled = self.client.patch(
            f'/rule/{rule["uuid"]}/enabled', json={'enabled': False}
        )
        enabled = self.client.patch(
            f'/rule/{rule["uuid"]}/enabled', json={'enabled': True}
        )

        assert disabled.status_code == 200
        assert disabled.json()['enabled'] is False
        assert enabled.status_code == 200
        assert enabled.json()['enabled'] is True
        assert enabled.json()['stale'] is True

    def test_delete_rule(self):
        self.publish(route_config(fallback=True))
        rule = self.created('fallback-triggered')

        response = self.client.delete(f'/rule/{rule["uuid"]}')

        assert response.status_code == 200
        assert self.client.get(f'/rule/{rule["uuid"]}').status_code == 404
        assert all(r['uuid'] != rule['uuid'] for r in self.client.get('/rule').json())

    # --- project budget ---

    def project_events(self, project_uuid=PROJECT_UUID) -> dict:
        response = self.client.get(f'/projects/{project_uuid}/alertable-events')
        assert response.status_code == 200
        return response.json()

    def created_project_rule(self, event: str = 'budget_limit-exceeded-1d') -> dict:
        response = self.create(
            event, scope='project', route=None, timeAggregation='limit_window'
        )
        assert response.status_code == 201, response.text
        return response.json()

    def test_project_events_offer_each_budget_limit_once(self):
        # (stored budget windows, project deleted, offered (category, window))
        cases = [
            (
                ['1 day', '30 days'],
                False,
                [('budget_limit', '1d'), ('budget_limit', '1mo')],
            ),
            (['1 day', '24 hours', '86400'], False, [('budget_limit', '1d')]),
            # An unreadable stored window is skipped
            (['whenever', '1 day'], False, [('budget_limit', '1d')]),
            ([], False, []),
            (['1 day'], True, []),
        ]
        for windows, deleted, offered in cases:
            with self.subTest(windows=windows, deleted=deleted):
                self.setUp()
                for window in windows:
                    self.project_budgets.add(PROJECT_UUID, window)
                if deleted:
                    self.projects.names.clear()

                # No published configuration is needed
                assert self.project_events() == no_events(*offered)

    def test_create_a_project_rule_on_a_budget_event(self):
        self.project_budgets.add(PROJECT_UUID, '1 day')

        rule = self.created_project_rule('budget_limit-98pct-1d')

        assert self.body(rule) == route_rule(
            'budget_limit-98pct-1d',
            scope='project',
            route=None,
            timeAggregation='limit_window',
        )

    def test_update_moves_a_project_rule_only_to_an_offered_event(self):
        self.project_budgets.add(PROJECT_UUID, '1 day')
        self.project_budgets.add(PROJECT_UUID, '1 month')
        rule = self.created_project_rule()

        rejected = self.patched(rule['uuid'], event='budget_limit-exceeded-1w')
        moved = self.patched(rule['uuid'], event='budget_limit-75pct-1mo')

        assert self.rejected(rejected) == (
            f'Event "budget_limit-exceeded-1w" is not valid for project "{PROJECT_UUID}"'
        )
        assert moved.status_code == 200, moved.text
        assert moved.json()['event'] == 'budget_limit-75pct-1mo'

    def test_a_project_rule_is_stale_once_its_budget_is_gone(self):
        def replace_budget(window, max_value=10.0):
            self.project_budgets.limits.clear()
            self.project_budgets.add(PROJECT_UUID, window, max_value=max_value)

        def delete_project():
            self.projects.names.clear()

        cases = [
            (delete_project, 'The project no longer exists'),
            (
                lambda: replace_budget('1 week'),
                'The project has no budget limit with a 1d window',
            ),
            (lambda: replace_budget('1 day', max_value=500), None),
            # A project rule does not depend on the published configuration
            (self.unpublish, None),
        ]
        for change, reason in cases:
            with self.subTest(reason=reason):
                self.setUp()
                self.project_budgets.add(PROJECT_UUID, '1 day', max_value=10)
                rule = self.created_project_rule()

                change()

                self.assert_stale(rule['uuid'], reason)

    # --- credential limits ---

    def credential_events(self, credential_uuid) -> dict:
        response = self.client.get(f'/keys/{credential_uuid}/alertable-events')
        assert response.status_code == 200
        return response.json()

    def add_credential_limit(
        self, credential, category: str, window_size: str, max_value: float = 10.0
    ):
        return self.insert(
            get_sample_key_limit(
                uuid=uuid.uuid4(),
                key_uuid=credential.uuid,
                category=category,
                window_size=window_size,
                max_value=max_value,
            )
        )

    def create_credential_rule(self, credential, event: str, **overrides):
        return self.create(
            event,
            **{
                'scope': 'credential',
                'project': None,
                'route': None,
                'credential': str(credential.uuid),
                'timeAggregation': 'limit_window',
                **overrides,
            },
        )

    def created_credential_rule(self, credential, event: str) -> dict:
        response = self.create_credential_rule(credential, event)
        assert response.status_code == 201, response.text
        return response.json()

    def test_credential_events_offer_each_limit_and_window_once(self):
        every_category = [
            (category, '1 hour')
            for category in ('budget', 'token_output', 'token_input', 'request_rate')
        ]
        # (stored (category, window) limits, offered (category, window))
        cases = [
            (
                [('request_rate', '1 minute'), ('request_rate', '1 day')],
                [('rate_limit', '1m'), ('rate_limit', '1d')],
            ),
            (
                every_category,
                [
                    ('rate_limit', '1h'),
                    ('token_input_limit', '1h'),
                    ('token_output_limit', '1h'),
                    ('budget_limit', '1h'),
                ],
            ),
            # A window saved in another unit, before windows were canonical
            (
                [('request_rate', '1 minute'), ('request_rate', '60 seconds')],
                [('rate_limit', '1m')],
            ),
            # Unreadable limits are skipped
            (
                [
                    ('request_rate', 'whenever'),
                    ('mystery', '1 hour'),
                    ('budget', '1 day'),
                ],
                [('budget_limit', '1d')],
            ),
            ([], []),
        ]
        for i, (limits, offered) in enumerate(cases):
            with self.subTest(limits=limits):
                credential = self.insert_credential(f'credential-{i}')
                for category, window in limits:
                    self.add_credential_limit(credential, category, window)

                assert self.credential_events(credential.uuid) == no_events(*offered)

        with self.subTest('unknown credential'):
            assert self.credential_events(uuid.uuid4()) == no_events()

    def test_credential_events_are_empty_when_credentials_are_not_wired(self):
        service = AlertRuleService(alert_rule_dao=AlertRuleDAO(self.db))
        app = FastAPI()
        app.include_router(AlertRuleRoute.get_alert_rule_router(service))
        credential = self.insert_credential('billing-service')
        self.add_credential_limit(credential, 'request_rate', '1 minute')

        response = TestClient(app).get(f'/keys/{credential.uuid}/alertable-events')

        assert response.status_code == 200
        assert response.json()['limit'] == []

    def test_create_a_credential_rule_on_a_limit_event(self):
        credential = self.insert_credential('billing-service')
        self.add_credential_limit(credential, 'request_rate', '1 minute')

        rule = self.created_credential_rule(credential, 'rate_limit-75pct-1m')

        assert self.body(rule) == route_rule(
            'rate_limit-75pct-1m',
            scope='credential',
            project=None,
            projectName=None,
            route=None,
            credentialUuid=str(credential.uuid),
            credentialName='billing-service',
            timeAggregation='limit_window',
        )
        assert self.listed(rule['uuid']) == rule

    def test_credential_rule_validation(self):
        credential = self.insert_credential('billing-service')
        self.add_credential_limit(credential, 'request_rate', '1 minute')
        self.add_credential_limit(credential, 'budget', '1 day')
        rule = self.created_credential_rule(credential, 'rate_limit-exceeded-1m')
        not_valid = f'Event "{{}}" is not valid for credential "{credential.uuid}"'

        assert self.rejected(
            self.create_credential_rule(credential, 'rate_limit-exceeded-1d')
        ) == not_valid.format('rate_limit-exceeded-1d')
        assert (
            self.rejected(
                self.create_credential_rule(
                    credential, 'rate_limit-exceeded-1m', timeAggregation='instant'
                )
            )
            == 'Limit and threshold events take only the limit_window aggregation'
        )
        assert self.rejected(
            self.patched(rule['uuid'], event='budget_limit-exceeded-1m')
        ) == not_valid.format('budget_limit-exceeded-1m')
        moved = self.patched(rule['uuid'], event='budget_limit-98pct-1d')
        assert moved.status_code == 200, moved.text
        assert moved.json()['event'] == 'budget_limit-98pct-1d'

    def test_a_credential_rule_is_stale_once_its_limit_is_gone(self):
        cases = [
            (
                lambda c, lim: KeyDAO(self.db).delete_by_uuid(c.uuid),
                None,
                'The credential no longer exists',
            ),
            (
                lambda c, lim: KeyLimitDAO(self.db).delete_by_uuid(lim.uuid),
                None,
                'The credential has no rate limit with a 1m window',
            ),
            (
                lambda c, lim: KeyLimitDAO(self.db).delete_by_uuid(lim.uuid),
                ('1 hour', 10.0),
                'The credential has no rate limit with a 1m window',
            ),
            (
                lambda c, lim: KeyLimitDAO(self.db).delete_by_uuid(lim.uuid),
                ('1 minute', 5.0),
                None,
            ),
        ]
        for i, (remove, replacement, reason) in enumerate(cases):
            with self.subTest(reason=reason, replacement=replacement):
                credential = self.insert_credential(f'credential-{i}')
                limit = self.add_credential_limit(
                    credential, 'request_rate', '1 minute', max_value=100
                )
                rule = self.created_credential_rule(
                    credential, 'rate_limit-exceeded-1m'
                )

                remove(credential, limit)
                if replacement:
                    self.add_credential_limit(credential, 'request_rate', *replacement)

                self.assert_stale(rule['uuid'], reason)
