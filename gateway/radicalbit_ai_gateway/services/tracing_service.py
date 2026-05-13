from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi_pagination import Page, Params

from radicalbit_ai_gateway.db.dao.otel_traces_dao import OtelTracesDAO
from radicalbit_ai_gateway.models.trace_dto import (
    ErrorEvents,
    GroupedSpanLatenciesDTO,
    GroupedSpanLatencyDTO,
    LatenciesDTO,
    SpanDTO,
    SpanLatenciesDTO,
    SpanLatencyDTO,
    TraceDTO,
    TracesChartDataDTO,
    TracesChartDataSeriesDTO,
    TraceStatus,
    TreeNodeDTO,
)
from radicalbit_ai_gateway.services.group_service import GroupService
from radicalbit_ai_gateway.services.key_service import KeyService
from radicalbit_ai_gateway.utils import NS_TO_MS
from radicalbit_ai_gateway.utils.chart_utils import (
    generate_chart_timestamps,
    prepare_chart_time_range,
)
from radicalbit_ai_gateway.utils.exceptions import GatewayNotFoundError


def _safe_parse_int(value: str | None) -> int:
    """Safely parse string to int, returning 0 if value is None or empty."""
    return int(value) if value else 0


def _parse_uuid(value: str | None) -> UUID | None:
    """Parse a string UUID to UUID or None."""
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _compute_trace_status(root_has_error: bool, total_error_count: int) -> TraceStatus:
    """Compute trace status based on span errors only.

    Logic:
    - Root span error → ERROR
    - Child span errors only → WARNING
    - No errors → SUCCESS
    """
    if root_has_error:
        return TraceStatus.ERROR
    if total_error_count > 0:
        return TraceStatus.WARNING
    return TraceStatus.SUCCESS


