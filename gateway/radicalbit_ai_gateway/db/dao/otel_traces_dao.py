from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi_pagination import Page, Params
from fastapi_pagination.ext.sqlalchemy import paginate
from sqlalchemy import ColumnElement, Label, Row, func as F, select

from radicalbit_ai_gateway.db.clickhouse_database import ClickHouseDatabase
from radicalbit_ai_gateway.db.clickhouse_functions import quantile
from radicalbit_ai_gateway.db.dao.tags_filter import add_tags_filter
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
from radicalbit_ai_gateway.models.request_event_type import RequestType
from radicalbit_ai_gateway.utils.chart_utils import (
    get_bucket_function,
    with_timezone_offset,
)

_T = OtelTraces.__table__


def _span_attribute(key: str) -> ColumnElement[Any]:
    """Return the SpanAttributes value at `key`: '' when the span lacks it."""
    return F.arrayElement(_T.c['SpanAttributes'], key)


_PROPERTIES = 'traceloop.association.properties.'


def _in_project(project_uuid: UUID) -> ColumnElement[bool]:
    """Keep the spans of the project."""
    return _span_attribute(f'{_PROPERTIES}project_uuid') == str(project_uuid)


_ROUTE_NAME = _span_attribute(f'{_PROPERTIES}route_name')
_API_KEY_UUID = _span_attribute(f'{_PROPERTIES}api_key_uuid')
_API_KEY_NAME = _span_attribute(f'{_PROPERTIES}api_key_name')
_GROUP_UUID = _span_attribute(f'{_PROPERTIES}group_uuid')
_GROUP_NAME = _span_attribute(f'{_PROPERTIES}group_name')
_REQUEST_UUID = _span_attribute(f'{_PROPERTIES}request_uuid')
_OPERATION_CATEGORY = _span_attribute(f'{_PROPERTIES}rb.gateway.operation_category')
_OUTPUT_TOKENS = _span_attribute('gen_ai.usage.output_tokens')
_INPUT_TOKENS = _span_attribute('gen_ai.usage.input_tokens')
_SPAN_KIND = _span_attribute('traceloop.span.kind')
_GEN_AI_PROVIDER = _span_attribute('gen_ai.provider.name')
# Stamped on the decide span. Span attributes are strings, so the boolean is
# stored as 'true' or 'false'. A span without it reads as false.
_FALLBACK_TRIGGERED = (
    F.lower(_span_attribute('decision.response.fallback_triggered')) == 'true'
)
_TAGS = _span_attribute(f'{_PROPERTIES}tags')
# Tags are stamped as one comma-joined "key=value,..." string (see
# set_trace_attributes) since SpanAttributes values are scalar - splitByChar
# turns it back into the Array(String) shape `add_tags_filter` expects.
_TAGS_ARRAY = F.if_(_TAGS == '', F.array(), F.splitByChar(',', _TAGS))
# Duration is in nanoseconds. divide() is ClickHouse's `/`: SQLAlchemy's `/`
# on two integers casts the divisor to NUMERIC, a Decimal in ClickHouse.
_DURATION_MS = F.divide(_T.c['Duration'], 1_000_000)

# The root span of a trace is the @workflow span of the endpoint that served
# it, so its SpanName tells the request type. Deriving it here, not from a
# stamped attribute, also covers traces written before this field existed.
_ROOT_SPAN_NAMES_BY_REQUEST_TYPE: dict[RequestType, list[str]] = {
    RequestType.CHAT_COMPLETIONS: [
        'chat_completions.workflow',
        'responses.workflow',
        'messages.workflow',
    ],
    RequestType.EMBEDDINGS: ['embeddings.workflow'],
    RequestType.TRANSCRIPTIONS: ['audio_transcriptions.workflow'],
    RequestType.DECISION_MODEL: ['decision_model.workflow'],
    RequestType.MCP: ['mcp_request.workflow'],
}
# Empty string for an unknown root span name, like the other string columns.
_REQUEST_TYPE = F.multiIf(
    *(
        branch
        for request_type, names in _ROOT_SPAN_NAMES_BY_REQUEST_TYPE.items()
        for name in names
        for branch in (_T.c['SpanName'] == name, request_type.value)
    ),
    '',
)


