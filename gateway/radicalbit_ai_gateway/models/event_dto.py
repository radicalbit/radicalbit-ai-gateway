from datetime import datetime
from enum import Enum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field
from pydantic.alias_generators import to_camel

from radicalbit_ai_gateway.db.models.event import (
    CostData,
    Counters,
    DetailedCostBreakdown,
    ErrorDetail,
    LastEventFallback,
    LastEventGuardrail,
    ModelInvocationCounter,
    RequestStats,
    SemanticCacheCostData,
)
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig


class BaseEventDetailDTO(BaseModel):
    """Base class with common fields shared by all event detail types."""

    timestamp: datetime
    api_key_uuid: UUID
    route_name: str
    api_key_name: str
    api_key_active: bool = True

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class FallbackEventDetailDTO(BaseEventDetailDTO):
    """DTO for FALLBACK event type."""

    event_type: Literal['FALLBACK']
    target: str | None = None
    fallback: str | None = None


class GuardrailEventDetailDTO(BaseEventDetailDTO):
    """DTO for GUARDRAIL event type."""

    event_type: Literal['GUARDRAIL']
    name: str | None = None
    type: str | None = None
    where: str | None = None
    parameters: str | None = None
    behavior: str | None = None


class RateLimitEventDetailDTO(BaseEventDetailDTO):
    """DTO for RATE_LIMIT event type."""

    event_type: Literal['RATE_LIMIT']


class TokenInputLimitEventDetailDTO(BaseEventDetailDTO):
    """DTO for TOKEN_INPUT_LIMIT event type."""

    event_type: Literal['TOKEN_INPUT_LIMIT']


class TokenOutputLimitEventDetailDTO(BaseEventDetailDTO):
    """DTO for TOKEN_OUTPUT_LIMIT event type."""

    event_type: Literal['TOKEN_OUTPUT_LIMIT']


class CacheHitEventDetailDTO(BaseEventDetailDTO):
    """DTO for CACHE_HIT event type."""

    event_type: Literal['CACHE_HIT']
    target: str | None = None


class CachedCounterDTO(BaseModel):
    cache_saved_tokens_input: int | None = None
    cache_saved_tokens_output: int | None = None


class TokensCounterDTO(CachedCounterDTO):
    total_input_token_processed: int = 0
    total_output_token_processed: int = 0


