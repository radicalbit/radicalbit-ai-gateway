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


def test_from_dao_no_semantic_cache():
    """Test CostDataDTO.from_dao when semantic_cache_cost_data is None."""
    cost_data = CostData(
        input_cost=10.0,
        output_cost=20.0,
        total_cost=30.0,
        cache_triggered=5,
        saved_amount_input=0.1,
        saved_amount_output=0.2,
        total_saved_amount=0.3,
    )

    result = CostDataDTO.from_dao(cost_data, None)

    assert result.input_cost == 10.0
    assert result.output_cost == 20.0
    assert result.total_cost == 30.0
    assert result.cache_triggered == 5
    assert result.saved_amount_input == 0.1
    assert result.saved_amount_output == 0.2
    assert result.total_saved_amount == 0.3


def test_from_dao_with_semantic_cache_full():
    """Test CostDataDTO.from_dao with all semantic cache fields populated."""
    cost_data = CostData(
        input_cost=10.0,
        output_cost=20.0,
        total_cost=30.0,
        cache_triggered=2,
        cache_saved_tokens_input=100,
        cache_saved_tokens_output=200,
        saved_amount_input=0.05,
        saved_amount_output=0.10,
        total_cached_tokens=300,
        total_saved_amount=0.15,
    )

    semantic_cache_data = SemanticCacheCostData(
        embedding_inference_cost=0.01,
        cache_triggered=3,
        cache_saved_tokens_input=50,
        cache_saved_tokens_output=100,
        llm_input_request_savings=0.02,
        llm_output_request_savings=0.04,
        llm_total_request_savings=0.06,
        total_cached_tokens=150,
        net_savings=0.05,  # 0.06 - 0.01
    )

    result = CostDataDTO.from_dao(cost_data, semantic_cache_data)

    assert result.input_cost == 10.01  # 10.0 + 0.01
    assert result.output_cost == 20.0
    assert result.total_cost == 30.01  # 30.0 + 0.01
    assert result.cache_triggered == 5  # 2 + 3
    assert result.cache_saved_tokens_input == 150  # 100 + 50
    assert result.cache_saved_tokens_output == 300  # 200 + 100
    assert result.saved_amount_input == 0.07  # 0.05 + 0.02
    assert result.saved_amount_output == 0.14  # 0.10 + 0.04
    assert result.total_cached_tokens == 450  # 300 + 150
    assert result.total_saved_amount == 0.20  # 0.15 + 0.05


def test_from_dao_semantic_cache_zero_values():
    """Test CostDataDTO.from_dao when semantic cache has zero/falsy values."""
    cost_data = CostData(
        input_cost=10.0,
        output_cost=20.0,
        total_cost=30.0,
    )

    semantic_cache_data = SemanticCacheCostData(
        embedding_inference_cost=0.0,
        cache_triggered=0,
        llm_input_request_savings=0.0,
        llm_output_request_savings=0.0,
        llm_total_request_savings=0.0,
        net_savings=0.0,
    )

    result = CostDataDTO.from_dao(cost_data, semantic_cache_data)

    # With zero embedding cost, input_cost and total_cost should remain unchanged
    assert result.input_cost == 10.0
    assert result.output_cost == 20.0
    assert result.total_cost == 30.0


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
