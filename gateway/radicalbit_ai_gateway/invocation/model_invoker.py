from collections.abc import Callable
import logging
from typing import Any, TypeAlias

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
from radicalbit_ai_gateway.models.fallback import Fallback
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.app_config import get_app_config

app_config = get_app_config()

logger = logging.getLogger(app_config.log_config.logger_name)

PrimaryModel: TypeAlias = Any
FallbackModels: TypeAlias = list[tuple[Model, Any]]


class ModelInvoker:
    def __init__(
        self,
        models: list[Model],
        cost_service: CostService,
        fallbacks: list[Fallback] | None = None,
        httpx_client=None,
    ):
        self.models = models
        self.cost_service = cost_service
        self.fallbacks = fallbacks
        self.httpx_client = httpx_client
        self.model_map: dict[str, tuple[Model, PrimaryModel, FallbackModels]] = {}

    def _initialize_models(self, build_fn: Callable[[Model], Any]):
        models_lookup: dict[str, Model] = {m.model_id: m for m in self.models}

        fallback_lookup: dict[str, list[str]] = {}
        if self.fallbacks:
            for f in self.fallbacks:
                fallback_lookup.setdefault(f.target, []).extend(f.fallbacks)

        for model in self.models:
            model_id = model.model_id
            primary_runnable = build_fn(model)
            fallbacks_runnable = []
            for f in fallback_lookup.get(model_id, []):
                fallback_model = models_lookup.get(f)
                if fallback_model:
                    try:
                        runnable = build_fn(fallback_model)
                        fallbacks_runnable.append((fallback_model, runnable))
                    except Exception as e:
                        logger.warning(
                            'Failed to create fallback model %s for target %s: %s',
                            fallback_model.model_id,
                            model_id,
                            str(e),
                        )
            self.model_map[model_id] = (model, primary_runnable, fallbacks_runnable)

    def _build_model(self, model: Model):
        raise NotImplementedError

    @staticmethod
    def _unwrap_fallbacks(fallbacks: FallbackModels) -> list:
        return [runnable for _, runnable in fallbacks]

    def _emit_input_token_metrics(
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
    ):
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

    def _emit_output_token_metrics(
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
    ):
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

    def _record_metrics(
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
    ):
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
        }
        for count, where, ct, is_cached, skip_if_zero in input_token_entries:
            if count is not None and (not skip_if_zero or count > 0):
                self._emit_input_token_metrics(
                    **common,
                    token_count=count,
                    where=where,
                    cache_type=ct,
                    is_cached_tokens=is_cached,
                )

        if token_output_count is not None:
            self._emit_output_token_metrics(
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
