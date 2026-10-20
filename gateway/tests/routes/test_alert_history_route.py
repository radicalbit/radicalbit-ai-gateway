"""GET /rule/history and GET /rule/{uuid}/history over HTTP.

The service runs for real on fake DAOs: the tests check the query parameters,
the response shape and the status codes a caller sees.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from radicalbit_ai_gateway.db.models.alert import AlertHistoryBucket
from radicalbit_ai_gateway.routes.alert_rule_route import AlertRuleRoute
from radicalbit_ai_gateway.services.alert_rule_service import AlertRuleService
from radicalbit_ai_gateway.utils.exceptions import (
    AlertRuleNotFoundError,
    alert_rule_exception_handler,
)

KNOWN_RULE = UUID('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
UNKNOWN_RULE = UUID('cccccccc-cccc-cccc-cccc-cccccccccccc')
NOW = datetime(2025, 1, 8, 10, 20, tzinfo=UTC)


class FakeAlertDAO:
    def __init__(self):
        self.calls = []

    def get_history(self, _from, _to, rule_uuid=None):
        self.calls.append((_from, _to, rule_uuid))
        return [
            AlertHistoryBucket(
                rule_uuid=KNOWN_RULE,
                rule_name='rule-a',
                bucket_start=datetime(2025, 1, 8, 9, tzinfo=UTC),
                sent=3,
                failed=1,
            )
        ]


class FakeAlertRuleDAO:
    def get_by_uuid(self, rule_uuid):
        return object() if rule_uuid == KNOWN_RULE else None


@pytest.fixture
def alert_dao():
    return FakeAlertDAO()


@pytest.fixture
def client(alert_dao):
    service = AlertRuleService(
        alert_rule_dao=FakeAlertRuleDAO(), alert_dao=alert_dao, clock=lambda: NOW
    )
    app = FastAPI()
    app.add_exception_handler(AlertRuleNotFoundError, alert_rule_exception_handler)
    app.include_router(AlertRuleRoute.get_alert_rule_router(service))
    return TestClient(app)


def test_history_returns_camel_case_buckets(client):
    response = client.get('/rule/history')

    assert response.status_code == 200
    assert response.json() == [
        {
            'ruleUuid': str(KNOWN_RULE),
            'ruleName': 'rule-a',
            'bucketStart': '2025-01-08T09:00:00Z',
            'sent': 3,
            'failed': 1,
        }
    ]


def test_history_without_a_range_covers_the_last_48_hours(client, alert_dao):
    client.get('/rule/history')

    assert alert_dao.calls == [
        (
            datetime(2025, 1, 6, 11, tzinfo=UTC),
            datetime(2025, 1, 8, 11, tzinfo=UTC),
            None,
        )
    ]


def test_history_takes_the_range_as_epoch_seconds(client, alert_dao):
    _from = datetime(2025, 1, 1, tzinfo=UTC)
    _to = datetime(2025, 1, 2, tzinfo=UTC)

    client.get(
        '/rule/history',
        params={'_from': int(_from.timestamp()), '_to': int(_to.timestamp())},
    )

    assert alert_dao.calls == [(_from, _to, None)]


def test_rule_history_asks_only_for_that_rule(client, alert_dao):
    response = client.get(f'/rule/{KNOWN_RULE}/history')

    assert response.status_code == 200
    assert [rule for _, _, rule in alert_dao.calls] == [KNOWN_RULE]


def test_rule_history_of_an_unknown_rule_is_404(client):
    response = client.get(f'/rule/{UNKNOWN_RULE}/history')

    assert response.status_code == 404
