from datetime import UTC, datetime, timedelta
from typing import Any, Literal, NamedTuple
from uuid import UUID

from fastapi_pagination import Page, Params
from pydantic import BaseModel
from sqlalchemy import Float, Row, func as F, select, text

from radicalbit_ai_gateway.db.clickhouse_database import ClickHouseDatabase
from radicalbit_ai_gateway.db.dao.tags_filter import add_tags_filter
from radicalbit_ai_gateway.db.models.event import (
    ErrorDetail,
    ErrorRequestChartDataPoint,
    ErrorRoute,
    RequestChartDataPoint,
    RequestGroupedChartDataPoint,
    RequestStats,
)
from radicalbit_ai_gateway.db.tables.request_event_table import RequestEvent
from radicalbit_ai_gateway.models.request_event_type import RequestStatus, RequestType
from radicalbit_ai_gateway.utils.chart_utils import (
    get_bucket_function,
    with_timezone_offset,
)

# The Requests list counts its rows per bucket of this size, then reads a page
# from the buckets that hold it. toStartOfHour in the query must match it.
_PAGE_BUCKET = timedelta(hours=1)


class PageWindow(NamedTuple):
    """Where a page lies among time buckets ordered newest first."""

    oldest: int  # start of the oldest bucket the page reaches, epoch seconds
    newest: int  # start of the newest bucket the page starts in, epoch seconds
    offset: int  # rows to skip inside the newest bucket


def page_window(
    buckets: list[tuple[int, int]], offset: int, size: int
) -> PageWindow | None:
    """Find the buckets that hold rows `[offset, offset + size)`.

    `buckets` is `(start, row count)`, newest first, the rows of a newer bucket
    all sorting before those of an older one. Returns None when the page
    starts past the last row.
    """
    skipped = 0
    newest = None
    for start, count in buckets:
        if newest is None:
            if skipped + count <= offset:
                skipped += count
                continue
            newest, inner_offset = start, offset - skipped
        skipped += count
        if skipped >= offset + size:
            return PageWindow(oldest=start, newest=newest, offset=inner_offset)
    if newest is None:
        return None
    # The page runs past the last row: it ends in the oldest bucket.
    return PageWindow(oldest=buckets[-1][0], newest=newest, offset=inner_offset)


