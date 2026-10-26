"""Alert history through AlertRuleService: the range it asks for and the rule check.

The ClickHouse query itself is covered in tests/dao/alert_dao_history_test.py;
here a fake DAO records the range and rule it was asked for.
"""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from radicalbit_ai_gateway.db.models.alert import AlertHistoryBucket
from radicalbit_ai_gateway.services.alert_rule_service import AlertRuleService
from radicalbit_ai_gateway.utils.exceptions import AlertRuleNotFoundError

KNOWN_RULE = UUID('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
UNKNOWN_RULE = UUID('cccccccc-cccc-cccc-cccc-cccccccccccc')
NOW = datetime(2025, 1, 8, 10, 20, tzinfo=UTC)

BUCKET = AlertHistoryBucket(
    rule_uuid=KNOWN_RULE,
    rule_name='rule-a',
    bucket_start=datetime(2025, 1, 8, 9, tzinfo=UTC),
    sent=3,
    failed=1,
)


class FakeAlertDAO:
    def __init__(self):
        self.calls = []

    def get_history(self, _from, _to, rule_uuid=None):
        self.calls.append((_from, _to, rule_uuid))
        return [BUCKET]


class FakeAlertRuleDAO:
    def get_by_uuid(self, rule_uuid):
        return object() if rule_uuid == KNOWN_RULE else None


@pytest.fixture
def alert_dao():
    return FakeAlertDAO()


@pytest.fixture
def service(alert_dao):
    return AlertRuleService(
        alert_rule_dao=FakeAlertRuleDAO(), alert_dao=alert_dao, clock=lambda: NOW
    )


def test_history_defaults_to_the_last_48_whole_hours_including_the_current_one(
    service, alert_dao
):
    service.get_history()

    assert alert_dao.calls == [
        (
            datetime(2025, 1, 6, 11, tzinfo=UTC),
            datetime(2025, 1, 8, 11, tzinfo=UTC),
            None,
        )
    ]


def test_history_uses_the_range_it_is_given(service, alert_dao):
    _from = datetime(2025, 1, 1, tzinfo=UTC)
    _to = datetime(2025, 1, 2, tzinfo=UTC)

    service.get_history(_from=_from, _to=_to)

    assert alert_dao.calls == [(_from, _to, None)]


def test_history_returns_the_buckets_in_camel_case(service):
    [out] = service.get_history()

    assert out.model_dump(by_alias=True, mode='json') == {
        'ruleUuid': str(KNOWN_RULE),
        'ruleName': 'rule-a',
        'bucketStart': '2025-01-08T09:00:00Z',
        'sent': 3,
        'failed': 1,
    }


def test_rule_history_asks_only_for_that_rule(service, alert_dao):
    service.get_rule_history(KNOWN_RULE)

    assert [rule for _, _, rule in alert_dao.calls] == [KNOWN_RULE]


def test_rule_history_of_an_unknown_rule_is_not_found(service, alert_dao):
    with pytest.raises(AlertRuleNotFoundError):
        service.get_rule_history(UNKNOWN_RULE)

    assert alert_dao.calls == []


def test_history_is_empty_without_an_alert_store():
    service = AlertRuleService(alert_rule_dao=FakeAlertRuleDAO(), clock=lambda: NOW)

    assert service.get_history() == []
