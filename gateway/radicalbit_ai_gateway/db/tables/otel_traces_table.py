from clickhouse_connect.cc_sqlalchemy.engines import MergeTree
from clickhouse_connect.cc_sqlalchemy.types import (
    Array,
    DateTime64,
    LowCardinality,
    Map,
    String,
    UInt64,
)
from sqlalchemy import Column, func

from radicalbit_ai_gateway.db.clickhouse_database import ClickHouseBaseTable


class OtelTraces(ClickHouseBaseTable):
    __tablename__ = 'otel_traces'
    timestamp = Column('Timestamp', DateTime64(9, timezone='UTC'), primary_key=True)
    trace_id = Column('TraceId', String, primary_key=True)
    span_id = Column('SpanId', String, primary_key=True)
    parent_span_id = Column('ParentSpanId', String)
    trace_state = Column('TraceState', String)
    span_name = Column('SpanName', LowCardinality(String))
    span_kind = Column('SpanKind', LowCardinality(String))
    service_name = Column('ServiceName', LowCardinality(String))
    resource_attributes = Column(
        'ResourceAttributes', Map(LowCardinality(String), String)
    )
    scope_name = Column('ScopeName', String)
    scope_version = Column('ScopeVersion', String)
    span_attributes = Column('SpanAttributes', Map(LowCardinality(String), String))
    duration = Column('Duration', UInt64)
    status_code = Column('StatusCode', LowCardinality(String))
    status_message = Column('StatusMessage', String)
    # Events stored as parallel arrays (ClickHouse columnar format)
    # These match the production schema: Events.Timestamp, Events.Name, Events.Attributes
    events_timestamp = Column('Events.Timestamp', Array(DateTime64(9)))
    events_name = Column('Events.Name', Array(LowCardinality(String)))
    events_attributes = Column(
        'Events.Attributes', Array(Map(LowCardinality(String), String))
    )
    # Links stored as parallel arrays (ClickHouse columnar format)
    links_trace_id = Column('Links.TraceId', Array(String))
    links_span_id = Column('Links.SpanId', Array(String))
    links_trace_state = Column('Links.TraceState', Array(String))
    links_attributes = Column(
        'Links.Attributes', Array(Map(LowCardinality(String), String))
    )
    __table_args__ = (
        MergeTree(
            partition_by=func.toDate(
                Column('Timestamp', DateTime64(9, timezone='UTC'))
            ),
            order_by=(
                'ServiceName',
                'SpanName',
                func.toDateTime(Column('Timestamp', DateTime64(9, timezone='UTC'))),
            ),
            settings={'index_granularity': 8192},
        ),
    )
