from decimal import Decimal
from unittest.mock import MagicMock, create_autospec, patch

from tests.common.mocked_gateway_config_openai import get_gateway_routing_llm
from tests.common.resolve_route_models import resolve_route_models

from radicalbit_ai_gateway.ai_gateway import GatewayRoute
from radicalbit_ai_gateway.limiting.limits import RequestLimits, Usage
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


def _build_gateway() -> GatewayRoute:
    route_cfg, chat_models, embedding_models = resolve_route_models(
        get_gateway_routing_llm(), 'smart_route'
    )
    return GatewayRoute(
        gateway_route_config=route_cfg,
        chat_models=chat_models,
        embedding_models=embedding_models,
        gateway_cache=None,
        cost_service=MagicMock(spec_set=CostService),
    )


def _limits() -> RequestLimits:
    limits = create_autospec(RequestLimits, instance=True)
    limits.identity = IDENTITY
    return limits


async def test_chat_router_spend_counts_input_and_output():
    gateway, limits = _build_gateway(), _limits()
    gateway.chat_invoker.recorder.record = MagicMock()
    record = gateway._routing_spend_recorder(limits, gateway.chat_invoker)

    await record(ROUTER_MODEL, 120, 12.0, model_type='chat-model', output_tokens=15)

    call = gateway.chat_invoker.recorder.record.call_args.kwargs
    assert call['request_uuid'] == IDENTITY.request_uuid
    assert call['is_routing'] is True
    assert call['token_input_count'] == 120
    assert call['token_output_count'] == 15
    limits.charge_call.assert_awaited_once_with(ROUTER_MODEL, 120, 15)


async def test_input_only_router_spend_counts_no_output():
    gateway, limits = _build_gateway(), _limits()
    gateway.chat_invoker.recorder.record = MagicMock()
    record = gateway._routing_spend_recorder(limits, gateway.chat_invoker)

    await record(ROUTER_MODEL, 120, 12.0, model_type='embeddings')

    limits.count.assert_awaited_once_with(Usage.priced(ROUTER_MODEL, 120))
    limits.charge_call.assert_not_awaited()


async def test_chat_router_call_emits_output_tokens_flagged_as_routing():
    gateway = _build_gateway()
    gateway.chat_invoker.recorder.cost_service.compute_cost.return_value = Decimal(
        '0.1'
    )
    record = gateway._routing_spend_recorder(_limits(), gateway.chat_invoker)
    with patch('radicalbit_ai_gateway.invocation.recorder.emit_event') as emit_event:
        await record(ROUTER_MODEL, 120, 12.0, model_type='chat-model', output_tokens=15)
    events = [call.args[0] for call in emit_event.call_args_list]

    assert [e.event_type for e in events] == [
        'MODEL_INVOCATION',
        'INPUT_TOKEN_PROCESSED',
        'OUTPUT_TOKEN_PROCESSED',
    ]
    assert all(e.is_routing for e in events)
