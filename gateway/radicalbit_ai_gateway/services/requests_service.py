from datetime import date, datetime, timedelta
from uuid import UUID

from fastapi_pagination import Page, Params

from radicalbit_ai_gateway.db.dao.event_dao import EventDAO
from radicalbit_ai_gateway.db.dao.otel_traces_dao import OtelTracesDAO
from radicalbit_ai_gateway.db.dao.request_event_dao import RequestEventDAO
from radicalbit_ai_gateway.db.models.event import RequestEventsSummary
from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.models.guardrails import GuardrailBehaviorType
from radicalbit_ai_gateway.models.request_dto import (
    RequestDetailDTO,
    RequestDTO,
    RequestEventDTO,
)
from radicalbit_ai_gateway.models.request_event_type import RequestStatus, RequestType
from radicalbit_ai_gateway.utils.exceptions import GatewayNotFoundError


def _enum_or_none(enum_cls, value):
    try:
        return enum_cls(value)
    except ValueError:
        return None


def _page_date_range(dates: list[date]) -> tuple[date, date]:
    """Return the DATE window the page's events and traces are read from.

    A request_event row is written when the request ends, while its events
    and spans happen before that: a request that crossed midnight has some on
    the previous DATE. The lower bound is widened by one day for them.
    """
    return min(dates) - timedelta(days=1), max(dates)


def _is_blocking(event_type: str, guardrail_behavior: str) -> bool:
    """Whether the event is one that stops the request.

    A guardrail blocks only with behavior BLOCK (WARN and SOFT_BLOCK let the
    request through); every limit event (`*_LIMIT`, route, credential or
    project) rejects it. LIMIT_THRESHOLD is a warning, not a limit hit.
    """
    if event_type == EventType.GUARDRAIL:
        return guardrail_behavior == GuardrailBehaviorType.BLOCK
    return event_type.endswith('_LIMIT')


def _event_dto(event: dict) -> RequestEventDTO:
    # Promoted string columns default to '' in ClickHouse: '' means absent.
    return RequestEventDTO(
        **{k: (None if v == '' else v) for k, v in event.items()},
        blocking=_is_blocking(event['event_type'], event['guardrail_behavior']),
    )


class RequestsService:
    """Requests, the unit of observability (ADR 0010).

    A request is a `request_event` row; its events and its trace (if any) are
    attached to it by request UUID.
    """

    def __init__(
        self,
        request_event_dao: RequestEventDAO,
        event_dao: EventDAO,
        otel_traces_dao: OtelTracesDAO,
    ):
        self.request_event_dao = request_event_dao
        self.event_dao = event_dao
        self.otel_traces_dao = otel_traces_dao

    def get_requests(
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
    ) -> Page[RequestDTO]:
        requests_page = self.request_event_dao.get_requests_paginated(
            project_uuid,
            route_names,
            group_uuids,
            key_uuids,
            _from,
            _to,
            params,
            tags=tags,
            request_types=request_types,
        )
        rows = requests_page.items
        if not rows:
            return Page.create([], params, total=requests_page.total)

        request_uuids = [str(row.request_uuid) for row in rows]
        date_from, date_to = _page_date_range([row.date for row in rows])
        summaries = self.event_dao.get_request_summaries(
            project_uuid, request_uuids, date_from, date_to
        )
        trace_ids = self.otel_traces_dao.get_trace_ids_by_request_uuids(
            project_uuid, request_uuids, date_from, date_to
        )

        items = [
            RequestDTO(
                request_uuid=row.request_uuid,
                trace_id=trace_ids.get(str(row.request_uuid)),
                route_name=row.route_name,
                request_type=_enum_or_none(RequestType, row.request_type),
                tags=row.tags,
                group_uuid=row.group_uuid,
                group_name=row.group_name or None,
                api_key_uuid=row.api_key_uuid,
                api_key_name=row.api_key_name or None,
                request_status=_enum_or_none(RequestStatus, row.request_status),
                http_status_code=row.http_status_code,
                error_type=row.error_type or None,
                duration_ms=row.duration_ms,
                created_at=int(row.timestamp.timestamp()),
                **summaries.get(
                    str(row.request_uuid), RequestEventsSummary()
                ).model_dump(),
            )
            for row in rows
        ]
        return Page.create(items, params, total=requests_page.total)

    def get_request(self, project_uuid: UUID, request_uuid: UUID) -> RequestDetailDTO:
        """One request by its UUID, traced or not."""
        row = self.request_event_dao.get_request(project_uuid, request_uuid)
        if row is None:
            raise GatewayNotFoundError(f"Request '{request_uuid}' not found")

        key = str(row.request_uuid)
        date_from, date_to = _page_date_range([row.date])
        trace_ids = self.otel_traces_dao.get_trace_ids_by_request_uuids(
            project_uuid, [key], date_from, date_to
        )
        events = self.event_dao.get_request_events(
            project_uuid, row.request_uuid, date_from, date_to
        )

        return RequestDetailDTO(
            request_uuid=row.request_uuid,
            trace_id=trace_ids.get(key),
            route_name=row.route_name,
            request_type=_enum_or_none(RequestType, row.request_type),
            tags=row.tags,
            group_uuid=row.group_uuid,
            group_name=row.group_name or None,
            api_key_uuid=row.api_key_uuid,
            api_key_name=row.api_key_name or None,
            request_status=_enum_or_none(RequestStatus, row.request_status),
            http_status_code=row.http_status_code,
            error_type=row.error_type or None,
            error_code=row.error_code or None,
            is_streaming=row.is_streaming,
            duration_ms=row.duration_ms,
            created_at=int(row.timestamp.timestamp()),
            events=[_event_dto(event) for event in events],
        )
