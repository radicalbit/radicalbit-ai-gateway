from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field


class Base(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SpanStats(Base):
    span_count: int = 0
    error_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    last_span: datetime | None = None


class Trace(Base):
    request_uuid: UUID
    route_name: str
    group_name: str
    group_uuid: UUID | None
    api_key_name: str
    api_key_uuid: UUID | None
    duration_ms: float
    created_at: datetime


class TracesChartDataPoint(Base):
    bucket: datetime
    trace_status: str
    total_requests: int

    @computed_field
    @property
    def timestamp(self) -> int:
        if self.bucket.tzinfo is None:
            return int(self.bucket.replace(tzinfo=timezone.utc).timestamp())
        return int(self.bucket.timestamp())


class TraceLatencies(Base):
    p50: float | None = None
    p90: float | None = None
    p95: float | None = None
    p99: float | None = None


class SpanLatencies(Base):
    span_name: str
    p50: float | None = None
    p90: float | None = None
    p95: float | None = None
    p99: float | None = None


class CategoryLatencies(Base):
    category: str
    p50: float | None = None
    p90: float | None = None
    p95: float | None = None
    p99: float | None = None


class CategorySpanLatencies(Base):
    category: str
    span_name: str
    p50: float | None = None
    p90: float | None = None
    p95: float | None = None
    p99: float | None = None


class SpanRecord(BaseModel):
    """DAO-layer model for a span from OtelTraces table."""

    timestamp: datetime
    trace_id: str
    request_uuid: str
    span_id: str
    span_name: str
    service_name: str
    duration: int  # nanoseconds
    status_code: str
    parent_span_id: str | None = None
    # Trace attributes extracted directly from span_attributes
    route_name: str
    api_key_uuid: str
    api_key_name: str
    group_uuid: str
    group_name: str
    # Token usage from span_attributes (stored as strings in ClickHouse)
    output_tokens: str | None = None
    input_tokens: str | None = None
    total_tokens: str | None = None
    tags: list[str] = Field(default_factory=list)
    # Additional fields for span detail
    span_attributes: dict = Field(default_factory=dict)
    status_message: str | None = None
    events: list[dict] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
