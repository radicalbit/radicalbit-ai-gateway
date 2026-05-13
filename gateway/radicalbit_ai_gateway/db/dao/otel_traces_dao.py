from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi_pagination import Page, Params
from fastapi_pagination.ext.sqlalchemy import paginate
from sqlalchemy import Row, func as F, literal_column, select, text

from radicalbit_ai_gateway.db.clickhouse_database import ClickHouseDatabase
from radicalbit_ai_gateway.db.models.trace import (
    CategoryLatencies,
    CategorySpanLatencies,
    SpanLatencies,
    SpanRecord,
    SpanStats,
    TraceLatencies,
    TracesChartDataPoint,
)
from radicalbit_ai_gateway.db.tables.otel_traces_table import OtelTraces
from radicalbit_ai_gateway.utils.chart_utils import (
    get_bucket_function,
    with_timezone_offset,
)

# SpanAttributes key constants
_ROUTE_NAME_ATTR = "SpanAttributes['traceloop.association.properties.route_name']"
_API_KEY_UUID_ATTR = "SpanAttributes['traceloop.association.properties.api_key_uuid']"
_API_KEY_NAME_ATTR = "SpanAttributes['traceloop.association.properties.api_key_name']"
_GROUP_UUID_ATTR = "SpanAttributes['traceloop.association.properties.group_uuid']"
_GROUP_NAME_ATTR = "SpanAttributes['traceloop.association.properties.group_name']"
_REQUEST_UUID_ATTR = "SpanAttributes['traceloop.association.properties.request_uuid']"
_PROJECT_UUID_ATTR = "SpanAttributes['traceloop.association.properties.project_uuid']"
_OUTPUT_TOKENS_ATTR = "SpanAttributes['gen_ai.usage.output_tokens']"
_INPUT_TOKENS_ATTR = "SpanAttributes['gen_ai.usage.input_tokens']"
_TOTAL_TOKENS_ATTR = "SpanAttributes['llm.usage.total_tokens']"
_OPERATION_CATEGORY_ATTR = (
    "SpanAttributes['traceloop.association.properties.rb.gateway.operation_category']"
)

_FIELD_NAMES = ['span_name', 'p50', 'p90', 'p95', 'p99']
_SPAN_FIELD_NAMES = [
    'timestamp',
    'trace_id',
    'request_uuid',
    'span_id',
    'span_name',
    'service_name',
    'duration',
    'status_code',
    'parent_span_id',
    'route_name',
    'api_key_uuid',
    'api_key_name',
    'group_uuid',
    'group_name',
    'output_tokens',
    'input_tokens',
    'total_tokens',
]
_SPAN_DETAIL_FIELD_NAMES = [
    'timestamp',
    'trace_id',
    'request_uuid',
    'span_id',
    'span_name',
    'service_name',
    'duration',
    'status_code',
    'parent_span_id',
    'route_name',
    'api_key_uuid',
    'api_key_name',
    'group_uuid',
    'group_name',
    'output_tokens',
    'input_tokens',
    'total_tokens',
    'span_attributes',
    'status_message',
    'events_timestamp',
    'events_name',
    'events_attributes',
]


def _quantile_columns() -> list:
    dur = literal_column('Duration / 1000000')
    return [
        F.quantile(p, dur).label(label)
        for p, label in [(0.50, 'p50'), (0.90, 'p90'), (0.95, 'p95'), (0.99, 'p99')]
    ]


def _convert_events_to_dicts(
    timestamps: list | None, names: list | None, attributes: list | None
) -> list[dict]:
    """Convert ClickHouse parallel event arrays to dictionaries.

    ClickHouse stores events as parallel arrays (columnar format):
    - Events.Timestamp: Array(DateTime64(9))
    - Events.Name: Array(String)
    - Events.Attributes: Array(Map(String, String))

    This zips them into dicts with lowercase keys matching SpanRecord model.
    """
    if not timestamps:
        return []
    return [
        {'timestamp': ts, 'name': n, 'attributes': a}
        for ts, n, a in zip(timestamps, names or [], attributes or [])
    ]


