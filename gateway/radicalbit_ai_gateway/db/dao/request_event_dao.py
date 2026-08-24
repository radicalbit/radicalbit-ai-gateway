from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import Float, func as F, select, text

from radicalbit_ai_gateway.db.clickhouse_database import ClickHouseDatabase
from radicalbit_ai_gateway.db.models.event import (
    ErrorDetail,
    ErrorRequestChartDataPoint,
    ErrorRoute,
    RequestChartDataPoint,
    RequestGroupedChartDataPoint,
    RequestStats,
)
from radicalbit_ai_gateway.db.tables.request_event_table import RequestEvent
from radicalbit_ai_gateway.models.request_event_type import RequestStatus
from radicalbit_ai_gateway.utils.chart_utils import (
    get_bucket_function,
    with_timezone_offset,
)


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
    ) -> str | None:
        if not configured_routes:
            return None
        T = self.T
        conditions = [T.c['ROUTE_NAME'].in_(configured_routes)]
        self._add_time_filters(project_uuid, conditions, _from, _to)

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
    ) -> ErrorRoute | None:
        if not configured_routes:
            return None
        T = self.T
        FIELD_NAMES = ['route_name', 'error_perc']
        conditions = [T.c['ROUTE_NAME'].in_(configured_routes)]
        self._add_time_filters(project_uuid, conditions, _from, _to)
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

    def get_request_stats_by_route(
        self,
        project_uuid: UUID,
        route_name: str,
        _from: datetime | None,
        _to: datetime | None,
    ) -> RequestStats:
        T = self.T
        conditions = [T.c['ROUTE_NAME'] == route_name]
        self._add_time_filters(project_uuid, conditions, _from, _to)
        stmt = (
            select(*self._base_columns()).where(*conditions).select_from(RequestEvent)
        )
        with self.db.begin_session() as session:
            res = session.execute(stmt).first()
            if res is None:
                return RequestStats()
            return RequestStats.model_validate(res)

    def get_request_stats_global(
        self,
        project_uuid: UUID,
        _from: datetime | None,
        _to: datetime | None,
    ) -> RequestStats:
        conditions = []
        self._add_time_filters(project_uuid, conditions, _from, _to)
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
    ) -> list[ErrorDetail]:
        T = self.T
        FIELD_NAMES = ['error_type', 'count']

        conditions = [T.c['REQUEST_STATUS'] != RequestStatus.SUCCESS]
        self._add_time_filters(project_uuid, conditions, _from, _to, route_name)

        stmt = (
            select(
                T.c['ERROR_TYPE'].label('error_type'),
                F.count().label('count'),
            )
            .select_from(RequestEvent)
            .where(*conditions)
            .group_by(T.c['ERROR_TYPE'])
            .order_by(text('count DESC'))
        )

        with self.db.begin_session() as session:
            res = session.execute(stmt).all()
            return [self._validate_row(ErrorDetail, FIELD_NAMES, row) for row in res]

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