class TracingService:
    def __init__(
        self,
        otel_traces_dao: OtelTracesDAO,
        key_service: KeyService,
        group_service: GroupService,
    ):
        self.otel_traces_dao = otel_traces_dao
        self.key_service = key_service
        self.group_service = group_service

    def get_traces_chart_data(
        self,
        project_uuid: UUID,
        route_names: list[str] | None,
        _from: datetime | None,
        _to: datetime | None,
        granularity: Literal['hours', 'days', 'weeks', 'months'],
    ) -> TracesChartDataDTO:
        _from_utc, _to_utc, timezone_offset_seconds = prepare_chart_time_range(
            _from, _to
        )

        points = self.otel_traces_dao.get_traces_chart_data(
            project_uuid,
            route_names,
            _from_utc,
            _to_utc,
            granularity,
            timezone_offset_seconds,
        )
        if not points:
            return TracesChartDataDTO(
                granularity=granularity, timestamp=[], data=[], total=0
            )

        _to_utc = _to_utc or datetime.now(timezone.utc)
        _from_utc = _from_utc or datetime.fromtimestamp(
            points[0].timestamp, timezone.utc
        )

        all_timestamps = generate_chart_timestamps(
            _from_utc, _to_utc, granularity, timezone_offset_seconds
        )

        # Accumulate per-status counts keyed by timestamp
        status_order = [
            TraceStatus.SUCCESS.value,
            TraceStatus.WARNING.value,
            TraceStatus.ERROR.value,
        ]
        series_data: dict[str, dict[int, int]] = {s: {} for s in status_order}
        for point in points:
            status = point.trace_status
            if status in series_data:
                series_data[status][point.timestamp] = (
                    series_data[status].get(point.timestamp, 0) + point.total_requests
                )

        total = sum(point.total_requests for point in points)
        return TracesChartDataDTO(
            granularity=granularity,
            timestamp=all_timestamps,
            data=[
                TracesChartDataSeriesDTO(
                    name=status,
                    data=[series_data[status].get(ts, 0) for ts in all_timestamps],
                )
                for status in status_order
            ],
            total=total,
        )

    def get_latencies(
        self,
        project_uuid: UUID,
        route_names: list[str] | None,
        _from: datetime | None,
        _to: datetime | None,
    ) -> LatenciesDTO:
        result = self.otel_traces_dao.get_latencies(
            project_uuid, route_names, _from, _to
        )
        return LatenciesDTO(
            p50=result.p50, p90=result.p90, p95=result.p95, p99=result.p99
        )

    def get_span_latencies(
        self,
        project_uuid: UUID,
        route_names: list[str] | None,
        _from: datetime | None,
        _to: datetime | None,
    ) -> SpanLatenciesDTO:
        results = self.otel_traces_dao.get_span_latencies(
            project_uuid, route_names, _from, _to
        )
        return SpanLatenciesDTO(
            data=[
                SpanLatencyDTO(
                    span_name=r.span_name,
                    p50=r.p50,
                    p90=r.p90,
                    p95=r.p95,
                    p99=r.p99,
                )
                for r in results
            ]
        )

    def get_grouped_span_latencies(
        self,
        project_uuid: UUID,
        route_names: list[str] | None,
        _from: datetime | None,
        _to: datetime | None,
        include_others: bool = False,
    ) -> GroupedSpanLatenciesDTO:
        category_results = self.otel_traces_dao.get_category_latencies(
            project_uuid, route_names, _from, _to, include_others
        )
        span_results = self.otel_traces_dao.get_category_span_latencies(
            project_uuid, route_names, _from, _to, include_others
        )

        spans_by_category: dict[str, list[SpanLatencyDTO]] = {}
        for r in span_results:
            spans_by_category.setdefault(r.category, []).append(
                SpanLatencyDTO(
                    span_name=r.span_name,
                    p50=r.p50,
                    p90=r.p90,
                    p95=r.p95,
                    p99=r.p99,
                )
            )

        return GroupedSpanLatenciesDTO(
            data=[
                GroupedSpanLatencyDTO(
                    category=cat.category,
                    p50=cat.p50,
                    p90=cat.p90,
                    p95=cat.p95,
                    p99=cat.p99,
                    spans=spans_by_category.get(cat.category, []),
                )
                for cat in category_results
            ]
        )

    def get_trace_by_id(self, project_uuid: UUID, trace_id: str) -> TraceDTO:
        spans = self.otel_traces_dao.get_spans_by_trace_id(project_uuid, trace_id)
        if not spans:
            raise GatewayNotFoundError(f"Trace '{trace_id}' not found")

        children_map: dict[str, list] = {}
        root_span = None
        total_duration = 0  # Spans always have positive duration
        error_count = 0
        output_tokens = 0
        input_tokens = 0
        total_tokens = 0
        latest_timestamp = spans[0].timestamp

        for span in spans:
            # Build parent-child relationships
            parent_span_id = span.parent_span_id or None
            if not parent_span_id:
                root_span = span
            else:
                children_map.setdefault(parent_span_id, []).append(span)

            # Aggregate metrics
            total_duration = max(total_duration, span.duration)
            if span.status_code.upper() == 'ERROR':
                error_count += 1
            output_tokens += _safe_parse_int(span.output_tokens)
            input_tokens += _safe_parse_int(span.input_tokens)
            total_tokens += _safe_parse_int(span.total_tokens)
            latest_timestamp = max(latest_timestamp, span.timestamp)

        if root_span is None:
            root_span = spans[0]

        def build_tree(span) -> TreeNodeDTO:
            children = children_map.get(span.span_id, [])
            output = _safe_parse_int(span.output_tokens)
            input_tokens = _safe_parse_int(span.input_tokens)
            total = _safe_parse_int(span.total_tokens)
            number_of_errors = 1 if span.status_code.upper() == 'ERROR' else 0

            return TreeNodeDTO(
                span_id=span.span_id,
                span_name=span.span_name,
                duration_ms=span.duration / NS_TO_MS,
                status_code=span.status_code,
                output_tokens=output,
                input_tokens=input_tokens,
                total_tokens=total,
                error_count=number_of_errors,
                created_at=int(span.timestamp.timestamp()),
                children=[build_tree(child) for child in children],
            )

        tree = build_tree(root_span)

        root_has_error = root_span.status_code.upper() == 'ERROR'
        trace_status = _compute_trace_status(root_has_error, error_count)

        resolved_key_uuid = _parse_uuid(root_span.api_key_uuid)
        resolved_group_uuid = _parse_uuid(root_span.group_uuid)
        # TODO: Implement soft delete for keys/groups in Postgres (deleted_at column)
        # so that deleted keys still have resolvable names, removing the need for this fallback.
        key_name = None
        group_name = None
        if resolved_key_uuid:
            key_names = self.key_service.get_names_by_uuids([resolved_key_uuid])
            key_name = key_names.get(
                resolved_key_uuid,
                f'Deleted Key ({str(resolved_key_uuid)[:8]})',
            )
        if resolved_group_uuid:
            group_names = self.group_service.get_names_by_uuids([resolved_group_uuid])
            group_name = group_names.get(
                resolved_group_uuid,
                f'Deleted Group ({str(resolved_group_uuid)[:8]})',
            )

        return TraceDTO(
            trace_id=root_span.trace_id,
            request_uuid=_parse_uuid(root_span.request_uuid),
            root_span_id=root_span.span_id,
            total_spans=len(spans),
            duration_ms=total_duration / NS_TO_MS,
            error_count=error_count,
            trace_status=trace_status,
            created_at=int(root_span.timestamp.timestamp()),
            latest_span_ts=int(latest_timestamp.timestamp()),
            output_tokens=output_tokens,
            input_tokens=input_tokens,
            total_tokens=total_tokens,
            route_name=root_span.route_name or None,
            api_key_uuid=resolved_key_uuid,
            api_key_name=key_name,
            group_uuid=resolved_group_uuid,
            group_name=group_name,
            tree=tree,
        )

    def get_traces(
        self,
        project_uuid: UUID,
        route_names: list[str] | None,
        group_uuids: list[UUID] | None,
        key_uuids: list[UUID] | None,
        _from: datetime | None,
        _to: datetime | None,
        params: Params,
    ) -> Page[TraceDTO]:
        # Get paginated traces - paginate() handles count query automatically
        traces_page = self.otel_traces_dao.get_root_traces_paginated(
            project_uuid, route_names, group_uuids, key_uuids, _from, _to, params
        )

        if not traces_page.items:
            return Page.create([], params, total=traces_page.total)

        # Enrich with span stats
        trace_ids = [row.trace_id for row in traces_page.items]
        spans_stats = self.otel_traces_dao.get_spans_stats_by_trace_ids(trace_ids)
        root_error_trace_ids = self.otel_traces_dao.get_root_span_error_by_trace_ids(
            trace_ids
        )

        # TODO: Implement soft delete for keys/groups in Postgres (deleted_at column)
        # so that deleted keys still have resolvable names, removing the need for this fallback.
        key_uuids = [u for r in traces_page.items if (u := _parse_uuid(r.api_key_uuid))]
        group_uuids = [u for r in traces_page.items if (u := _parse_uuid(r.group_uuid))]
        key_names = self.key_service.get_names_by_uuids(key_uuids) if key_uuids else {}
        group_names = (
            self.group_service.get_names_by_uuids(group_uuids) if group_uuids else {}
        )

        # Transform rows to TraceDTO
        items = []
        for row in traces_page.items:
            trace_id = row.trace_id
            stats = spans_stats.get(trace_id)
            error_count = stats.error_count if stats else 0
            input_tokens = stats.input_tokens if stats else 0
            output_tokens = stats.output_tokens if stats else 0
            last_span = stats.last_span if stats else None

            root_has_error = trace_id in root_error_trace_ids
            trace_status = _compute_trace_status(root_has_error, error_count)

            resolved_key_uuid = _parse_uuid(row.api_key_uuid)
            resolved_group_uuid = _parse_uuid(row.group_uuid)

            items.append(
                TraceDTO(
                    trace_id=trace_id,
                    request_uuid=row.request_uuid if row.request_uuid else None,
                    route_name=row.route_name or None,
                    api_key_uuid=resolved_key_uuid,
                    api_key_name=key_names.get(
                        resolved_key_uuid, f'Deleted Key ({str(resolved_key_uuid)[:8]})'
                    )
                    if resolved_key_uuid
                    else None,
                    group_uuid=resolved_group_uuid,
                    group_name=group_names.get(
                        resolved_group_uuid,
                        f'Deleted Group ({str(resolved_group_uuid)[:8]})',
                    )
                    if resolved_group_uuid
                    else None,
                    duration_ms=row.duration_ms,
                    total_spans=stats.span_count if stats else 0,
                    error_count=error_count,
                    trace_status=trace_status,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=input_tokens + output_tokens,
                    created_at=int(row.created_at.timestamp()),
                    latest_span_ts=int(last_span.timestamp())
                    if last_span
                    else int(row.created_at.timestamp()),
                )
            )

        return Page.create(items, params, total=traces_page.total)

    def get_span_by_id(
        self, project_uuid: UUID, trace_id: str, span_id: str
    ) -> SpanDTO:
        span = self.otel_traces_dao.get_span_by_trace_and_span_id(
            project_uuid, trace_id, span_id
        )
        if not span:
            raise GatewayNotFoundError(
                f"Span '{span_id}' not found in trace '{trace_id}'"
            )

        # Parse UUIDs
        request_uuid = _parse_uuid(span.request_uuid) if span.request_uuid else None
        api_key_uuid = _parse_uuid(span.api_key_uuid)
        group_uuid = _parse_uuid(span.group_uuid)

        # Convert events (DB only stores error events, no filtering needed)
        error_events = [
            ErrorEvents(
                timestamp=event.get('timestamp'),
                name=event.get('name'),
                attributes=event.get('attributes'),
            )
            for event in span.events
        ]

        # Parse tokens
        output_tokens = _safe_parse_int(span.output_tokens)
        input_tokens = _safe_parse_int(span.input_tokens)
        total_tokens = _safe_parse_int(span.total_tokens)

        # TODO: Implement soft delete for keys/groups in Postgres (deleted_at column)
        # so that deleted keys still have resolvable names, removing the need for this fallback.
        resolved_key_name = None
        resolved_group_name = None
        if api_key_uuid:
            key_names = self.key_service.get_names_by_uuids([api_key_uuid])
            resolved_key_name = key_names.get(
                api_key_uuid,
                f'Deleted Key ({str(api_key_uuid)[:8]})',
            )
        if group_uuid:
            group_names = self.group_service.get_names_by_uuids([group_uuid])
            resolved_group_name = group_names.get(
                group_uuid,
                f'Deleted Group ({str(group_uuid)[:8]})',
            )

        return SpanDTO(
            trace_id=span.trace_id,
            span_id=span.span_id,
            span_name=span.span_name,
            request_uuid=request_uuid,
            duration_ms=span.duration / NS_TO_MS,
            created_at=int(span.timestamp.timestamp()),
            output_tokens=output_tokens,
            input_tokens=input_tokens,
            total_tokens=total_tokens,
            route_name=span.route_name or None,
            api_key_uuid=api_key_uuid,
            api_key_name=resolved_key_name,
            group_uuid=group_uuid,
            group_name=resolved_group_name,
            attributes=span.span_attributes or {},
            status_message=span.status_message,
            error_count=len(error_events),
            error_events=error_events,
        )
