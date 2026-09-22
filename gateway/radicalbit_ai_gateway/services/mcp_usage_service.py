import contextlib
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi_pagination import Page, Params

from radicalbit_ai_gateway.db.dao.event_dao import EventDAO
from radicalbit_ai_gateway.models.mcp_usage_dto import (
    McpKeyUsageDTO,
    McpServerChartDataDTO,
    McpServerChartDataSeriesDTO,
)
from radicalbit_ai_gateway.services.group_service import GroupService
from radicalbit_ai_gateway.services.key_service import KeyService
from radicalbit_ai_gateway.utils.chart_utils import (
    determine_granularity,
    generate_chart_timestamps,
    prepare_chart_time_range,
)


class McpUsageService:
    """MCP usage views on the Usage page, read from MCP invocation events."""

    def __init__(
        self,
        event_dao: EventDAO,
        key_service: KeyService,
        group_service: GroupService,
    ):
        self.event_dao = event_dao
        self.key_service = key_service
        self.group_service = group_service

    def get_mcp_key_usage(
        self,
        project_uuid: UUID,
        route_names: list[str] | None,
        _from: datetime | None,
        _to: datetime | None,
        params: Params,
        tags: list[str] | None = None,
    ) -> Page[McpKeyUsageDTO]:
        page = self.event_dao.get_mcp_key_usage_paginated(
            project_uuid=project_uuid,
            route_names=route_names,
            _from=_from,
            _to=_to,
            params=params,
            tags=tags,
        )
        items = [
            McpKeyUsageDTO(
                key_name=row.key_name,
                key_uuid=row.key_uuid,
                group_name=row.group_name,
                group_uuid=row.group_uuid,
                counter=row.counter,
                last_call=int(row.last_call.timestamp()),
            )
            for row in page.items
        ]
        return Page.create(items, params, total=page.total)

    def get_mcp_server_chart_data(
        self,
        project_uuid: UUID,
        route_names: list[str] | None,
        _from: datetime | None,
        _to: datetime | None,
        group_by: Literal['services', 'groups', 'keys'] = 'services',
        tags: list[str] | None = None,
    ) -> McpServerChartDataDTO:
        """MCP invocations over time, one series per entity in the grouping.

        The granularity follows the requested range, so an hour and a year
        both read well without the caller picking one.
        """
        _from_utc, _to_utc, timezone_offset_seconds = prepare_chart_time_range(
            _from, _to
        )
        granularity = determine_granularity(_from, _to)
        chart_data_points = self.event_dao.get_mcp_server_chart_data(
            project_uuid=project_uuid,
            route_names=route_names,
            _from=_from_utc,
            _to=_to_utc,
            granularity=granularity,
            group_by=group_by,
            timezone_offset_seconds=timezone_offset_seconds,
            tags=tags,
        )
        if not chart_data_points:
            return McpServerChartDataDTO(
                granularity=granularity,
                timestamp=[],
                data=[],
                total=0,
            )

        _to_utc = _to_utc or datetime.now(timezone.utc)
        _from_utc = _from_utc or datetime.fromtimestamp(
            chart_data_points[0].timestamp, timezone.utc
        )
        all_timestamps = generate_chart_timestamps(
            _from_utc, _to_utc, granularity, timezone_offset_seconds
        )

        # Keyed by the raw grouping value, never by the display name. Two
        # groups can carry the same name, and merging them here would hide
        # one of them and break the drill-in link.
        series_data: dict[str, dict[int, int]] = {}
        for point in chart_data_points:
            series_data.setdefault(point.group_by_value, {})[point.timestamp] = (
                point.value
            )

        names = self._resolve_names(list(series_data), group_by)

        series_list = sorted(
            (
                McpServerChartDataSeriesDTO(
                    name=names[value][0],
                    uuid=names[value][1],
                    data=[series_data[value].get(ts, 0) for ts in all_timestamps],
                )
                for value in series_data
            ),
            key=lambda series: (series.name, str(series.uuid or '')),
        )

        return McpServerChartDataDTO(
            granularity=granularity,
            timestamp=all_timestamps,
            data=series_list,
            total=sum(point.value for point in chart_data_points),
        )

    def _resolve_names(
        self,
        group_by_values: list[str],
        group_by: Literal['services', 'groups', 'keys'],
    ) -> dict[str, tuple[str, UUID | None]]:
        """Map each raw grouping value to its display name and uuid.

        Grouping by services needs no lookup: the alias is both the name and
        the identifier, and an empty alias stays an empty name so the caller
        can label the unresolved series itself.
        """
        if group_by == 'services':
            return {value: (value, None) for value in group_by_values}

        # TODO: Implement soft delete for keys/groups in Postgres (deleted_at column)
        # so that deleted keys still have resolvable names, removing the need for this fallback.
        uuid_str_to_obj: dict[str, UUID] = {}
        for value in group_by_values:
            with contextlib.suppress(ValueError):
                uuid_str_to_obj[value] = UUID(value)
        unique_ids = list(uuid_str_to_obj.values())
        names_map = (
            self.key_service.get_names_by_uuids(unique_ids)
            if group_by == 'keys'
            else self.group_service.get_names_by_uuids(unique_ids)
        )
        entity_label = 'Key' if group_by == 'keys' else 'Group'

        resolved: dict[str, tuple[str, UUID | None]] = {}
        for value in group_by_values:
            uuid_obj = uuid_str_to_obj.get(value)
            if uuid_obj is None:
                resolved[value] = (value, None)
                continue
            resolved[value] = (
                names_map.get(uuid_obj, f'Deleted {entity_label} ({value[:8]})'),
                uuid_obj,
            )
        return resolved
