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

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )
