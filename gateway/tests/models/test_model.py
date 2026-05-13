from decimal import Decimal
from unittest.mock import Mock

import pytest

from tests.common.mocked_gateway_config import get_chat_models

from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.prompt_manager import PromptManager


def test_costs_model_in_config():
    model = get_chat_models()[0]
    assert model.input_cost_per_million_tokens == Decimal('0.3')
    assert model.output_cost_per_million_tokens == Decimal('0.6')
    assert model.input_cached_cost_per_million_tokens == Decimal('0.03')
    assert model.input_cost_per_token == Decimal('3e-07')
    assert model.output_cost_per_token == Decimal('6e-07')
    assert model.input_cached_cost_per_token == Decimal('3e-08')


def test_costs_from_file():
    model = get_chat_models(third_model='deepseek/deepseek-r1')[2]
    assert model.input_cost_per_million_tokens == Decimal('0.55')
    assert model.output_cost_per_million_tokens == Decimal('0.4')
    assert model.input_cached_cost_per_million_tokens == Decimal('0.0')
    assert model.input_cost_per_token == Decimal('5.5e-07')
    assert model.output_cost_per_token == Decimal('4e-07')
    assert model.input_cached_cost_per_token == Decimal('0.0')


def test_costs_file_and_config():
    model = get_chat_models(second_model='azure/gpt-4.1-nano-2025-04-14')[1]
    assert model.input_cost_per_million_tokens == Decimal('0.2')
    assert model.output_cost_per_million_tokens == Decimal('0.4')
    assert model.input_cached_cost_per_million_tokens == Decimal('0.02')
    assert model.input_cost_per_token == Decimal('2e-07')
    assert model.output_cost_per_token == Decimal('4e-07')
    assert model.input_cached_cost_per_token == Decimal('2e-8')


def test_costs_model_openai():
    model = get_chat_models(second_model='openai/gpt-4o')[1]
    assert model.input_cost_per_million_tokens == Decimal('0.2')
    assert model.output_cost_per_million_tokens == Decimal('10')
    assert model.input_cached_cost_per_million_tokens == Decimal('0.02')
    assert model.input_cost_per_token == Decimal('2e-07')
    assert model.output_cost_per_token == Decimal('1e-05')
    assert model.input_cached_cost_per_token == Decimal('2e-8')


def test_costs_ollama():
    model = get_chat_models(third_model='openai/llama-3.2')[2]
    assert model.input_cost_per_million_tokens == Decimal('0.0')
    assert model.output_cost_per_million_tokens == Decimal('0.4')
    assert model.input_cached_cost_per_million_tokens == Decimal('0.0')
    assert model.input_cost_per_token == Decimal('0')
    assert model.output_cost_per_token == Decimal('4e-07')
    assert model.input_cached_cost_per_token == Decimal('0')


def test_cache_creation_cost_loaded_from_prices():
    # claude-sonnet-4-6 has cache_creation_input_token_cost: 3.75e-06 in model_prices.json
    model = Model(model_id='sonnet', model='anthropic/claude-sonnet-4-6')
    assert model.input_cache_creation_5m_cost_per_million_tokens > Decimal('0')
    assert model.input_cache_creation_5m_cost_per_token > Decimal('0')


def test_cache_creation_cost_overridden_by_config():
    model = Model(
        model_id='sonnet',
        model='anthropic/claude-sonnet-4-6',
        input_cache_creation_5m_cost_per_million_tokens=Decimal('9.99'),
    )
    assert model.input_cache_creation_5m_cost_per_million_tokens == Decimal('9.99')


def test_openai_model_has_no_cache_creation_cost():
    model = Model(model_id='gpt4o', model='openai/gpt-4o')
    assert model.input_cache_creation_5m_cost_per_million_tokens == Decimal('0')


def test_valid_model_with_prompt_and_role():
    model = Model(
        model_id='openai',
        model='openai/gpt-4o',
        prompt='You are a helpful assistant.',
        role='system',
    )
    assert model.prompt == 'You are a helpful assistant.'
    assert model.role == 'system'


def teardown_module(module):
    PromptManager._global_instance = None


def test_invalid_model_with_both_prompt_and_prompt_ref():
    with pytest.raises(
        ValueError, match="Only one between 'prompt' and 'prompt_ref' can be set"
    ):
        Model(
            model_id='openai',
            model='openai/gpt-4o',
            prompt='inline prompt',
            prompt_ref='jamie.md',
            role='system',
        )


def test_invalid_role_when_prompt_is_set():
    with pytest.raises(
        ValueError, match="role.*must be either 'system' or 'developer'"
    ):
        Model(
            model_id='openai',
            model='openai/gpt-4o',
            prompt='inline prompt',
            role='user',
        )


def test_invalid_role_when_prompt_ref_is_set():
    with pytest.raises(
        ValueError, match="role.*must be either 'system' or 'developer'"
    ):
        Model(
            model_id='openai',
            model='openai/gpt-4o',
            prompt_ref='jamie.md',
            role='assistant',
        )


def test_valid_prompt_ref_resolves_prompt_using_global_prompt_manager():
    pm = Mock(spec=PromptManager)
    pm.get_model_prompt.return_value = 'SYSTEM PROMPT FROM FILE'
    PromptManager.set_global(pm)

    model = Model(
        model_id='openai',
        model='openai/gpt-4o',
        prompt_ref='jamie.md',
        role='system',
    )

    assert model.effective_prompt == 'SYSTEM PROMPT FROM FILE'
    pm.get_model_prompt.assert_called_with('jamie.md')


def test_valid_model_with_no_prompt_fields_allows_defaults():
    model = Model(
        model_id='openai',
        model='openai/gpt-4o',
    )
    assert model.prompt is None
    assert model.prompt_ref is None
    assert model.role == 'system'
