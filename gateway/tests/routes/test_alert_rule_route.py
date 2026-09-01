from unittest.mock import MagicMock
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from radicalbit_ai_gateway.routes.alert_rule_route import AlertRuleRoute
from radicalbit_ai_gateway.services.alert_rule_service import AlertRuleService


@pytest.fixture
def mock_alert_rule_service():
    return MagicMock(spec=AlertRuleService)


@pytest.fixture
def client(mock_alert_rule_service):
    app = FastAPI()
    router = AlertRuleRoute.get_alert_rule_router(mock_alert_rule_service)
    app.include_router(router)
    return TestClient(app)


def test_get_all_rules(client, mock_alert_rule_service):
    mock_alert_rule_service.get_all_rules.return_value = [
        {
            'uuid': str(uuid4()),
            'name': 'Test Rule',
            'description': 'Test Description',
            'project': 'p1',
            'route': 'r1',
            'scope': 'route',
            'event': 'guardrail-input-pii',
            'timeAggregation': 'instant',
            'channel': 'email',
            'recipients': ['test@example.com'],
            'enabled': True,
            'disabledReason': None,
            'createdAt': '2026-08-07T12:00:00Z',
            'updatedAt': '2026-08-07T12:00:00Z',
        }
    ]

    response = client.get('/rule')
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]['name'] == 'Test Rule'


def test_create_rule(client, mock_alert_rule_service):
    rule_id = str(uuid4())
    mock_alert_rule_service.create_rule.return_value = {
        'uuid': rule_id,
        'name': 'New Rule',
        'description': None,
        'project': 'p1',
        'route': 'r1',
        'scope': 'route',
        'event': 'guardrail-input-pii',
        'timeAggregation': 'instant',
        'channel': 'email',
        'recipients': ['dev@example.com'],
        'enabled': True,
        'disabledReason': None,
        'createdAt': '2026-08-07T12:00:00Z',
        'updatedAt': '2026-08-07T12:00:00Z',
    }

    payload = {
        'name': 'New Rule',
        'project': 'p1',
        'route': 'r1',
        'event': 'guardrail-input-pii',
        'recipients': ['dev@example.com'],
        'enabled': True,
    }
    response = client.post('/rule', json=payload)
    assert response.status_code == 201
    assert response.json()['uuid'] == rule_id


def test_get_rule_by_uuid(client, mock_alert_rule_service):
    rule_id = str(uuid4())
    mock_alert_rule_service.get_rule_by_uuid.return_value = {
        'uuid': rule_id,
        'name': 'Fetched Rule',
        'description': None,
        'project': 'p1',
        'route': 'r1',
        'scope': 'route',
        'event': 'guardrail-input-pii',
        'timeAggregation': 'instant',
        'channel': 'email',
        'recipients': ['dev@example.com'],
        'enabled': True,
        'disabledReason': None,
        'createdAt': '2026-08-07T12:00:00Z',
        'updatedAt': '2026-08-07T12:00:00Z',
    }

    response = client.get(f'/rule/{rule_id}')
    assert response.status_code == 200
    assert response.json()['uuid'] == rule_id


def test_update_rule(client, mock_alert_rule_service):
    rule_id = str(uuid4())
    mock_alert_rule_service.update_rule.return_value = {
        'uuid': rule_id,
        'name': 'Updated Rule',
        'description': 'Updated Desc',
        'project': 'p1',
        'route': 'r1',
        'scope': 'route',
        'event': 'guardrail-input-pii',
        'timeAggregation': 'instant',
        'channel': 'email',
        'recipients': ['dev2@example.com'],
        'enabled': True,
        'disabledReason': None,
        'createdAt': '2026-08-07T12:00:00Z',
        'updatedAt': '2026-08-07T12:00:00Z',
    }

    response = client.patch(
        f'/rule/{rule_id}', json={'name': 'Updated Rule', 'description': 'Updated Desc'}
    )
    assert response.status_code == 200
    assert response.json()['name'] == 'Updated Rule'


def test_toggle_rule_enabled(client, mock_alert_rule_service):
    rule_id = str(uuid4())
    mock_alert_rule_service.toggle_rule_enabled.return_value = {
        'uuid': rule_id,
        'name': 'Toggle Rule',
        'description': None,
        'project': 'p1',
        'route': 'r1',
        'scope': 'route',
        'event': 'guardrail-input-pii',
        'timeAggregation': 'instant',
        'channel': 'email',
        'recipients': ['dev@example.com'],
        'enabled': False,
        'disabledReason': None,
        'createdAt': '2026-08-07T12:00:00Z',
        'updatedAt': '2026-08-07T12:00:00Z',
    }

    response = client.patch(f'/rule/{rule_id}/enabled', json={'enabled': False})
    assert response.status_code == 200
    assert response.json()['enabled'] is False


def test_delete_rule(client, mock_alert_rule_service):
    rule_id = str(uuid4())
    mock_alert_rule_service.delete_rule.return_value = {
        'uuid': rule_id,
        'name': 'Deleted Rule',
        'description': None,
        'project': 'p1',
        'route': 'r1',
        'scope': 'route',
        'event': 'guardrail-input-pii',
        'timeAggregation': 'instant',
        'channel': 'email',
        'recipients': [],
        'enabled': False,
        'disabledReason': None,
        'createdAt': '2026-08-07T12:00:00Z',
        'updatedAt': '2026-08-07T12:00:00Z',
    }

    response = client.delete(f'/rule/{rule_id}')
    assert response.status_code == 200
    assert response.json()['uuid'] == rule_id


def test_get_alertable_events(client, mock_alert_rule_service):
    project_uuid = uuid4()
    mock_alert_rule_service.get_alertable_events_for_route.return_value = {
        'guardrail': [
            {'event': 'guardrail-input-pii', 'label': 'Guardrail: PII (input)'}
        ],
        'caching': [{'event': 'cache-exact', 'label': 'Caching: exact match'}],
        'fallback': [{'event': 'fallback-triggered', 'label': 'Fallback: triggered'}],
    }

    response = client.get(
        f'/projects/{project_uuid}/routes/openai-prod/alertable-events'
    )
    assert response.status_code == 200
    data = response.json()
    assert 'guardrail' in data
    assert data['guardrail'][0]['event'] == 'guardrail-input-pii'
    mock_alert_rule_service.get_alertable_events_for_route.assert_called_once_with(
        project_uuid=project_uuid, route_name='openai-prod'
    )