class RequestEventDAO:
    def __init__(self, database: ClickHouseDatabase):
        self.db = database
        self.T = RequestEvent.__table__

    def _base_columns(self):
        T = self.T
        return [
            F.countIf(T.c['REQUEST_STATUS'] == RequestStatus.SUCCESS).label(
                'successful_requests'
            ),
            F.countIf(T.c['REQUEST_STATUS'] != RequestStatus.SUCCESS).label(
                'error_requests'
            ),
            F.count().label('total_requests'),
            # nullIf converts epoch (returned by MAX on empty result sets) to NULL
            F.nullIf(F.max(T.c['TIMESTAMP']), text('toDateTime(0)')).label(
                'last_request_timestamp'
            ),
        ]

    def _add_time_filters(
        self,
        project_uuid: UUID,
        conditions: list,
        _from: datetime | None,
        _to: datetime | None,
        route_name: str | None = None,
    ) -> None:
        if route_name is not None:
            conditions.append(self.T.c['ROUTE_NAME'] == route_name)
        if project_uuid is not None:
            conditions.append(self.T.c['PROJECT_UUID'] == str(project_uuid))
        if _from is not None:
            conditions.append(self.T.c['TIMESTAMP'] >= _from)
        if _to is not None:
            conditions.append(self.T.c['TIMESTAMP'] <= _to)

    def _add_tags_filter(self, conditions: list, tags: list[str] | None) -> None:
        add_tags_filter(conditions, self.T.c['TAGS'], tags=tags)

    def _validate_row(
        self, model_class: type[BaseModel], field_names: list[str], row: tuple
    ) -> Any:
        return model_class.model_validate(dict(zip(field_names, row)))

    def get_request_chart_data(
        self,
        project_uuid: UUID,
        route_name: str,
        _from: datetime | None,
        _to: datetime | None,
        granularity: Literal['hours', 'days', 'weeks', 'months'],
        timezone_offset_seconds: int = 0,
        tags: list[str] | None = None,
    ) -> list[RequestChartDataPoint]:
        T = self.T
        FIELD_NAMES = ['bucket', 'total_requests']

        bucket_expr = with_timezone_offset(
            get_bucket_function(granularity),
            timezone_offset_seconds,
            T.c['TIMESTAMP'],
        )

        conditions = [T.c['ROUTE_NAME'] == route_name]
        self._add_time_filters(project_uuid, conditions, _from, _to)
        self._add_tags_filter(conditions, tags=tags)

        stmt = (
            select(
                bucket_expr.label('bucket'),
                F.count().label('total_requests'),
            )
            .select_from(RequestEvent)
            .where(*conditions)
            .group_by(text('bucket'))
            .order_by(text('bucket'))
        )

        with self.db.begin_session() as session:
            res = session.execute(stmt).all()
            return [
                self._validate_row(RequestChartDataPoint, FIELD_NAMES, row_tuple)
                for row_tuple in res
            ]

    def get_request_chart_data_grouped(
        self,
        project_uuid: UUID,
        route_name: str,
        _from: datetime | None,
        _to: datetime | None,
        granularity: Literal['hours', 'days', 'weeks', 'months'],
        timezone_offset_seconds: int = 0,
        tags: list[str] | None = None,
    ) -> list[RequestGroupedChartDataPoint]:
        T = self.T
        FIELD_NAMES = ['bucket', 'success_count', 'error_count']

        bucket_expr = with_timezone_offset(
            get_bucket_function(granularity),
            timezone_offset_seconds,
            T.c['TIMESTAMP'],
        )

        conditions = [T.c['ROUTE_NAME'] == route_name]
        self._add_time_filters(project_uuid, conditions, _from, _to)
        self._add_tags_filter(conditions, tags=tags)

        stmt = (
            select(
                bucket_expr.label('bucket'),
                F.countIf(T.c['REQUEST_STATUS'] == RequestStatus.SUCCESS).label(
                    'success_count'
                ),
                F.countIf(T.c['REQUEST_STATUS'] != RequestStatus.SUCCESS).label(
                    'error_count'
                ),
            )
            .select_from(RequestEvent)
            .where(*conditions)
            .group_by(text('bucket'))
            .order_by(text('bucket'))
        )

        with self.db.begin_session() as session:
            res = session.execute(stmt).all()
            return [
                self._validate_row(RequestGroupedChartDataPoint, FIELD_NAMES, row_tuple)
                for row_tuple in res
            ]

    def get_most_requested_route(
        self,
        project_uuid: UUID,
        configured_routes: list[str],
        _from: datetime | None,
        _to: datetime | None,
        tags: list[str] | None = None,
    ) -> str | None:
        if not configured_routes:
            return None
        T = self.T
        conditions = [T.c['ROUTE_NAME'].in_(configured_routes)]
        self._add_time_filters(project_uuid, conditions, _from, _to)
        self._add_tags_filter(conditions, tags=tags)

        stmt = (
            select(
                T.c['ROUTE_NAME'].label('route_name'),
                F.count().label('total_requests'),
            )
            .select_from(RequestEvent)
            .where(*conditions)
            .group_by(T.c['ROUTE_NAME'])
            .order_by(text('total_requests DESC'))
            .limit(1)
        )

        with self.db.begin_session() as session:
            res = session.execute(stmt).first()
            return res.route_name if res else None

    def get_most_route_with_error(
        self,
        project_uuid: UUID,
        configured_routes: list[str],
        _from: datetime | None = None,
        _to: datetime | None = None,
        tags: list[str] | None = None,
    ) -> ErrorRoute | None:
        if not configured_routes:
            return None
        T = self.T
        FIELD_NAMES = ['route_name', 'error_perc']
        conditions = [T.c['ROUTE_NAME'].in_(configured_routes)]
        self._add_time_filters(project_uuid, conditions, _from, _to)
        self._add_tags_filter(conditions, tags=tags)
        non_succeeded_condition = F.countIf(
            T.c['REQUEST_STATUS'] != RequestStatus.SUCCESS
        )
        route_stmt = (
            select(
                T.c['ROUTE_NAME'].label('route_name'),
                (non_succeeded_condition / F.count().cast(Float) * 100).label(
                    'error_perc'
                ),
            )
            .select_from(RequestEvent)
            .where(*conditions)
            .group_by(T.c['ROUTE_NAME'])
            .having(non_succeeded_condition > 0)
            .order_by(text('error_perc DESC'))
            .limit(1)
        )

        with self.db.begin_session() as session:
            res = session.execute(route_stmt).first()
            if res is None:
                return None
            return self._validate_row(ErrorRoute, FIELD_NAMES, res)

    def get_request_error_chart_data(
        self,
        project_uuid: UUID,
        route_name: str | None,
        granularity: Literal['hours', 'days', 'weeks', 'months'],
        _from: datetime | None = None,
        _to: datetime | None = None,
        timezone_offset_seconds: int = 0,
        tags: list[str] | None = None,
    ) -> list[ErrorRequestChartDataPoint]:
        if route_name is None:
            return []
        T = self.T
        FIELD_NAMES = ['bucket', 'total_requests']
        bucket_expr = with_timezone_offset(
            get_bucket_function(granularity),
            timezone_offset_seconds,
            T.c['TIMESTAMP'],
        )
        bucket_conditions = [
            T.c['REQUEST_STATUS'] != RequestStatus.SUCCESS,
            T.c['ROUTE_NAME'] == route_name,
        ]
        self._add_time_filters(project_uuid, bucket_conditions, _from, _to)
        self._add_tags_filter(bucket_conditions, tags=tags)

        bucket_stmt = (
            select(
                bucket_expr.label('bucket'),
                F.count().label('total_requests'),
            )
            .select_from(RequestEvent)
            .where(*bucket_conditions)
            .group_by(text('bucket'))
            .order_by(text('bucket'))
        )

        with self.db.begin_session() as session:
            res = session.execute(bucket_stmt).all()
            return [
                self._validate_row(ErrorRequestChartDataPoint, FIELD_NAMES, row_tuple)
                for row_tuple in res
            ]

    def get_request_stats_of_routes(
        self,
        project_uuid: UUID,
        route_names: list[str],
        _from: datetime | None,
        _to: datetime | None,
        tags: list[str] | None = None,
    ) -> dict[str, RequestStats]:
        """Count the requests of each route, in one query for all of them.

        A route with no request is absent from the result.
        """
        if not route_names:
            return {}
        T = self.T
        conditions = [T.c['ROUTE_NAME'].in_(route_names)]
        self._add_time_filters(project_uuid, conditions, _from, _to)
        self._add_tags_filter(conditions, tags=tags)
        stmt = (
            select(T.c['ROUTE_NAME'].label('route_name'), *self._base_columns())
            .where(*conditions)
            .group_by(T.c['ROUTE_NAME'])
            .select_from(RequestEvent)
        )
        with self.db.begin_session() as session:
            rows = session.execute(stmt).all()
        return {row.route_name: RequestStats.model_validate(row) for row in rows}

    def get_request_stats_by_route(
        self,
        project_uuid: UUID,
        route_name: str,
        _from: datetime | None,
        _to: datetime | None,
        tags: list[str] | None = None,
    ) -> RequestStats:
        stats = self.get_request_stats_of_routes(
            project_uuid, [route_name], _from, _to, tags=tags
        )
        return stats.get(route_name, RequestStats())

    def get_error_breakdown_of_routes(
        self,
        project_uuid: UUID,
        route_names: list[str],
        _from: datetime | None,
        _to: datetime | None,
        tags: list[str] | None = None,
    ) -> dict[str, list[ErrorDetail]]:
        """Count the failed requests of each route by error type, most frequent first.

        One query for all the routes; a route with no error is absent.
        """
        if not route_names:
            return {}
        T = self.T
        conditions = [
            T.c['REQUEST_STATUS'] != RequestStatus.SUCCESS,
            T.c['ROUTE_NAME'].in_(route_names),
        ]
        self._add_time_filters(project_uuid, conditions, _from, _to)
        self._add_tags_filter(conditions, tags=tags)
        stmt = (
            select(T.c['ROUTE_NAME'], T.c['ERROR_TYPE'], F.count().label('count'))
            .select_from(RequestEvent)
            .where(*conditions)
            .group_by(T.c['ROUTE_NAME'], T.c['ERROR_TYPE'])
            # ERROR_TYPE breaks ties, so equal counts always list the same way.
            .order_by(text('count DESC'), T.c['ERROR_TYPE'])
        )
        errors: dict[str, list[ErrorDetail]] = {}
        with self.db.begin_session() as session:
            rows = session.execute(stmt).all()
        for route_name, error_type, count in rows:
            errors.setdefault(route_name, []).append(
                ErrorDetail(error_type=error_type, count=count)
            )
        return errors

    def get_request_stats_global(
        self,
        project_uuid: UUID,
        _from: datetime | None,
        _to: datetime | None,
        tags: list[str] | None = None,
    ) -> RequestStats:
        conditions = []
        self._add_time_filters(project_uuid, conditions, _from, _to)
        self._add_tags_filter(conditions, tags=tags)
        stmt = select(*self._base_columns()).select_from(RequestEvent)
        if conditions:
            stmt = stmt.where(*conditions)
        with self.db.begin_session() as session:
            res = session.execute(stmt).first()
            if res is None:
                return RequestStats()
            return RequestStats.model_validate(res)

    def get_error_breakdown(
        self,
        project_uuid: UUID,
        route_name: str | None,
        _from: datetime | None,
        _to: datetime | None,
        tags: list[str] | None = None,
    ) -> list[ErrorDetail]:
        T = self.T
        FIELD_NAMES = ['error_type', 'count']

        conditions = [T.c['REQUEST_STATUS'] != RequestStatus.SUCCESS]
        self._add_time_filters(project_uuid, conditions, _from, _to, route_name)
        self._add_tags_filter(conditions, tags=tags)

        stmt = (
            select(
                T.c['ERROR_TYPE'].label('error_type'),
                F.count().label('count'),
            )
            .select_from(RequestEvent)
            .where(*conditions)
            .group_by(T.c['ERROR_TYPE'])
            # ERROR_TYPE breaks ties, so equal counts always list the same way.
            .order_by(text('count DESC'), T.c['ERROR_TYPE'])
        )

        with self.db.begin_session() as session:
            res = session.execute(stmt).all()
            return [self._validate_row(ErrorDetail, FIELD_NAMES, row) for row in res]

    def _request_columns(self) -> list:
        """Return the columns of one request, shared by the Requests list and detail."""
        T = self.T
        return [
            T.c['REQUEST_UUID'].label('request_uuid'),
            T.c['TIMESTAMP'].label('timestamp'),
            T.c['DATE'].label('date'),
            T.c['ROUTE_NAME'].label('route_name'),
            T.c['API_KEY_UUID'].label('api_key_uuid'),
            T.c['API_KEY_NAME'].label('api_key_name'),
            T.c['GROUP_UUID'].label('group_uuid'),
            T.c['GROUP_NAME'].label('group_name'),
            T.c['REQUEST_TYPE'].label('request_type'),
            T.c['REQUEST_STATUS'].label('request_status'),
            T.c['HTTP_STATUS_CODE'].label('http_status_code'),
            T.c['DURATION_MS'].label('duration_ms'),
            T.c['ERROR_TYPE'].label('error_type'),
            T.c['ERROR_CODE'].label('error_code'),
            T.c['TAGS'].label('tags'),
        ]

    def get_requests_paginated(
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
    ) -> Page[Row]:
        """One page of the project's requests, newest first."""
        T = self.T
        conditions: list = []
        self._add_time_filters(project_uuid, conditions, _from, _to)
        self._add_tags_filter(conditions, tags=tags)
        if route_names:
            conditions.append(T.c['ROUTE_NAME'].in_(route_names))
        if group_uuids:
            conditions.append(T.c['GROUP_UUID'].in_([str(g) for g in group_uuids]))
        if key_uuids:
            conditions.append(T.c['API_KEY_UUID'].in_([str(k) for k in key_uuids]))
        if request_types:
            conditions.append(T.c['REQUEST_TYPE'].in_([r.value for r in request_types]))

        # Requests per hour, newest hour first. It costs what a plain count
        # costs, gives the same total, and tells which hours hold the page.
        hour = F.toUnixTimestamp(F.toStartOfHour(T.c['TIMESTAMP']))
        hours_stmt = (
            select(hour.label('hour'), F.count().label('requests'))
            .select_from(RequestEvent)
            .where(*conditions)
            .group_by(text('hour'))
            .order_by(text('hour DESC'))
        )
        with self.db.begin_session() as session:
            rows = session.execute(hours_stmt).all()
        hours = [tuple(row) for row in rows]
        total = sum(requests for _, requests in hours)
        window = page_window(hours, (params.page - 1) * params.size, params.size)
        if window is None:
            return Page.create([], params, total=total)

        # The page is read from its own hours only: without the bound,
        # ClickHouse sorts every matching request to return fifty of them.
        stmt = (
            select(*self._request_columns())
            .select_from(RequestEvent)
            .where(
                *conditions,
                T.c['TIMESTAMP'] >= datetime.fromtimestamp(window.oldest, UTC),
                T.c['TIMESTAMP']
                < datetime.fromtimestamp(window.newest, UTC) + _PAGE_BUCKET,
            )
            # REQUEST_UUID breaks ties so pages never overlap.
            .order_by(T.c['TIMESTAMP'].desc(), T.c['REQUEST_UUID'].desc())
            .limit(params.size)
            .offset(window.offset)
        )
        with self.db.begin_session() as session:
            rows = session.execute(stmt).all()
        return Page.create(rows, params, total=total)

    def get_http_status_by_request_uuids(
        self,
        request_uuids: list[str],
    ) -> dict[str, int]:
        if not request_uuids:
            return {}

        T = self.T
        stmt = (
            select(
                T.c['REQUEST_UUID'].label('request_uuid'),
                T.c['HTTP_STATUS_CODE'].label('http_status_code'),
            )
            .select_from(RequestEvent)
            .where(T.c['REQUEST_UUID'].in_(request_uuids))
        )

        with self.db.begin_session() as session:
            res = session.execute(stmt).all()
            return {str(row.request_uuid): row.http_status_code for row in res}

    def get_request(self, project_uuid: UUID, request_uuid: UUID) -> Row | None:
        """One request of the project by its UUID, or None if there is none."""
        T = self.T
        stmt = (
            select(
                *self._request_columns(),
                T.c['IS_STREAMING'].label('is_streaming'),
            )
            .select_from(RequestEvent)
            .where(
                T.c['PROJECT_UUID'] == str(project_uuid),
                T.c['REQUEST_UUID'] == str(request_uuid),
            )
            .limit(1)
        )

        with self.db.begin_session() as session:
            return session.execute(stmt).first()

    def get_distinct_tags(self, project_uuid: UUID) -> list[str]:
        T = self.T
        tag = F.arrayJoin(T.c['TAGS'])
        stmt = (
            select(F.distinct(tag))
            .select_from(RequestEvent)
            .where(T.c['PROJECT_UUID'] == str(project_uuid))
        )
        with self.db.begin_session() as session:
            return sorted(row[0] for row in session.execute(stmt).fetchall())

    def get_distinct_tag_values(self, project_uuid: UUID, tag_key: str) -> list[str]:
        T = self.T
        prefix = f'{tag_key}='
        tags_sq = (
            select(F.arrayJoin(T.c['TAGS']).label('tag'))
            .select_from(RequestEvent)
            .where(T.c['PROJECT_UUID'] == str(project_uuid))
            .subquery()
        )
        tag = tags_sq.c['tag']
        stmt = select(F.distinct(F.substring(tag, F.length(prefix) + 1))).where(
            F.startsWith(tag, prefix)
        )
        with self.db.begin_session() as session:
            return sorted(row[0] for row in session.execute(stmt).fetchall())