class OtelTracesDAO:
    def __init__(self, database: ClickHouseDatabase):
        self.db = database
        self.T = OtelTraces.__table__

    def get_span_latencies(
        self,
        project_uuid: UUID,
        route_names: list[str] | None,
        _from: datetime | None,
        _to: datetime | None,
    ) -> list[SpanLatencies]:
        T = self.T
        conditions = [literal_column(_PROJECT_UUID_ATTR) == str(project_uuid)]

        if _from is not None:
            conditions.append(T.c['Timestamp'] >= _from)
        if _to is not None:
            conditions.append(T.c['Timestamp'] <= _to)
        if route_names:
            conditions.append(literal_column(_ROUTE_NAME_ATTR).in_(route_names))

        stmt = (
            select(
                T.c['SpanName'].label('span_name'),
                F.quantile(0.50, literal_column('Duration / 1000000')).label('p50'),
                F.quantile(0.90, literal_column('Duration / 1000000')).label('p90'),
                F.quantile(0.95, literal_column('Duration / 1000000')).label('p95'),
                F.quantile(0.99, literal_column('Duration / 1000000')).label('p99'),
            )
            .select_from(OtelTraces)
            .where(*conditions)
            .group_by(text('SpanName'))
            .order_by(text('SpanName'))
        )

        with self.db.begin_session() as session:
            res = session.execute(stmt).all()
            return [
                SpanLatencies.model_validate(dict(zip(_FIELD_NAMES, row)))
                for row in res
            ]

    def _build_time_route_conditions(
        self,
        project_uuid: UUID,
        route_names: list[str] | None,
        _from: datetime | None,
        _to: datetime | None,
    ) -> list:
        T = self.T
        conditions = [literal_column(_PROJECT_UUID_ATTR) == str(project_uuid)]
        if _from is not None:
            conditions.append(T.c['Timestamp'] >= _from)
        if _to is not None:
            conditions.append(T.c['Timestamp'] <= _to)
        if route_names:
            conditions.append(literal_column(_ROUTE_NAME_ATTR).in_(route_names))
        return conditions

    def _build_category_expr(self, include_others: bool, conditions: list) -> tuple:
        if include_others:
            expr = f"if({_OPERATION_CATEGORY_ATTR} = '', 'other', {_OPERATION_CATEGORY_ATTR})"
            col = literal_column(expr).label('category')
            return col, text(expr), text(expr)
        conditions.append(literal_column(_OPERATION_CATEGORY_ATTR) != '')
        col = literal_column(_OPERATION_CATEGORY_ATTR).label('category')
        return col, text(_OPERATION_CATEGORY_ATTR), text(_OPERATION_CATEGORY_ATTR)

    def get_category_latencies(
        self,
        project_uuid: UUID,
        route_names: list[str] | None,
        _from: datetime | None,
        _to: datetime | None,
        include_others: bool = False,
    ) -> list[CategoryLatencies]:
        conditions = self._build_time_route_conditions(
            project_uuid, route_names, _from, _to
        )
        cat_col, group_expr, order_expr = self._build_category_expr(
            include_others, conditions
        )
        field_names = ['category', 'p50', 'p90', 'p95', 'p99']

        stmt = (
            select(cat_col, *_quantile_columns())
            .select_from(OtelTraces)
            .where(*conditions)
            .group_by(group_expr)
            .order_by(order_expr)
        )

        with self.db.begin_session() as session:
            return [
                CategoryLatencies.model_validate(dict(zip(field_names, row)))
                for row in session.execute(stmt).all()
            ]

    def get_category_span_latencies(
        self,
        project_uuid: UUID,
        route_names: list[str] | None,
        _from: datetime | None,
        _to: datetime | None,
        include_others: bool = False,
    ) -> list[CategorySpanLatencies]:
        conditions = self._build_time_route_conditions(
            project_uuid, route_names, _from, _to
        )
        cat_col, group_expr, order_expr = self._build_category_expr(
            include_others, conditions
        )
        field_names = ['category', 'span_name', 'p50', 'p90', 'p95', 'p99']

        stmt = (
            select(
                cat_col,
                self.T.c['SpanName'].label('span_name'),
                *_quantile_columns(),
            )
            .select_from(OtelTraces)
            .where(*conditions)
            .group_by(group_expr, text('SpanName'))
            .order_by(order_expr, text('SpanName'))
        )

        with self.db.begin_session() as session:
            return [
                CategorySpanLatencies.model_validate(dict(zip(field_names, row)))
                for row in session.execute(stmt).all()
            ]

    def get_spans_by_trace_id(
        self, project_uuid: UUID, trace_id: str
    ) -> list[SpanRecord]:
        T = self.T
        stmt = (
            select(
                T.c['Timestamp'].label('timestamp'),
                T.c['TraceId'].label('trace_id'),
                literal_column(_REQUEST_UUID_ATTR).label('request_uuid'),
                T.c['SpanId'].label('span_id'),
                T.c['SpanName'].label('span_name'),
                T.c['ServiceName'].label('service_name'),
                T.c['Duration'].label('duration'),
                T.c['StatusCode'].label('status_code'),
                T.c['ParentSpanId'].label('parent_span_id'),
                literal_column(_ROUTE_NAME_ATTR).label('route_name'),
                literal_column(_API_KEY_UUID_ATTR).label('api_key_uuid'),
                literal_column(_API_KEY_NAME_ATTR).label('api_key_name'),
                literal_column(_GROUP_UUID_ATTR).label('group_uuid'),
                literal_column(_GROUP_NAME_ATTR).label('group_name'),
                literal_column(_OUTPUT_TOKENS_ATTR).label('output_tokens'),
                literal_column(_INPUT_TOKENS_ATTR).label('input_tokens'),
                literal_column(_TOTAL_TOKENS_ATTR).label('total_tokens'),
            )
            .select_from(OtelTraces)
            .where(
                literal_column(_PROJECT_UUID_ATTR) == str(project_uuid),
                T.c['TraceId'] == trace_id,
            )
            .order_by(text('Timestamp ASC'))
        )

        with self.db.begin_session() as session:
            res = session.execute(stmt).all()
            return [
                SpanRecord.model_validate(dict(zip(_SPAN_FIELD_NAMES, row)))
                for row in res
            ]

    def get_span_by_trace_and_span_id(
        self, project_uuid: UUID, trace_id: str, span_id: str
    ) -> SpanRecord | None:
        T = self.T
        stmt = (
            select(
                T.c['Timestamp'].label('timestamp'),
                T.c['TraceId'].label('trace_id'),
                literal_column(_REQUEST_UUID_ATTR).label('request_uuid'),
                T.c['SpanId'].label('span_id'),
                T.c['SpanName'].label('span_name'),
                T.c['ServiceName'].label('service_name'),
                T.c['Duration'].label('duration'),
                T.c['StatusCode'].label('status_code'),
                T.c['ParentSpanId'].label('parent_span_id'),
                literal_column(_ROUTE_NAME_ATTR).label('route_name'),
                literal_column(_API_KEY_UUID_ATTR).label('api_key_uuid'),
                literal_column(_API_KEY_NAME_ATTR).label('api_key_name'),
                literal_column(_GROUP_UUID_ATTR).label('group_uuid'),
                literal_column(_GROUP_NAME_ATTR).label('group_name'),
                literal_column(_OUTPUT_TOKENS_ATTR).label('output_tokens'),
                literal_column(_INPUT_TOKENS_ATTR).label('input_tokens'),
                literal_column(_TOTAL_TOKENS_ATTR).label('total_tokens'),
                T.c['SpanAttributes'].label('span_attributes'),
                T.c['StatusMessage'].label('status_message'),
                T.c['Events.Timestamp'].label('events_timestamp'),
                T.c['Events.Name'].label('events_name'),
                T.c['Events.Attributes'].label('events_attributes'),
            )
            .select_from(OtelTraces)
            .where(
                literal_column(_PROJECT_UUID_ATTR) == str(project_uuid),
                T.c['TraceId'] == trace_id,
                T.c['SpanId'] == span_id,
            )
        )

        with self.db.begin_session() as session:
            res = session.execute(stmt).first()
            if res is None:
                return None
            row_data = dict(zip(_SPAN_DETAIL_FIELD_NAMES, res))
            row_data['events'] = _convert_events_to_dicts(
                row_data.get('events_timestamp'),
                row_data.get('events_name'),
                row_data.get('events_attributes'),
            )
            return SpanRecord.model_validate(row_data)

    def get_spans_stats_by_request_uuids(
        self,
        request_uuids: list[str],
    ) -> dict[str, SpanStats]:
        if not request_uuids:
            return {}

        T = self.T
        req_uuid_attr = literal_column(_REQUEST_UUID_ATTR)

        stmt = (
            select(
                req_uuid_attr.label('request_uuid'),
                F.count().label('span_count'),
                F.countIf(T.c['StatusCode'] == 'Error').label('error_count'),
                literal_column(
                    f'SUM(toInt64OrDefault({_INPUT_TOKENS_ATTR}, toInt64(0)))'
                ).label('input_tokens'),
                literal_column(
                    f'SUM(toInt64OrDefault({_OUTPUT_TOKENS_ATTR}, toInt64(0)))'
                ).label('output_tokens'),
                F.max(T.c['Timestamp']).label('last_span'),
            )
            .select_from(OtelTraces)
            .where(req_uuid_attr.in_(request_uuids))
            .group_by(text(_REQUEST_UUID_ATTR))
        )

        with self.db.begin_session() as session:
            res = session.execute(stmt).all()
            return {
                row[0]: SpanStats(
                    span_count=row[1],
                    error_count=row[2],
                    input_tokens=row[3],
                    output_tokens=row[4],
                    last_span=row[5],
                )
                for row in res
            }

    def get_traces_chart_data(
        self,
        project_uuid: UUID,
        route_names: list[str] | None,
        _from: datetime | None,
        _to: datetime | None,
        granularity: Literal['hours', 'days', 'weeks', 'months'],
        timezone_offset_seconds: int = 0,
    ) -> list[TracesChartDataPoint]:
        """Get trace count data aggregated by time buckets from root spans.

        Single-pass query: groups by TraceId first to extract root span info
        and child error counts, then buckets and classifies.

        Classifies each root span into trace_status:
        - error: root span has StatusCode = 'Error'
        - warning: root span is OK but child spans have errors
        - success: no errors in any span
        """
        T = self.T
        FIELD_NAMES = ['bucket', 'trace_status', 'total_requests']

        conditions = [literal_column(_PROJECT_UUID_ATTR) == str(project_uuid)]
        if _from is not None:
            conditions.append(T.c['Timestamp'] >= _from)
        if _to is not None:
            conditions.append(T.c['Timestamp'] <= _to)

        # Single-pass: aggregate per TraceId using conditional functions
        trace_agg = (
            select(
                T.c['TraceId'].label('trace_id'),
                F.anyIf(T.c['Timestamp'], T.c['ParentSpanId'] == '').label(
                    'root_timestamp'
                ),
                F.anyIf(T.c['StatusCode'], T.c['ParentSpanId'] == '').label(
                    'root_status'
                ),
                F.countIf(
                    T.c['ParentSpanId'] != '', T.c['StatusCode'] == 'Error'
                ).label('child_error_count'),
                F.anyIf(
                    literal_column(_ROUTE_NAME_ATTR), T.c['ParentSpanId'] == ''
                ).label('route_name'),
            )
            .select_from(OtelTraces)
            .where(*conditions)
            .group_by(T.c['TraceId'])
        ).subquery('trace_agg')

        # Filter by route names on the aggregated root span route_name
        outer_conditions = []
        if route_names:
            outer_conditions.append(trace_agg.c.route_name.in_(route_names))

        # Build bucket expression
        bucket_expr = with_timezone_offset(
            get_bucket_function(granularity),
            timezone_offset_seconds,
            trace_agg.c.root_timestamp,
        )

        # Classify: root error → error, child errors only → warning, else success
        trace_status_expr = literal_column(
            'multiIf('
            "root_status = 'Error', 'error', "
            "child_error_count > 0, 'warning', "
            "'success'"
            ')'
        )

        stmt = (
            select(
                bucket_expr.label('bucket'),
                trace_status_expr.label('trace_status'),
                F.count().label('total_requests'),
            )
            .select_from(trace_agg)
            .where(*outer_conditions)
            .group_by(text('bucket'), text('trace_status'))
            .order_by(text('bucket'))
        )

        with self.db.begin_session() as session:
            res = session.execute(stmt).all()
            return [
                TracesChartDataPoint.model_validate(dict(zip(FIELD_NAMES, row_tuple)))
                for row_tuple in res
            ]

    def get_root_span_error_by_trace_ids(self, trace_ids: list[str]) -> set[str]:
        """Return trace IDs where the root span has StatusCode = 'Error'."""
        if not trace_ids:
            return set()

        T = self.T
        stmt = (
            select(T.c['TraceId'].label('trace_id'))
            .select_from(OtelTraces)
            .where(
                T.c['TraceId'].in_(trace_ids),
                T.c['ParentSpanId'] == '',
                T.c['StatusCode'] == 'Error',
            )
        )

        with self.db.begin_session() as session:
            return {row[0] for row in session.execute(stmt).all()}

    def get_latencies(
        self,
        project_uuid: UUID,
        route_names: list[str] | None,
        _from: datetime | None,
        _to: datetime | None,
    ) -> TraceLatencies:
        """Get trace latencies (in ms) from root spans."""
        T = self.T
        FIELD_NAMES = ['p50', 'p90', 'p95', 'p99']
        route_name_attr = literal_column(_ROUTE_NAME_ATTR)

        conditions = [
            T.c['ParentSpanId'] == '',
            literal_column(_PROJECT_UUID_ATTR) == str(project_uuid),
        ]
        if route_names:
            conditions.append(route_name_attr.in_(route_names))
        if _from is not None:
            conditions.append(T.c['Timestamp'] >= _from)
        if _to is not None:
            conditions.append(T.c['Timestamp'] <= _to)

        stmt = select(
            F.quantile(0.50, literal_column('Duration / 1000000')).label('p50'),
            F.quantile(0.90, literal_column('Duration / 1000000')).label('p90'),
            F.quantile(0.95, literal_column('Duration / 1000000')).label('p95'),
            F.quantile(0.99, literal_column('Duration / 1000000')).label('p99'),
        ).select_from(OtelTraces)

        if conditions:
            stmt = stmt.where(*conditions)

        with self.db.begin_session() as session:
            res = session.execute(stmt).first()
            if res is None:
                return TraceLatencies()
            return TraceLatencies.model_validate(dict(zip(FIELD_NAMES, res)))

    def get_root_traces_paginated(
        self,
        project_uuid: UUID,
        route_names: list[str] | None,
        group_uuids: list[UUID] | None,
        key_uuids: list[UUID] | None,
        _from: datetime | None,
        _to: datetime | None,
        params: Params,
    ) -> Page[Row]:
        """Get paginated root spans with metadata."""
        T = self.T
        route_name_attr = literal_column(_ROUTE_NAME_ATTR)
        api_key_uuid_attr = literal_column(_API_KEY_UUID_ATTR)
        api_key_name_attr = literal_column(_API_KEY_NAME_ATTR)
        group_uuid_attr = literal_column(_GROUP_UUID_ATTR)
        group_name_attr = literal_column(_GROUP_NAME_ATTR)
        request_uuid_attr = literal_column(_REQUEST_UUID_ATTR)

        stmt = (
            select(
                T.c['TraceId'].label('trace_id'),
                request_uuid_attr.label('request_uuid'),
                route_name_attr.label('route_name'),
                group_name_attr.label('group_name'),
                group_uuid_attr.label('group_uuid'),
                api_key_name_attr.label('api_key_name'),
                api_key_uuid_attr.label('api_key_uuid'),
                literal_column('Duration / 1000000').label('duration_ms'),
                T.c['Timestamp'].label('created_at'),
            )
            .select_from(OtelTraces)
            .where(
                T.c['ParentSpanId'] == '',
                literal_column(_PROJECT_UUID_ATTR) == str(project_uuid),
            )
            .order_by(text('Timestamp DESC'))
        )

        if route_names:
            stmt = stmt.where(route_name_attr.in_(route_names))
        if group_uuids:
            stmt = stmt.where(group_uuid_attr.in_([str(g) for g in group_uuids]))
        if key_uuids:
            stmt = stmt.where(api_key_uuid_attr.in_([str(k) for k in key_uuids]))
        if _from is not None:
            stmt = stmt.where(T.c['Timestamp'] >= _from)
        if _to is not None:
            stmt = stmt.where(T.c['Timestamp'] <= _to)

        with self.db.begin_session() as session:
            return paginate(session, stmt, params)

    def get_spans_stats_by_trace_ids(
        self,
        trace_ids: list[str],
    ) -> dict[str, SpanStats]:
        """Aggregate span stats by TraceId."""
        if not trace_ids:
            return {}

        T = self.T

        stmt = (
            select(
                T.c['TraceId'].label('trace_id'),
                F.count().label('span_count'),
                F.countIf(T.c['StatusCode'] == 'Error').label('error_count'),
                literal_column(
                    f'SUM(toInt64OrDefault({_INPUT_TOKENS_ATTR}, toInt64(0)))'
                ).label('input_tokens'),
                literal_column(
                    f'SUM(toInt64OrDefault({_OUTPUT_TOKENS_ATTR}, toInt64(0)))'
                ).label('output_tokens'),
                F.max(T.c['Timestamp']).label('last_span'),
            )
            .select_from(OtelTraces)
            .where(T.c['TraceId'].in_(trace_ids))
            .group_by(T.c['TraceId'])
        )

        with self.db.begin_session() as session:
            res = session.execute(stmt).all()
            return {
                row[0]: SpanStats(
                    span_count=row[1],
                    error_count=row[2],
                    input_tokens=row[3],
                    output_tokens=row[4],
                    last_span=row[5],
                )
                for row in res
            }