class Fallback(BaseModel):
    value: int = 0
    last_event: LastEventFallback | None

    @staticmethod
    def from_dict(value: int, last_event: LastEventFallback | None) -> 'Fallback':
        return Fallback(value=value, last_event=last_event)

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class Guardrail(BaseModel):
    value: int = 0
    last_event: LastEventGuardrail | None

    @staticmethod
    def from_dict(value: int, last_event: LastEventGuardrail | None) -> 'Guardrail':
        return Guardrail(value=value, last_event=last_event)

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class Cache(BaseModel):
    cache_triggered: int | None = None
    cache_saved_tokens_input: int | None = None
    cache_saved_tokens_output: int | None = None
    hit_percentage: float | None = None

    @computed_field
    @property
    def total_cached_tokens(self) -> int | None:
        if (
            self.cache_saved_tokens_input is None
            and self.cache_saved_tokens_output is None
        ):
            return None
        return (self.cache_saved_tokens_input or 0) + (
            self.cache_saved_tokens_output or 0
        )

    @staticmethod
    def from_dict(
        cache_triggered: int | None,
        cache_saved_tokens_input: int | None,
        cache_saved_tokens_output: int | None,
        hit_percentage: float | None,
    ) -> 'Cache':
        return Cache(
            cache_triggered=cache_triggered,
            cache_saved_tokens_input=cache_saved_tokens_input,
            cache_saved_tokens_output=cache_saved_tokens_output,
            hit_percentage=hit_percentage,
        )

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class ModelInvocationDTO(BaseModel):
    model_id: str
    value: int

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class Routing(BaseModel):
    value: int = 0
    model_invocations: list[ModelInvocationDTO] = Field(default_factory=list)

    @staticmethod
    def from_dict(
        value: int, model_invocations: list[ModelInvocationCounter]
    ) -> 'Routing':
        return Routing(
            value=value,
            model_invocations=[
                ModelInvocationDTO(model_id=c.model_id, value=c.value)
                for c in model_invocations
            ],
        )

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class ErrorDetailDTO(BaseModel):
    error_type: str | None = None
    count: int = 0

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class Errors(BaseModel):
    request_error: int = 0
    request_error_percentage: float = 0.0
    details: list[ErrorDetailDTO] = Field(default_factory=list)

    @staticmethod
    def from_dto(
        request_error: int,
        request_error_percentage: float,
        error_details: list[ErrorDetail] | None,
    ) -> 'Errors':
        return Errors(
            request_error=request_error,
            request_error_percentage=request_error_percentage,
            details=[
                ErrorDetailDTO(error_type=e.error_type, count=e.count)
                for e in (error_details or [])
            ],
        )

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class EventsDTO(BaseModel):
    fallbacks: Fallback | None = None
    guardrails: Guardrail | None = None
    routing: Routing | None = None
    total_input_token_processed: int = 0
    total_output_token_processed: int = 0
    rate_limit_triggered: int | None = None
    token_input_limit_triggered: int | None = None
    token_output_limit_triggered: int | None = None
    cache: Cache | None = None
    total_requests: int = 0
    request_error_percentage: Annotated[
        float,
        Field(default=0.0, deprecated='Use errors.requestErrorPercentage instead'),
    ]
    errors: Errors = Field(default_factory=Errors)
    last_request_timestamp: datetime | None = None

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )

    @computed_field
    @property
    def cache_triggered(self) -> int | None:
        if self.cache:
            return self.cache.cache_triggered
        return None

    @staticmethod
    def _get_enablement_flags(
        config: GatewayConfig, route_name: str | None
    ) -> dict[str, bool]:
        if route_name:
            route_config = config.routes[route_name]
            return {
                'fallback_enabled': bool(route_config.fallback),
                'guardrail_enabled': bool(
                    config.guardrails and route_config.guardrails
                ),
                'routing_enabled': bool(config.routing and route_config.routing),
                'cache_enabled': bool(
                    config.cache
                    and route_config.caching
                    and route_config.caching.enabled
                ),
                'rate_limiting_enabled': bool(route_config.rate_limiting),
                'token_limiting_enabled': bool(route_config.token_limiting),
            }
        return {
            'fallback_enabled': any(r.fallback for r in config.routes.values()),
            'guardrail_enabled': bool(config.guardrails),
            'routing_enabled': bool(
                config.routing and any(r.routing for r in config.routes.values())
            ),
            'cache_enabled': bool(
                config.cache
                and any(r.caching and r.caching.enabled for r in config.routes.values())
            ),
            'rate_limiting_enabled': any(
                r.rate_limiting for r in config.routes.values()
            ),
            'token_limiting_enabled': any(
                r.token_limiting for r in config.routes.values()
            ),
        }

    @staticmethod
    def _create_dto(
        counters: Counters,
        tokens_counter_dto: TokensCounterDTO,
        last_event_guardrail: LastEventGuardrail | None,
        last_event_fallback: LastEventFallback | None,
        flags: dict[str, bool],
        include_cache: bool = False,
        routing_model_counters: list[ModelInvocationCounter] | None = None,
        request_stats: RequestStats | None = None,
        error_details: list[ErrorDetail] | None = None,
    ) -> 'EventsDTO':
        fallback = (
            Fallback.from_dict(
                value=counters.fallback_value, last_event=last_event_fallback
            )
            if flags['fallback_enabled']
            else None
        )
        guardrail = (
            Guardrail.from_dict(
                value=counters.guardrail_value, last_event=last_event_guardrail
            )
            if flags['guardrail_enabled']
            else None
        )
        routing = (
            Routing.from_dict(
                value=counters.routing_value,
                model_invocations=routing_model_counters or [],
            )
            if flags['routing_enabled']
            else None
        )
        total_requests = request_stats.total_requests if request_stats else 0
        cache = (
            Cache.from_dict(
                cache_triggered=counters.cache_triggered,
                cache_saved_tokens_input=tokens_counter_dto.cache_saved_tokens_input,
                cache_saved_tokens_output=tokens_counter_dto.cache_saved_tokens_output,
                hit_percentage=(counters.cache_triggered / total_requests * 100)
                if total_requests > 0
                else 0.0,
            )
            if include_cache and flags['cache_enabled']
            else None
        )

        request_error_percentage: float = 0.0
        last_request_timestamp: datetime | None = None
        error_request_count: int = 0
        if request_stats is not None:
            error_request_count = request_stats.error_requests
            if total_requests > 0:
                request_error_percentage = round(
                    request_stats.error_requests / total_requests * 100, 2
                )
            last_request_timestamp = request_stats.last_request_timestamp

        errors = Errors.from_dto(
            request_error=error_request_count,
            request_error_percentage=request_error_percentage,
            error_details=error_details,
        )

        return EventsDTO(
            fallbacks=fallback,
            guardrails=guardrail,
            routing=routing,
            rate_limit_triggered=counters.rate_limit_triggered
            if counters and flags['rate_limiting_enabled']
            else None,
            token_input_limit_triggered=counters.token_input_limit_triggered
            if counters and flags['token_limiting_enabled']
            else None,
            token_output_limit_triggered=counters.token_output_limit_triggered
            if counters and flags['token_limiting_enabled']
            else None,
            total_input_token_processed=tokens_counter_dto.total_input_token_processed,
            total_output_token_processed=tokens_counter_dto.total_output_token_processed,
            cache=cache,
            total_requests=total_requests,
            request_error_percentage=request_error_percentage,
            errors=errors,
            last_request_timestamp=last_request_timestamp,
        )

    @staticmethod
    def from_dao_per_route(
        config: GatewayConfig,
        route_name: str,
        counters: Counters,
        tokens_counter_dto: TokensCounterDTO,
        last_event_guardrail: LastEventGuardrail | None,
        last_event_fallback: LastEventFallback | None,
        routing_model_counters: list[ModelInvocationCounter] | None = None,
        request_stats: RequestStats | None = None,
        error_details: list[ErrorDetail] | None = None,
    ) -> 'EventsDTO':
        flags = EventsDTO._get_enablement_flags(config, route_name)
        return EventsDTO._create_dto(
            counters=counters,
            tokens_counter_dto=tokens_counter_dto,
            last_event_guardrail=last_event_guardrail,
            last_event_fallback=last_event_fallback,
            flags=flags,
            include_cache=True,
            routing_model_counters=routing_model_counters,
            request_stats=request_stats,
            error_details=error_details,
        )

    @staticmethod
    def from_dao_global(
        config: GatewayConfig,
        counters: Counters,
        tokens_counter_dto: TokensCounterDTO,
        last_event_guardrail: LastEventGuardrail | None,
        last_event_fallback: LastEventFallback | None,
        routing_model_counters: list[ModelInvocationCounter] | None = None,
        request_stats: RequestStats | None = None,
        error_details: list[ErrorDetail] | None = None,
    ) -> 'EventsDTO':
        flags = EventsDTO._get_enablement_flags(config, None)
        return EventsDTO._create_dto(
            counters=counters,
            tokens_counter_dto=tokens_counter_dto,
            last_event_guardrail=last_event_guardrail,
            last_event_fallback=last_event_fallback,
            flags=flags,
            routing_model_counters=routing_model_counters,
            request_stats=request_stats,
            error_details=error_details,
        )


