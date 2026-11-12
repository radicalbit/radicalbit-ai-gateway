import pytest

from tests.common.mocked_gateway_config import (
    get_default_gateway,
    get_default_gateway_without_features,
    get_gateway_with_routing,
)

from radicalbit_ai_gateway.db.models.event import (
    CostData,
    DetailedCostBreakdown,
    SemanticCacheCostData,
)
from radicalbit_ai_gateway.models.event_dto import CostDataDTO, EventsDTO


def test_flags_event_dto():
    config = get_default_gateway()
    flags = EventsDTO._get_enablement_flags(config=config, route_name=None)
    assert isinstance(flags, dict)
    assert flags == {
        'fallback_enabled': True,
        'guardrail_enabled': True,
        'routing_enabled': False,
        'cache_enabled': False,
        'rate_limiting_enabled': True,
        'token_limiting_enabled': True,
        'duration_limiting_enabled': False,
    }


def test_flags_event_dto_route():
    config = get_default_gateway_without_features()
    flags = EventsDTO._get_enablement_flags(config=config, route_name='rb-gateway')
    assert isinstance(flags, dict)
    assert flags == {
        'fallback_enabled': False,
        'guardrail_enabled': False,
        'routing_enabled': False,
        'cache_enabled': True,
        'rate_limiting_enabled': True,
        'token_limiting_enabled': True,
        'duration_limiting_enabled': False,
    }


def test_flags_event_dto_routing_global():
    config = get_gateway_with_routing()
    flags = EventsDTO._get_enablement_flags(config=config, route_name=None)
    assert flags == {
        'fallback_enabled': False,
        'guardrail_enabled': False,
        'routing_enabled': True,
        'cache_enabled': False,
        'rate_limiting_enabled': False,
        'token_limiting_enabled': False,
        'duration_limiting_enabled': False,
    }


def test_flags_event_dto_routing_per_route():
    config = get_gateway_with_routing()
    flags = EventsDTO._get_enablement_flags(config=config, route_name='rb-gateway')
    assert flags == {
        'fallback_enabled': False,
        'guardrail_enabled': False,
        'routing_enabled': True,
        'cache_enabled': False,
        'rate_limiting_enabled': False,
        'token_limiting_enabled': False,
        'duration_limiting_enabled': False,
    }


COSTS = {'input_cost': 10.0, 'output_cost': 20.0, 'total_cost': 30.0}


@pytest.mark.parametrize(
    ('saved', 'semantic_net_savings', 'expected'),
    [
        pytest.param(0.3, None, 0.3, id='no_semantic_cache'),
        pytest.param(0.15, 0.05, 0.20, id='semantic_cache_savings_added'),
        pytest.param(0.15, 0.0, 0.15, id='semantic_cache_without_savings'),
        pytest.param(None, 0.05, None, id='nothing_saved'),
    ],
)
def test_from_dao_saved_amount(saved, semantic_net_savings, expected):
    """totals.saved is what the route saved, plus the semantic cache's net savings."""
    semantic = (
        None
        if semantic_net_savings is None
        else SemanticCacheCostData(net_savings=semantic_net_savings)
    )

    result = CostDataDTO.from_dao(
        CostData(**COSTS, total_saved_amount=saved), semantic, DetailedCostBreakdown()
    )

    assert result.totals.saved == pytest.approx(expected)


def test_from_dao_without_a_breakdown_serves_nothing():
    result = CostDataDTO.from_dao(CostData(**COSTS, total_saved_amount=0.3), None)

    assert result.model_dump(exclude_none=True) == {}


def test_from_dao_with_transcription_models():
    """CostDataDTO.from_dao builds a transcription_models breakdown parallel to
    chat/embedding, and folds it into totals/total when has_transcription_models.
    """
    cost_data = CostData(input_cost=0.0, output_cost=0.0, total_cost=0.0)
    detailed_breakdown = DetailedCostBreakdown(
        transcription_duration=0.000825,
        transcription_audio=0.000492,
        transcription_text=0.0000125,
        transcription_output=0.00038,
    )

    result = CostDataDTO.from_dao(
        cost_data,
        None,
        detailed_breakdown,
        has_chat_models=False,
        has_transcription_models=True,
    )

    assert result.transcription_models is not None
    assert result.transcription_models.input.duration == 0.000825
    assert result.transcription_models.input.audio == 0.000492
    assert result.transcription_models.input.text == 0.0000125
    assert result.transcription_models.input.total == (0.000825 + 0.000492 + 0.0000125)
    assert result.transcription_models.output == 0.00038
    assert result.transcription_models.total == (
        0.000825 + 0.000492 + 0.0000125 + 0.00038
    )
    assert result.totals is not None
    assert result.totals.input == result.transcription_models.input.total
    assert result.totals.output == 0.00038
    assert result.total == result.transcription_models.total


def test_from_dao_without_transcription_models_is_none():
    """has_transcription_models=False (default) keeps transcription_models unset."""
    cost_data = CostData(input_cost=0.0, output_cost=0.0, total_cost=0.0)
    detailed_breakdown = DetailedCostBreakdown()

    result = CostDataDTO.from_dao(
        cost_data, None, detailed_breakdown, has_chat_models=False
    )

    assert result.transcription_models is None


def test_from_dao_with_decision_models():
    """Decision input reaches decision_models, totals.input and total."""
    cost_data = CostData(input_cost=0.0, output_cost=0.0, total_cost=0.0)
    detailed_breakdown = DetailedCostBreakdown(
        chat_input_direct=0.5,
        chat_output_direct=1.0,
        decision_input=0.0000109,
    )

    result = CostDataDTO.from_dao(
        cost_data,
        None,
        detailed_breakdown,
        has_chat_models=True,
        has_decision_models=True,
    )

    assert result.decision_models is not None
    assert result.decision_models.input == 0.0000109
    assert result.decision_models.total == 0.0000109
    assert result.totals.input == 0.5 + 0.0000109
    assert result.totals.output == 1.0
    assert result.total == 0.5 + 1.0 + 0.0000109


def test_from_dao_with_decision_models_and_no_spend_is_zero():
    """A configured decision model with no spend reads $0, not missing."""
    cost_data = CostData(input_cost=0.0, output_cost=0.0, total_cost=0.0)

    result = CostDataDTO.from_dao(
        cost_data,
        None,
        DetailedCostBreakdown(),
        has_chat_models=False,
        has_decision_models=True,
    )

    assert result.decision_models is not None
    assert result.decision_models.input == 0.0
    assert result.decision_models.total == 0.0


def test_from_dao_without_decision_models_is_none():
    """has_decision_models=False (default) keeps decision_models unset."""
    cost_data = CostData(input_cost=0.0, output_cost=0.0, total_cost=0.0)

    result = CostDataDTO.from_dao(
        cost_data,
        None,
        DetailedCostBreakdown(decision_input=0.3),
        has_chat_models=False,
    )

    assert result.decision_models is None
    assert result.total == 0.0


def test_cost_data_dto_serializes_decision_models_in_camel_case():
    cost_data = CostData(input_cost=0.0, output_cost=0.0, total_cost=0.0)

    result = CostDataDTO.from_dao(
        cost_data,
        None,
        DetailedCostBreakdown(decision_input=0.25),
        has_chat_models=False,
        has_decision_models=True,
    )

    dumped = result.model_dump(by_alias=True)
    assert dumped['decisionModels'] == {'input': 0.25, 'total': 0.25}
