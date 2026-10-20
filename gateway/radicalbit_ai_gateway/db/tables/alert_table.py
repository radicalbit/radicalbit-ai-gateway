import uuid

from clickhouse_sqlalchemy.engines import MergeTree
from clickhouse_sqlalchemy.types import (
    UUID,
    DateTime64,
    LowCardinality,
    Nullable,
    UInt64,
)
from sqlalchemy import Column, Date, String, func

from radicalbit_ai_gateway.db.clickhouse_database import ClickHouseBaseTable


class Alert(ClickHouseBaseTable):
    """One row per alert send attempt, written by the metrics-worker."""

    __tablename__ = 'alert'
    alert_uuid = Column('ALERT_UUID', UUID, primary_key=True, default=uuid.uuid4)
    timestamp = Column('TIMESTAMP', DateTime64(9, timezone='UTC'), primary_key=True)
    date = Column('DATE', Date)
    rule_uuid = Column('RULE_UUID', UUID)
    rule_name = Column('RULE_NAME', String)
    scope = Column('SCOPE', LowCardinality(Nullable(String)))
    project_uuid = Column('PROJECT_UUID', Nullable(UUID))
    route_name = Column('ROUTE_NAME', LowCardinality(Nullable(String)))
    credential_uuid = Column('CREDENTIAL_UUID', Nullable(UUID))
    event = Column('EVENT', LowCardinality(String))
    aggregation = Column('AGGREGATION', LowCardinality(String))
    count = Column('COUNT', UInt64, default=1)
    window_start = Column('WINDOW_START', Nullable(DateTime64(9, timezone='UTC')))
    window_end = Column('WINDOW_END', Nullable(DateTime64(9, timezone='UTC')))
    status = Column('STATUS', LowCardinality(String))

    __table_args__ = (
        MergeTree(
            partition_by=func.toDate(
                Column('TIMESTAMP', DateTime64(9, timezone='UTC'))
            ),
            order_by=('RULE_UUID', 'TIMESTAMP'),
            index_granularity=8192,
        ),
    )
