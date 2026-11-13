"""The events and metrics of a model call: what it cost, who called it, and
whether a fallback answered.
"""

from dataclasses import dataclass
from decimal import Decimal
import logging
from typing import Any

from radicalbit_ai_gateway.events.events_processor import emit_event
from radicalbit_ai_gateway.metrics.define_metrics import (
    fallbacks_triggered_counter,
    invocations_latency_histogram,
    model_invocations_counter,
    tokens_per_request_histogram_input,
    tokens_per_request_histogram_output,
    total_tokens_counter_input,
    total_tokens_counter_output,
)
from radicalbit_ai_gateway.models.event_payload import (
    FallbackEventPayload,
    InputTokenProcessedPayload,
    ModelInvocationPayload,
    OutputTokenProcessedPayload,
)
from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.models.request_identity import RequestIdentity
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.app_config import get_app_config

logger = logging.getLogger(get_app_config().log_config.logger_name)


@dataclass(frozen=True)
class Tokens:
    """The tokens of one call. None is "not reported": nothing is emitted for it."""

    input: int | float | None = None
    output: int | None = None
    cached: int | None = None
    cache_5m: int | None = None
    cache_1h: int | None = None


@dataclass(frozen=True)
class Call:
    """Who a model call is for, and what kind of model it calls."""

    identity: RequestIdentity
    model_type: str
    target_model_id: str
    is_semantic_search: bool = False
    is_judge: bool = False
    is_routing: bool = False


