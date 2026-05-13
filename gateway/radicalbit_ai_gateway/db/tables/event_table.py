import uuid

from clickhouse_sqlalchemy.engines import MergeTree
from clickhouse_sqlalchemy.types import (
    UUID,
    DateTime64,
    Decimal,
    Float,
    LowCardinality,
    Map,
    Nullable,
)
from sqlalchemy import Boolean, Column, Date, String, func

from radicalbit_ai_gateway.db.clickhouse_database import ClickHouseBaseTable


class Event(ClickHouseBaseTable):
    __tablename__ = 'event'
    request_uuid = Column('REQUEST_UUID', UUID, primary_key=True, default=uuid.uuid4)
    timestamp = Column('TIMESTAMP', DateTime64(9, timezone='UTC'), primary_key=True)
    date = Column('DATE', Date)
    event_type = Column('EVENT_TYPE', LowCardinality(String), primary_key=True)
    route_name = Column('ROUTE_NAME', LowCardinality(String))
    project_uuid = Column('PROJECT_UUID', Nullable(UUID))
    project_name = Column('PROJECT_NAME', LowCardinality(String), default='')
    api_key_uuid = Column('API_KEY_UUID', UUID, primary_key=True, default=uuid.uuid4)
    api_key_name = Column('API_KEY_NAME', LowCardinality(String))
    group_uuid = Column('GROUP_UUID', UUID, primary_key=True, default=uuid.uuid4)
    group_name = Column('GROUP_NAME', LowCardinality(String))
    attributes = Column('ATTRIBUTES', Map(LowCardinality(String), String))
    model_id = Column('MODEL_ID', LowCardinality(String), default='')
    model_type = Column('MODEL_TYPE', LowCardinality(String), default='')
    is_cached_tokens = Column('IS_CACHED_TOKENS', Boolean, default=False)
    cache_type = Column('CACHE_TYPE', LowCardinality(String), default='')
    target = Column('TARGET', LowCardinality(String), default='')
    fallback = Column('FALLBACK', LowCardinality(String), default='')
    guardrail_name = Column('GUARDRAIL_NAME', LowCardinality(String), default='')
    guardrail_type = Column('GUARDRAIL_TYPE', LowCardinality(String), default='')
    guardrail_where = Column('GUARDRAIL_WHERE', LowCardinality(String), default='')
    guardrail_params = Column('GUARDRAIL_PARAMS', String, default='')
    guardrail_behavior = Column(
        'GUARDRAIL_BEHAVIOR', LowCardinality(String), default=''
    )
    is_judge = Column('IS_JUDGE', Boolean, default=False)
    routing_name = Column('ROUTING_NAME', LowCardinality(String), default='')
    routing_selected_model_id = Column(
        'ROUTING_SELECTED_MODEL_ID', LowCardinality(String), default=''
    )
    value = Column('VALUE', Float, default=1.0)
    cost = Column('COST', Decimal(64, 9), default=0.0)
    __table_args__ = (
        MergeTree(
            partition_by=func.toDate(
                Column('TIMESTAMP', DateTime64(9, timezone='UTC'))
            ),
            order_by=(
                'ROUTE_NAME',
                'EVENT_TYPE',
                'TIMESTAMP',
                'API_KEY_UUID',
                'GROUP_UUID',
            ),
            index_granularity=8192,
        ),
    )
