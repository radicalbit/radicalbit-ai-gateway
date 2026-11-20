import uuid

from clickhouse_connect.cc_sqlalchemy.engines import MergeTree
from clickhouse_connect.cc_sqlalchemy.types import (
    UUID,
    Array,
    DateTime64,
    Float64,
    Int32,
    LowCardinality,
    Nullable,
    String,
)
from sqlalchemy import Boolean, Column, Date, func

from radicalbit_ai_gateway.db.clickhouse_database import ClickHouseBaseTable


class RequestEvent(ClickHouseBaseTable):
    __tablename__ = 'request_event'
    request_uuid = Column('REQUEST_UUID', UUID, primary_key=True, default=uuid.uuid4)
    timestamp = Column('TIMESTAMP', DateTime64(9, timezone='UTC'), primary_key=True)
    date = Column('DATE', Date)
    route_name = Column('ROUTE_NAME', LowCardinality(String), primary_key=True)
    project_uuid = Column('PROJECT_UUID', Nullable(UUID))
    project_name = Column('PROJECT_NAME', LowCardinality(String), default='')
    api_key_uuid = Column('API_KEY_UUID', Nullable(UUID))
    api_key_name = Column('API_KEY_NAME', LowCardinality(String))
    group_uuid = Column('GROUP_UUID', Nullable(UUID))
    group_name = Column('GROUP_NAME', LowCardinality(String))
    request_type = Column('REQUEST_TYPE', LowCardinality(String))
    request_status = Column('REQUEST_STATUS', LowCardinality(String))
    http_status_code = Column('HTTP_STATUS_CODE', Int32, default=0)
    duration_ms = Column('DURATION_MS', Float64, default=0.0)
    error_type = Column('ERROR_TYPE', LowCardinality(String))
    error_code = Column('ERROR_CODE', LowCardinality(String))
    is_streaming = Column('IS_STREAMING', Boolean, default=False)
    tags = Column('TAGS', Array(String), default=[])
    __table_args__ = (
        MergeTree(
            partition_by=func.toDate(
                Column('TIMESTAMP', DateTime64(9, timezone='UTC'))
            ),
            order_by=('ROUTE_NAME', 'TIMESTAMP', 'REQUEST_UUID'),
            settings={'index_granularity': 8192},
        ),
    )