class LastNEvents(BaseModel):
    fallbacks: list[FallbackEventDetailDTO] | None = Field(default_factory=list)
    guardrails: list[GuardrailEventDetailDTO] | None = Field(default_factory=list)
    rate_limit: list[RateLimitEventDetailDTO] | None = Field(default_factory=list)
    token_input_limit: list[TokenInputLimitEventDetailDTO] | None = Field(
        default_factory=list
    )
    token_output_limit: list[TokenOutputLimitEventDetailDTO] | None = Field(
        default_factory=list
    )
    cache_triggered: list[CacheHitEventDetailDTO] | None = Field(default_factory=list)

    @staticmethod
    def create_dto(
        fallbacks: list[FallbackEventDetailDTO],
        guardrails: list[GuardrailEventDetailDTO],
        rate_limit: list[RateLimitEventDetailDTO],
        token_input_limit: list[TokenInputLimitEventDetailDTO],
        token_output_limit: list[TokenOutputLimitEventDetailDTO],
        cache_triggered: list[CacheHitEventDetailDTO],
        route_config: GatewayRouteConfig,
    ) -> 'LastNEvents':
        return LastNEvents(
            fallbacks=fallbacks if route_config.fallback is not None else None,
            guardrails=guardrails if route_config.guardrails is not None else None,
            rate_limit=rate_limit if route_config.rate_limiting is not None else None,
            token_input_limit=token_input_limit
            if route_config.token_limiting is not None
            else None,
            token_output_limit=token_output_limit
            if route_config.token_limiting is not None
            else None,
            cache_triggered=cache_triggered
            if route_config.caching is not None
            else None,
        )

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class ChartDataSeriesDTO(BaseModel):
    name: str
    data: list[float]

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class CostChartDataSeriesDTO(BaseModel):
    name: str
    uuid: UUID | None = None
    data: list[float]

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class CostChartDataDTO(BaseModel):
    granularity: Literal['hours', 'days', 'weeks', 'months']
    timestamp: list[int]
    data: list[CostChartDataSeriesDTO]
    total: float

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class InvocationChartDataDTO(BaseModel):
    granularity: Literal['hours', 'days', 'weeks', 'months']
    timestamp: list[int]
    data: list[float] | list[ChartDataSeriesDTO]
    total: int

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class TotalCostsDTO(BaseModel):
    total_cost: float
    routes: dict[str, float]

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class TokenChartDataSeriesDTO(BaseModel):
    name: Literal['INPUT', 'OUTPUT']
    data: list[int]

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class TokenChartDataDTO(BaseModel):
    total: int
    granularity: Literal['hours', 'days', 'weeks', 'months']
    timestamp: list[int]
    data: list[TokenChartDataSeriesDTO]

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class RequestChartDataDTO(BaseModel):
    total: int | float
    granularity: Literal['hours', 'days', 'weeks', 'months']
    timestamp: list[int]
    data: list[int]

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class RequestGroupedChartDataDTO(BaseModel):
    total: int
    granularity: Literal['hours', 'days', 'weeks', 'months']
    timestamp: list[int]
    data: list[ChartDataSeriesDTO]

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class MostRequestedRouteDTO(BaseModel):
    name: str = Field(description='Name of the most requested route')
    increment_percentage: float = Field(
        description='Percentage change between last two time buckets'
    )
    chart: RequestChartDataDTO = Field(
        description='Chart data with time-bucketed request counts'
    )

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class InputCostBreakdownDTO(BaseModel):
    standard: float = 0
    cached: float = 0
    total: float = 0

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
        protected_namespaces=(),
    )


