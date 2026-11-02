from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from tests.common.mocked_gateway_config_openai import get_gateway_routing_llm
from tests.common.resolve_route_models import resolve_route_models

from radicalbit_ai_gateway.ai_gateway import GatewayRoute
from radicalbit_ai_gateway.guardrails.guardrail_engine import GuardrailEngine
from radicalbit_ai_gateway.models.credentials import Credentials
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.models.request_identity import RequestIdentity
from radicalbit_ai_gateway.services.cost_service import CostService

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


def _build_gateway() -> tuple[GatewayRoute, MagicMock, MagicMock]:
    route_cfg, chat_models, embedding_models = resolve_route_models(
        get_gateway_routing_llm(), 'smart_route'
    )
    token_limiter = MagicMock(count_input=AsyncMock(), count_output=AsyncMock())
    budget_limiter = MagicMock(count_input=AsyncMock(), count_output=AsyncMock())
    gateway = GatewayRoute(
        gateway_route_config=route_cfg,
        chat_models=chat_models,
        embedding_models=embedding_models,
        guardrail_engine=MagicMock(spec_set=GuardrailEngine),
        gateway_cache=None,
        cost_service=MagicMock(spec_set=CostService),
        token_limiter=token_limiter,
        budget_limiter=budget_limiter,
    )
    return gateway, token_limiter, budget_limiter


async def test_chat_router_spend_counts_input_and_output():
    gateway, token_limiter, budget_limiter = _build_gateway()
    gateway.chat_invoker.record_routing_call = MagicMock()
    record = gateway._routing_spend_recorder(IDENTITY, gateway.chat_invoker)

    await record(ROUTER_MODEL, 120, 12.0, model_type='chat-model', output_tokens=15)

    call = gateway.chat_invoker.record_routing_call.call_args.kwargs
    assert call['input_tokens'] == 120
    assert call['output_tokens'] == 15
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


async def test_input_only_router_spend_counts_no_output():
    gateway, token_limiter, budget_limiter = _build_gateway()
    gateway.chat_invoker.record_routing_call = MagicMock()
    record = gateway._routing_spend_recorder(IDENTITY, gateway.chat_invoker)

    await record(ROUTER_MODEL, 120, 12.0, model_type='embeddings')

    token_limiter.count_input.assert_awaited_once()
    token_limiter.count_output.assert_not_awaited()
    budget_limiter.count_output.assert_not_awaited()


def test_chat_router_call_emits_output_tokens_flagged_as_routing():
    gateway, _, _ = _build_gateway()
    gateway.chat_invoker.cost_service = MagicMock(spec_set=CostService)
    gateway.chat_invoker.cost_service.compute_cost.return_value = Decimal('0.1')
    with patch(
        'radicalbit_ai_gateway.invocation.model_invoker.emit_event'
    ) as emit_event:
        gateway.chat_invoker.record_routing_call(
            identity=IDENTITY,
            model=ROUTER_MODEL,
            target_model_id=ROUTER_MODEL.model_id,
            input_tokens=120,
            latency_ms=12.0,
            model_type='chat-model',
            output_tokens=15,
        )
    events = [call.args[0] for call in emit_event.call_args_list]

    assert [e.event_type for e in events] == [
        'MODEL_INVOCATION',
        'INPUT_TOKEN_PROCESSED',
        'OUTPUT_TOKEN_PROCESSED',
    ]
    assert all(e.is_routing for e in events)