def request_type_of_root_span(span_name: str) -> RequestType | None:
    """Python twin of _REQUEST_TYPE, for spans already loaded."""
    for request_type, names in _ROOT_SPAN_NAMES_BY_REQUEST_TYPE.items():
        if span_name in names:
            return request_type
    return None


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
    'tags',
    'operation_category',
    'span_kind',
    'fallback_triggered',
    'gen_ai_provider',
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
    'span_attributes',
    'status_message',
    'events_timestamp',
    'events_name',
    'events_attributes',
]


def _quantile_columns() -> list[Label[float]]:
    """Span duration in ms at p50, p90, p95 and p99."""
    return [
        quantile(level, _DURATION_MS).label(label)
        for level, label in [(0.50, 'p50'), (0.90, 'p90'), (0.95, 'p95'), (0.99, 'p99')]
    ]


def _convert_events_to_dicts(
    timestamps: list[datetime] | None,
    names: list[str] | None,
    attributes: list[dict[str, str]] | None,
) -> list[dict[str, object]]:
    """Convert ClickHouse parallel event arrays to dictionaries.

    ClickHouse stores events as parallel arrays (columnar format):
    - Events.Timestamp: Array(DateTime64(9))
    - Events.Name: Array(String)
    - Events.Attributes: Array(Map(String, String))

    This zips them into dicts with lowercase keys matching SpanRecord model.
    """
    if timestamps is None or len(timestamps) == 0:
        return []
    return [
        {'timestamp': ts, 'name': n, 'attributes': a}
        for ts, n, a in zip(timestamps, names or [], attributes or [])
    ]


