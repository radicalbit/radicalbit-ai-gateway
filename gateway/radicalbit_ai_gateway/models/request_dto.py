from datetime import datetime
from enum import StrEnum
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from radicalbit_ai_gateway.models.request_event_type import RequestStatus, RequestType


class _CamelModel(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class IconTone(StrEnum):
    """How an event icon is drawn, from the mildest to the strongest."""

    SUCCESS = 'success'
    WARNING = 'warning'
    ERROR = 'error'

    @property
    def rank(self) -> int:
        return list(IconTone).index(self)


class GuardrailTooltip(_CamelModel):
    name: str | None = None
    behavior: str | None = None
    position: str | None = None


class CacheTooltip(_CamelModel):
    cache_type: str | None = None


class FallbackTooltip(_CamelModel):
    target: str | None = None
    fallback_model: str | None = None


class RoutingTooltip(_CamelModel):
    routing_name: str | None = None
    selected_model: str | None = None


class LimitTooltip(_CamelModel):
    # route, project or credential: the entity that owns the limit counter
    limit_scope: str | None = None
    category: str | None = None
    # Only a LIMIT_THRESHOLD carries the percentage it crossed
    threshold_percentage: int | None = None


TooltipT = TypeVar('TooltipT', bound=BaseModel)


class EventIcon(_CamelModel, Generic[TooltipT]):
    """An icon that fired: its strongest tone, one tooltip entry per event."""

    tone: IconTone
    details: list[TooltipT] = Field(default_factory=list)


class RequestIcons(_CamelModel):
    """The icons of a Requests row; None for an icon whose events never fired.

    MCP_INVOCATION has no icon.
    """

    guardrail: EventIcon[GuardrailTooltip] | None = None
    cache: EventIcon[CacheTooltip] | None = None
    fallback: EventIcon[FallbackTooltip] | None = None
    routing: EventIcon[RoutingTooltip] | None = None
    limits: EventIcon[LimitTooltip] | None = None


class RequestDTO(_CamelModel):
    """One row of the Requests list: one request, traced or not (ADR 0010)."""

    request_uuid: UUID
    # None when the request left no trace (rejected early, no exporter...)
    trace_id: str | None = None
    route_name: str
    # None when the stored value is not a known request type
    request_type: RequestType | None = None
    tags: list[str] = Field(default_factory=list)
    group_uuid: UUID | None = None
    group_name: str | None = None
    api_key_uuid: UUID | None = None
    api_key_name: str | None = None
    request_status: RequestStatus | None = None
    http_status_code: int
    error_type: str | None = None
    error_code: str | None = None
    duration_ms: float
    created_at: int
    total_tokens: int = 0
    cost: float = 0.0
    icons: RequestIcons = Field(default_factory=RequestIcons)


class EventDTO(_CamelModel):
    """One event of a request, as the request detail lists it.

    GUARDRAIL_PARAMS and the `parameters` attribute are never carried.
    """

    event_type: str
    timestamp: datetime
    value: float
    cost: float
    model_id: str | None = None
    model_type: str | None = None
    is_cached_tokens: bool = False
    cache_type: str | None = None
    target: str | None = None
    fallback: str | None = None
    guardrail_name: str | None = None
    guardrail_type: str | None = None
    guardrail_where: str | None = None
    guardrail_behavior: str | None = None
    is_judge: bool = False
    is_routing: bool = False
    routing_name: str | None = None
    routing_selected_model_id: str | None = None
    mcp_method: str | None = None
    mcp_alias: str | None = None
    mcp_target: str | None = None
    attributes: dict[str, str] = Field(default_factory=dict)
    # A BLOCK guardrail or any *_LIMIT event: the event that stopped the request
    blocking: bool = False


class RequestDetailDTO(_CamelModel):
    """One request: its Outcome, its trace ID if any, its events in time order."""

    request_uuid: UUID
    # None when the request left no trace (rejected early, no exporter...)
    trace_id: str | None = None
    route_name: str
    request_type: RequestType | None = None
    tags: list[str] = Field(default_factory=list)
    group_uuid: UUID | None = None
    group_name: str | None = None
    api_key_uuid: UUID | None = None
    api_key_name: str | None = None
    request_status: RequestStatus | None = None
    http_status_code: int
    error_type: str | None = None
    error_code: str | None = None
    is_streaming: bool = False
    duration_ms: float
    created_at: int
    total_tokens: int = 0
    cost: float = 0.0
    events: list[EventDTO] = Field(default_factory=list)
