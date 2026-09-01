from datetime import datetime
from enum import Enum
from typing import Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

T = TypeVar('T')


class TraceStatus(str, Enum):
    SUCCESS = 'success'
    WARNING = 'warning'
    ERROR = 'error'


class TreeNodeDTO(BaseModel):
    span_id: str
    span_name: str
    duration_ms: float
    status_code: str
    output_tokens: int = 0
    input_tokens: int = 0
    total_tokens: int = 0
    error_count: int = 0
    created_at: int
    children: list['TreeNodeDTO'] = Field(default_factory=list)

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class TraceDTO(BaseModel):
    trace_id: str
    request_uuid: UUID | None = None
    root_span_id: str | None = None  # Optional - only for detail view
    total_spans: int
    duration_ms: float
    error_count: int = 0
    trace_status: TraceStatus = TraceStatus.SUCCESS
    created_at: int
    latest_span_ts: int  # Required - use created_at as fallback in list
    output_tokens: int = 0
    input_tokens: int = 0
    total_tokens: int = 0
    route_name: str | None = None
    api_key_uuid: UUID | None = None
    api_key_name: str | None = None
    group_uuid: UUID | None = None
    group_name: str | None = None
    tags: list[str] = Field(default_factory=list)
    tree: TreeNodeDTO | None = None  # Optional - only for detail view

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class LatenciesDTO(BaseModel):
    p50: float | None = Field(default=None, description='50th percentile latency in ms')
    p90: float | None = Field(default=None, description='90th percentile latency in ms')
    p95: float | None = Field(default=None, description='95th percentile latency in ms')
    p99: float | None = Field(default=None, description='99th percentile latency in ms')

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class TracesChartDataSeriesDTO(BaseModel):
    name: str
    data: list[int]

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class TracesChartDataDTO(BaseModel):
    granularity: Literal['hours', 'days', 'weeks', 'months']
    timestamp: list[int]
    data: list[TracesChartDataSeriesDTO]
    total: int

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class SpanLatencyDTO(BaseModel):
    span_name: str
    p50: float | None = Field(default=None, description='50th percentile latency in ms')
    p90: float | None = Field(default=None, description='90th percentile latency in ms')
    p95: float | None = Field(default=None, description='95th percentile latency in ms')
    p99: float | None = Field(default=None, description='99th percentile latency in ms')

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class SpanLatenciesDTO(BaseModel):
    data: list[SpanLatencyDTO]

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class GroupedSpanLatencyDTO(BaseModel):
    category: str
    p50: float | None = Field(default=None, description='50th percentile latency in ms')
    p90: float | None = Field(default=None, description='90th percentile latency in ms')
    p95: float | None = Field(default=None, description='95th percentile latency in ms')
    p99: float | None = Field(default=None, description='99th percentile latency in ms')
    spans: list[SpanLatencyDTO]

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class GroupedSpanLatenciesDTO(BaseModel):
    data: list[GroupedSpanLatencyDTO]

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class ErrorEvents(BaseModel):
    timestamp: datetime | None = None
    name: str | None = None
    attributes: dict | None = None

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class SpanDTO(BaseModel):
    trace_id: str
    span_id: str
    span_name: str
    request_uuid: UUID | None = None
    duration_ms: float
    created_at: int
    output_tokens: int = 0
    input_tokens: int = 0
    total_tokens: int = 0
    route_name: str | None = None
    api_key_uuid: UUID | None = None
    api_key_name: str | None = None
    group_uuid: UUID | None = None
    group_name: str | None = None
    attributes: dict
    status_message: str | None = None
    error_count: int = 0
    error_events: list[ErrorEvents]

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )
