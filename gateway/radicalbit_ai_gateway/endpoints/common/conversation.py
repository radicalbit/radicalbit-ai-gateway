"""What chat and Responses requests share: their limit check, their routing
and the route's system prompt.
"""

import logging

from traceloop.sdk.decorators import task

from radicalbit_ai_gateway.endpoints.common.messages import select_message_by_role
from radicalbit_ai_gateway.events.events_processor import emit_event
from radicalbit_ai_gateway.gateway_route.scope import RequestScope
from radicalbit_ai_gateway.invocation.model_invoker import ModelInvoker
from radicalbit_ai_gateway.invocation.recorder import Call, Tokens
from radicalbit_ai_gateway.limiting.limits import (
    Demand,
    InputEstimate,
    RequestLimits,
    Usage,
)
from radicalbit_ai_gateway.llm.messages import BaseMessage, SystemMessage
from radicalbit_ai_gateway.models.event_payload import RoutingEventPayload
from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.models.model import ENABLE_PROMPT_CACHE_PARAM, Model
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.build_user_content import build_user_content
from radicalbit_ai_gateway.utils.trace_attributes import (
    OperationCategory,
    set_operation_category,
)

logger = logging.getLogger(get_app_config().log_config.logger_name)


def chat_demand(messages: list[BaseMessage], model: Model) -> Demand:
    """Return what a chat request demands; ``model`` picks the tokenizer."""
    return Demand(
        input=InputEstimate(build_user_content(messages), model.model),
        output_room=True,
        cost_room=True,
    )


async def _check(limits: RequestLimits, demand: Demand) -> None:
    await limits.check(demand)


def checked_in_span(name: str):
    """Return a limit check that runs in a trace span named ``name``."""
    return task(name=name)(_check)


_check_in_chat_span = checked_in_span('check_limiters')


async def check_limits(limits: RequestLimits, demand: Demand, check=None) -> None:
    """Check ``demand`` on the request's limits, if any applies.

    ``check`` runs the check in a trace span of its own.
    """
    if limits.applies(demand):
        await (check or _check)(limits, demand)


async def check_chat_limits(scope: RequestScope, messages: list[BaseMessage]) -> None:
    """Check a conversation on the request's limits, before anything spends.
    Routing has not run yet: the route's first chat model picks the
    tokenizer.
    """
    await check_limits(
        scope.limits,
        chat_demand(messages, scope.route.chat_models[0]),
        _check_in_chat_span,
    )


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


def apply_config_prompt(messages: list[BaseMessage], model_selected: Model) -> int:
    """Prepend the route's configured system prompt to *messages* in place.

    Runs *after* preprocessing so the configured prompt is never exposed to
    preprocessing plugins. Return how many messages it added (0 or 1).
    """
    config_prompt, role = model_selected.effective_prompt, model_selected.role

    logger.debug(
        'Config prompt for model %s: %s and role: %s',
        model_selected.model_id,
        config_prompt,
        role,
    )

    if config_prompt:
        logger.debug('Adding config prompt to messages')
        enable_prompt_cache = bool(
            (model_selected.params or {}).get(ENABLE_PROMPT_CACHE_PARAM, False)
        )
        if model_selected.model.startswith('anthropic/') and enable_prompt_cache:
            # Wrap the system prompt as a content block with cache_control so Anthropic
            # caches it across requests (requires enable_prompt_cache: true in model params)
            system_msg = SystemMessage(
                content=[
                    {
                        'type': 'text',
                        'text': config_prompt,
                        'cache_control': {'type': 'ephemeral'},
                    }
                ]
            )
        else:
            system_msg = select_message_by_role(
                content=config_prompt, role=role, tool_calls=[], tool_call_id=None
            )
        messages[:] = [system_msg, *messages]
        return 1
    return 0
