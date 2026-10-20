from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import HumanMessage
import pytest

from tests.common.mocked_gateway_config_openai import get_gateway_routing_llm
from tests.common.resolve_route_models import resolve_route_models

from radicalbit_ai_gateway.ai_gateway import GatewayRoute
from radicalbit_ai_gateway.guardrails.guardrail_engine import GuardrailEngine
from radicalbit_ai_gateway.models.credentials import Credentials
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.models.request_identity import RequestIdentity
from radicalbit_ai_gateway.routing import DeterministicRouter, LLMRouter, SemanticRouter
from radicalbit_ai_gateway.routing.usage import RoutingUsage
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.exceptions import (
    InputTokenLimitExceeded,
    OutputTokenLimitExceeded,
)

IDENTITY = RequestIdentity(
    request_uuid='req-1',
    route_name='smart_route',
    api_key_uuid='key-1',
    api_key_name='rb-key',
    group_uuid='group-1',
    group_name='test-group',
)

ROUTER_MODEL = Model(
    model_id='router_model',
    model='openai/gpt-4o-mini',
    credentials=Credentials(api_key='sk-dummy'),
    input_cost_per_million_tokens=Decimal('0.15'),
    output_cost_per_million_tokens=Decimal('0.6'),
)


def _build_gateway(router=None) -> tuple[GatewayRoute, MagicMock, MagicMock]:
    route_cfg, chat_models, embedding_models = resolve_route_models(
        get_gateway_routing_llm(), 'smart_route'
    )
    token_limiter = MagicMock(
        count_input=AsyncMock(),
        count_output=AsyncMock(),
        check_input_room=AsyncMock(),
        check_output=AsyncMock(),
    )
    budget_limiter = MagicMock(
        count_input=AsyncMock(),
        count_output=AsyncMock(),
        check_budget=AsyncMock(),
    )
    gateway = GatewayRoute(
        gateway_route_config=route_cfg,
        chat_models=chat_models,
        embedding_models=embedding_models,
        guardrail_engine=MagicMock(spec_set=GuardrailEngine),
        gateway_cache=None,
        cost_service=MagicMock(spec_set=CostService),
        router=router,
        token_limiter=token_limiter,
        budget_limiter=budget_limiter,
    )
    gateway.chat_invoker._record_metrics = MagicMock()
    return gateway, token_limiter, budget_limiter


async def test_router_usage_is_costed_and_counted_against_limits():
    gateway, token_limiter, budget_limiter = _build_gateway()
    usage = RoutingUsage(
        model=ROUTER_MODEL,
        model_type='chat-model',
        latency_ms=12.0,
        input_tokens=120,
        output_tokens=15,
    )

    await gateway._record_routing_usage(usage, IDENTITY)

    gateway.chat_invoker._record_metrics.assert_called_once()
    metrics = gateway.chat_invoker._record_metrics.call_args.kwargs
    assert metrics['model'] == ROUTER_MODEL
    assert metrics['model_type'] == 'chat-model'
    assert metrics['token_input_count'] == 120
    assert metrics['token_output_count'] == 15
    assert metrics['request_uuid'] == 'req-1'
    assert metrics['routing_name'] == 'llm_routing'

    token_limiter.count_input.assert_awaited_once_with(
        prompt_tokens=120, identity=IDENTITY
    )
    token_limiter.count_output.assert_awaited_once_with(
        token_count=15, identity=IDENTITY
    )
    budget_limiter.count_input.assert_awaited_once_with(
        token_count=120,
        input_cost_per_token=ROUTER_MODEL.input_cost_per_token,
        identity=IDENTITY,
    )
    budget_limiter.count_output.assert_awaited_once_with(
        token_count=15,
        output_cost_per_token=ROUTER_MODEL.output_cost_per_token,
        identity=IDENTITY,
    )


async def test_select_chat_model_passes_usage_to_the_gateway():
    usage = RoutingUsage(
        model=ROUTER_MODEL,
        model_type='chat-model',
        latency_ms=12.0,
        input_tokens=120,
        output_tokens=15,
    )
    config = get_gateway_routing_llm()
    selected = config.chat_models_by_id['code_model']

    async def _select_model(_messages, on_usage=None):
        await on_usage(usage)
        return selected

    router = MagicMock()
    router.select_model = AsyncMock(side_effect=_select_model)
    gateway, token_limiter, _ = _build_gateway(router=router)

    result = await gateway._select_chat_model(
        [HumanMessage(content='fix this bug')], identity=IDENTITY
    )

    assert result == selected
    gateway.chat_invoker._record_metrics.assert_called_once()
    token_limiter.count_input.assert_awaited_once_with(
        prompt_tokens=120, identity=IDENTITY
    )


