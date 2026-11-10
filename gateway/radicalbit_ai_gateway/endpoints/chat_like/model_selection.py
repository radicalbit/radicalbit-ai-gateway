"""Selecting the model of a chat-like request, and charging the request for
the routing calls that select it.
"""

import logging

from traceloop.sdk.decorators import task

from radicalbit_ai_gateway.events.events_processor import emit_event
from radicalbit_ai_gateway.gateway_route.scope import RequestScope
from radicalbit_ai_gateway.invocation.model_invoker import ModelInvoker
from radicalbit_ai_gateway.invocation.recorder import Call, Tokens
from radicalbit_ai_gateway.limiting.limits import RequestLimits, Usage
from radicalbit_ai_gateway.llm.messages import BaseMessage
from radicalbit_ai_gateway.models.event_payload import RoutingEventPayload
from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.trace_attributes import (
    OperationCategory,
    set_operation_category,
)

logger = logging.getLogger(get_app_config().log_config.logger_name)


class RoutingSpend:
    """Charges a request for its routing calls: see ``RoutingSpendRecorder``."""

    def __init__(self, limits: RequestLimits, metrics: ModelInvoker):
        self._limits = limits
        self._metrics = metrics

    async def __call__(
        self,
        model: Model,
        input_tokens: int,
        latency_ms: float,
        *,
        model_type: str,
        target_model_id: str | None = None,
        output_tokens: int | None = None,
    ) -> None:
        target_model_id = target_model_id or model.model_id
        self._metrics.recorder.invocation(
            Call(
                identity=self._limits.identity,
                model_type=model_type,
                target_model_id=target_model_id,
                is_routing=True,
            ),
            model,
            latency_ms,
            tokens=Tokens(input=input_tokens, output=output_tokens),
            fallback_triggered=target_model_id != model.model_id,
        )
        if output_tokens is None:
            # Embedding and decision calls bill input tokens only.
            if input_tokens > 0:
                await self._limits.count(Usage.priced(model, input_tokens))
        else:
            # A chat model router also bills the tokens it answers with.
            await self._limits.charge_call(model, input_tokens, output_tokens)

    def failed(
        self, model: Model, latency_ms: float, *, model_type: str, target_model_id: str
    ) -> None:
        self._metrics.recorder.failure(
            Call(
                identity=self._limits.identity,
                model_type=model_type,
                target_model_id=target_model_id,
                is_routing=True,
            ),
            model,
            latency_ms,
            fallback_triggered=model.model_id != target_model_id,
        )


@task(name='select_model')
async def _select_chat_model(scope: RequestScope, messages: list[BaseMessage]) -> Model:
    """Select the chat model for this request based on the routing config."""
    route = scope.route
    if route.router:
        # Routing runs on chat routes: the chat invoker emits its cost events.
        model_selected = await route.router.select_model(
            messages,
            RoutingSpend(scope.limits, route.chat_invoker)
            if route.chat_invoker
            else None,
        )
    else:
        model_selected = route.chat_models[0]

    logger.debug('Selected chat model: %s', model_selected.model_id)

    return model_selected


async def route_chat(scope: RequestScope, messages: list[BaseMessage]) -> Model:
    """Select the chat model of a request and record the routing decision."""
    set_operation_category(OperationCategory.ROUTING)
    model_selected = await _select_chat_model(scope, messages)

    config = scope.route.gateway_route_config
    if scope.route.router and config.routing:
        emit_event(
            RoutingEventPayload(
                value=1.0,
                event_type=EventType.ROUTING,
                **scope.identity.event_fields(),
                routing_name=config.routing,
                selected_model_id=model_selected.model_id,
            )
        )
    return model_selected
