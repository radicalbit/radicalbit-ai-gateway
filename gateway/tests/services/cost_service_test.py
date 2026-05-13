from decimal import Decimal
import unittest

import pytest

from tests.common.mocked_gateway_config import (
    get_default_cache_config,
    get_default_gateway,
    get_global_guardrails,
)

from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.services.cost_service import CostService


class CostServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global_guardrails = get_global_guardrails()

        gw_a = get_default_gateway(route_name='route-A')

        cls.gateway_config = GatewayConfig(
            chat_models=gw_a.chat_models,
            embedding_models=gw_a.embedding_models,
            routes={'route-A': gw_a.routes['route-A']},
            guardrails=global_guardrails,
            cache=get_default_cache_config(),
        )
        cls.cost_service = CostService(
            chat_models_by_id=cls.gateway_config.chat_models_by_id,
            embedding_models_by_id=cls.gateway_config.embedding_models_by_id,
        )

    def test_extract_model_costs(self):
        prices = CostService._extract_model_costs(
            self.gateway_config.chat_models_by_id,
            self.gateway_config.embedding_models_by_id,
        )
        assert prices is not None
        assert isinstance(prices, dict)
        assert prices == {
            'openai': (
                Decimal('3e-07'),
                Decimal('6e-07'),
                Decimal('3e-08'),
                Decimal('0'),
                Decimal('0'),
            ),
            'azure': (
                Decimal('2.e-07'),
                Decimal('0.0'),
                Decimal('2.e-08'),
                Decimal('0'),
                Decimal('0'),
            ),
            'deepseek': (
                Decimal('0.0'),
                Decimal('4e-07'),
                Decimal('0.0'),
                Decimal('0'),
                Decimal('0'),
            ),
            'text-embedding-3-small': (
                Decimal('2e-08'),
                Decimal('0.0'),
                Decimal('0.0'),
                Decimal('0'),
                Decimal('0'),
            ),
        }

    def test_compute_cost_input_tokens(self):
        # openai model has input cost of 3e-07 per token
        cost = self.cost_service.compute_cost(
            token_processed=1000,
            where='input',
            model_id='openai',
        )
        expected_cost = Decimal('1000') * Decimal('3e-07')
        assert cost == expected_cost

    def test_compute_cost_output_tokens(self):
        # openai model has output cost of 6e-07 per token
        cost = self.cost_service.compute_cost(
            token_processed=1000,
            where='output',
            model_id='openai',
        )
        expected_cost = Decimal('1000') * Decimal('6e-07')
        assert cost == expected_cost

    def test_compute_cost_zero_input_cost(self):
        # deepseek model has input cost of 0.0
        cost = self.cost_service.compute_cost(
            token_processed=500,
            where='input',
            model_id='deepseek',
        )
        assert cost == Decimal('0.0')

    def test_compute_cost_zero_output_cost(self):
        # azure model has output cost of 0.0
        cost = self.cost_service.compute_cost(
            token_processed=500,
            where='output',
            model_id='azure',
        )
        assert cost == Decimal('0.0')

    def test_compute_cost_embedding_model(self):
        # text-embedding-3-small has input cost of 2e-08 per token
        cost = self.cost_service.compute_cost(
            token_processed=2000,
            where='input',
            model_id='text-embedding-3-small',
        )
        expected_cost = Decimal('2000') * Decimal('2e-08')
        assert cost == expected_cost

    def test_compute_cost_cached_creation_tokens(self):
        # openai model has no cache_creation cost (Decimal 0), result should be 0
        cost = self.cost_service.compute_cost(
            token_processed=1000,
            where='cached_creation',
            model_id='openai',
        )
        assert cost == Decimal('0')

    def test_compute_cost_cached_creation_1h_tokens(self):
        # openai model has no cache_creation_1h cost (Decimal 0), result should be 0
        cost = self.cost_service.compute_cost(
            token_processed=1000,
            where='cached_creation_1h',
            model_id='openai',
        )
        assert cost == Decimal('0')

    def test_compute_cost_unknown_model_raises_unbound_local_error(self):
        with pytest.raises(UnboundLocalError):
            self.cost_service.compute_cost(
                token_processed=100,
                where='input',
                model_id='unknown-model',
            )
