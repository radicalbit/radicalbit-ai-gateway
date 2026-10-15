import datetime
import json
from unittest.mock import patch
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
import yaml

from tests.common import db_mock  # noqa: F401  (registers every table Key relates to)
from tests.common.db_integration import DatabaseIntegration

from radicalbit_ai_gateway.db.dao.alert_rule_dao import AlertRuleDAO
from radicalbit_ai_gateway.db.dao.key_dao import KeyDAO
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
    """The project budget limits, by project uuid."""

    def __init__(self):
        self.projects: set[str] = set()

    def get_by_project_uuid(self, project_uuid):
        return ['a budget limit'] if str(project_uuid) in self.projects else []


class TestAlertRuleRoute(DatabaseIntegration):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project_configs: dict[str, ProjectEntry] = {}
        cls.project_budgets = FakeProjectBudgets()
        service = AlertRuleService(
            alert_rule_dao=AlertRuleDAO(cls.db),
            project_configs=cls.project_configs,
            key_dao=KeyDAO(cls.db),
            project_budget_limit_dao=cls.project_budgets,
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
        self.project_budgets.projects.clear()

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

    # --- alertable events ---

    def test_alertable_events_lists_guardrails_by_phase_and_fallback(self):
        self.publish(
            route_config(
                guardrails={'pii': 'input', 'toxicity': 'io', 'format': 'output'},
                fallback=True,
            )
        )

        events = self.alertable_events()

        assert [e['event'] for e in events['guardrail']] == [
            'guardrail-input-pii',
            'guardrail-input-toxicity',
            'guardrail-output-toxicity',
            'guardrail-output-format',
        ]
        assert [e['event'] for e in events['fallback']] == ['fallback-triggered']

    def test_alertable_events_never_offer_cache_events(self):
        self.publish(route_config(caching=True))

        assert self.alertable_events() == {
            'guardrail': [],
            'fallback': [],
            'limit': [],
            'threshold': [],
        }

    def test_alertable_events_empty_for_unpublished_route(self):
        self.publish(route_config(fallback=True))

        assert self.alertable_events(route='missing') == {
            'guardrail': [],
            'fallback': [],
            'limit': [],
            'threshold': [],
        }

    # --- limit and threshold events ---

    def test_alertable_events_offer_every_route_limit(self):
        self.publish(route_config(limits=EVERY_LIMIT))

        events = self.alertable_events()

        assert [e['event'] for e in events['limit']] == [
            'rate_limit-exceeded-1m',
            'token_input_limit-exceeded-1h',
            'token_output_limit-exceeded-1d',
            'budget_limit-exceeded-1mo',
            'audio_duration_limit-exceeded-90m',
        ]

    def test_alertable_events_offer_one_threshold_per_global_percentage(self):
        self.publish(route_config(limits=rate_limit()))

        with patch.object(
            get_app_config().alert_config, 'alert_threshold_percentages', [50, 90]
        ):
            events = self.alertable_events()

        assert [e['event'] for e in events['threshold']] == [
            'rate_limit-50pct-1m',
            'rate_limit-90pct-1m',
        ]

    def test_limit_and_threshold_events_use_the_limit_window_aggregation(self):
        self.publish(route_config(limits=EVERY_LIMIT))

        events = self.alertable_events()

        items = events['limit'] + events['threshold']
        assert len(events['threshold']) == 2 * len(events['limit'])
        assert {item['aggregation'] for item in items} == {'limit_window'}

    def test_limit_events_carry_a_label(self):
        self.publish(route_config(limits=rate_limit()))

        [exceeded] = self.alertable_events()['limit']

        assert exceeded['label']

    def test_the_window_is_named_by_the_largest_unit_that_divides_it(self):
        cases = {
            '1 month': '1mo',
            '30 days': '1mo',
            '2 weeks': '2w',
            '14 days': '2w',
            '8 days': '8d',
            '90 minutes': '90m',
            '120 minutes': '2h',
            '45 seconds': '45s',
            3600: '1h',
        }
        for window_size, name in cases.items():
            with self.subTest(window_size=window_size):
                self.publish(route_config(limits=rate_limit(window_size)))

                [exceeded] = self.alertable_events()['limit']

                assert exceeded['event'] == f'rate_limit-exceeded-{name}'

    def test_the_algorithm_is_not_part_of_the_name(self):
        self.publish(
            route_config(
                limits={
                    'rate_limiting': {
                        'algorithm': 'ALIGNED_FIXED_WINDOW',
                        'window_size': '1 hour',
                        'max_requests': 10,
                    }
                }
            )
        )

        [exceeded] = self.alertable_events()['limit']

        assert exceeded['event'] == 'rate_limit-exceeded-1h'

    def test_route_budget_is_not_offered_when_the_project_has_a_budget(self):
        self.publish(route_config(limits=EVERY_LIMIT))
        self.project_budgets.projects.add(str(PROJECT_UUID))

        events = self.alertable_events()

        offered = [e['event'] for e in events['limit'] + events['threshold']]
        assert offered
        assert not [e for e in offered if e.startswith('budget_limit-')]

    def test_create_rule_on_a_limit_event_with_limit_window(self):
        self.publish(route_config(limits=rate_limit()))

        rule = self.created('rate_limit-exceeded-1m', timeAggregation='limit_window')

        assert rule['timeAggregation'] == 'limit_window'

    def test_create_rule_on_a_threshold_event_with_limit_window(self):
        self.publish(route_config(limits=rate_limit()))

        rule = self.created('rate_limit-75pct-1m', timeAggregation='limit_window')

        assert rule['event'] == 'rate_limit-75pct-1m'

    def test_a_limit_event_takes_only_the_limit_window_aggregation(self):
        self.publish(route_config(limits=rate_limit()))

        message = self.rejected(self.create('rate_limit-exceeded-1m'))

        assert 'limit_window' in message

    def test_limit_window_is_only_for_limit_and_threshold_events(self):
        self.publish(route_config(fallback=True))

        message = self.rejected(
            self.create('fallback-triggered', timeAggregation='limit_window')
        )

        assert 'limit_window' in message

    def test_update_keeps_a_limit_rule_on_limit_window(self):
        self.publish(route_config(limits=rate_limit()))
        rule = self.created('rate_limit-exceeded-1m', timeAggregation='limit_window')

        response = self.client.patch(
            f'/rule/{rule["uuid"]}', json={'timeAggregation': 'instant'}
        )

        assert 'limit_window' in self.rejected(response)

    def test_a_limit_rule_is_stale_when_the_limit_is_removed(self):
        self.publish(route_config(limits=rate_limit()))
        rule = self.created('rate_limit-exceeded-1m', timeAggregation='limit_window')

        self.publish(route_config())

        listed = self.listed(rule['uuid'])
        assert listed['stale'] is True
        assert 'rate limit' in listed['staleReason'].lower()

    def test_a_limit_rule_is_stale_when_the_window_changes(self):
        self.publish(route_config(limits=rate_limit('1 minute')))
        rule = self.created('rate_limit-exceeded-1m', timeAggregation='limit_window')

        self.publish(route_config(limits=rate_limit('1 hour')))

        listed = self.listed(rule['uuid'])
        assert listed['stale'] is True
        assert '1m' in listed['staleReason']

    def test_a_limit_rule_is_not_stale_when_the_maximum_changes(self):
        self.publish(route_config(limits=rate_limit(max_requests=10)))
        rule = self.created('rate_limit-75pct-1m', timeAggregation='limit_window')

        self.publish(route_config(limits=rate_limit(max_requests=99)))

        assert self.listed(rule['uuid'])['stale'] is False

    def test_a_route_budget_rule_is_stale_once_the_project_has_a_budget(self):
        self.publish(route_config(limits=EVERY_LIMIT))
        rule = self.created('budget_limit-exceeded-1mo', timeAggregation='limit_window')

        self.project_budgets.projects.add(str(PROJECT_UUID))

        listed = self.listed(rule['uuid'])
        assert listed['stale'] is True
        assert 'project' in listed['staleReason'].lower()

    def test_a_threshold_rule_is_stale_when_its_percentage_is_dropped(self):
        self.publish(route_config(limits=rate_limit()))
        rule = self.created('rate_limit-75pct-1m', timeAggregation='limit_window')

        with patch.object(
            get_app_config().alert_config, 'alert_threshold_percentages', [90]
        ):
            listed = self.listed(rule['uuid'])

        assert listed['stale'] is True
        assert '75%' in listed['staleReason']

    # --- create / update validation ---

    def test_create_rule_on_offered_event(self):
        self.publish(route_config(guardrails={'pii': 'input'}))

        response = self.create('guardrail-input-pii')

        assert response.status_code == 201
        body = response.json()
        assert body['event'] == 'guardrail-input-pii'
        assert body['stale'] is False
        assert body['staleReason'] is None
        assert 'disabledReason' not in body

    def test_create_rule_rejects_event_not_offered(self):
        self.publish(route_config(guardrails={'pii': 'input'}))

        assert self.create('guardrail-output-pii').status_code == 400

    def test_create_rule_rejects_cache_event(self):
        self.publish(route_config(caching=True))

        assert self.create('cache-exact').status_code == 400

    def test_update_rule_rejects_event_not_offered(self):
        self.publish(route_config(guardrails={'pii': 'input'}, fallback=True))
        rule = self.created('guardrail-input-pii')

        response = self.client.patch(
            f'/rule/{rule["uuid"]}', json={'event': 'guardrail-output-pii'}
        )

        assert response.status_code == 400

    def test_update_rule_to_offered_event(self):
        self.publish(route_config(guardrails={'pii': 'input'}, fallback=True))
        rule = self.created('guardrail-input-pii')

        response = self.client.patch(
            f'/rule/{rule["uuid"]}', json={'event': 'fallback-triggered'}
        )

        assert response.status_code == 200
        assert response.json()['event'] == 'fallback-triggered'

    # --- staleness ---

    def test_rule_is_stale_when_route_is_no_longer_published(self):
        self.publish(route_config(guardrails={'pii': 'input'}))
        rule = self.created('guardrail-input-pii')

        self.unpublish()

        listed = self.listed(rule['uuid'])
        assert listed['stale'] is True
        assert '"chat"' in listed['staleReason']
        assert listed['enabled'] is True

    def test_rule_is_stale_when_guardrail_is_renamed(self):
        self.publish(route_config(guardrails={'pii': 'input'}))
        rule = self.created('guardrail-input-pii')

        self.publish(route_config(guardrails={'pii_v2': 'input'}))

        listed = self.listed(rule['uuid'])
        assert listed['stale'] is True
        assert '"pii"' in listed['staleReason']

    def test_rule_is_stale_when_guardrail_phase_changes(self):
        self.publish(route_config(guardrails={'pii': 'input'}))
        rule = self.created('guardrail-input-pii')

        self.publish(route_config(guardrails={'pii': 'output'}))

        listed = self.listed(rule['uuid'])
        assert listed['stale'] is True
        assert 'input' in listed['staleReason']

    def test_rule_is_stale_when_fallback_is_removed(self):
        self.publish(route_config(fallback=True))
        rule = self.created('fallback-triggered')

        self.publish(route_config())

        listed = self.listed(rule['uuid'])
        assert listed['stale'] is True
        assert 'fallback' in listed['staleReason'].lower()

    def test_rule_is_not_stale_when_guardrail_parameters_change(self):
        self.publish(route_config(guardrails={'pii': 'io'}, pii_values=('secret',)))
        rule = self.created('guardrail-output-pii')

        self.publish(route_config(guardrails={'pii': 'io'}, pii_values=('password',)))

        listed = self.listed(rule['uuid'])
        assert listed['stale'] is False
        assert listed['staleReason'] is None

    def test_republishing_clears_the_warning(self):
        self.publish(route_config(fallback=True))
        rule = self.created('fallback-triggered')
        self.unpublish()
        assert self.listed(rule['uuid'])['stale'] is True

        self.publish(route_config(fallback=True))

        assert self.listed(rule['uuid'])['stale'] is False

    def test_existing_cache_rule_is_stale(self):
        self.publish(route_config(caching=True))
        rule = self.insert_rule('cache-exact')

        listed = self.listed(rule.uuid)
        assert listed['stale'] is True
        assert 'cache' in listed['staleReason'].lower()

    def test_get_rule_carries_staleness(self):
        self.publish(route_config(fallback=True))
        rule = self.created('fallback-triggered')
        assert self.fetched(rule['uuid'])['stale'] is False

        self.publish(route_config())

        fetched = self.fetched(rule['uuid'])
        assert fetched['stale'] is True
        assert fetched['staleReason']

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

    def test_create_rule_is_disabled_by_default(self):
        self.publish(route_config(fallback=True))

        response = self.client.post(
            '/rule',
            json={
                'name': 'rule',
                'project': str(PROJECT_UUID),
                'route': 'chat',
                'event': 'fallback-triggered',
                'recipients': ['ops@example.com'],
            },
        )

        assert response.status_code == 201
        assert response.json()['enabled'] is False

    # --- toggle / delete ---

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

    # --- scopes and aggregations ---

    def test_alertable_guardrail_and_fallback_events_let_the_user_pick_the_aggregation(
        self,
    ):
        self.publish(route_config(guardrails={'pii': 'input'}, fallback=True))

        events = self.alertable_events()

        items = events['guardrail'] + events['fallback']
        assert items
        assert {item['aggregation'] for item in items} == {'selectable'}

    def test_a_route_rule_carries_its_scope_and_no_credential_or_window(self):
        self.publish(route_config(fallback=True))

        rule = self.created('fallback-triggered')

        assert rule['scope'] == 'route'
        assert rule['project'] == str(PROJECT_UUID)
        assert rule['route'] == 'chat'
        assert rule['credentialUuid'] is None
        assert rule['credentialName'] is None
        assert rule['timeAggregation'] == 'instant'
        assert rule['windowSize'] is None

    def test_route_scope_requires_a_route(self):
        self.publish(route_config(fallback=True))

        message = self.rejected(self.create('fallback-triggered', route=None))

        assert 'route' in message.lower()

    def test_route_scope_requires_a_project(self):
        self.publish(route_config(fallback=True))

        message = self.rejected(self.create('fallback-triggered', project=None))

        assert 'project' in message.lower()

    def test_route_scope_takes_no_credential(self):
        self.publish(route_config(fallback=True))

        message = self.rejected(
            self.create('fallback-triggered', credential=str(uuid.uuid4()))
        )

        assert 'credential' in message.lower()

    def test_project_scope_requires_a_project(self):
        message = self.rejected(
            self.create(
                'budget_limit-exceeded-1mo', scope='project', project=None, route=None
            )
        )

        assert 'project' in message.lower()

    def test_project_scope_takes_no_route(self):
        message = self.rejected(
            self.create('budget_limit-exceeded-1mo', scope='project')
        )

        assert 'route' in message.lower()

    def test_credential_scope_requires_a_credential(self):
        message = self.rejected(
            self.create(
                'rate_limit-exceeded-1m', scope='credential', project=None, route=None
            )
        )

        assert 'credential' in message.lower()

    def test_credential_scope_takes_no_project_or_route(self):
        message = self.rejected(
            self.create(
                'rate_limit-exceeded-1m',
                scope='credential',
                credential=str(uuid.uuid4()),
            )
        )

        assert 'project' in message.lower()

    def test_window_aggregation_requires_a_window_size(self):
        self.publish(route_config(fallback=True))

        message = self.rejected(
            self.create('fallback-triggered', timeAggregation='window')
        )

        assert 'window size' in message.lower()

    def test_a_window_size_is_rejected_without_window_aggregation(self):
        self.publish(route_config(fallback=True))

        message = self.rejected(self.create('fallback-triggered', windowSize='5m'))

        assert 'window size' in message.lower()

    def test_an_unknown_window_size_is_invalid(self):
        self.publish(route_config(fallback=True))

        response = self.create(
            'fallback-triggered', timeAggregation='window', windowSize='10m'
        )

        assert response.status_code == 422

    def test_project_and_credential_scopes_are_not_supported_yet(self):
        project_rule = self.create(
            'budget_limit-exceeded-1mo', scope='project', route=None
        )
        credential_rule = self.create(
            'rate_limit-exceeded-1m',
            scope='credential',
            project=None,
            route=None,
            credential=str(uuid.uuid4()),
        )

        assert 'not supported' in self.rejected(project_rule)
        assert 'not supported' in self.rejected(credential_rule)

    def test_window_aggregation_is_not_supported_yet(self):
        self.publish(route_config(fallback=True))

        window = self.create(
            'fallback-triggered', timeAggregation='window', windowSize='15m'
        )

        assert 'not supported' in self.rejected(window)

    def test_update_validates_the_merged_rule(self):
        self.publish(route_config(fallback=True))
        rule = self.created('fallback-triggered')

        response = self.client.patch(
            f'/rule/{rule["uuid"]}',
            json={'scope': 'credential', 'credential': str(uuid.uuid4())},
        )

        assert 'project' in self.rejected(response).lower()

    def test_update_rejects_a_window_size_on_an_instant_rule(self):
        self.publish(route_config(fallback=True))
        rule = self.created('fallback-triggered')

        response = self.client.patch(f'/rule/{rule["uuid"]}', json={'windowSize': '1h'})

        assert 'window size' in self.rejected(response).lower()

    def test_a_rule_still_holding_a_project_name_is_stale(self):
        self.publish(route_config(fallback=True))
        rule = self.insert_rule('fallback-triggered', project=PROJECT_NAME)

        listed = self.listed(rule.uuid)

        assert listed['stale'] is True

    def test_a_credential_rule_shows_the_credential_and_no_project(self):
        credential = self.insert_credential('billing-service')
        rule = self.insert_rule(
            'rate_limit-exceeded-1m',
            scope='credential',
            project=None,
            route=None,
            credential_uuid=credential.uuid,
            time_aggregation='limit_window',
        )

        listed = self.listed(rule.uuid)

        assert listed['scope'] == 'credential'
        assert listed['credentialUuid'] == str(credential.uuid)
        assert listed['credentialName'] == 'billing-service'
        assert listed['project'] is None
        assert listed['projectName'] is None
        assert listed['route'] is None
        assert listed['timeAggregation'] == 'limit_window'

    def test_a_rule_still_holding_a_project_name_can_be_renamed(self):
        self.publish(route_config(fallback=True))
        rule = self.insert_rule('fallback-triggered', project=PROJECT_NAME)

        response = self.client.patch(f'/rule/{rule.uuid}', json={'name': 'renamed'})

        assert response.status_code == 200, response.text
        assert response.json()['name'] == 'renamed'

    def test_a_project_given_by_name_is_rejected_with_a_400(self):
        self.publish(route_config(fallback=True))

        assert (
            self.create('fallback-triggered', project=PROJECT_NAME).status_code == 400
        )
