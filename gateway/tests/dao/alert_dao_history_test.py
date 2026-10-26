"""Hourly alert history per rule over the `alert` table, against a real ClickHouse.

Every case asserts on the buckets the alert history view would show: which
rule, which hour, how many alerts were sent and how many failed.
"""

import datetime
import uuid

from tests.common.db_integration_ch import DatabaseIntegrationClickhouse

from radicalbit_ai_gateway.db.dao.alert_dao import AlertDAO
from radicalbit_ai_gateway.db.models.alert import AlertHistoryBucket
from radicalbit_ai_gateway.db.tables.alert_table import Alert

RULE_A = uuid.UUID('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
RULE_B = uuid.UUID('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb')

UTC = datetime.timezone.utc
TEN = datetime.datetime(2025, 1, 8, 10, 0, 0, tzinfo=UTC)
ELEVEN = TEN + datetime.timedelta(hours=1)
DAY_START = datetime.datetime(2025, 1, 8, 0, 0, 0, tzinfo=UTC)
DAY_END = datetime.datetime(2025, 1, 9, 0, 0, 0, tzinfo=UTC)


def alert(
    rule_uuid: uuid.UUID = RULE_A,
    rule_name: str = 'rule-a',
    timestamp: datetime.datetime = TEN,
    status: str = 'sent',
    count: int = 1,
) -> Alert:
    return Alert(
        alert_uuid=uuid.uuid4(),
        timestamp=timestamp,
        date=timestamp.date(),
        rule_uuid=rule_uuid,
        rule_name=rule_name,
        scope='route',
        project_uuid=None,
        route_name='chat',
        credential_uuid=None,
        event='fallback',
        aggregation='instant',
        count=count,
        window_start=None,
        window_end=None,
        status=status,
    )


def bucket(
    start: datetime.datetime,
    sent: int = 0,
    failed: int = 0,
    rule_uuid: uuid.UUID = RULE_A,
    rule_name: str = 'rule-a',
) -> AlertHistoryBucket:
    return AlertHistoryBucket(
        rule_uuid=rule_uuid,
        rule_name=rule_name,
        bucket_start=start,
        sent=sent,
        failed=failed,
    )


class AlertDAOHistoryTest(DatabaseIntegrationClickhouse):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.alert_dao = AlertDAO(cls.db)

    def history(self, **kwargs) -> list[AlertHistoryBucket]:
        kwargs.setdefault('_from', DAY_START)
        kwargs.setdefault('_to', DAY_END)
        return self.alert_dao.get_history(**kwargs)

    def test_alerts_in_the_same_hour_share_a_bucket_split_by_outcome(self):
        self.insert(
            [
                alert(timestamp=TEN + datetime.timedelta(minutes=5)),
                alert(timestamp=TEN + datetime.timedelta(minutes=40)),
                alert(timestamp=TEN + datetime.timedelta(minutes=59), status='failed'),
            ]
        )

        assert self.history() == [bucket(TEN, sent=2, failed=1)]

    def test_each_rule_and_hour_gets_its_own_bucket(self):
        self.insert(
            [
                alert(timestamp=TEN),
                alert(timestamp=ELEVEN, status='failed'),
                alert(rule_uuid=RULE_B, rule_name='rule-b', timestamp=TEN),
            ]
        )

        assert self.history() == [
            bucket(TEN, sent=1),
            bucket(ELEVEN, failed=1),
            bucket(TEN, sent=1, rule_uuid=RULE_B, rule_name='rule-b'),
        ]

    def test_a_window_alert_counts_once_whatever_events_it_covers(self):
        self.insert([alert(count=7)])

        assert self.history() == [bucket(TEN, sent=1)]

    def test_the_range_includes_its_start_and_excludes_its_end(self):
        self.insert(
            [
                alert(timestamp=TEN - datetime.timedelta(microseconds=1)),
                alert(timestamp=TEN),
                alert(timestamp=ELEVEN),
            ]
        )

        assert self.history(_from=TEN, _to=ELEVEN) == [bucket(TEN, sent=1)]

    def test_the_rule_filter_keeps_only_that_rule(self):
        self.insert(
            [
                alert(timestamp=TEN),
                alert(rule_uuid=RULE_B, rule_name='rule-b', timestamp=TEN),
            ]
        )

        assert self.history(rule_uuid=RULE_B) == [
            bucket(TEN, sent=1, rule_uuid=RULE_B, rule_name='rule-b'),
        ]

    def test_a_renamed_rule_shows_under_its_latest_name(self):
        self.insert(
            [
                alert(timestamp=TEN, rule_name='old name'),
                alert(
                    timestamp=TEN + datetime.timedelta(minutes=30), rule_name='new name'
                ),
            ]
        )

        assert self.history() == [bucket(TEN, sent=2, rule_name='new name')]

    def test_no_alerts_means_no_buckets(self):
        assert self.history() == []