def _router(router_class) -> MagicMock:
    router = MagicMock(spec=router_class)
    router.select_model = AsyncMock(side_effect=RuntimeError('routed'))
    return router


async def _prepare(gateway: GatewayRoute):
    return await gateway._prepare_and_validate_request(
        request_uuid='req-1',
        api_key_uuid='key-1',
        group_uuid='group-1',
        api_key_name='rb-key',
        group_name='test-group',
        route_name='smart_route',
        messages=[HumanMessage(content='fix this bug')],
        tools=None,
        tool_choice=None,
    )


@pytest.mark.parametrize('router_class', [LLMRouter, SemanticRouter])
async def test_full_input_counter_blocks_before_paid_routing(router_class):
    router = _router(router_class)
    gateway, token_limiter, _ = _build_gateway(router=router)
    token_limiter.check_input_room.side_effect = InputTokenLimitExceeded('full')

    with pytest.raises(InputTokenLimitExceeded):
        await _prepare(gateway)

    router.select_model.assert_not_awaited()


async def test_full_output_counter_blocks_before_paid_routing():
    router = _router(LLMRouter)
    gateway, token_limiter, _ = _build_gateway(router=router)
    token_limiter.check_output.side_effect = OutputTokenLimitExceeded('full')

    with pytest.raises(OutputTokenLimitExceeded):
        await _prepare(gateway)

    router.select_model.assert_not_awaited()


async def test_room_left_lets_paid_routing_run():
    router = _router(LLMRouter)
    gateway, token_limiter, budget_limiter = _build_gateway(router=router)

    with pytest.raises(RuntimeError, match='routed'):
        await _prepare(gateway)

    budget_limiter.check_budget.assert_awaited_once()
    token_limiter.check_input_room.assert_awaited_once()
    token_limiter.check_output.assert_awaited_once()
    router.select_model.assert_awaited_once()


async def test_free_router_is_not_prechecked():
    router = _router(DeterministicRouter)
    gateway, token_limiter, budget_limiter = _build_gateway(router=router)

    with pytest.raises(RuntimeError, match='routed'):
        await _prepare(gateway)

    budget_limiter.check_budget.assert_not_awaited()
    token_limiter.check_input_room.assert_not_awaited()


def _emitted_usage_events(gateway: GatewayRoute, **kwargs) -> list:
    gateway.chat_invoker.cost_service = MagicMock(spec_set=CostService)
    gateway.chat_invoker.cost_service.compute_cost.return_value = Decimal('0.1')
    with patch(
        'radicalbit_ai_gateway.invocation.model_invoker.emit_event'
    ) as emit_event:
        # _build_gateway mocks _record_metrics: call the real one.
        type(gateway.chat_invoker)._record_metrics(
            gateway.chat_invoker,
            request_uuid='req-1',
            api_key_uuid='key-1',
            api_key_name='rb-key',
            group_name='test-group',
            group_uuid='group-1',
            route_name='smart_route',
            target_model_id='router_model',
            model=ROUTER_MODEL,
            latency_ms=12.0,
            model_type='chat-model',
            token_input_count=120,
            token_output_count=15,
            **kwargs,
        )
    return [call.args[0] for call in emit_event.call_args_list]


def test_router_usage_events_carry_the_routing_name():
    gateway, _, _ = _build_gateway()
    events = _emitted_usage_events(gateway, routing_name='llm_routing')

    assert [e.event_type for e in events] == [
        'MODEL_INVOCATION',
        'INPUT_TOKEN_PROCESSED',
        'OUTPUT_TOKEN_PROCESSED',
    ]
    for event in events:
        assert event.model_dump(exclude_none=True)['routing_name'] == 'llm_routing'


def test_other_usage_events_carry_no_routing_name():
    gateway, _, _ = _build_gateway()
    events = _emitted_usage_events(gateway)

    assert len(events) == 3
    for event in events:
        assert 'routing_name' not in event.model_dump(exclude_none=True)
