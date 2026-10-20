from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from langchain_core.messages import HumanMessage

from tests.common.mocked_gateway_config_openai import get_gateway_routing_llm
from tests.common.resolve_route_models import resolve_route_models

from radicalbit_ai_gateway.ai_gateway import GatewayRoute
from radicalbit_ai_gateway.guardrails.guardrail_engine import GuardrailEngine
from radicalbit_ai_gateway.models.credentials import Credentials
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.models.request_identity import RequestIdentity
from radicalbit_ai_gateway.routing.usage import RoutingUsage
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


def _build_gateway(router=None) -> tuple[GatewayRoute, MagicMock, MagicMock]:
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
