from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, computed_field
from pydantic.alias_generators import to_camel


class Base(BaseModel):
    """Pydantic Config for Base: allow population from object attributes."""

    model_config = ConfigDict(from_attributes=True)


class Counters(Base):
    guardrail_value: int = 0
    fallback_value: int = 0
    routing_value: int = 0
    rate_limit_triggered: int = 0
    token_input_limit_triggered: int = 0
    token_output_limit_triggered: int = 0
    cache_triggered: int = 0


class LastEventFallback(Base):
    route_name: str
    timestamp: datetime
    api_key_uuid: UUID
    target: str
    fallback: str
    api_key_name: str

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class LastEventGuardrail(Base):
    route_name: str
    timestamp: datetime
    api_key_uuid: UUID
    name: str
    where: str
    type: str
    behavior: str
    api_key_name: str

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class ModelInvocationCounter(Base):
    model_id: str
    value: int


class RequestStats(Base):
    successful_requests: int = 0
    error_requests: int = 0
    total_requests: int = 0
    last_request_timestamp: datetime | None = None

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class TokensCounter(Base):
    event_type: str
    route_name: str
    model_id: str
    value: int


class EventDetails(Base):
    timestamp: datetime
    api_key_uuid: UUID = UUID(int=0)
    route_name: str
    event_type: str
    target: str | None = None
    fallback: str | None = None
    name: str | None = None
    type: str | None = None
    where: str | None = None
    parameters: str | None = None
    behavior: str | None = None
    api_key_name: str = 'fake-name'
    api_key_active: bool = True

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class CostChartDataPoint(Base):
    bucket: datetime
    group_by_value: str
    total_cost: float

    @computed_field
    @property
    def timestamp(self) -> int:
        if self.bucket.tzinfo is None:
            return int(self.bucket.replace(tzinfo=timezone.utc).timestamp())
        return int(self.bucket.timestamp())


class TokenChartDataPoint(Base):
    bucket: datetime
    event_type: str
    total_tokens: int

    @computed_field
    @property
    def timestamp(self) -> int:
        if self.bucket.tzinfo is None:
            return int(self.bucket.replace(tzinfo=timezone.utc).timestamp())
        return int(self.bucket.timestamp())


class RequestChartDataPoint(Base):
    bucket: datetime
    total_requests: int

    @computed_field
    @property
    def timestamp(self) -> int:
        if self.bucket.tzinfo is None:
            return int(self.bucket.replace(tzinfo=timezone.utc).timestamp())
        return int(self.bucket.timestamp())


class CostData(Base):
    input_cost: float = 0.0
    output_cost: float = 0.0
    total_cost: float = 0.0
    cache_triggered: int | None = None
    partial_saved_amount_input: float | None = None
    partial_saved_amount_output: float | None = None
    partial_saved_amount: float | None = None
    llm_input_request_savings: float | None = None
    llm_output_request_savings: float | None = None
    llm_total_request_savings: float | None = None
    embedding_inference_cost: float | None = None
    saved_amount_input: float | None = None
    saved_amount_output: float | None = None
    total_saved_amount: float | None = None
    cache_saved_tokens_output: int | None = None
    cache_saved_tokens_input: int | None = None
    total_cached_tokens: int | None = None

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
        protected_namespaces=(),
    )


class RouteCostData(CostData):
    route_name: str


class SemanticCacheCostData(Base):
    embedding_inference_cost: float | None = None
    cache_triggered: int | None = None
    cache_saved_tokens_input: int | None = None
    cache_saved_tokens_output: int | None = None
    llm_input_request_savings: float | None = None
    llm_output_request_savings: float | None = None
    llm_total_request_savings: float | None = None
    total_cached_tokens: int | None = None
    net_savings: float | None = None

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
        protected_namespaces=(),
    )


class DetailedCostBreakdown(Base):
    chat_input_direct: float = 0.0
    chat_input_cached: float = 0.0
    chat_input_judges: float = 0.0
    chat_input_judges_cached: float = 0.0
    chat_output_direct: float = 0.0
    chat_output_judges: float = 0.0
    embedding_input_total: float = 0.0
    embedding_input_direct: float = 0.0
    embedding_input_semantic_cache: float = 0.0

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
        protected_namespaces=(),
    )


class RouteDetailedCostBreakdown(DetailedCostBreakdown):
    route_name: str


class InvocationChartDataPoint(Base):
    bucket: datetime
    group_by_value: str
    value: int

    @computed_field
    @property
    def timestamp(self) -> int:
        if self.bucket.tzinfo is None:
            return int(self.bucket.replace(tzinfo=timezone.utc).timestamp())
        return int(self.bucket.timestamp())


class ErrorRoute(Base):
    route_name: str
    error_perc: float


class ErrorDetail(Base):
    error_type: str | None
    count: int


class ErrorRequestChartDataPoint(Base):
    bucket: datetime
    total_requests: int

    @computed_field
    @property
    def timestamp(self) -> int:
        if self.bucket.tzinfo is None:
            return int(self.bucket.replace(tzinfo=timezone.utc).timestamp())
        return int(self.bucket.timestamp())


class RequestGroupedChartDataPoint(Base):
    bucket: datetime
    success_count: int
    error_count: int

    @computed_field
    @property
    def timestamp(self) -> int:
        if self.bucket.tzinfo is None:
            return int(self.bucket.replace(tzinfo=timezone.utc).timestamp())
        return int(self.bucket.timestamp())


class MostExpensiveChartData(Base):
    bucket: datetime
    cost: float

    @computed_field
    @property
    def timestamp(self) -> int:
        if self.bucket.tzinfo is None:
            return int(self.bucket.replace(tzinfo=timezone.utc).timestamp())
        return int(self.bucket.timestamp())


class MostExpensiveRoute(Base):
    route_name: str
    total_cost: float


class RouteCostBreakdown(Base):
    route_name: str
    total_cost: float
