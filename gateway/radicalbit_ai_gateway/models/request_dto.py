from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from radicalbit_ai_gateway.models.request_event_type import RequestStatus, RequestType


class RequestDTO(BaseModel):
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
    duration_ms: float
    created_at: int
    total_tokens: int = 0
    cost: float = 0.0
    # True only when that kind of event fired in this request, any behavior
    # for guardrails; has_limit means a `*_LIMIT` block.
    has_guardrail: bool = False
    has_cache_hit: bool = False
    has_fallback: bool = False
    has_routing: bool = False
    has_limit: bool = False

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class EventDTO(BaseModel):
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

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class RequestDetailDTO(BaseModel):
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
    events: list[EventDTO] = Field(default_factory=list)

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )
