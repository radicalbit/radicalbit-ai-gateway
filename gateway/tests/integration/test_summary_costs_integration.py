"""Integration test suite for get_summary_costs service method.

This test uses real ClickHouse data to verify that cost aggregation works correctly
for the get_summary_costs service method in EventService.
"""

import datetime
from unittest.mock import MagicMock
import uuid

import pytest

from tests.common.db_integration_ch import DatabaseIntegrationClickhouse
from tests.common.db_mock import get_sample_event
from tests.common.mocked_gateway_config import (
    get_default_cache_config,
    get_default_gateway,
    get_default_gateway_with_caching,
    get_gateway_with_judge_and_semantic_cache,
    get_global_guardrails,
)

from radicalbit_ai_gateway.db.dao.event_dao import EventDAO
from radicalbit_ai_gateway.db.dao.request_event_dao import RequestEventDAO
from radicalbit_ai_gateway.models.caching import SemanticCaching
from radicalbit_ai_gateway.models.event_dto import (
    ChatModelsCachedInputBreakdownDTO,
    ChatModelsCostDTO,
    ChatModelsInputBreakdownDTO,
    ChatModelsOutputBreakdownDTO,
    CostDataDTO,
    EmbeddingInputBreakdownDTO,
    EmbeddingModelsCostDTO,
    TotalCostDTO,
)
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.services.event_service import EventService
from radicalbit_ai_gateway.services.group_service import GroupService
from radicalbit_ai_gateway.services.key_service import KeyService


