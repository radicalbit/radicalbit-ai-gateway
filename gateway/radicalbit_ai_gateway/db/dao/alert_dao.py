from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func as F, select

from radicalbit_ai_gateway.db.clickhouse_database import ClickHouseDatabase
from radicalbit_ai_gateway.db.models.alert import AlertHistoryBucket
from radicalbit_ai_gateway.db.tables.alert_table import Alert
from radicalbit_ai_gateway.events.alerts_processor import AlertStatus


class AlertDAO:
    def __init__(self, database: ClickHouseDatabase):
        self.db = database
        self.T = Alert.__table__

    def get_history(
        self,
        _from: datetime,
        _to: datetime,
        rule_uuid: UUID | None = None,
    ) -> list[AlertHistoryBucket]:
        """Count the alerts of each rule per hour, sent and failed apart.

        Only hours with at least one alert are returned. The rule name is the
        latest one recorded, so a renamed rule shows under its current name.
        """
        T = self.T
        bucket_start = F.toStartOfHour(T.c['TIMESTAMP']).label('bucket_start')
        conditions = [T.c['TIMESTAMP'] >= _from, T.c['TIMESTAMP'] < _to]
        if rule_uuid is not None:
            conditions.append(T.c['RULE_UUID'] == rule_uuid)

        stmt = (
            select(
                T.c['RULE_UUID'],
                F.argMax(T.c['RULE_NAME'], T.c['TIMESTAMP']),
                bucket_start,
                F.countIf(T.c['STATUS'] == AlertStatus.SENT.value),
                F.countIf(T.c['STATUS'] == AlertStatus.FAILED.value),
            )
            .where(*conditions)
            .group_by(T.c['RULE_UUID'], bucket_start)
            .order_by(T.c['RULE_UUID'], bucket_start)
        )
        with self.db.begin_session() as session:
            rows = session.execute(stmt).all()

        return [
            AlertHistoryBucket(
                rule_uuid=rule,
                rule_name=name,
                bucket_start=start.replace(tzinfo=UTC),
                sent=sent,
                failed=failed,
            )
            for rule, name, start, sent, failed in rows
        ]