class Recorder:
    """Emits the events and metrics of model calls, priced by ``cost_service``."""

    def __init__(self, cost_service: CostService):
        self.cost_service = cost_service

    def invocation(
        self,
        call: Call,
        model: Model,
        latency_ms: float,
        tokens: Tokens = Tokens(),
        fallback_triggered: bool = False,
    ) -> None:
        """Record one invocation of ``model``: the invocation, its tokens, and
        the fallback when ``fallback_triggered``.
        """
        self.record(
            **call.identity.event_fields(),
            target_model_id=call.target_model_id,
            model=model,
            latency_ms=latency_ms,
            model_type=call.model_type,
            token_input_count=tokens.input,
            token_output_count=tokens.output,
            cached_token_count=tokens.cached,
            cache_creation_5m_token_count=tokens.cache_5m,
            cache_creation_1h_token_count=tokens.cache_1h,
            fallback_triggered=fallback_triggered,
            is_semantic_search=call.is_semantic_search,
            is_judge=call.is_judge,
            is_routing=call.is_routing,
        )

    def failure(
        self, call: Call, model: Model, latency_ms: float, fallback_triggered: bool
    ) -> None:
        """Record a call that got no answer: the invocation of the last model
        tried, and the fallback when one was tried. No tokens.
        """
        self.invocation(call, model, latency_ms, fallback_triggered=fallback_triggered)

    def input_tokens(
        self,
        request_uuid: str,
        api_key_uuid: str,
        api_key_name: str,
        group_name: str,
        group_uuid: str,
        route_name: str,
        model: Model,
        model_type: str,
        token_count: int | float,
        where: str,
        cache_type: str | None,
        is_cached_tokens: bool = False,
        project_uuid: str = '',
        project_name: str = '',
        is_judge: bool = False,
        is_routing: bool = False,
    ) -> Decimal:
        cost = self.cost_service.compute_cost(
            model_id=model.model_id,
            token_processed=token_count,
            where=where,
        )
        emit_event(
            InputTokenProcessedPayload(
                request_uuid=request_uuid,
                event_type=EventType.INPUT_TOKEN_PROCESSED,
                route_name=route_name,
                value=token_count,
                api_key_uuid=api_key_uuid,
                group_uuid=group_uuid,
                api_key_name=api_key_name,
                group_name=group_name,
                cost=cost,
                model_id=model.model_id,
                model_type=model_type,
                cache_type=cache_type,
                is_cached_tokens=is_cached_tokens,
                project_uuid=project_uuid,
                project_name=project_name,
                is_judge=is_judge,
                is_routing=is_routing,
            )
        )
        total_tokens_counter_input.add(
            token_count,
            {'route_name': route_name, 'model_name': model.model_id},
        )
        tokens_per_request_histogram_input.record(
            token_count,
            {'route_name': route_name, 'model_name': model.model_id},
        )
        return cost

    def output_tokens(
        self,
        request_uuid: str,
        api_key_uuid: str,
        api_key_name: str,
        group_name: str,
        group_uuid: str,
        route_name: str,
        model: Model,
        model_type: str,
        token_count: int | float,
        cache_type: str | None = None,
        project_uuid: str = '',
        project_name: str = '',
        is_judge: bool = False,
        is_routing: bool = False,
    ) -> Decimal:
        cost = self.cost_service.compute_cost(
            model_id=model.model_id,
            token_processed=token_count,
            where='output',
        )
        emit_event(
            OutputTokenProcessedPayload(
                request_uuid=request_uuid,
                event_type=EventType.OUTPUT_TOKEN_PROCESSED,
                route_name=route_name,
                value=token_count,
                api_key_uuid=api_key_uuid,
                group_uuid=group_uuid,
                api_key_name=api_key_name,
                group_name=group_name,
                cost=cost,
                model_id=model.model_id,
                model_type=model_type,
                cache_type=cache_type,
                project_uuid=project_uuid,
                project_name=project_name,
                is_judge=is_judge,
                is_routing=is_routing,
            )
        )
        total_tokens_counter_output.add(
            token_count,
            {'route_name': route_name, 'model_name': model.model_id},
        )
        tokens_per_request_histogram_output.record(
            token_count,
            {'route_name': route_name, 'model_name': model.model_id},
        )
        return cost

    def record(
        self,
        request_uuid: str,
        api_key_uuid: str,
        api_key_name: str,
        group_name: str,
        group_uuid: str,
        route_name: str,
        target_model_id: str,
        model: Model,
        latency_ms: float,
        model_type: str,
        token_input_count: int | None = None,
        token_output_count: int | None = None,
        cached_token_count: int | None = None,
        cache_creation_5m_token_count: int | None = None,
        cache_creation_1h_token_count: int | None = None,
        fallback_triggered: bool = False,
        is_semantic_search: bool = False,
        project_uuid: str = '',
        project_name: str = '',
        is_judge: bool = False,
        is_routing: bool = False,
    ) -> None:
        cache_type = 'semantic' if is_semantic_search else None
        emit_event(
            ModelInvocationPayload(
                request_uuid=request_uuid,
                event_type=EventType.MODEL_INVOCATION,
                route_name=route_name,
                value=1.0,
                api_key_uuid=api_key_uuid,
                group_uuid=group_uuid,
                api_key_name=api_key_name,
                group_name=group_name,
                model_id=model.model_id,
                model_type=model_type,
                cache_type=cache_type,
                project_uuid=project_uuid,
                project_name=project_name,
                is_judge=is_judge,
                is_routing=is_routing,
            )
        )
        model_invocations_counter.add(
            1, {'route_name': route_name, 'model_name': model.model_id}
        )
        invocations_latency_histogram.record(
            latency_ms, {'route_name': route_name, 'model_name': model.model_id}
        )

        # (count, cost_where, event_cache_type, is_cached_tokens, skip_if_zero)
        input_token_entries = [
            (token_input_count, 'input', cache_type, False, False),
            (cached_token_count, 'cached', 'read', True, True),
            (cache_creation_5m_token_count, 'cached_creation', 'creation', True, True),
            (
                cache_creation_1h_token_count,
                'cached_creation_1h',
                'creation_1h',
                True,
                True,
            ),
        ]
        common = {
            'request_uuid': request_uuid,
            'api_key_uuid': api_key_uuid,
            'api_key_name': api_key_name,
            'group_name': group_name,
            'group_uuid': group_uuid,
            'route_name': route_name,
            'model': model,
            'model_type': model_type,
            'project_uuid': project_uuid,
            'project_name': project_name,
            'is_judge': is_judge,
            'is_routing': is_routing,
        }
        for count, where, ct, is_cached, skip_if_zero in input_token_entries:
            if count is not None and (not skip_if_zero or count > 0):
                self.input_tokens(
                    **common,
                    token_count=count,
                    where=where,
                    cache_type=ct,
                    is_cached_tokens=is_cached,
                )

        if token_output_count is not None:
            self.output_tokens(
                **common,
                token_count=token_output_count,
                cache_type=cache_type,
            )

        if fallback_triggered:
            emit_event(
                FallbackEventPayload(
                    request_uuid=request_uuid,
                    event_type=EventType.FALLBACK,
                    route_name=route_name,
                    value=1.0,
                    api_key_uuid=api_key_uuid,
                    group_uuid=group_uuid,
                    api_key_name=api_key_name,
                    group_name=group_name,
                    project_uuid=project_uuid,
                    project_name=project_name,
                    target=target_model_id,
                    fallback=model.model_id,
                    is_judge=is_judge,
                    is_routing=is_routing,
                )
            )
            fallbacks_triggered_counter.add(
                1,
                {
                    'route_name': route_name,
                    'target': target_model_id,
                    'fallback': model.model_id,
                },
            )

    def transcription_usage(self, call: Call, model: Model, usage: Any) -> Decimal:
        """Record what a transcription's ``usage`` costs: seconds, or audio,
        text and output tokens.
        """
        if usage is None:
            return Decimal(0)
        identity = call.identity
        common = {
            'request_uuid': identity.request_uuid,
            'api_key_uuid': identity.api_key_uuid,
            'api_key_name': identity.api_key_name,
            'group_name': identity.group_name,
            'group_uuid': identity.group_uuid,
            'route_name': identity.route_name,
            'model': model,
            'model_type': call.model_type,
            'project_uuid': identity.project_uuid,
            'project_name': identity.project_name,
        }

        if usage.type == 'duration':
            return self.input_tokens(
                **common,
                token_count=usage.seconds,
                where='duration',
                cache_type='duration',
            )

        details = getattr(usage, 'input_token_details', None)
        audio_tokens = getattr(details, 'audio_tokens', None) or 0
        text_tokens = getattr(details, 'text_tokens', None)
        if text_tokens is None:
            text_tokens = usage.input_tokens

        total_cost = Decimal(0)
        if audio_tokens > 0:
            total_cost += self.input_tokens(
                **common,
                token_count=audio_tokens,
                where='audio',
                cache_type='audio',
            )
        if text_tokens > 0:
            total_cost += self.input_tokens(
                **common,
                token_count=text_tokens,
                where='input',
                cache_type=None,
            )
        if usage.output_tokens > 0:
            total_cost += self.output_tokens(
                **common,
                token_count=usage.output_tokens,
            )
        return total_cost
