"""GET /rule/history and GET /rule/{uuid}/history over HTTP.

The service runs for real on fake DAOs: the tests check the query parameters,
the response shape and the status codes a caller sees.
"""

from datetime import UTC, datetime
from unittest.mock import create_autospec
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from typing_extensions import override

from radicalbit_ai_gateway.db.dao.alert_dao import AlertDAO
from radicalbit_ai_gateway.db.dao.alert_rule_dao import AlertRuleDAO
from radicalbit_ai_gateway.db.models.alert import AlertHistoryBucket
from radicalbit_ai_gateway.middleware.exception_handlers import add_exception_handler
from radicalbit_ai_gateway.routes.alert_rule_route import AlertRuleRoute
from radicalbit_ai_gateway.services.alert_rule_service import AlertRuleService
from radicalbit_ai_gateway.utils.exceptions import (
    AlertRuleNotFoundError,
    alert_rule_exception_handler,
)

KNOWN_RULE = UUID('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
UNKNOWN_RULE = UUID('cccccccc-cccc-cccc-cccc-cccccccccccc')
NOW = datetime(2025, 1, 8, 10, 20, tzinfo=UTC)


class FakeAlertDAO(AlertDAO):
    """Records each history query and answers with one bucket."""

    def __init__(self):  # no database: only get_history is called
        self.calls = []

    @override
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


def alert_rule_dao() -> AlertRuleDAO:
    """Build an alert rule DAO that knows only ``KNOWN_RULE``."""
    dao = create_autospec(AlertRuleDAO, instance=True, spec_set=True)
    dao.get_by_uuid.side_effect = lambda rule_uuid: (
        object() if rule_uuid == KNOWN_RULE else None
    )
    assert isinstance(dao, AlertRuleDAO)
    return dao


@pytest.fixture
def alert_dao() -> FakeAlertDAO:
    return FakeAlertDAO()


@pytest.fixture
def client(alert_dao):
    service = AlertRuleService(
        alert_rule_dao=alert_rule_dao(), alert_dao=alert_dao, clock=lambda: NOW
    )
    app = FastAPI()
    add_exception_handler(app, AlertRuleNotFoundError, alert_rule_exception_handler)
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
