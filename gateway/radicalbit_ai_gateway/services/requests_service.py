from datetime import date, datetime, timedelta
from uuid import UUID

from fastapi_pagination import Page, Params
from pydantic import BaseModel
from sqlalchemy import Row

from radicalbit_ai_gateway.db.dao.event_dao import EventDAO
from radicalbit_ai_gateway.db.dao.otel_traces_dao import OtelTracesDAO
from radicalbit_ai_gateway.db.dao.request_event_dao import RequestEventDAO
from radicalbit_ai_gateway.db.models.event import EventsSummary
from radicalbit_ai_gateway.models.event_type import LIMIT_BLOCK_EVENT_TYPES, EventType
from radicalbit_ai_gateway.models.guardrails import GuardrailBehaviorType
from radicalbit_ai_gateway.models.request_dto import (
    CacheTooltip,
    EventDTO,
    EventIcon,
    FallbackTooltip,
    GuardrailTooltip,
    IconTone,
    LimitTooltip,
    RequestDetailDTO,
    RequestDTO,
    RequestIcons,
    RoutingTooltip,
)
from radicalbit_ai_gateway.models.request_event_type import RequestStatus, RequestType
from radicalbit_ai_gateway.utils.exceptions import GatewayNotFoundError


def _enum_or_none(enum_cls, value):
    try:
        return enum_cls(value)
    except ValueError:
        return None


def _events_date_range(dates: list[date]) -> tuple[date, date]:
    """Return the DATE window the requests' events and traces are read from.

    A request_event row is written when the request ends, while its events
    and spans happen before that: a request that crossed midnight has some on
    the previous DATE. The lower bound is widened by one day for them.
    """
    return min(dates) - timedelta(days=1), max(dates)


def _is_blocking(event_type: str, guardrail_behavior: str) -> bool:
    """Whether the event is one that stops the request.

    A guardrail blocks only with behavior BLOCK (WARN and SOFT_BLOCK let the
    request through); every limit block event rejects it.
    """
    if event_type == EventType.GUARDRAIL:
        return guardrail_behavior == GuardrailBehaviorType.BLOCK
    return event_type in LIMIT_BLOCK_EVENT_TYPES


def _event_dto(event: dict) -> EventDTO:
    # Promoted string columns default to '' in ClickHouse: '' means absent.
    return EventDTO(
        **{k: (None if v == '' else v) for k, v in event.items()},
        blocking=_is_blocking(event['event_type'], event['guardrail_behavior']),
    )


def _or_none(value: str) -> str | None:
    # Promoted string columns and missing ATTRIBUTES keys read as ''.
    return value or None


def _icon(tones_and_details: list[tuple[IconTone, BaseModel]]) -> EventIcon | None:
    """Build the icon of one kind of event: None if none fired, else its top tone."""
    if not tones_and_details:
        return None
    return EventIcon(
        tone=max((tone for tone, _ in tones_and_details), key=lambda t: t.rank),
        details=[detail for _, detail in tones_and_details],
    )


def _guardrail_tone(behavior: str) -> IconTone:
    if behavior == GuardrailBehaviorType.BLOCK:
        return IconTone.ERROR
    if behavior in (GuardrailBehaviorType.WARN, GuardrailBehaviorType.SOFT_BLOCK):
        return IconTone.WARNING
    return IconTone.SUCCESS


def _limit_tone(event_type: str) -> IconTone:
    # A *_LIMIT event blocked the request; LIMIT_THRESHOLD only warns.
    return IconTone.ERROR if event_type in LIMIT_BLOCK_EVENT_TYPES else IconTone.WARNING