class OtelTracesDAO:
    def __init__(self, database: ClickHouseDatabase):
        self.db = database
        self.T = OtelTraces.__table__

    def _add_tags_filter(
        self, conditions: list[ColumnElement[Any]], tags: list[str] | None
    ) -> None:
        add_tags_filter(conditions, F.splitByChar(',', _TAGS), tags=tags)

    def get_span_latencies(
        self,
        project_uuid: UUID,
        route_names: list[str] | None,
        _from: datetime | None,
        _to: datetime | None,
        tags: list[str] | None = None,
    ) -> list[SpanLatencies]:
        T = self.T
        conditions = [_in_project(project_uuid)]

        if _from is not None:
            conditions.append(T.c['Timestamp'] >= _from)
        if _to is not None:
            conditions.append(T.c['Timestamp'] <= _to)
        if route_names is not None and len(route_names) > 0:
            conditions.append(_ROUTE_NAME.in_(route_names))
        self._add_tags_filter(conditions, tags=tags)

        stmt = (
            select(T.c['SpanName'].label('span_name'), *_quantile_columns())
            .select_from(OtelTraces)
            .where(*conditions)
            .group_by(T.c['SpanName'])
            .order_by(T.c['SpanName'])
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
        tags: list[str] | None = None,
    ) -> list[ColumnElement[Any]]:
        T = self.T
        conditions: list[ColumnElement[Any]] = [_in_project(project_uuid)]
        if _from is not None:
            conditions.append(T.c['Timestamp'] >= _from)
        if _to is not None:
            conditions.append(T.c['Timestamp'] <= _to)
        if route_names is not None and len(route_names) > 0:
            conditions.append(_ROUTE_NAME.in_(route_names))
        self._add_tags_filter(conditions, tags=tags)
        return conditions

    def _build_category_column(
        self, include_others: bool, conditions: list[ColumnElement[Any]]
    ) -> Label[Any]:
        """Return the `category` column.

        Spans without a category count as 'other' with `include_others`, else
        a condition filters them out.
        """
        if include_others:
            category = F.if_(_OPERATION_CATEGORY == '', 'other', _OPERATION_CATEGORY)
        else:
            conditions.append(_OPERATION_CATEGORY != '')
            category = _OPERATION_CATEGORY
        return category.label('category')

    def get_category_latencies(
        self,
        project_uuid: UUID,
        route_names: list[str] | None,
        _from: datetime | None,
        _to: datetime | None,
        include_others: bool = False,
        tags: list[str] | None = None,
    ) -> list[CategoryLatencies]:
        conditions = self._build_time_route_conditions(
            project_uuid, route_names, _from, _to, tags=tags
        )
        category = self._build_category_column(include_others, conditions)
        field_names = ['category', 'p50', 'p90', 'p95', 'p99']

        stmt = (
            select(category, *_quantile_columns())
            .select_from(OtelTraces)
            .where(*conditions)
            .group_by(category)
            .order_by(category)
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
        tags: list[str] | None = None,
    ) -> list[CategorySpanLatencies]:
        conditions = self._build_time_route_conditions(
            project_uuid, route_names, _from, _to, tags=tags
        )
        category = self._build_category_column(include_others, conditions)
        field_names = ['category', 'span_name', 'p50', 'p90', 'p95', 'p99']
        span_name = self.T.c['SpanName']

        stmt = (
            select(category, span_name.label('span_name'), *_quantile_columns())
            .select_from(OtelTraces)
            .where(*conditions)
            .group_by(category, span_name)
            .order_by(category, span_name)
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
                _REQUEST_UUID.label('request_uuid'),
                T.c['SpanId'].label('span_id'),
                T.c['SpanName'].label('span_name'),
                T.c['ServiceName'].label('service_name'),
                T.c['Duration'].label('duration'),
                T.c['StatusCode'].label('status_code'),
                T.c['ParentSpanId'].label('parent_span_id'),
                _ROUTE_NAME.label('route_name'),
                _API_KEY_UUID.label('api_key_uuid'),
                _API_KEY_NAME.label('api_key_name'),
                _GROUP_UUID.label('group_uuid'),
                _GROUP_NAME.label('group_name'),
                _OUTPUT_TOKENS.label('output_tokens'),
                _INPUT_TOKENS.label('input_tokens'),
                _TAGS_ARRAY.label('tags'),
                _OPERATION_CATEGORY.label('operation_category'),
                _SPAN_KIND.label('span_kind'),
                _FALLBACK_TRIGGERED.label('fallback_triggered'),
                _GEN_AI_PROVIDER.label('gen_ai_provider'),
            )
            .select_from(OtelTraces)
            .where(_in_project(project_uuid), T.c['TraceId'] == trace_id)
            .order_by(T.c['Timestamp'].asc())
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
                _REQUEST_UUID.label('request_uuid'),
                T.c['SpanId'].label('span_id'),
                T.c['SpanName'].label('span_name'),
                T.c['ServiceName'].label('service_name'),
                T.c['Duration'].label('duration'),
                T.c['StatusCode'].label('status_code'),
                T.c['ParentSpanId'].label('parent_span_id'),
                _ROUTE_NAME.label('route_name'),
                _API_KEY_UUID.label('api_key_uuid'),
                _API_KEY_NAME.label('api_key_name'),
                _GROUP_UUID.label('group_uuid'),
                _GROUP_NAME.label('group_name'),
                _OUTPUT_TOKENS.label('output_tokens'),
                _INPUT_TOKENS.label('input_tokens'),
                T.c['SpanAttributes'].label('span_attributes'),
                T.c['StatusMessage'].label('status_message'),
                T.c['Events.Timestamp'].label('events_timestamp'),
                T.c['Events.Name'].label('events_name'),
                T.c['Events.Attributes'].label('events_attributes'),
            )
            .select_from(OtelTraces)
            .where(
                _in_project(project_uuid),
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

    def _span_stats_columns(self) -> list[Label[Any]]:
        """Return the SpanStats columns of a group of spans, in SpanStats order."""
        T = self.T
        return [
            F.count().label('span_count'),
            F.countIf(T.c['StatusCode'] == 'Error').label('error_count'),
            F.sum(F.toInt64OrDefault(_INPUT_TOKENS, F.toInt64(0))).label(
                'input_tokens'
            ),
            F.sum(F.toInt64OrDefault(_OUTPUT_TOKENS, F.toInt64(0))).label(
                'output_tokens'
            ),
            F.max(T.c['Timestamp']).label('last_span'),
        ]

    def get_spans_stats_by_request_uuids(
        self,
        request_uuids: list[str],
    ) -> dict[str, SpanStats]:
        if not request_uuids:
            return {}

        stmt = (
            select(_REQUEST_UUID.label('request_uuid'), *self._span_stats_columns())
            .select_from(OtelTraces)
            .where(_REQUEST_UUID.in_(request_uuids))
            .group_by(_REQUEST_UUID)
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

    def get_trace_ids_by_request_uuids(
        self,
        project_uuid: UUID,
        request_uuids: list[str],
        date_from: date,
        date_to: date,
    ) -> dict[str, str]:
        """Map each request UUID to the trace its root span belongs to.

        Requests that left no trace are absent from the result. Spans are
        bounded to `[date_from, date_to]` so ClickHouse prunes partitions.
        """
        if not request_uuids:
            return {}

        T = self.T
        stmt = (
            select(
                _REQUEST_UUID.label('request_uuid'),
                F.any(T.c['TraceId']).label('trace_id'),
            )
            .select_from(OtelTraces)
            .where(
                T.c['ParentSpanId'] == '',
                _in_project(project_uuid),
                _REQUEST_UUID.in_(request_uuids),
                # Timestamp has no column timezone: read its date in UTC, as
                # event and request_event DATE are, or the window shifts on a
                # server whose timezone is not UTC.
                F.toDate(T.c['Timestamp'], 'UTC') >= date_from,
                F.toDate(T.c['Timestamp'], 'UTC') <= date_to,
            )
            .group_by(_REQUEST_UUID)
        )

        with self.db.begin_session() as session:
            return {row[0]: row[1] for row in session.execute(stmt).all()}

    def get_traces_chart_data(
        self,
        project_uuid: UUID,
        route_names: list[str] | None,
        _from: datetime | None,
        _to: datetime | None,
        granularity: Literal['hours', 'days', 'weeks', 'months'],
        timezone_offset_seconds: int = 0,
        tags: list[str] | None = None,
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

        conditions = [_in_project(project_uuid)]
        if _from is not None:
            conditions.append(T.c['Timestamp'] >= _from)
        if _to is not None:
            conditions.append(T.c['Timestamp'] <= _to)

        # Single-pass: aggregate per TraceId using conditional functions
        trace_agg = (
            select(
                T.c['TraceId'].label('trace_id'),
                # nullIf converts the epoch default (returned by anyIf when a
                # trace has no root span, i.e. no span with an empty
                # ParentSpanId) to NULL, so rootless traces can be filtered out
                # below instead of bucketing to 1970 and exploding the range.
                F.nullIf(
                    F.anyIf(T.c['Timestamp'], T.c['ParentSpanId'] == ''),
                    F.toDateTime(0),
                ).label('root_timestamp'),
                F.anyIf(T.c['StatusCode'], T.c['ParentSpanId'] == '').label(
                    'root_status'
                ),
                F.countIf(
                    T.c['ParentSpanId'] != '', T.c['StatusCode'] == 'Error'
                ).label('child_error_count'),
                F.anyIf(_ROUTE_NAME, T.c['ParentSpanId'] == '').label('route_name'),
                F.anyIf(_TAGS, T.c['ParentSpanId'] == '').label('tags_str'),
            )
            .select_from(OtelTraces)
            .where(*conditions)
            .group_by(T.c['TraceId'])
        ).subquery('trace_agg')

        # Drop traces with no root span: their root_timestamp is NULL (see the
        # nullIf above) and they would otherwise bucket to the Unix epoch.
        outer_conditions: list[ColumnElement[Any]] = [
            trace_agg.c.root_timestamp.isnot(None)
        ]
        if route_names is not None and len(route_names) > 0:
            outer_conditions.append(trace_agg.c.route_name.in_(route_names))
        add_tags_filter(
            outer_conditions, F.splitByChar(',', trace_agg.c.tags_str), tags=tags
        )

        # Build bucket expression
        bucket_expr = with_timezone_offset(
            get_bucket_function(granularity),
            timezone_offset_seconds,
            trace_agg.c.root_timestamp,
        )

        # Classify: root error → error, child errors only → warning, else success
        trace_status_expr = F.multiIf(
            trace_agg.c.root_status == 'Error',
            'error',
            trace_agg.c.child_error_count > 0,
            'warning',
            'success',
        )

        stmt = (
            select(
                bucket_expr.label('bucket'),
                trace_status_expr.label('trace_status'),
                F.count().label('total_requests'),
            )
            .select_from(trace_agg)
            .where(*outer_conditions)
            .group_by('bucket', 'trace_status')
            .order_by('bucket')
        )

        with self.db.begin_session() as session:
            res = session.execute(stmt).all()
            return [
                TracesChartDataPoint.model_validate(dict(zip(FIELD_NAMES, row_tuple)))
                for row_tuple in res
            ]

    def _date_window(
        self, date_from: date | None, date_to: date | None
    ) -> list[ColumnElement[Any]]:
        """Bound spans to `[date_from, date_to]` so ClickHouse prunes partitions.

        Timestamp has no column timezone: its date is read in UTC, as the
        callers compute theirs.
        """
        conditions: list[ColumnElement[Any]] = []
        if date_from is not None:
            conditions.append(F.toDate(self.T.c['Timestamp'], 'UTC') >= date_from)
        if date_to is not None:
            conditions.append(F.toDate(self.T.c['Timestamp'], 'UTC') <= date_to)
        return conditions

    def get_root_span_error_by_trace_ids(
        self,
        trace_ids: list[str],
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> set[str]:
        """Return trace IDs where the root span has StatusCode = 'Error'.

        A lookup by TraceId alone reads every partition: pass the dates the
        traces span to bound it.
        """
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
                *self._date_window(date_from, date_to),
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
        tags: list[str] | None = None,
    ) -> TraceLatencies:
        """Get trace latencies (in ms) from root spans."""
        T = self.T
        FIELD_NAMES = ['p50', 'p90', 'p95', 'p99']

        conditions = [
            T.c['ParentSpanId'] == '',
            _in_project(project_uuid),
        ]
        if route_names is not None and len(route_names) > 0:
            conditions.append(_ROUTE_NAME.in_(route_names))
        if _from is not None:
            conditions.append(T.c['Timestamp'] >= _from)
        if _to is not None:
            conditions.append(T.c['Timestamp'] <= _to)
        self._add_tags_filter(conditions, tags=tags)

        stmt = select(*_quantile_columns()).select_from(OtelTraces)

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
        tags: list[str] | None = None,
        request_types: list[RequestType] | None = None,
    ) -> Page[Row[*tuple[Any, ...]]]:
        """Get paginated root spans with metadata."""
        T = self.T

        stmt = (
            select(
                T.c['TraceId'].label('trace_id'),
                _REQUEST_UUID.label('request_uuid'),
                _ROUTE_NAME.label('route_name'),
                _GROUP_NAME.label('group_name'),
                _GROUP_UUID.label('group_uuid'),
                _API_KEY_NAME.label('api_key_name'),
                _API_KEY_UUID.label('api_key_uuid'),
                _DURATION_MS.label('duration_ms'),
                T.c['Timestamp'].label('created_at'),
                _TAGS_ARRAY.label('tags'),
                _REQUEST_TYPE.label('request_type'),
            )
            .select_from(OtelTraces)
            .where(
                T.c['ParentSpanId'] == '',
                _in_project(project_uuid),
            )
            .order_by(T.c['Timestamp'].desc())
        )

        if route_names is not None and len(route_names) > 0:
            stmt = stmt.where(_ROUTE_NAME.in_(route_names))
        if request_types is not None and len(request_types) > 0:
            # Filter on SpanName, not on the derived label, so ClickHouse
            # compares a plain column.
            stmt = stmt.where(
                T.c['SpanName'].in_(
                    [
                        name
                        for request_type in request_types
                        for name in _ROOT_SPAN_NAMES_BY_REQUEST_TYPE[request_type]
                    ]
                )
            )
        if group_uuids is not None and len(group_uuids) > 0:
            stmt = stmt.where(_GROUP_UUID.in_([str(g) for g in group_uuids]))
        if key_uuids is not None and len(key_uuids) > 0:
            stmt = stmt.where(_API_KEY_UUID.in_([str(k) for k in key_uuids]))
        if _from is not None:
            stmt = stmt.where(T.c['Timestamp'] >= _from)
        if _to is not None:
            stmt = stmt.where(T.c['Timestamp'] <= _to)
        tags_conditions: list[ColumnElement[Any]] = []
        self._add_tags_filter(tags_conditions, tags=tags)
        if tags_conditions:
            stmt = stmt.where(*tags_conditions)

        with self.db.begin_session() as session:
            # unique=False: rows now include the `tags` array column, which
            # isn't hashable, so paginate()'s default row-dedup can't run.
            # Every row is already unique (TraceId is unique per root span).
            return paginate(session, stmt, params, unique=False)

    def get_spans_stats_by_trace_ids(
        self,
        trace_ids: list[str],
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> dict[str, SpanStats]:
        """Aggregate span stats by TraceId.

        A lookup by TraceId alone reads every partition: pass the dates the
        traces span to bound it.
        """
        if not trace_ids:
            return {}

        T = self.T

        stmt = (
            select(T.c['TraceId'].label('trace_id'), *self._span_stats_columns())
            .select_from(OtelTraces)
            .where(
                T.c['TraceId'].in_(trace_ids),
                *self._date_window(date_from, date_to),
            )
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