class TotalCostDTO(BaseModel):
    input: float = Field(
        description='Total input costs from all model types (chat + embedding)'
    )
    cached_input: float = Field(description='Total cached input costs from chat models')
    output: float = Field(description='Total output costs from chat models')
    saved: float | None = Field(
        default=None, description='Total amount saved from caching'
    )

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
        protected_namespaces=(),
    )


class ChatModelsInputBreakdownDTO(BaseModel):
    total: float = Field(
        default=0, description='Total standard (non-cached) input costs for chat models'
    )
    direct: float = Field(
        default=0, description='Input costs for direct chat models (excluding judges)'
    )
    judges: float | None = Field(
        default=None, description='Input costs for judge models'
    )

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
        protected_namespaces=(),
    )


class ChatModelsCachedInputBreakdownDTO(BaseModel):
    total: float = Field(
        default=0, description='Total cached input costs for chat models'
    )
    direct: float = Field(
        default=0,
        description='Cached input costs for direct chat models (excluding judges)',
    )
    judges: float | None = Field(
        default=None, description='Cached input costs for judge models'
    )

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
        protected_namespaces=(),
    )


class ChatModelsOutputBreakdownDTO(BaseModel):
    total: float = Field(default=0, description='Total output costs for chat models')
    direct: float = Field(
        default=0, description='Output costs for direct chat models (excluding judges)'
    )
    judges: float | None = Field(
        default=None, description='Output costs for judge models'
    )

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
        protected_namespaces=(),
    )