class TestSummaryCostsIntegration(DatabaseIntegrationClickhouse):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.event_dao = EventDAO(cls.db)
        cls.request_event_dao = MagicMock(spec_set=RequestEventDAO)

        # Create mock services for EventService dependencies
        cls.key_service = MagicMock(spec_set=KeyService)
        cls.group_service = MagicMock(spec_set=GroupService)
        cls.cost_service = MagicMock(spec_set=CostService)

        # Create gateway config
        gw = get_default_gateway(route_name='test-route')
        global_guardrails = get_global_guardrails()
        cls.gateway_config = GatewayConfig(
            chat_models=gw.chat_models,
            embedding_models=gw.embedding_models,
            routes=gw.routes,
            guardrails=global_guardrails,
            cache=get_default_cache_config(),
        )

        cls.request_event_dao = MagicMock(spec_set=RequestEventDAO)
        cls.event_service = EventService(
            event_dao=cls.event_dao,
            request_event_dao=cls.request_event_dao,
            key_service=cls.key_service,
            group_service=cls.group_service,
        )

    def test_basic_cost_calculation_no_cache(self):
        """Test basic input/output cost aggregation when caching is disabled.

        Scenario: Route without caching configuration.
        Expected: Only INPUT_TOKEN_PROCESSED and OUTPUT_TOKEN_PROCESSED costs are summed.
        CACHE_HIT events should be excluded since cache_enabled=False.

        Expected calculation:
            input_cost = sum(COST) where EVENT_TYPE = 'INPUT_TOKEN_PROCESSED'
            output_cost = sum(COST) where EVENT_TYPE = 'OUTPUT_TOKEN_PROCESSED'
            total_cost = input_cost + output_cost
        """
        route_name = 'test-route'

        # Insert test events with various costs
        events = [
            # Input tokens with different costs
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 0, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=1000,
                model_id='openai/gpt-4o',
                model_type='chat-model',
                cost=0.03,  # First input cost
            ),
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 5, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=500,
                model_id='openai/gpt-4o',
                model_type='chat-model',
                cost=0.015,  # Second input cost
            ),
            # Output tokens
            get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 6, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=300,
                model_id='openai/gpt-4o',
                model_type='chat-model',
                cost=0.045,  # Output cost
            ),
            # CACHE_HIT event (should be excluded since cache_enabled=False)
            get_sample_event(
                event_type='CACHE_HIT',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 7, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=1,
            ),
        ]

        for event in events:
            self.insert([event])

        # Query without cache enabled (route has no caching config)
        result = self.event_service.get_summary_costs(
            None,
            self.gateway_config,
            route_names=[route_name],
            _from=None,
            _to=None,
            _with_saved_tokens=False,
        )

        # Build expected DTO with all fields explicitly set
        expected = CostDataDTO(
            input_cost=0.045,
            output_cost=0.045,
            total_cost=0.09,
            cache_triggered=None,
            cache_saved_tokens_input=None,
            cache_saved_tokens_output=None,
            saved_amount_input=None,
            saved_amount_output=None,
            total_cached_tokens=None,
            total_saved_amount=None,
            # The breakdowns are always returned
            total=0.09,
            totals=TotalCostDTO(
                input=0.045, cached_input=0.0, output=0.045, saved=None
            ),
            chat_models=ChatModelsCostDTO(
                input=ChatModelsInputBreakdownDTO(
                    total=0.045, direct=0.045, judges=None
                ),
                cached_input=ChatModelsCachedInputBreakdownDTO(
                    total=0.0, direct=0.0, judges=None
                ),
                output=ChatModelsOutputBreakdownDTO(
                    total=0.045, direct=0.045, judges=None
                ),
                total=0.09,
            ),
            embedding_models=EmbeddingModelsCostDTO(
                input=EmbeddingInputBreakdownDTO(
                    total=0.0, embedding=0.0, semantic_cache=None
                ),
                total=0.0,
            ),
        )

        # Use helper method to compare all fields
        self._assert_dto_equals(result, expected)

    def test_cache_enabled_without_saved_tokens(self):
        """Test cache metrics when cache is enabled but saved tokens are not requested.

        Scenario: Route with exact caching enabled.
        Expected: Cache costs are calculated, but token counts are None.

        Expected calculation:
            cache_triggered = count(EVENT_TYPE = 'CACHE_HIT')
            saved_amount_input = sum(COST) where EVENT_TYPE = 'CACHE_INPUT_TOKENS'
            saved_amount_output = sum(COST) where EVENT_TYPE = 'CACHE_OUTPUT_TOKENS'
            total_saved_amount = saved_amount_input + saved_amount_output
            cache_saved_tokens_* = None (when _with_saved_tokens=False)
        """
        route_name = 'test-cache-route'

        # Update gateway config to include caching
        gw = get_default_gateway_with_caching(route_name=route_name)
        self.gateway_config.routes[route_name] = gw.routes[route_name]
        self.event_service.gateway_config = self.gateway_config

        # Insert test events
        events = [
            # Standard input/output tokens (should be counted in base costs)
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 0, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=1000,
                model_id='openai/gpt-4o',
                model_type='chat-model',
                cost=0.03,
            ),
            get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 1, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=500,
                model_id='openai/gpt-4o',
                model_type='chat-model',
                cost=0.045,
            ),
            # Cache hits (for counting cache_triggered)
            get_sample_event(
                event_type='CACHE_HIT',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 2, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=1,
            ),
            get_sample_event(
                event_type='CACHE_HIT',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 3, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=1,
            ),
            # Cache input tokens with costs
            get_sample_event(
                event_type='CACHE_INPUT_TOKENS',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 4, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=800,
                model_id='openai/gpt-4o',
                cost=0.024,  # Saved input cost
            ),
            # Cache output tokens with costs
            get_sample_event(
                event_type='CACHE_OUTPUT_TOKENS',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 5, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=400,
                model_id='openai/gpt-4o',
                cost=0.036,  # Saved output cost
            ),
        ]

        for event in events:
            self.insert([event])

        # Query with cache enabled, without saved tokens
        result = self.event_service.get_summary_costs(
            None,
            self.gateway_config,
            route_names=[route_name],
            _from=None,
            _to=None,
            _with_saved_tokens=False,
        )

        # Build expected DTO with all expected values
        expected = CostDataDTO(
            input_cost=0.03,
            output_cost=0.045,
            total_cost=0.075,
            cache_triggered=2,
            cache_saved_tokens_input=None,
            cache_saved_tokens_output=None,
            saved_amount_input=0.024,
            saved_amount_output=0.036,
            total_cached_tokens=None,
            total_saved_amount=0.06,
            total=0.075,
            totals=TotalCostDTO(input=0.03, cached_input=0.0, output=0.045, saved=0.06),
            chat_models=ChatModelsCostDTO(
                input=ChatModelsInputBreakdownDTO(total=0.03, direct=0.03, judges=None),
                cached_input=ChatModelsCachedInputBreakdownDTO(
                    total=0.0, direct=0.0, judges=None
                ),
                output=ChatModelsOutputBreakdownDTO(
                    total=0.045, direct=0.045, judges=None
                ),
                total=0.075,
            ),
            embedding_models=EmbeddingModelsCostDTO(
                input=EmbeddingInputBreakdownDTO(
                    total=0.0, embedding=0.0, semantic_cache=None
                ),
                total=0.0,
            ),
        )

        # Use helper method to compare all fields
        self._assert_dto_equals(result, expected)

    def test_cache_enabled_with_saved_tokens(self):
        """Test both cost and token savings when cache is enabled and tokens are requested.

        Scenario: Route with caching enabled and _with_saved_tokens=True.
        Expected: Both costs and token counts are calculated for cached tokens.

        Expected calculation:
            cache_saved_tokens_input = sum(VALUE) where EVENT_TYPE = 'CACHE_INPUT_TOKENS'
            cache_saved_tokens_output = sum(VALUE) where EVENT_TYPE = 'CACHE_OUTPUT_TOKENS'
            total_cached_tokens = cache_saved_tokens_input + cache_saved_tokens_output
        """
        route_name = 'test-cache-tokens-route'

        # Update gateway config to include caching
        gw = get_default_gateway_with_caching(route_name=route_name)
        self.gateway_config.routes[route_name] = gw.routes[route_name]
        self.event_service.gateway_config = self.gateway_config

        # Insert test events
        events = [
            # Standard input/output tokens
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 0, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=1000,
                model_id='openai/gpt-4o',
                model_type='chat-model',
                cost=0.03,
            ),
            get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 1, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=500,
                model_id='openai/gpt-4o',
                model_type='chat-model',
                cost=0.045,
            ),
            # Cache hits
            get_sample_event(
                event_type='CACHE_HIT',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 2, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=1,
            ),
            # Cache input tokens with both cost and value
            get_sample_event(
                event_type='CACHE_INPUT_TOKENS',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 3, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=800,  # Token count
                model_id='openai/gpt-4o',
                cost=0.024,  # Cost
            ),
            get_sample_event(
                event_type='CACHE_INPUT_TOKENS',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 4, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=1200,  # Token count
                model_id='openai/gpt-4o',
                cost=0.036,  # Cost
            ),
            # Cache output tokens with both cost and value
            get_sample_event(
                event_type='CACHE_OUTPUT_TOKENS',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 5, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=400,  # Token count
                model_id='openai/gpt-4o',
                cost=0.036,  # Cost
            ),
        ]

        for event in events:
            self.insert([event])

        # Query with cache enabled AND saved tokens
        result = self.event_service.get_summary_costs(
            None,
            self.gateway_config,
            route_names=[route_name],
            _from=None,
            _to=None,
            _with_saved_tokens=True,  # Enable token counting
        )

        # Build expected DTO with all expected values
        expected = CostDataDTO(
            input_cost=0.03,
            output_cost=0.045,
            total_cost=0.075,
            cache_triggered=1,
            cache_saved_tokens_input=2000,
            cache_saved_tokens_output=400,
            saved_amount_input=0.06,
            saved_amount_output=0.036,
            total_cached_tokens=2400,
            total_saved_amount=0.096,
            total=0.075,
            totals=TotalCostDTO(
                input=0.03, cached_input=0.0, output=0.045, saved=0.096
            ),
            chat_models=ChatModelsCostDTO(
                input=ChatModelsInputBreakdownDTO(total=0.03, direct=0.03, judges=None),
                cached_input=ChatModelsCachedInputBreakdownDTO(
                    total=0.0, direct=0.0, judges=None
                ),
                output=ChatModelsOutputBreakdownDTO(
                    total=0.045, direct=0.045, judges=None
                ),
                total=0.075,
            ),
            embedding_models=EmbeddingModelsCostDTO(
                input=EmbeddingInputBreakdownDTO(
                    total=0.0, embedding=0.0, semantic_cache=None
                ),
                total=0.0,
            ),
        )

        # Use helper method to compare all fields
        self._assert_dto_equals(result, expected)

    def test_date_range_filtering(self):
        """Test that only events within the specified time range are included.

        Scenario: Events at different timestamps relative to query range.
        Expected: Only costs from events within [12:00, 14:00] are summed.

        Expected calculation:
            Only events where TIMESTAMP >= _from AND TIMESTAMP <= _to
            Events at 10:00 (before 12:00): EXCLUDED
            Events at 13:00 (within 12:00-14:00): INCLUDED
            Events at 15:00 (after 14:00): EXCLUDED
        """
        route_name = 'test-date-range-route'

        # Add route to gateway config
        gw = get_default_gateway(route_name=route_name)
        self.gateway_config.routes[route_name] = gw.routes[route_name]
        self.event_service.gateway_config = self.gateway_config

        # Define time range
        _from = datetime.datetime(2026, 1, 15, 12, 0, 0, tzinfo=datetime.timezone.utc)
        _to = datetime.datetime(2026, 1, 15, 14, 0, 0, tzinfo=datetime.timezone.utc)

        # Insert test events at different times
        events = [
            # BEFORE range (at 10:00) - should be EXCLUDED
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 10, 0, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=1000,
                model_id='openai/gpt-4o',
                model_type='chat-model',
                cost=0.5,  # Should NOT be included
            ),
            # WITHIN range (at 13:00) - should be INCLUDED
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 13, 0, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=1000,
                model_id='openai/gpt-4o',
                model_type='chat-model',
                cost=0.03,  # Should be included
            ),
            # WITHIN range (at 13:30) - should be INCLUDED
            get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 13, 30, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=500,
                model_id='openai/gpt-4o',
                model_type='chat-model',
                cost=0.045,  # Should be included
            ),
            # AFTER range (at 15:00) - should be EXCLUDED
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 15, 0, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=1000,
                model_id='openai/gpt-4o',
                model_type='chat-model',
                cost=0.7,  # Should NOT be included
            ),
        ]

        for event in events:
            self.insert([event])

        # Query with time range
        result = self.event_service.get_summary_costs(
            None,
            self.gateway_config,
            route_names=[route_name],
            _from=_from,
            _to=_to,
            _with_saved_tokens=False,
        )

        # Build expected DTO with only events within [12:00, 14:00]
        expected = CostDataDTO(
            input_cost=0.03,
            output_cost=0.045,
            total_cost=0.075,
            cache_triggered=None,
            cache_saved_tokens_input=None,
            cache_saved_tokens_output=None,
            saved_amount_input=None,
            saved_amount_output=None,
            total_cached_tokens=None,
            total_saved_amount=None,
            total=0.075,
            totals=TotalCostDTO(input=0.03, cached_input=0.0, output=0.045, saved=None),
            chat_models=ChatModelsCostDTO(
                input=ChatModelsInputBreakdownDTO(total=0.03, direct=0.03, judges=None),
                cached_input=ChatModelsCachedInputBreakdownDTO(
                    total=0.0, direct=0.0, judges=None
                ),
                output=ChatModelsOutputBreakdownDTO(
                    total=0.045, direct=0.045, judges=None
                ),
                total=0.075,
            ),
            embedding_models=EmbeddingModelsCostDTO(
                input=EmbeddingInputBreakdownDTO(
                    total=0.0, embedding=0.0, semantic_cache=None
                ),
                total=0.0,
            ),
        )

        # Use helper method to compare all fields
        self._assert_dto_equals(result, expected)

    def test_semantic_cache_enabled(self):
        """Test semantic cache costs are added separately.

        Scenario: Route with SemanticCaching configuration.
        Expected: Standard costs from main query + semantic costs from get_semantic_cache_details().

        Expected calculation:
            Standard costs from get_summary_costs() with cache_type in ('', 'exact')
            Semantic costs from get_semantic_cache_details() with cache_type='semantic'
            Final input_cost = standard_input_cost + semantic.embedding_inference_cost
        """
        route_name = 'test-semantic-cache-route'

        # Update gateway config to include semantic caching
        gw = get_default_gateway(route_name=route_name)
        route_config = gw.routes[route_name]
        route_config.caching = SemanticCaching(
            enabled=True,
            type='semantic',
            ttl=3600,
            embedding_model_id='text-embedding-3-small',
        )
        self.gateway_config.routes[route_name] = route_config
        self.event_service.gateway_config = self.gateway_config

        # Insert test events
        events = [
            # Standard input/output tokens (cache_type='')
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 0, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=1000,
                model_id='openai/gpt-4o',
                model_type='chat-model',
                cost=0.03,
                cache_type='',  # Standard - included in main query
            ),
            get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 1, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=500,
                model_id='openai/gpt-4o',
                model_type='chat-model',
                cost=0.045,
                cache_type='',
            ),
            # Semantic cache events (cache_type='semantic')
            # These will be retrieved via get_semantic_cache_details()
            get_sample_event(
                event_type='CACHE_HIT',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 2, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=1,
                cache_type='semantic',
            ),
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',  # Embedding inference
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 3, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=300,
                model_id='text-embedding-3-small',
                model_type='embeddings',
                cost=0.01,  # Embedding inference cost
                cache_type='semantic',
            ),
            get_sample_event(
                event_type='CACHE_INPUT_TOKENS',  # LLM input savings
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 4, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=800,
                model_id='openai/gpt-4o',
                cost=0.024,
                cache_type='semantic',
            ),
        ]

        for event in events:
            self.insert([event])

        # Query with semantic cache enabled
        result = self.event_service.get_summary_costs(
            None,
            self.gateway_config,
            route_names=[route_name],
            _from=None,
            _to=None,
            _with_saved_tokens=True,
        )

        # Build expected DTO
        # Standard costs: input_cost = 0.03, output_cost = 0.045
        # Semantic embedding cost: 0.01
        # Cache savings: 0.024
        # Net savings: 0.024 - 0.01 = 0.014 (embedding cost is subtracted from savings)
        expected = CostDataDTO(
            input_cost=0.04,
            output_cost=0.045,
            total_cost=0.085,
            cache_triggered=1,
            cache_saved_tokens_input=800,
            cache_saved_tokens_output=0,
            saved_amount_input=0.024,
            saved_amount_output=0.0,
            total_cached_tokens=800,
            total_saved_amount=0.014,
            total=0.085,
            totals=TotalCostDTO(
                input=0.04, cached_input=0.0, output=0.045, saved=0.014
            ),
            chat_models=ChatModelsCostDTO(
                input=ChatModelsInputBreakdownDTO(total=0.03, direct=0.03, judges=None),
                cached_input=ChatModelsCachedInputBreakdownDTO(
                    total=0.0, direct=0.0, judges=None
                ),
                output=ChatModelsOutputBreakdownDTO(
                    total=0.045, direct=0.045, judges=None
                ),
                total=0.075,
            ),
            embedding_models=EmbeddingModelsCostDTO(
                input=EmbeddingInputBreakdownDTO(
                    total=0.01, embedding=0.0, semantic_cache=0.01
                ),
                total=0.01,
            ),
        )

        # Use helper method to compare all fields
        self._assert_dto_equals(result, expected)

    def test_empty_result_no_events(self):
        """Test behavior when no events exist for the route.

        Scenario: Route exists but has no events.
        Expected: All cost fields are 0, optional fields are None, no errors thrown.
        """
        route_name = 'test-empty-route'

        # Add route to gateway config
        gw = get_default_gateway(route_name=route_name)
        self.gateway_config.routes[route_name] = gw.routes[route_name]
        self.event_service.gateway_config = self.gateway_config

        # No events inserted

        # Query the route
        result = self.event_service.get_summary_costs(
            None,
            self.gateway_config,
            route_names=[route_name],
            _from=None,
            _to=None,
            _with_saved_tokens=False,
        )

        # Build expected DTO - all fields should be 0 or None
        expected = CostDataDTO(
            input_cost=0.0,
            output_cost=0.0,
            total_cost=0.0,
            cache_triggered=None,
            cache_saved_tokens_input=None,
            cache_saved_tokens_output=None,
            saved_amount_input=None,
            saved_amount_output=None,
            total_cached_tokens=None,
            total_saved_amount=None,
            total=0.0,
            totals=TotalCostDTO(input=0.0, cached_input=0.0, output=0.0, saved=None),
            chat_models=ChatModelsCostDTO(
                input=ChatModelsInputBreakdownDTO(total=0.0, direct=0.0, judges=None),
                cached_input=ChatModelsCachedInputBreakdownDTO(
                    total=0.0, direct=0.0, judges=None
                ),
                output=ChatModelsOutputBreakdownDTO(total=0.0, direct=0.0, judges=None),
                total=0.0,
            ),
            embedding_models=EmbeddingModelsCostDTO(
                input=EmbeddingInputBreakdownDTO(
                    total=0.0, embedding=0.0, semantic_cache=None
                ),
                total=0.0,
            ),
        )

        # Use helper method to compare all fields
        self._assert_dto_equals(result, expected)

    def test_multiple_requests_aggregation(self):
        """Test costs are correctly aggregated across multiple requests.

        Scenario: Multiple events with same/different request_uuids.
        Expected: All costs are summed correctly regardless of request_uuid.

        Expected calculation:
            Total equals sum of all individual event costs
            request_uuid grouping doesn't affect aggregation
        """
        route_name = 'test-multiple-requests-route'

        # Add route to gateway config
        gw = get_default_gateway(route_name=route_name)
        self.gateway_config.routes[route_name] = gw.routes[route_name]
        self.event_service.gateway_config = self.gateway_config

        request_1_uuid = uuid.UUID(int=1)
        request_2_uuid = uuid.UUID(int=2)
        request_3_uuid = uuid.UUID(int=3)

        # Insert test events across multiple requests
        events = [
            # Request 1: Multiple events
            get_sample_event(
                request_uuid=request_1_uuid,
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 0, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=1000,
                model_id='openai/gpt-4o',
                model_type='chat-model',
                cost=0.03,
            ),
            get_sample_event(
                request_uuid=request_1_uuid,
                event_type='OUTPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 1, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=500,
                model_id='openai/gpt-4o',
                model_type='chat-model',
                cost=0.045,
            ),
            # Request 2: Different request
            get_sample_event(
                request_uuid=request_2_uuid,
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 2, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=800,
                model_id='openai/gpt-4o',
                model_type='chat-model',
                cost=0.024,
            ),
            # Request 3: Another request
            get_sample_event(
                request_uuid=request_3_uuid,
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 3, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=1200,
                model_id='openai/gpt-4o',
                model_type='chat-model',
                cost=0.036,
            ),
            get_sample_event(
                request_uuid=request_3_uuid,
                event_type='OUTPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 4, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=600,
                model_id='openai/gpt-4o',
                model_type='chat-model',
                cost=0.054,
            ),
        ]

        for event in events:
            self.insert([event])

        # Query - should aggregate across all requests
        result = self.event_service.get_summary_costs(
            None,
            self.gateway_config,
            route_names=[route_name],
            _from=None,
            _to=None,
            _with_saved_tokens=False,
        )

        # Build expected DTO - all costs summed regardless of request_uuid
        # Expected: input_cost = 0.03 + 0.024 + 0.036 = 0.09
        # Expected: output_cost = 0.045 + 0.054 = 0.099
        # Expected: total_cost = 0.09 + 0.099 = 0.189
        expected = CostDataDTO(
            input_cost=0.09,
            output_cost=0.099,
            total_cost=0.189,
            cache_triggered=None,
            cache_saved_tokens_input=None,
            cache_saved_tokens_output=None,
            saved_amount_input=None,
            saved_amount_output=None,
            total_cached_tokens=None,
            total_saved_amount=None,
            total=0.189,
            totals=TotalCostDTO(input=0.09, cached_input=0.0, output=0.099, saved=None),
            chat_models=ChatModelsCostDTO(
                input=ChatModelsInputBreakdownDTO(total=0.09, direct=0.09, judges=None),
                cached_input=ChatModelsCachedInputBreakdownDTO(
                    total=0.0, direct=0.0, judges=None
                ),
                output=ChatModelsOutputBreakdownDTO(
                    total=0.099, direct=0.099, judges=None
                ),
                total=0.189,
            ),
            embedding_models=EmbeddingModelsCostDTO(
                input=EmbeddingInputBreakdownDTO(
                    total=0.0, embedding=0.0, semantic_cache=None
                ),
                total=0.0,
            ),
        )

        # Use helper method to compare all fields
        self._assert_dto_equals(result, expected)

    def test_complete_dto_structure_with_breakdowns(self):
        """Test complete CostDataDTO structure with all nested breakdowns.

        Scenario: Events with various model_type, is_cached_tokens, is_judge, and cache_type.
        Expected: All DTO fields are properly populated including nested structures.

        Expected calculation:
            - input breakdown: standard + cached = total
            - chat_models breakdown: input (total, direct, judges), cached_input, output
            - embedding_models breakdown: input (total, embedding, semantic_cache)
            - output field: duplicate of output_cost
            - savings field: duplicate of total_saved_amount
        """
        route_name = 'test-complete-dto-route'

        # Use helper to get gateway with JUDGE guardrail and semantic caching
        gw = get_gateway_with_judge_and_semantic_cache(route_name=route_name)
        self.gateway_config.guardrails = gw.guardrails
        self.gateway_config.routes[route_name] = gw.routes[route_name]
        self.event_service.gateway_config = self.gateway_config

        # Insert comprehensive test events
        events = [
            # ===== Chat Model - Standard (non-cached, non-judge) =====
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 0, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=1000,
                model_id='openai/gpt-4o',
                model_type='chat-model',
                cost=0.03,
                is_cached_tokens=False,
                is_judge=False,
                cache_type='',
            ),
            get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 1, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=500,
                model_id='openai/gpt-4o',
                model_type='chat-model',
                cost=0.045,
                is_judge=False,
            ),
            # ===== Chat Model - Cached =====
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 2, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=800,
                model_id='openai/gpt-4o',
                model_type='chat-model',
                cost=0.024,  # Cached input cost
                is_cached_tokens=True,
                is_judge=False,
                cache_type='',
            ),
            # ===== Chat Model - Judge =====
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 3, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=600,
                model_id='openai/gpt-4o',
                model_type='chat-model',
                cost=0.018,  # Judge input cost
                is_cached_tokens=False,
                is_judge=True,
                cache_type='',
            ),
            get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 4, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=300,
                model_id='openai/gpt-4o',
                model_type='chat-model',
                cost=0.027,  # Judge output cost
                is_judge=True,
            ),
            # ===== Chat Model - Judge + Cached =====
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 5, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=400,
                model_id='openai/gpt-4o',
                model_type='chat-model',
                cost=0.012,  # Judge cached input cost
                is_cached_tokens=True,
                is_judge=True,
                cache_type='',
            ),
            # ===== Embedding Model - Direct =====
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 6, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=500,
                model_id='text-embedding-3-small',
                model_type='embeddings',
                cost=0.005,  # Direct embedding cost
                cache_type='',
            ),
            # ===== Embedding Model - Semantic Cache =====
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 7, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=300,
                model_id='text-embedding-3-small',
                model_type='embeddings',
                cost=0.003,  # Semantic cache embedding cost
                cache_type='semantic',
            ),
            # ===== Cache Savings =====
            get_sample_event(
                event_type='CACHE_HIT',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 8, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=1,
                cache_type='exact',
            ),
            get_sample_event(
                event_type='CACHE_INPUT_TOKENS',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 9, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=1500,  # Saved input tokens
                model_id='openai/gpt-4o',
                cost=0.045,  # Saved input cost
                cache_type='exact',
            ),
            get_sample_event(
                event_type='CACHE_OUTPUT_TOKENS',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 10, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=700,  # Saved output tokens
                model_id='openai/gpt-4o',
                cost=0.063,  # Saved output cost
                cache_type='exact',
            ),
        ]

        for event in events:
            self.insert([event])

        # Query with cache enabled and saved tokens
        result = self.event_service.get_summary_costs(
            None,
            self.gateway_config,
            route_names=[route_name],
            _from=None,
            _to=None,
            _with_saved_tokens=True,
        )

        # Build expected DTO with all fields explicitly set
        # Input: 0.084 (chat) + 0.005 (direct embedding) + 0.003 (semantic embedding) = 0.092
        # Output: 0.072
        # Total: 0.164
        expected = CostDataDTO(
            input_cost=0.092,
            output_cost=0.072,
            total_cost=0.164,
            cache_triggered=1,
            cache_saved_tokens_input=1500,
            cache_saved_tokens_output=700,
            saved_amount_input=0.045,
            saved_amount_output=0.063,
            total_cached_tokens=2200,
            total_saved_amount=0.105,  # 0.108 - 0.003 (semantic embedding cost)
            # Nested breakdowns
            total=0.164,  # chat_models.total (0.156) + embedding_models.total (0.008)
            totals=TotalCostDTO(
                input=0.056,  # chat_models.input.total (0.048) + embedding_models.input.total (0.008)
                cached_input=0.036,  # chat_models.cached_input.total
                output=0.072,  # chat_models.output.total
                saved=0.105,  # total_saved_amount
            ),
            chat_models=ChatModelsCostDTO(
                input=ChatModelsInputBreakdownDTO(
                    total=0.048,  # All chat input
                    direct=0.03,  # Direct only (0.084 - 0.030)
                    judges=0.018,  # Judge input
                ),
                cached_input=ChatModelsCachedInputBreakdownDTO(
                    total=0.036,  # All cached chat
                    direct=0.024,  # Direct only (0.036 - 0.012)
                    judges=0.012,  # Cached judge
                ),
                output=ChatModelsOutputBreakdownDTO(
                    total=0.072,  # All chat output
                    direct=0.045,  # Direct only (0.072 - 0.027)
                    judges=0.027,  # Judge output
                ),
                total=0.156,  # input (0.048) + cached_input (0.036) + output (0.072)
            ),
            embedding_models=EmbeddingModelsCostDTO(
                input=EmbeddingInputBreakdownDTO(
                    total=0.008,  # All embedding input
                    embedding=0.005,  # Direct embedding
                    semantic_cache=0.003,  # Semantic cache
                ),
                total=0.008,  # embedding input total
            ),
        )

        # Use helper method to compare all fields
        self._assert_dto_equals(result, expected)

    @staticmethod
    def _assert_dto_equals(result: CostDataDTO, expected: CostDataDTO) -> None:
        """Compare CostDataDTO instances with tolerance for floating point values."""

        def apply_approx(obj):
            """Recursively apply pytest.approx to floats in nested structures."""
            if isinstance(obj, float):
                return pytest.approx(obj, abs=1e-3)
            if isinstance(obj, dict):
                return {k: apply_approx(v) for k, v in obj.items()}
            if isinstance(obj, list | tuple):
                return type(obj)(apply_approx(v) for v in obj)
            return obj

        # Recursively apply approx to expected dict, then compare
        expected_dict = expected.model_dump()
        approx_expected = apply_approx(expected_dict)

        assert result.model_dump() == approx_expected
