from datetime import datetime, timezone
from typing import Annotated, Union
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi_pagination import Page, Params

from radicalbit_ai_gateway.models.trace_dto import (
    GroupedSpanLatenciesDTO,
    LatenciesDTO,
    SpanDTO,
    SpanLatenciesDTO,
    TraceDTO,
    TracesChartDataDTO,
)
from radicalbit_ai_gateway.services.project_service import ProjectService
from radicalbit_ai_gateway.services.tracing_service import TracingService
from radicalbit_ai_gateway.utils.chart_utils import determine_granularity


class TracingRoute:
    @staticmethod
    def get_tracing_router(
        tracing_service: TracingService,
        project_service: ProjectService,
    ) -> APIRouter:
        router = APIRouter(tags=['tracing_api'])

        @router.get(
            '/projects/{project_uuid}/traces/chart',
            status_code=200,
            response_model=TracesChartDataDTO,
            response_model_exclude_none=True,
        )
        def get_traces_chart_data(
            project_uuid: UUID,
            _from: Annotated[int | None, Query()] = None,
            _to: Annotated[int | None, Query()] = None,
            routes: Annotated[list[str] | None, Query()] = None,
        ):
            project_service.validate_exists(project_uuid)
            from_dt = datetime.fromtimestamp(_from, timezone.utc) if _from else None
            to_dt = datetime.fromtimestamp(_to, timezone.utc) if _to else None
            granularity = determine_granularity(from_dt, to_dt)
            return tracing_service.get_traces_chart_data(
                project_uuid=project_uuid,
                route_names=routes,
                _from=from_dt,
                _to=to_dt,
                granularity=granularity,
            )

        @router.get(
            '/projects/{project_uuid}/traces/latencies',
            status_code=200,
            response_model=LatenciesDTO,
            response_model_exclude_none=True,
        )
        def get_latencies(
            project_uuid: UUID,
            _from: Annotated[int | None, Query()] = None,
            _to: Annotated[int | None, Query()] = None,
            routes: Annotated[list[str] | None, Query()] = None,
        ):
            project_service.validate_exists(project_uuid)
            from_dt = datetime.fromtimestamp(_from, timezone.utc) if _from else None
            to_dt = datetime.fromtimestamp(_to, timezone.utc) if _to else None
            return tracing_service.get_latencies(
                project_uuid=project_uuid,
                route_names=routes,
                _from=from_dt,
                _to=to_dt,
            )

        @router.get(
            '/projects/{project_uuid}/traces/spans/latencies',
            status_code=200,
            response_model=Union[SpanLatenciesDTO, GroupedSpanLatenciesDTO],
            response_model_exclude_none=True,
        )
        def get_span_latencies(
            project_uuid: UUID,
            _from: Annotated[int | None, Query()] = None,
            _to: Annotated[int | None, Query()] = None,
            routes: Annotated[list[str] | None, Query()] = None,
            grouped: Annotated[bool, Query()] = False,
            include_others: Annotated[bool, Query()] = False,
        ):
            project_service.validate_exists(project_uuid)
            from_dt = datetime.fromtimestamp(_from, timezone.utc) if _from else None
            to_dt = datetime.fromtimestamp(_to, timezone.utc) if _to else None
            if grouped:
                return tracing_service.get_grouped_span_latencies(
                    project_uuid=project_uuid,
                    route_names=routes,
                    _from=from_dt,
                    _to=to_dt,
                    include_others=include_others,
                )
            return tracing_service.get_span_latencies(
                project_uuid=project_uuid,
                route_names=routes,
                _from=from_dt,
                _to=to_dt,
            )

        @router.get(
            '/projects/{project_uuid}/traces',
            status_code=200,
            response_model=Page[TraceDTO],
            response_model_exclude_none=True,
        )
        def get_traces(
            project_uuid: UUID,
            _from: Annotated[int | None, Query()] = None,
            _to: Annotated[int | None, Query()] = None,
            routes: Annotated[list[str] | None, Query()] = None,
            groups: Annotated[list[UUID] | None, Query()] = None,
            keys: Annotated[list[UUID] | None, Query()] = None,
            _page: Annotated[int, Query(ge=1)] = 1,
            _limit: Annotated[int, Query(ge=1, le=100)] = 50,
        ):
            project_service.validate_exists(project_uuid)
            from_dt = datetime.fromtimestamp(_from, timezone.utc) if _from else None
            to_dt = datetime.fromtimestamp(_to, timezone.utc) if _to else None
            params = Params(page=_page, size=_limit)
            return tracing_service.get_traces(
                project_uuid=project_uuid,
                route_names=routes,
                group_uuids=groups,
                key_uuids=keys,
                _from=from_dt,
                _to=to_dt,
                params=params,
            )

        @router.get(
            '/projects/{project_uuid}/traces/{trace_id}/spans/{span_id}',
            status_code=200,
            response_model=SpanDTO,
            response_model_exclude_none=True,
        )
        def get_span_by_id(project_uuid: UUID, trace_id: str, span_id: str):
            project_service.validate_exists(project_uuid)
            return tracing_service.get_span_by_id(
                project_uuid=project_uuid, trace_id=trace_id, span_id=span_id
            )

        @router.get(
            '/projects/{project_uuid}/traces/{trace_id}',
            status_code=200,
            response_model=TraceDTO,
            response_model_exclude_none=True,
        )
        def get_trace_by_id(project_uuid: UUID, trace_id: str):
            project_service.validate_exists(project_uuid)
            return tracing_service.get_trace_by_id(
                project_uuid=project_uuid, trace_id=trace_id
            )

        return router