def _icons(summary: EventsSummary) -> RequestIcons:
    """Return the Requests row icons: which kinds of event fired, in which tone."""
    return RequestIcons(
        guardrail=_icon(
            [
                (
                    _guardrail_tone(behavior),
                    GuardrailTooltip(
                        name=_or_none(name),
                        behavior=_or_none(behavior),
                        position=_or_none(where),
                    ),
                )
                for name, behavior, where in sorted(summary.guardrails)
            ]
        ),
        cache=_icon(
            [
                (IconTone.SUCCESS, CacheTooltip(cache_type=_or_none(cache_type)))
                for (cache_type,) in sorted(summary.cache_hits)
            ]
        ),
        fallback=_icon(
            [
                (
                    IconTone.WARNING,
                    FallbackTooltip(
                        target=_or_none(target), fallback_model=_or_none(fallback)
                    ),
                )
                for target, fallback in sorted(summary.fallbacks)
            ]
        ),
        routing=_icon(
            [
                (
                    IconTone.SUCCESS,
                    RoutingTooltip(
                        routing_name=_or_none(name), selected_model=_or_none(model)
                    ),
                )
                for name, model in sorted(summary.routings)
            ]
        ),
        limits=_icon(
            [
                (
                    _limit_tone(event_type),
                    LimitTooltip(
                        limit_scope=_or_none(scope),
                        category=_or_none(category),
                        threshold_percentage=int(pct) if pct else None,
                    ),
                )
                for event_type, scope, category, pct in sorted(summary.limits)
            ]
        ),
    )


def _request_fields(row: Row) -> dict:
    """Return the fields a request_event row gives the Requests list and detail."""
    return {
        'request_uuid': row.request_uuid,
        'route_name': row.route_name,
        'request_type': _enum_or_none(RequestType, row.request_type),
        'tags': row.tags,
        'group_uuid': row.group_uuid,
        'group_name': row.group_name or None,
        'api_key_uuid': row.api_key_uuid,
        'api_key_name': row.api_key_name or None,
        'request_status': _enum_or_none(RequestStatus, row.request_status),
        'http_status_code': row.http_status_code,
        'error_type': row.error_type or None,
        'error_code': row.error_code or None,
        'duration_ms': row.duration_ms,
        'created_at': int(row.timestamp.timestamp()),
    }


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
        date_from, date_to = _events_date_range([row.date for row in rows])
        summaries = self.event_dao.get_request_summaries(
            project_uuid, request_uuids, date_from, date_to
        )
        trace_ids = self.otel_traces_dao.get_trace_ids_by_request_uuids(
            project_uuid, request_uuids, date_from, date_to
        )

        items = []
        for row in rows:
            summary = summaries.get(str(row.request_uuid), EventsSummary())
            items.append(
                RequestDTO(
                    **_request_fields(row),
                    trace_id=trace_ids.get(str(row.request_uuid)),
                    total_tokens=summary.total_tokens,
                    cost=summary.cost,
                    icons=_icons(summary),
                )
            )
        return Page.create(items, params, total=requests_page.total)

    def get_request(self, project_uuid: UUID, request_uuid: UUID) -> RequestDetailDTO:
        """One request by its UUID, traced or not."""
        row = self.request_event_dao.get_request(project_uuid, request_uuid)
        if row is None:
            raise GatewayNotFoundError(f"Request '{request_uuid}' not found")

        key = str(row.request_uuid)
        date_from, date_to = _events_date_range([row.date])
        trace_ids = self.otel_traces_dao.get_trace_ids_by_request_uuids(
            project_uuid, [key], date_from, date_to
        )
        events = self.event_dao.get_request_events(
            project_uuid, row.request_uuid, date_from, date_to
        )
        # Same totals as the request's row in the list, by the same rule.
        summary = self.event_dao.get_request_summaries(
            project_uuid, [key], date_from, date_to
        ).get(key, EventsSummary())

        return RequestDetailDTO(
            **_request_fields(row),
            trace_id=trace_ids.get(key),
            total_tokens=summary.total_tokens,
            cost=summary.cost,
            is_streaming=row.is_streaming,
            events=[_event_dto(event) for event in events],
        )
