from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from radicalbit_ai_gateway.db.dao.request_event_dao import RequestEventDAO
from radicalbit_ai_gateway.models.event_dto import (
    ChartDataSeriesDTO,
    MostRequestedErrorRouteDTO,
    MostRequestedRouteDTO,
    RequestChartDataDTO,
    RequestGroupedChartDataDTO,
)
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.tag_dto import TagKeysDTO
from radicalbit_ai_gateway.utils.chart_utils import (
    calculate_increment_percentage,
    determine_granularity,
    generate_chart_timestamps,
    prepare_chart_time_range,
)


class RequestEventService:
    def __init__(self, request_event_dao: RequestEventDAO):
        self.request_event_dao = request_event_dao

    def get_tag_keys(self, project_uuid: UUID) -> TagKeysDTO:
        tags = self.request_event_dao.get_distinct_tags(project_uuid)
        tag_keys = sorted({tag.split('=', 1)[0] for tag in tags})
        return TagKeysDTO(tag_keys=tag_keys)

    def get_request_chart_data(
        self,
        project_uuid: UUID,
        route_name: str,
        _from: datetime | None,
        _to: datetime | None,
        granularity: Literal['hours', 'days', 'weeks', 'months'],
    ) -> RequestChartDataDTO:
        _from_utc, _to_utc, timezone_offset_seconds = prepare_chart_time_range(
            _from, _to
        )

        request_chart_data_points = self.request_event_dao.get_request_chart_data(
            project_uuid,
            route_name,
            _from_utc,
            _to_utc,
            granularity,
            timezone_offset_seconds,
        )
        if not request_chart_data_points:
            return RequestChartDataDTO(
                total=0,
                granularity=granularity,
                timestamp=[],
                data=[],
            )

        _to_utc = _to_utc or datetime.now(timezone.utc)
        _from_utc = _from_utc or datetime.fromtimestamp(
            request_chart_data_points[0].timestamp, timezone.utc
        )

        all_timestamps = generate_chart_timestamps(
            _from_utc, _to_utc, granularity, timezone_offset_seconds
        )

        bucket_data: dict[int, int] = {}
        total_requests = 0
        for point in request_chart_data_points:
            bucket_data[point.timestamp] = point.total_requests
            total_requests += point.total_requests

        data = [bucket_data.get(ts, 0) for ts in all_timestamps]

        return RequestChartDataDTO(
            total=total_requests,
            granularity=granularity,
            timestamp=all_timestamps,
            data=data,
        )

    def get_request_grouped_chart_data(
        self,
        project_uuid: UUID,
        route_name: str,
        _from: datetime | None,
        _to: datetime | None,
        granularity: Literal['hours', 'days', 'weeks', 'months'],
    ) -> RequestGroupedChartDataDTO:
        _from_utc, _to_utc, timezone_offset_seconds = prepare_chart_time_range(
            _from, _to
        )

        data_points = self.request_event_dao.get_request_chart_data_grouped(
            project_uuid,
            route_name,
            _from_utc,
            _to_utc,
            granularity,
            timezone_offset_seconds,
        )
        if not data_points:
            return RequestGroupedChartDataDTO(
                total=0,
                granularity=granularity,
                timestamp=[],
                data=[],
            )

        _to_utc = _to_utc or datetime.now(timezone.utc)
        _from_utc = _from_utc or datetime.fromtimestamp(
            data_points[0].timestamp, timezone.utc
        )

        all_timestamps = generate_chart_timestamps(
            _from_utc, _to_utc, granularity, timezone_offset_seconds
        )

        success_map: dict[int, int] = {}
        error_map: dict[int, int] = {}
        total = 0
        for point in data_points:
            success_map[point.timestamp] = point.success_count
            error_map[point.timestamp] = point.error_count
            total += point.success_count + point.error_count

        success_data = [float(success_map.get(ts, 0)) for ts in all_timestamps]
        error_data = [float(error_map.get(ts, 0)) for ts in all_timestamps]

        return RequestGroupedChartDataDTO(
            total=total,
            granularity=granularity,
            timestamp=all_timestamps,
            data=[
                ChartDataSeriesDTO(name='success', data=success_data),
                ChartDataSeriesDTO(name='error', data=error_data),
            ],
        )

    def get_most_requested_route(
        self,
        project_uuid: UUID,
        config: GatewayConfig,
        _from: datetime | None,
        _to: datetime | None,
    ) -> MostRequestedRouteDTO | None:
        configured_routes = list(config.routes.keys())

        route_name = self.request_event_dao.get_most_requested_route(
            project_uuid, configured_routes, _from, _to
        )
        if route_name is None:
            return None

        granularity = determine_granularity(_from, _to)
        chart_data = self.get_request_chart_data(
            project_uuid, route_name, _from, _to, granularity
        )
        increment_percentage = calculate_increment_percentage(chart_data.data)

        return MostRequestedRouteDTO(
            name=route_name,
            increment_percentage=increment_percentage,
            chart=chart_data,
        )

    def get_most_requested_error_route(
        self,
        project_uuid: UUID,
        config: GatewayConfig,
        _from: datetime | None,
        _to: datetime | None,
    ) -> MostRequestedErrorRouteDTO | None:
        configured_routes = list(config.routes.keys())

        error_route = self.request_event_dao.get_most_route_with_error(
            project_uuid, configured_routes, _from=_from, _to=_to
        )
        if error_route is None:
            return None

        _from_utc, _to_utc, timezone_offset_seconds = prepare_chart_time_range(
            _from, _to
        )
        granularity = determine_granularity(_from, _to)

        error_chart_data_points = self.request_event_dao.get_request_error_chart_data(
            project_uuid,
            error_route.route_name,
            granularity,
            _from_utc,
            _to_utc,
            timezone_offset_seconds,
        )

        if not error_chart_data_points:
            return MostRequestedErrorRouteDTO(
                name=error_route.route_name,
                increment_percentage=0.0,
                chart=RequestChartDataDTO(
                    total=0.0,
                    granularity=granularity,
                    timestamp=[],
                    data=[],
                ),
            )

        _to_utc = _to_utc or datetime.now(timezone.utc)
        _from_utc = _from_utc or datetime.fromtimestamp(
            error_chart_data_points[0].timestamp, timezone.utc
        )

        all_timestamps = generate_chart_timestamps(
            _from_utc, _to_utc, granularity, timezone_offset_seconds
        )

        bucket_data: dict[int, int] = {}
        for point in error_chart_data_points:
            bucket_data[point.timestamp] = point.total_requests

        data = [bucket_data.get(ts, 0) for ts in all_timestamps]
        increment_percentage = calculate_increment_percentage(data)

        chart = RequestChartDataDTO(
            total=error_route.error_perc,
            granularity=granularity,
            timestamp=all_timestamps,
            data=data,
        )

        return MostRequestedErrorRouteDTO(
            name=error_route.route_name,
            increment_percentage=increment_percentage,
            chart=chart,
        )