class ChatModelsCostDTO(BaseModel):
    input: ChatModelsInputBreakdownDTO = Field(
        description='Standard input costs broken down by direct vs judge models'
    )
    cached_input: ChatModelsCachedInputBreakdownDTO = Field(
        description='Cached input costs broken down by direct vs judge models'
    )
    output: ChatModelsOutputBreakdownDTO = Field(
        description='Output costs broken down by direct vs judge models'
    )
    total: float = Field(
        description='Sum of all chat model costs (input + cached_input + output)'
    )

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
        protected_namespaces=(),
    )


class EmbeddingInputBreakdownDTO(BaseModel):
    total: float = Field(
        default=0, description='Total input costs for embedding models'
    )
    embedding: float = Field(
        default=0,
        description='Input costs for direct embedding model invocations (non-semantic cache)',
    )
    semantic_cache: float | None = Field(
        default=None,
        description='Input costs for semantic cache operations (embedding inference for caching)',
    )

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
        protected_namespaces=(),
    )


class EmbeddingModelsCostDTO(BaseModel):
    input: EmbeddingInputBreakdownDTO = Field(
        description='Input costs broken down by direct vs semantic cache'
    )
    total: float = Field(description='Total input costs for embedding models')

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
        protected_namespaces=(),
    )


class CostDataDTO(BaseModel):
    input_cost: Annotated[
        float,
        Field(
            default=0,
            deprecated='Deprecated after the new cost breakdown implementation.',
        ),
    ]
    output_cost: Annotated[
        float,
        Field(
            default=0,
            deprecated='Deprecated after the new cost breakdown implementation.',
        ),
    ]
    total_cost: Annotated[
        float,
        Field(
            default=0,
            deprecated='Deprecated after the new cost breakdown implementation.',
        ),
    ]

    cache_triggered: Annotated[
        int | None,
        Field(
            default=None,
            deprecated='Deprecated after the new cost breakdown implementation.',
        ),
    ]
    cache_saved_tokens_input: Annotated[
        int | None,
        Field(
            default=None,
            deprecated='Deprecated after the new cost breakdown implementation.',
        ),
    ]
    cache_saved_tokens_output: Annotated[
        int | None,
        Field(
            default=None,
            deprecated='Deprecated after the new cost breakdown implementation.',
        ),
    ]
    saved_amount_input: Annotated[
        float | None,
        Field(
            default=None,
            deprecated='Deprecated after the new cost breakdown implementation.',
        ),
    ]
    saved_amount_output: Annotated[
        float | None,
        Field(
            default=None,
            deprecated='Deprecated after the new cost breakdown implementation.',
        ),
    ]
    total_cached_tokens: Annotated[
        int | None,
        Field(
            default=None,
            deprecated='Deprecated after the new cost breakdown implementation.',
        ),
    ]
    total_saved_amount: Annotated[
        float | None,
        Field(
            default=None,
            deprecated='Deprecated after the new cost breakdown implementation',
        ),
    ]

    # === New Fields (Current recommended structure) ===

    total: float | None = Field(
        default=None,
        description='Grand total of all costs',
    )
    totals: TotalCostDTO | None = Field(
        default=None,
        description='Aggregated totals across input, cached_input, output, and saved',
    )
    chat_models: ChatModelsCostDTO | None = Field(
        default=None, description='Cost breakdown for chat models (direct + judges)'
    )
    embedding_models: EmbeddingModelsCostDTO | None = Field(
        default=None,
        description='Cost breakdown for embedding models (direct + semantic cache)',
    )

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
        protected_namespaces=(),
    )

    @staticmethod
    def from_dao(
        cost_data: CostData,
        semantic_cache_cost_data: SemanticCacheCostData | None,
        detailed_breakdown: DetailedCostBreakdown | None = None,
        has_chat_models: bool = True,
        has_judges: bool = False,
        has_embedding_models: bool = False,
        has_semantic_cache: bool = False,
    ) -> 'CostDataDTO':
        cache_triggered: int | None = None
        input_cost = cost_data.input_cost
        total_cost = cost_data.total_cost
        cache_saved_tokens_input: int | None = None
        cache_saved_tokens_output: int | None = None
        total_cached_tokens: int | None = None
        saved_amount_input: float | None = None
        saved_amount_output: float | None = None
        total_saved_amount: float | None = None

        if cost_data.cache_triggered is not None:
            cache_triggered = cost_data.cache_triggered
            if semantic_cache_cost_data and semantic_cache_cost_data.cache_triggered:
                cache_triggered += semantic_cache_cost_data.cache_triggered

        if cost_data.cache_saved_tokens_input is not None:
            cache_saved_tokens_input = cost_data.cache_saved_tokens_input
            if (
                semantic_cache_cost_data
                and semantic_cache_cost_data.cache_saved_tokens_input
            ):
                cache_saved_tokens_input += (
                    semantic_cache_cost_data.cache_saved_tokens_input
                )

        if cost_data.cache_saved_tokens_output is not None:
            cache_saved_tokens_output = cost_data.cache_saved_tokens_output
            if (
                semantic_cache_cost_data
                and semantic_cache_cost_data.cache_saved_tokens_output
            ):
                cache_saved_tokens_output += (
                    semantic_cache_cost_data.cache_saved_tokens_output
                )

        if cost_data.total_cached_tokens is not None:
            total_cached_tokens = cost_data.total_cached_tokens
            if (
                semantic_cache_cost_data
                and semantic_cache_cost_data.total_cached_tokens
            ):
                total_cached_tokens += semantic_cache_cost_data.total_cached_tokens

        if cost_data.saved_amount_input is not None:
            saved_amount_input = cost_data.saved_amount_input
            if (
                semantic_cache_cost_data
                and semantic_cache_cost_data.llm_input_request_savings
            ):
                saved_amount_input += semantic_cache_cost_data.llm_input_request_savings

        if cost_data.saved_amount_output is not None:
            saved_amount_output = cost_data.saved_amount_output
            if (
                semantic_cache_cost_data
                and semantic_cache_cost_data.llm_output_request_savings
            ):
                saved_amount_output += (
                    semantic_cache_cost_data.llm_output_request_savings
                )

        if cost_data.total_saved_amount is not None:
            total_saved_amount = cost_data.total_saved_amount
            if semantic_cache_cost_data and semantic_cache_cost_data.net_savings:
                total_saved_amount += semantic_cache_cost_data.net_savings

        if (
            semantic_cache_cost_data
            and semantic_cache_cost_data.embedding_inference_cost
        ):
            input_cost += semantic_cache_cost_data.embedding_inference_cost
            total_cost += semantic_cache_cost_data.embedding_inference_cost

        # Build new nested breakdown structure
        total_dto: TotalCostDTO | None = None
        total_all: float | None = None
        chat_models_cost: ChatModelsCostDTO | None = None
        embedding_models_cost: EmbeddingModelsCostDTO | None = None

        if detailed_breakdown:
            # Calculate chat models breakdown (None if no chat models)
            if has_chat_models:
                chat_models_cost = ChatModelsCostDTO(
                    input=ChatModelsInputBreakdownDTO(
                        total=detailed_breakdown.chat_input_direct
                        + detailed_breakdown.chat_input_judges,
                        direct=detailed_breakdown.chat_input_direct,
                        judges=detailed_breakdown.chat_input_judges
                        if has_judges
                        else None,
                    ),
                    cached_input=ChatModelsCachedInputBreakdownDTO(
                        total=detailed_breakdown.chat_input_cached
                        + detailed_breakdown.chat_input_judges_cached,
                        direct=detailed_breakdown.chat_input_cached,
                        judges=detailed_breakdown.chat_input_judges_cached
                        if has_judges
                        else None,
                    ),
                    output=ChatModelsOutputBreakdownDTO(
                        total=detailed_breakdown.chat_output_direct
                        + detailed_breakdown.chat_output_judges,
                        direct=detailed_breakdown.chat_output_direct,
                        judges=detailed_breakdown.chat_output_judges
                        if has_judges
                        else None,
                    ),
                    total=(
                        detailed_breakdown.chat_input_direct
                        + detailed_breakdown.chat_input_judges
                        + detailed_breakdown.chat_input_cached
                        + detailed_breakdown.chat_input_judges_cached
                        + detailed_breakdown.chat_output_direct
                        + detailed_breakdown.chat_output_judges
                    ),
                )

            # Calculate embedding models breakdown (None if no embedding models)
            if has_embedding_models:
                embedding_models_cost = EmbeddingModelsCostDTO(
                    input=EmbeddingInputBreakdownDTO(
                        total=detailed_breakdown.embedding_input_total,
                        embedding=detailed_breakdown.embedding_input_direct,
                        semantic_cache=detailed_breakdown.embedding_input_semantic_cache
                        if has_semantic_cache
                        else None,
                    ),
                    total=detailed_breakdown.embedding_input_total,
                )

            # Calculate total DTO
            chat_input_total = chat_models_cost.input.total if chat_models_cost else 0
            embed_input_total = (
                embedding_models_cost.input.total if embedding_models_cost else 0
            )
            chat_cached_total = (
                chat_models_cost.cached_input.total if chat_models_cost else 0
            )
            chat_output_total = chat_models_cost.output.total if chat_models_cost else 0

            total_dto = TotalCostDTO(
                input=chat_input_total + embed_input_total,
                cached_input=chat_cached_total,
                output=chat_output_total,
                saved=total_saved_amount,
            )

            # Calculate grand total
            chat_total = chat_models_cost.total if chat_models_cost else 0
            embed_total = embedding_models_cost.total if embedding_models_cost else 0
            total_all = chat_total + embed_total

        return CostDataDTO(
            input_cost=input_cost,
            output_cost=cost_data.output_cost,
            total_cost=total_cost,
            cache_triggered=cache_triggered,
            cache_saved_tokens_input=cache_saved_tokens_input,
            cache_saved_tokens_output=cache_saved_tokens_output,
            total_cached_tokens=total_cached_tokens,
            saved_amount_input=saved_amount_input,
            saved_amount_output=saved_amount_output,
            total_saved_amount=total_saved_amount,
            total=total_all,
            totals=total_dto,
            chat_models=chat_models_cost,
            embedding_models=embedding_models_cost,
        )


