import datetime
import json
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
import yaml

from tests.common.db_integration import DatabaseIntegration

from radicalbit_ai_gateway.db.dao.alert_rule_dao import AlertRuleDAO
from radicalbit_ai_gateway.db.tables.alert_rule_table import AlertRule
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.project_entry import ProjectEntry
from radicalbit_ai_gateway.routes.alert_rule_route import AlertRuleRoute
from radicalbit_ai_gateway.services.alert_rule_service import AlertRuleService
from radicalbit_ai_gateway.utils.exceptions import (
    AlertRuleInternalError,
    AlertRuleInvalidEventError,
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
"""


def route_config(
    guardrails: dict[str, str] | None = None,
    fallback: bool = False,
    caching: bool = False,
    pii_values: tuple[str, ...] = ('secret',),
) -> GatewayConfig:
    """Build a published configuration with one route, `chat`.

    `guardrails` maps each guardrail attached to the route to its phase.
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
    raw['routes'] = {'chat': route}
    return GatewayConfig.model_validate(raw)


class TestAlertRuleRoute(DatabaseIntegration):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project_configs: dict[str, ProjectEntry] = {}
        service = AlertRuleService(
            alert_rule_dao=AlertRuleDAO(cls.db),
            project_configs=cls.project_configs,
        )
        app = FastAPI()
        for err in (
            AlertRuleNotFoundError,
            AlertRuleInvalidEventError,
            AlertRuleUnsupportedTimeAggregationError,
            AlertRuleInternalError,
        ):
            app.add_exception_handler(err, alert_rule_exception_handler)
        app.include_router(AlertRuleRoute.get_alert_rule_router(service))
        cls.client = TestClient(app)

    def setUp(self):
        self.project_configs.clear()

    def publish(self, config: GatewayConfig) -> None:
        self.project_configs[PROJECT_NAME] = ProjectEntry(
            uuid=PROJECT_UUID, config=config
        )

    def unpublish(self) -> None:
        self.project_configs.pop(PROJECT_NAME, None)

    def create(self, event: str, route: str = 'chat'):
        payload = {
            'name': 'rule',
            'project': str(PROJECT_UUID),
            'route': route,
            'event': event,
            'recipients': ['ops@example.com'],
            'enabled': True,
        }
        return self.client.post('/rule', json=payload)

    def created(self, event: str) -> dict:
        response = self.create(event)
        assert response.status_code == 201, response.text
        return response.json()

    def insert_rule(self, event: str, route: str = 'chat') -> AlertRule:
        """Store a rule bypassing validation, as an older release could have."""
        now = datetime.datetime.now(tz=datetime.UTC)
        return self.insert(
            AlertRule(
                name='legacy',
                project=str(PROJECT_UUID),
                route=route,
                scope='route',
                event=event,
                time_aggregation='instant',
                channel='email',
                recipients=json.dumps(['ops@example.com']),
                enabled=True,
                deleted=False,
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

        assert self.alertable_events() == {'guardrail': [], 'fallback': []}

    def test_alertable_events_empty_for_unpublished_route(self):
        self.publish(route_config(fallback=True))

        assert self.alertable_events(route='missing') == {
            'guardrail': [],
            'fallback': [],
        }

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

    # --- list order ---

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

    # --- defaults ---

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