class RouteCostDTO(BaseModel):
    route_name: str = Field(description='Name of the route')
    summary: CostDataDTO = Field(description='Cost summary for this route')

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class UsageCostsDTO(BaseModel):
    total: float = Field(description='Grand total cost across all routes')
    routes: list[RouteCostDTO] = Field(description='List of cost breakdowns per route')

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class ModelCostDTO(BaseModel):
    route_name: str
    cost: float

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class RequestErrorChartDataDTO(BaseModel):
    total: int
    granularity: Literal['hours', 'days', 'weeks', 'months']
    timestamp: list[int]
    data: list[int]

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class MostRequestedErrorRouteDTO(BaseModel):
    name: str = Field(description='Name of the most requested route with error')
    increment_percentage: float = Field(
        description='Percentage change between last two time buckets'
    )
    chart: RequestChartDataDTO = Field(
        description='Chart data with time-bucketed request counts'
    )

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class MostExpensiveRouteChartDataDTO(BaseModel):
    total: float
    granularity: Literal['hours', 'days', 'weeks', 'months']
    timestamp: list[int]
    data: list[float]

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class MostExpensiveRouteDTO(BaseModel):
    name: str = Field(description='Name of the most expensive route')
    increment_percentage: float = Field(
        description='Percentage change between last two time buckets'
    )
    chart: MostExpensiveRouteChartDataDTO = Field(
        description='Chart data with time-bucketed costs count'
    )
    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class WindowStatus(str, Enum):
    OK = 'ok'
    WARNING = 'warning'
    CRITICAL = 'critical'


class WindowProgressBarDTO(BaseModel):
    window_length: int
    window_start_time: int
    window_end_time: int
    window_size: float
    window_filled_size: float
    window_filled_percentage: float

    @computed_field
    @property
    def window_status(self) -> WindowStatus:
        if self.window_filled_percentage <= 70:
            return WindowStatus.OK
        if self.window_filled_percentage <= 90:
            return WindowStatus.WARNING
        return WindowStatus.CRITICAL

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class RouteProgressBarsDTO(BaseModel):
    budget: WindowProgressBarDTO | None = None
    token_input: WindowProgressBarDTO | None = None
    token_output: WindowProgressBarDTO | None = None
    rate: WindowProgressBarDTO | None = None

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class RouteProgressBarDTO(BaseModel):
    route_name: str
    progress_bar: RouteProgressBarsDTO | None = None

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )
