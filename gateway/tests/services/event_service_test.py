import datetime
import unittest
from unittest.mock import AsyncMock, MagicMock
import uuid
from uuid import UUID

import pytest

from tests.common import db_mock
from tests.common.mocked_gateway_config import (
    get_default_cache_config,
    get_default_gateway,
    get_default_gateway_with_caching,
    get_gateway_with_judge_and_semantic_cache,
    get_gateway_with_routing,
    get_global_guardrails,
)

from radicalbit_ai_gateway.db.dao.event_dao import EventDAO
from radicalbit_ai_gateway.db.dao.request_event_dao import RequestEventDAO
from radicalbit_ai_gateway.db.models.event import (
    CostChartDataPoint,
    CostData,
    Counters,
    DetailedCostBreakdown,
    InvocationChartDataPoint,
    LastEventFallback,
    LastEventGuardrail,
    ModelInvocationCounter,
    MostExpensiveChartData,
    MostExpensiveRoute,
    RequestStats,
    RouteCostData,
    RouteDetailedCostBreakdown,
    SemanticCacheCostData,
    TokenChartDataPoint,
    TokensCounter,
)
from radicalbit_ai_gateway.limiter.window_config import WindowStats
from radicalbit_ai_gateway.models.auth_dto import KeyOut
from radicalbit_ai_gateway.models.caching import SemanticCaching
from radicalbit_ai_gateway.models.event_dto import (
    Cache,
    CacheHitEventDetailDTO,
    ChartDataSeriesDTO,
    ChatModelsCachedInputBreakdownDTO,
    ChatModelsCostDTO,
    ChatModelsInputBreakdownDTO,
    ChatModelsOutputBreakdownDTO,
    CostChartDataDTO,
    CostChartDataSeriesDTO,
    CostDataDTO,
    EmbeddingInputBreakdownDTO,
    EmbeddingModelsCostDTO,
    Errors,
    EventsDTO,
    Fallback,
    FallbackEventDetailDTO,
    Guardrail,
    GuardrailEventDetailDTO,
    InvocationChartDataDTO,
    LastNEvents,
    ModelInvocationDTO,
    RateLimitEventDetailDTO,
    RouteCostDTO,
    TokenChartDataDTO,
    TokenChartDataSeriesDTO,
    TotalCostDTO,
    UsageCostsDTO,
    WindowStatus,
)
from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.gateway_route_out import GatewayRouteOut
from radicalbit_ai_gateway.services.event_service import EventService
from radicalbit_ai_gateway.services.group_service import GroupService
from radicalbit_ai_gateway.services.key_service import KeyService
from radicalbit_ai_gateway.utils import BUDGET_MULTIPLIER


class EventServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.event_dao: EventDAO = MagicMock(spec_set=EventDAO)
        cls.request_event_dao: RequestEventDAO = MagicMock(spec_set=RequestEventDAO)
        cls.key_service: KeyService = MagicMock(spec_set=KeyService)
        cls.group_service: GroupService = MagicMock(spec_set=GroupService)

        global_guardrails = get_global_guardrails()

        gw_a = get_default_gateway_with_caching(route_name='route-A')
        gw_b = get_default_gateway_with_caching(route_name='route-B')

        cls.gateway_config = GatewayConfig(
            chat_models=gw_a.chat_models,
            embedding_models=gw_a.embedding_models,
            routes={
                'route-A': gw_a.routes['route-A'],
                'route-B': gw_b.routes['route-B'],
            },
            guardrails=global_guardrails,
            cache=get_default_cache_config(),
        )

        cls.TEST_PROJECT_UUID = uuid.UUID('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
        cls.TEST_PROJECT_NAME = 'test'

        cls.event_service = EventService(
            event_dao=cls.event_dao,
            request_event_dao=cls.request_event_dao,
            key_service=cls.key_service,
            group_service=cls.group_service,
        )

        cls.gateway_config_with_routing = get_gateway_with_routing(route_name='route-R')
        cls.event_service_routing = EventService(
            event_dao=cls.event_dao,
            request_event_dao=cls.request_event_dao,
            key_service=cls.key_service,
            group_service=cls.group_service,
        )
        cls.routing_model_counters = [
            ModelInvocationCounter(model_id='openai', value=3),
            ModelInvocationCounter(model_id='azure', value=2),
        ]

        cls.dev_key_uuid = uuid.uuid4()
        cls.data_key_uuid = uuid.uuid4()
        cls.counters = Counters(
            guardrail_value=2,
            fallback_value=3,
            rate_limit_triggered=2,
            token_input_limit_triggered=0,
            token_output_limit_triggered=0,
            cache_triggered=1,
        )
        cls.counters_per_route = Counters(
            guardrail_value=4,
            fallback_value=1,
            rate_limit_triggered=2,
            token_input_limit_triggered=0,
            token_output_limit_triggered=0,
            cache_triggered=3,
        )
        cls.tokens_counter = [
            TokensCounter(
                event_type='OUTPUT_TOKEN_PROCESSED',
                route_name='route-A',
                model_id='azure',
                value=150,
            ),
            TokensCounter(
                event_type='CACHE_INPUT_TOKENS',
                route_name='route-A',
                model_id='openai',
                value=47,
            ),
            TokensCounter(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-A',
                model_id='openai',
                value=250,
            ),
            TokensCounter(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-B',
                model_id='openai',
                value=150,
            ),
            TokensCounter(
                event_type='CACHE_OUTPUT_TOKENS',
                route_name='route-A',
                model_id='azure',
                value=60,
            ),
            TokensCounter(
                event_type='CACHE_OUTPUT_TOKENS',
                route_name='route-B',
                model_id='azure',
                value=60,
            ),
            TokensCounter(
                event_type='OUTPUT_TOKEN_PROCESSED',
                route_name='route-B',
                model_id='azure',
                value=75,
            ),
            TokensCounter(
                event_type='CACHE_INPUT_TOKENS',
                route_name='route-B',
                model_id='openai',
                value=47,
            ),
        ]
        cls.get_last_event_details_fallback = LastEventFallback(
            route_name='route-A',
            target='gpt-4.1',
            fallback='llama3.1',
            timestamp=datetime.datetime(
                2025, 10, 14, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
            ),
            api_key_uuid=cls.dev_key_uuid,
            api_key_name='dev',
        )
        cls.get_last_event_details_guardrail = LastEventGuardrail(
            route_name='route-A',
            name='PRESIDIO',
            where='INPUT',
            type='READACT',
            behavior='BLOCK',
            timestamp=datetime.datetime(
                2025, 10, 14, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
            ),
            api_key_uuid=cls.data_key_uuid,
            api_key_name='data',
        )
        cls.mocks = [cls.event_dao]

    def test_total_counter(self):
        def get_event_details_side_effect(
            project_uuid, event_type, _from, _to, **kwargs
        ):
            if event_type == EventType.GUARDRAIL:
                return self.get_last_event_details_guardrail
            if event_type == EventType.FALLBACK:
                return self.get_last_event_details_fallback
            return None

        def get_api_key_name_side_effect(api_key_uuid, include_groups):
            if api_key_uuid == self.dev_key_uuid:
                return KeyOut.from_key(
                    db_mock.get_sample_key(uuid=self.dev_key_uuid, name='dev')
                )
            return KeyOut.from_key(
                db_mock.get_sample_key(uuid=self.data_key_uuid, name='data')
            )

        self.event_dao.get_all_counters = MagicMock(return_value=self.counters)
        self.event_dao.get_tokens_by_model = MagicMock(return_value=self.tokens_counter)
        self.event_dao.get_last_event = MagicMock(
            side_effect=get_event_details_side_effect
        )
        self.key_service.get_key_by_uuid = MagicMock(
            side_effect=get_api_key_name_side_effect
        )
        self.request_event_dao.get_request_stats_global = MagicMock(
            return_value=RequestStats()
        )
        res = self.event_service.get_total_counter(
            _from=None,
            _to=None,
            project_uuid=self.TEST_PROJECT_UUID,
            config=self.gateway_config,
        )
        expected = EventsDTO(
            rate_limit_triggered=2,
            token_input_limit_triggered=0,
            token_output_limit_triggered=0,
            total_input_token_processed=400,
            total_output_token_processed=225,
            fallbacks=Fallback(
                value=3, last_event=self.get_last_event_details_fallback
            ),
            guardrails=Guardrail(
                value=2, last_event=self.get_last_event_details_guardrail
            ),
        )
        assert res == expected

    def test_get_total_counter_per_route(self):
        def get_event_details_side_effect(
            project_uuid, event_type, route_name, _from, _to, **kwargs
        ):
            if event_type == EventType.GUARDRAIL:
                return self.get_last_event_details_guardrail
            if event_type == EventType.FALLBACK:
                return self.get_last_event_details_fallback
            return None

        self.event_dao.get_tokens_by_model_per_route = MagicMock(
            return_value=self.tokens_counter
        )
        self.event_dao.get_all_counters_by_route = MagicMock(
            return_value=self.counters_per_route
        )
        self.event_dao.get_last_event_route = MagicMock(
            side_effect=get_event_details_side_effect
        )
        self.request_event_dao.get_request_stats_by_route = MagicMock(
            return_value=RequestStats(
                successful_requests=10, error_requests=1, total_requests=11
            )
        )
        res = self.event_service.get_total_counter_per_route(
            config=self.gateway_config,
            include_groups=False,
            _from=None,
            _to=None,
            project_uuid=self.TEST_PROJECT_UUID,
            project_name=self.TEST_PROJECT_NAME,
        )
        assert res is not None
        assert isinstance(res, list)
        expected_metrics = EventsDTO(
            rate_limit_triggered=2,
            token_input_limit_triggered=0,
            token_output_limit_triggered=0,
            total_input_token_processed=250,
            total_output_token_processed=150,
            cache=Cache(
                cache_triggered=3,
                cache_saved_tokens_input=47,
                cache_saved_tokens_output=60,
                hit_percentage=3 / 11 * 100,
            ),
            fallbacks=Fallback(
                value=1, last_event=self.get_last_event_details_fallback
            ),
            guardrails=Guardrail(
                value=4, last_event=self.get_last_event_details_guardrail
            ),
            total_requests=11,
            request_error_percentage=round(1 / 11 * 100, 2),
            errors=Errors(
                request_error=1,
                request_error_percentage=round(1 / 11 * 100, 2),
                details=[],
            ),
            last_request_timestamp=None,
        )
        # Just check the metrics object, not the entire GatewayRouteOut
        assert res[0].metrics == expected_metrics

    def test_get_counter_per_route(self):
        def get_event_details_side_effect(
            project_uuid, event_type, route_name, _from, _to, **kwargs
        ):
            if event_type == EventType.GUARDRAIL:
                return self.get_last_event_details_guardrail
            if event_type == EventType.FALLBACK:
                return self.get_last_event_details_fallback
            return None

        self.event_dao.get_tokens_by_model_per_route = MagicMock(
            return_value=self.tokens_counter
        )
        self.event_dao.get_all_counters_by_route = MagicMock(
            return_value=self.counters_per_route
        )
        self.event_dao.get_last_event_route = MagicMock(
            side_effect=get_event_details_side_effect
        )
        self.request_event_dao.get_request_stats_by_route = MagicMock(
            return_value=RequestStats(
                successful_requests=10, error_requests=1, total_requests=11
            )
        )
        res = self.event_service.get_counter_per_route(
            route_name='route-A',
            config=self.gateway_config,
            include_groups=False,
            _from=None,
            _to=None,
            project_uuid=self.TEST_PROJECT_UUID,
            project_name=self.TEST_PROJECT_NAME,
        )
        assert res is not None
        assert isinstance(res, GatewayRouteOut)
        expected_metrics = EventsDTO(
            rate_limit_triggered=2,
            token_input_limit_triggered=0,
            token_output_limit_triggered=0,
            total_input_token_processed=250,
            total_output_token_processed=150,
            cache=Cache(
                cache_triggered=3,
                cache_saved_tokens_input=47,
                cache_saved_tokens_output=60,
                hit_percentage=3 / 11 * 100,
            ),
            fallbacks=Fallback(
                value=1, last_event=self.get_last_event_details_fallback
            ),
            guardrails=Guardrail(
                value=4, last_event=self.get_last_event_details_guardrail
            ),
            total_requests=11,
            request_error_percentage=round(1 / 11 * 100, 2),
            errors=Errors(
                request_error=1,
                request_error_percentage=round(1 / 11 * 100, 2),
                details=[],
            ),
            last_request_timestamp=None,
        )
        # Just check the metrics object
        assert res.metrics == expected_metrics

    def test_get_latest_n_per_event_type(self):
        mocked_events = [
            db_mock.get_event_detail(
                timestamp=datetime.datetime(
                    2025, 10, 13, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
                ),
                route_name='route-A',
                event_type='CACHE_HIT',
            ),
            db_mock.get_event_detail(
                timestamp=datetime.datetime(
                    2025, 10, 14, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
                ),
                route_name='route-A',
                event_type='FALLBACK',
                target='gpt-4.1',
                fallback='llama3.1',
            ),
            db_mock.get_event_detail(
                timestamp=datetime.datetime(
                    2025, 10, 13, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
                ),
                route_name='route-A',
                event_type='FALLBACK',
            ),
            db_mock.get_event_detail(
                timestamp=datetime.datetime(
                    2025, 10, 14, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
                ),
                route_name='route-A',
                event_type='GUARDRAIL',
                name='PRESIDIO',
                type='READACT',
                where='INPUT',
                parameters='PARAMS',
                behavior='BLOCK',
            ),
            db_mock.get_event_detail(
                timestamp=datetime.datetime(
                    2025, 10, 13, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
                ),
                route_name='route-A',
                event_type='RATE_LIMIT',
            ),
        ]
        self.event_dao.get_latest_n_per_event_type = MagicMock(
            return_value=mocked_events
        )
        self.key_service.get_names_by_uuids = MagicMock(
            return_value={
                uuid.UUID('00000000-0000-0000-0000-000000000000'): 'fake-name',
            }
        )
        res = self.event_service.get_latest_n_per_event_type(
            self.TEST_PROJECT_UUID,
            self.gateway_config,
            'route-A',
            10,
            None,
            None,
        )

        # Build expected result with typed DTOs
        api_key_uuid = uuid.UUID('00000000-0000-0000-0000-000000000000')
        expected = LastNEvents(
            fallbacks=[
                FallbackEventDetailDTO(
                    timestamp=datetime.datetime(
                        2025, 10, 14, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
                    ),
                    api_key_uuid=api_key_uuid,
                    route_name='route-A',
                    api_key_name='fake-name',
                    event_type='FALLBACK',
                    target='gpt-4.1',
                    fallback='llama3.1',
                ),
                FallbackEventDetailDTO(
                    timestamp=datetime.datetime(
                        2025, 10, 13, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
                    ),
                    api_key_uuid=api_key_uuid,
                    route_name='route-A',
                    api_key_name='fake-name',
                    event_type='FALLBACK',
                    target=None,
                    fallback=None,
                ),
            ],
            guardrails=[
                GuardrailEventDetailDTO(
                    timestamp=datetime.datetime(
                        2025, 10, 14, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
                    ),
                    api_key_uuid=api_key_uuid,
                    route_name='route-A',
                    api_key_name='fake-name',
                    event_type='GUARDRAIL',
                    name='PRESIDIO',
                    type='READACT',
                    where='INPUT',
                    parameters='PARAMS',
                    behavior='BLOCK',
                )
            ],
            rate_limit=[
                RateLimitEventDetailDTO(
                    timestamp=datetime.datetime(
                        2025, 10, 13, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
                    ),
                    api_key_uuid=api_key_uuid,
                    route_name='route-A',
                    api_key_name='fake-name',
                    event_type='RATE_LIMIT',
                )
            ],
            token_input_limit=[],
            token_output_limit=[],
            cache_triggered=[
                CacheHitEventDetailDTO(
                    timestamp=datetime.datetime(
                        2025, 10, 13, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
                    ),
                    api_key_uuid=api_key_uuid,
                    route_name='route-A',
                    api_key_name='fake-name',
                    event_type='CACHE_HIT',
                    target=None,
                )
            ],
        )
        assert res == expected

    def test_get_chart_data_multiple_groups(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        uuid_1 = '550e8400-e29b-41d4-a716-446655440001'
        uuid_2 = '550e8400-e29b-41d4-a716-446655440002'

        mocked_chart_data = [
            CostChartDataPoint(
                bucket=base_time, group_by_value=uuid_1, total_cost=100.0
            ),
            CostChartDataPoint(
                bucket=base_time + datetime.timedelta(hours=1),
                group_by_value=uuid_1,
                total_cost=150.0,
            ),
            CostChartDataPoint(
                bucket=base_time, group_by_value=uuid_2, total_cost=200.0
            ),
            CostChartDataPoint(
                bucket=base_time + datetime.timedelta(hours=1),
                group_by_value=uuid_2,
                total_cost=250.0,
            ),
        ]

        self.event_dao.get_costs_chart_data = MagicMock(return_value=mocked_chart_data)
        self.group_service.get_names_by_uuids = MagicMock(
            return_value={
                UUID(uuid_1): 'group-1',
                UUID(uuid_2): 'group-2',
            }
        )

        res = self.event_service.get_costs_chart_data(
            route_names=['rb-gateway'],
            _from=base_time - datetime.timedelta(hours=1),
            _to=base_time + datetime.timedelta(hours=11),
            group_by='groups',
            project_uuid=self.TEST_PROJECT_UUID,
        )
        expected = CostChartDataDTO(
            granularity='hours',
            timestamp=[
                int((base_time + datetime.timedelta(hours=i)).timestamp())
                for i in range(-1, 12)
            ],
            data=[
                CostChartDataSeriesDTO(
                    name='group-1',
                    uuid=UUID(uuid_1),
                    data=[
                        0.0,
                        100.0,
                        150.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                    ],
                ),
                CostChartDataSeriesDTO(
                    name='group-2',
                    uuid=UUID(uuid_2),
                    data=[
                        0.0,
                        200.0,
                        250.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                    ],
                ),
            ],
            total=700.0,
        )
        assert res == expected

    def test_get_chart_data_missing_timestamps(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        uuid_1 = '660e8400-e29b-41d4-a716-446655440001'
        uuid_2 = '660e8400-e29b-41d4-a716-446655440002'

        mocked_chart_data = [
            CostChartDataPoint(
                bucket=base_time, group_by_value=uuid_1, total_cost=100.0
            ),
            CostChartDataPoint(
                bucket=base_time + datetime.timedelta(hours=2),
                group_by_value=uuid_1,
                total_cost=150.0,
            ),
            CostChartDataPoint(
                bucket=base_time + datetime.timedelta(hours=1),
                group_by_value=uuid_2,
                total_cost=200.0,
            ),
        ]

        self.event_dao.get_costs_chart_data = MagicMock(return_value=mocked_chart_data)
        self.key_service.get_names_by_uuids = MagicMock(
            return_value={
                UUID(uuid_1): 'key-1',
                UUID(uuid_2): 'key-2',
            }
        )

        res = self.event_service.get_costs_chart_data(
            route_names=['rb-gateway'],
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=3),
            group_by='keys',
            project_uuid=self.TEST_PROJECT_UUID,
        )

        expected = CostChartDataDTO(
            granularity='hours',
            timestamp=[
                int((base_time + datetime.timedelta(hours=i)).timestamp())
                for i in range(4)
            ],
            data=[
                CostChartDataSeriesDTO(
                    name='key-1', uuid=UUID(uuid_1), data=[100.0, 0.0, 150.0, 0.0]
                ),
                CostChartDataSeriesDTO(
                    name='key-2', uuid=UUID(uuid_2), data=[0.0, 200.0, 0.0, 0.0]
                ),
            ],
            total=450.0,
        )
        assert res == expected

    def test_get_chart_data_single_group(self):
        base_time = datetime.datetime(2025, 1, 8, 0, 0, 0, tzinfo=datetime.timezone.utc)

        uuid_1 = '770e8400-e29b-41d4-a716-446655440001'

        mocked_chart_data = [
            CostChartDataPoint(
                bucket=base_time, group_by_value=uuid_1, total_cost=50.0
            ),
            CostChartDataPoint(
                bucket=base_time + datetime.timedelta(days=1),
                group_by_value=uuid_1,
                total_cost=75.0,
            ),
        ]

        self.event_dao.get_costs_chart_data = MagicMock(return_value=mocked_chart_data)
        self.key_service.get_names_by_uuids = MagicMock(
            return_value={
                UUID(uuid_1): 'api-key-1',
            }
        )

        res = self.event_service.get_costs_chart_data(
            route_names=['rb-gateway'],
            _from=base_time,
            _to=base_time + datetime.timedelta(days=3),
            group_by='keys',
            project_uuid=self.TEST_PROJECT_UUID,
        )
        expected = CostChartDataDTO(
            granularity='days',
            timestamp=[
                int((base_time + datetime.timedelta(days=i)).timestamp())
                for i in range(4)
            ],
            data=[
                CostChartDataSeriesDTO(
                    name='api-key-1', uuid=UUID(uuid_1), data=[50.0, 75.0, 0.0, 0.0]
                ),
            ],
            total=125.0,
        )
        assert res == expected

    def test_get_chart_data_empty(self):
        base_time = datetime.datetime(2025, 1, 8, 0, 0, 0, tzinfo=datetime.timezone.utc)

        self.event_dao.get_costs_chart_data = MagicMock(return_value=[])

        res = self.event_service.get_costs_chart_data(
            route_names=['rb-gateway'],
            _from=base_time,
            _to=base_time + datetime.timedelta(days=7),
            group_by='groups',
            project_uuid=self.TEST_PROJECT_UUID,
        )

        expected = CostChartDataDTO(
            granularity='days', timestamp=[], data=[], total=0.0
        )
        assert res == expected

    def test_get_chart_data_empty_no_from(self):
        """Test that empty chart data with _from=None returns early without error."""
        base_time = datetime.datetime(2025, 1, 8, 0, 0, 0, tzinfo=datetime.timezone.utc)

        self.event_dao.get_costs_chart_data = MagicMock(return_value=[])

        res = self.event_service.get_costs_chart_data(
            route_names=['rb-gateway'],
            _from=None,
            _to=base_time + datetime.timedelta(days=7),
            group_by='keys',
            project_uuid=self.TEST_PROJECT_UUID,
        )

        expected = CostChartDataDTO(
            granularity='weeks', timestamp=[], data=[], total=0.0
        )
        assert res == expected

    def test_get_chart_data_no_from(self):
        base_time = datetime.datetime(2025, 1, 6, 0, 0, 0, tzinfo=datetime.timezone.utc)

        uuid_1 = '880e8400-e29b-41d4-a716-446655440001'
        uuid_2 = '880e8400-e29b-41d4-a716-446655440002'

        mocked_chart_data = [
            CostChartDataPoint(
                bucket=base_time, group_by_value=uuid_1, total_cost=50.0
            ),
            CostChartDataPoint(
                bucket=base_time + datetime.timedelta(days=7),
                group_by_value=uuid_2,
                total_cost=45.0,
            ),
            CostChartDataPoint(
                bucket=base_time + datetime.timedelta(days=7),
                group_by_value=uuid_1,
                total_cost=75.0,
            ),
        ]
        self.event_dao.get_costs_chart_data = MagicMock(return_value=mocked_chart_data)
        self.key_service.get_names_by_uuids = MagicMock(
            return_value={
                UUID(uuid_1): 'api-key-1',
                UUID(uuid_2): 'api-key-2',
            }
        )

        res = self.event_service.get_costs_chart_data(
            route_names=['rb-gateway'],
            _from=None,
            _to=base_time + datetime.timedelta(days=7),
            group_by='keys',
            project_uuid=self.TEST_PROJECT_UUID,
        )
        expected = CostChartDataDTO(
            granularity='weeks',
            timestamp=[
                int(base_time.timestamp()),
                int((base_time + datetime.timedelta(days=7)).timestamp()),
            ],
            data=[
                CostChartDataSeriesDTO(
                    name='api-key-1', uuid=UUID(uuid_1), data=[50.0, 75.0]
                ),
                CostChartDataSeriesDTO(
                    name='api-key-2', uuid=UUID(uuid_2), data=[0.0, 45.0]
                ),
            ],
            total=170.0,
        )
        assert res == expected

    def test_get_costs_chart_data_by_route_api_key(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        key_uuid = '550e8400-e29b-41d4-a716-446655440001'

        mocked_chart_data = [
            CostChartDataPoint(
                bucket=base_time, group_by_value='route-A', total_cost=100.0
            ),
            CostChartDataPoint(
                bucket=base_time + datetime.timedelta(hours=1),
                group_by_value='route-A',
                total_cost=50.0,
            ),
            CostChartDataPoint(
                bucket=base_time, group_by_value='route-B', total_cost=200.0
            ),
        ]
        self.event_dao.get_costs_chart_data_by_route = MagicMock(
            return_value=mocked_chart_data
        )

        res = self.event_service.get_costs_chart_data_by_route(
            entity_column='API_KEY_UUID',
            entity_value=key_uuid,
            route_names=None,
            _from=base_time - datetime.timedelta(hours=1),
            _to=base_time + datetime.timedelta(hours=2),
            project_uuid=self.TEST_PROJECT_UUID,
        )

        self.event_dao.get_costs_chart_data_by_route.assert_called_once()
        call_kwargs = self.event_dao.get_costs_chart_data_by_route.call_args.kwargs
        assert call_kwargs['project_uuid'] == self.TEST_PROJECT_UUID
        assert call_kwargs['entity_column'] == 'API_KEY_UUID'
        assert call_kwargs['entity_value'] == key_uuid

        assert res.granularity == 'hours'
        assert len(res.data) == 2
        route_a = next(s for s in res.data if s.name == 'route-A')
        route_b = next(s for s in res.data if s.name == 'route-B')
        assert route_a.uuid is None
        assert route_b.uuid is None
        assert route_a.data[1] == 100.0
        assert route_b.data[1] == 200.0
        assert res.total == 350.0

    def test_get_costs_chart_data_by_route_empty(self):
        self.event_dao.get_costs_chart_data_by_route = MagicMock(return_value=[])

        res = self.event_service.get_costs_chart_data_by_route(
            entity_column='GROUP_UUID',
            entity_value='550e8400-e29b-41d4-a716-446655440001',
            route_names=None,
            _from=None,
            _to=None,
            project_uuid=self.TEST_PROJECT_UUID,
        )

        assert res == CostChartDataDTO(
            granularity='weeks', timestamp=[], data=[], total=0.0
        )

    def test_get_costs_chart_data_by_route_model(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        mocked_chart_data = [
            CostChartDataPoint(
                bucket=base_time, group_by_value='route-A', total_cost=42.0
            ),
        ]
        self.event_dao.get_costs_chart_data_by_route = MagicMock(
            return_value=mocked_chart_data
        )

        res = self.event_service.get_costs_chart_data_by_route(
            entity_column='MODEL_ID',
            entity_value='gpt-4o',
            route_names=None,
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
            project_uuid=self.TEST_PROJECT_UUID,
        )

        call_kwargs = self.event_dao.get_costs_chart_data_by_route.call_args.kwargs
        assert call_kwargs['project_uuid'] == self.TEST_PROJECT_UUID
        assert call_kwargs['entity_column'] == 'MODEL_ID'
        assert call_kwargs['entity_value'] == 'gpt-4o'
        assert len(res.data) == 1
        assert res.data[0].name == 'route-A'
        assert res.total == 42.0

    def test_get_costs_chart_data_by_route_with_route_names_filter(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        key_uuid = '550e8400-e29b-41d4-a716-446655440001'
        mocked_chart_data = [
            CostChartDataPoint(
                bucket=base_time, group_by_value='route-A', total_cost=50.0
            ),
        ]
        self.event_dao.get_costs_chart_data_by_route = MagicMock(
            return_value=mocked_chart_data
        )

        self.event_service.get_costs_chart_data_by_route(
            entity_column='API_KEY_UUID',
            entity_value=key_uuid,
            route_names=['route-A', 'route-B'],
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
            project_uuid=self.TEST_PROJECT_UUID,
        )

        call_args = self.event_dao.get_costs_chart_data_by_route.call_args.kwargs
        assert call_args['route_names'] == ['route-A', 'route-B']

    def test_get_summary_costs(self):
        base_time = datetime.datetime(2025, 1, 6, 0, 0, 0, tzinfo=datetime.timezone.utc)
        mocked_chart_data = CostData(
            input_cost=10,
            output_cost=20,
            total_cost=30,
        )
        mocked_detailed_breakdown = DetailedCostBreakdown(
            chat_input_direct=10,
            chat_input_cached=0,
            chat_input_judges=0,
            chat_input_judges_cached=0,
            chat_output_direct=20,
            chat_output_judges=0,
            embedding_input_total=0,
            embedding_input_direct=0,
            embedding_input_semantic_cache=0,
        )
        self.event_dao.get_summary_costs = MagicMock(return_value=mocked_chart_data)
        self.event_dao.get_detailed_cost_breakdown = MagicMock(
            return_value=mocked_detailed_breakdown
        )
        expected = CostDataDTO(
            input_cost=10,
            output_cost=20,
            total_cost=30,
            total=30,
            totals=TotalCostDTO(input=10, cached_input=0, output=20, saved=None),
            chat_models=ChatModelsCostDTO(
                input=ChatModelsInputBreakdownDTO(total=10, direct=10, judges=None),
                cached_input=ChatModelsCachedInputBreakdownDTO(
                    total=0, direct=0, judges=None
                ),
                output=ChatModelsOutputBreakdownDTO(total=20, direct=20, judges=None),
                total=30,
            ),
            embedding_models=EmbeddingModelsCostDTO(
                input=EmbeddingInputBreakdownDTO(
                    total=0, embedding=0, semantic_cache=None
                ),
                total=0,
            ),
        )
        res = self.event_service.get_summary_costs(
            route_names=['route-A'],
            _from=None,
            _to=base_time + datetime.timedelta(days=7),
            _with_saved_tokens=False,
            project_uuid=self.TEST_PROJECT_UUID,
            config=self.gateway_config,
        )
        assert res is not None
        assert res == expected

    def test_get_summary_costs_with_cache(self):
        base_time = datetime.datetime(2025, 1, 6, 0, 0, 0, tzinfo=datetime.timezone.utc)
        mocked_chart_data = CostData(
            input_cost=10,
            output_cost=20,
            total_cost=30,
            cache_triggered=2,
            cache_saved_tokens_input=10,
            cache_saved_tokens_output=20,
            saved_amount_input=0.0044,
            saved_amount_output=0.0088,
            total_cached_tokens=30,
            total_saved_amount=0.0132,
        )
        mocked_detailed_breakdown = DetailedCostBreakdown(
            chat_input_direct=10,
            chat_input_cached=0,
            chat_input_judges=0,
            chat_input_judges_cached=0,
            chat_output_direct=20,
            chat_output_judges=0,
            embedding_input_total=0,
            embedding_input_direct=0,
            embedding_input_semantic_cache=0,
        )
        expected = CostDataDTO(
            input_cost=10,
            output_cost=20,
            total_cost=30,
            cache_triggered=2,
            cache_saved_tokens_input=10,
            cache_saved_tokens_output=20,
            saved_amount_input=0.0044,
            saved_amount_output=0.0088,
            total_cached_tokens=30,
            total_saved_amount=0.0132,
            total=30,
            totals=TotalCostDTO(input=10, cached_input=0, output=20, saved=0.0132),
            chat_models=ChatModelsCostDTO(
                input=ChatModelsInputBreakdownDTO(total=10, direct=10, judges=None),
                cached_input=ChatModelsCachedInputBreakdownDTO(
                    total=0, direct=0, judges=None
                ),
                output=ChatModelsOutputBreakdownDTO(total=20, direct=20, judges=None),
                total=30,
            ),
            embedding_models=EmbeddingModelsCostDTO(
                input=EmbeddingInputBreakdownDTO(
                    total=0, embedding=0, semantic_cache=None
                ),
                total=0,
            ),
        )
        self.event_dao.get_summary_costs = MagicMock(return_value=mocked_chart_data)
        self.event_dao.get_detailed_cost_breakdown = MagicMock(
            return_value=mocked_detailed_breakdown
        )
        res = self.event_service.get_summary_costs(
            route_names=['route-A'],
            _from=None,
            _to=base_time + datetime.timedelta(days=7),
            _with_saved_tokens=True,
            project_uuid=self.TEST_PROJECT_UUID,
            config=self.gateway_config,
        )
        assert res is not None
        assert res == expected

    def test_get_summary_costs_with_semantic_cache(self):
        base_time = datetime.datetime(2025, 1, 6, 0, 0, 0, tzinfo=datetime.timezone.utc)

        # Mock the gateway config to have semantic caching enabled
        semantic_caching = SemanticCaching(
            enabled=True,
            type='semantic',
            ttl=3600,
            embedding_model_id='text-embedding-3-small',
            similarity_threshold=0.8,
            distance_metric='cosine',
            dim=1536,
        )

        # Create a new event service with semantic caching
        gateway_config_with_semantic = GatewayConfig(
            chat_models=self.gateway_config.chat_models,
            embedding_models=self.gateway_config.embedding_models,
            routes={
                'route-A': self.gateway_config.routes['route-A'].model_copy(
                    update={'caching': semantic_caching}
                ),
            },
            guardrails=self.gateway_config.guardrails,
            cache=self.gateway_config.cache,
        )

        event_service_with_semantic = EventService(
            event_dao=self.event_dao,
            key_service=self.key_service,
            group_service=self.group_service,
            request_event_dao=self.request_event_dao,
        )

        # Mock cost data from regular cache
        mocked_cost_data = CostData(
            input_cost=10.0,
            output_cost=20.0,
            total_cost=30.0,
            cache_triggered=2,
            cache_saved_tokens_input=10,
            cache_saved_tokens_output=20,
            saved_amount_input=0.0044,
            saved_amount_output=0.0088,
            total_cached_tokens=30,
            total_saved_amount=0.0132,
        )

        # Mock semantic cache cost data
        mocked_semantic_cache_data = SemanticCacheCostData(
            embedding_inference_cost=0.005,
            cache_triggered=3,
            cache_saved_tokens_input=15,
            cache_saved_tokens_output=25,
            llm_input_request_savings=0.006,
            llm_output_request_savings=0.012,
            llm_total_request_savings=0.018,
            total_cached_tokens=40,
            net_savings=0.013,  # llm_total_request_savings - embedding_inference_cost
        )

        # Mock detailed breakdown - includes semantic cache embedding costs
        mocked_detailed_breakdown = DetailedCostBreakdown(
            chat_input_direct=6,
            chat_input_cached=2,
            chat_input_judges=0,
            chat_input_judges_cached=0,
            chat_output_direct=20,
            chat_output_judges=0,
            embedding_input_total=2.005,  # Includes semantic cache embedding cost
            embedding_input_direct=2,
            embedding_input_semantic_cache=0.005,
        )

        expected = CostDataDTO(
            input_cost=10.005,  # 10.0 + embedding_inference_cost (0.005)
            output_cost=20.0,
            total_cost=30.005,  # 30.0 + embedding_inference_cost (0.005)
            cache_triggered=5,
            cache_saved_tokens_input=25,
            cache_saved_tokens_output=45,
            saved_amount_input=0.0104,
            saved_amount_output=0.0208,
            total_cached_tokens=70,
            total_saved_amount=0.0262,  # 0.0132 + net_savings (0.013)
            total=30.005,  # chat_models.total (30) + embedding_models.total (2.005)
            totals=TotalCostDTO(
                input=6.0
                + 2.005,  # chat_models.input.total (6) + embedding_models.input.total (2.005)
                cached_input=2,  # chat_models.cached_input.total
                output=20,  # chat_models.output.total
                saved=0.0262,  # total_saved_amount
            ),
            chat_models=ChatModelsCostDTO(
                input=ChatModelsInputBreakdownDTO(total=6, direct=6, judges=None),
                cached_input=ChatModelsCachedInputBreakdownDTO(
                    total=2, direct=2, judges=None
                ),
                output=ChatModelsOutputBreakdownDTO(total=20, direct=20, judges=None),
                total=28,
            ),
            embedding_models=EmbeddingModelsCostDTO(
                input=EmbeddingInputBreakdownDTO(
                    total=2.005, embedding=2, semantic_cache=0.005
                ),
                total=2.005,
            ),
        )

        self.event_dao.get_summary_costs = MagicMock(return_value=mocked_cost_data)
        self.event_dao.get_semantic_cache_details = MagicMock(
            return_value=mocked_semantic_cache_data
        )
        self.event_dao.get_detailed_cost_breakdown = MagicMock(
            return_value=mocked_detailed_breakdown
        )

        res = event_service_with_semantic.get_summary_costs(
            route_names=['route-A'],
            _from=None,
            _to=base_time + datetime.timedelta(days=7),
            _with_saved_tokens=True,
            project_uuid=self.TEST_PROJECT_UUID,
            config=gateway_config_with_semantic,
        )

        assert res is not None
        assert res == expected

    def test_get_summary_costs_with_semantic_cache_zero_embedding_cost(self):
        """Test semantic cache when embedding cost is zero (shouldn't add to total)."""
        base_time = datetime.datetime(2025, 1, 6, 0, 0, 0, tzinfo=datetime.timezone.utc)

        semantic_caching = SemanticCaching(
            enabled=True,
            type='semantic',
            ttl=3600,
            embedding_model_id='text-embedding-3-small',
            similarity_threshold=0.8,
            distance_metric='cosine',
            dim=1536,
        )

        gateway_config_with_semantic = GatewayConfig(
            chat_models=self.gateway_config.chat_models,
            embedding_models=self.gateway_config.embedding_models,
            routes={
                'route-A': self.gateway_config.routes['route-A'].model_copy(
                    update={'caching': semantic_caching}
                ),
            },
            guardrails=self.gateway_config.guardrails,
            cache=self.gateway_config.cache,
        )

        event_service_with_semantic = EventService(
            event_dao=self.event_dao,
            key_service=self.key_service,
            group_service=self.group_service,
            request_event_dao=self.request_event_dao,
        )

        mocked_cost_data = CostData(
            input_cost=10.0,
            output_cost=20.0,
            total_cost=30.0,
            cache_triggered=2,
            saved_amount_input=0.01,
            saved_amount_output=0.02,
            total_saved_amount=0.03,
        )

        # Semantic cache with zero embedding cost
        mocked_semantic_cache_data = SemanticCacheCostData(
            embedding_inference_cost=0.0,
            cache_triggered=1,
            llm_input_request_savings=0.005,
            llm_output_request_savings=0.010,
            llm_total_request_savings=0.015,
            net_savings=0.015,  # Same as llm_total since embedding cost is 0
        )

        # Detailed breakdown with zero embedding cost
        mocked_detailed_breakdown = DetailedCostBreakdown(
            chat_input_direct=8,
            chat_input_cached=2,
            chat_input_judges=0,
            chat_input_judges_cached=0,
            chat_output_direct=20,
            chat_output_judges=0,
            embedding_input_total=0,
            embedding_input_direct=0,
            embedding_input_semantic_cache=0,
        )

        expected = CostDataDTO(
            input_cost=10.0,  # No embedding cost added (0.0 is falsy)
            output_cost=20.0,
            total_cost=30.0,  # No embedding cost added
            cache_triggered=3,
            saved_amount_input=0.015,
            saved_amount_output=0.030,
            total_saved_amount=0.045,
            total=30,  # chat_models.total (8 + 2 + 20) + embedding_models.total (0)
            totals=TotalCostDTO(input=8, cached_input=2, output=20, saved=0.045),
            chat_models=ChatModelsCostDTO(
                input=ChatModelsInputBreakdownDTO(total=8, direct=8, judges=None),
                cached_input=ChatModelsCachedInputBreakdownDTO(
                    total=2, direct=2, judges=None
                ),
                output=ChatModelsOutputBreakdownDTO(total=20, direct=20, judges=None),
                total=30,  # input (8) + cached_input (2) + output (20)
            ),
            embedding_models=EmbeddingModelsCostDTO(
                input=EmbeddingInputBreakdownDTO(
                    total=0, embedding=0, semantic_cache=0
                ),
                total=0,
            ),
        )

        self.event_dao.get_summary_costs = MagicMock(return_value=mocked_cost_data)
        self.event_dao.get_semantic_cache_details = MagicMock(
            return_value=mocked_semantic_cache_data
        )
        self.event_dao.get_detailed_cost_breakdown = MagicMock(
            return_value=mocked_detailed_breakdown
        )

        res = event_service_with_semantic.get_summary_costs(
            route_names=['route-A'],
            _from=None,
            _to=base_time + datetime.timedelta(days=7),
            _with_saved_tokens=False,
            project_uuid=self.TEST_PROJECT_UUID,
            config=gateway_config_with_semantic,
        )

        assert res is not None
        assert res == expected

    def test_get_summary_costs_semantic_cache_none_optional_fields(self):
        """Test semantic cache when optional fields are None."""
        base_time = datetime.datetime(2025, 1, 6, 0, 0, 0, tzinfo=datetime.timezone.utc)

        semantic_caching = SemanticCaching(
            enabled=True,
            type='semantic',
            ttl=3600,
            embedding_model_id='text-embedding-3-small',
            similarity_threshold=0.8,
            distance_metric='cosine',
            dim=1536,
        )

        gateway_config_with_semantic = GatewayConfig(
            chat_models=self.gateway_config.chat_models,
            embedding_models=self.gateway_config.embedding_models,
            routes={
                'route-A': self.gateway_config.routes['route-A'].model_copy(
                    update={'caching': semantic_caching}
                ),
            },
            guardrails=self.gateway_config.guardrails,
            cache=self.gateway_config.cache,
        )

        event_service_with_semantic = EventService(
            event_dao=self.event_dao,
            key_service=self.key_service,
            group_service=self.group_service,
            request_event_dao=self.request_event_dao,
        )

        # Base cost data without cache fields populated
        mocked_cost_data = CostData(
            input_cost=10.0,
            output_cost=20.0,
            total_cost=30.0,
        )

        # Semantic cache with only embedding cost (no savings yet)
        mocked_semantic_cache_data = SemanticCacheCostData(
            embedding_inference_cost=0.002,
            cache_triggered=0,
            llm_input_request_savings=None,
            llm_output_request_savings=None,
            llm_total_request_savings=None,
            net_savings=None,
        )

        # Detailed breakdown with embedding cost
        mocked_detailed_breakdown = DetailedCostBreakdown(
            chat_input_direct=8,
            chat_input_cached=0,
            chat_input_judges=0,
            chat_input_judges_cached=0,
            chat_output_direct=20,
            chat_output_judges=0,
            embedding_input_total=0.002,
            embedding_input_direct=0,
            embedding_input_semantic_cache=0.002,
        )

        expected = CostDataDTO(
            input_cost=10.002,
            output_cost=20.0,
            total_cost=30.002,
            cache_triggered=None,  # Not populated in base, semantic has 0
            saved_amount_input=None,
            saved_amount_output=None,
            total_saved_amount=None,
            total=28.002,  # chat_models.total (28) + embedding_models.total (0.002)
            totals=TotalCostDTO(
                input=8.002,  # chat_models.input.total (8) + embedding_models.input.total (0.002)
                cached_input=0,  # chat_models.cached_input.total
                output=20,  # chat_models.output.total
                saved=None,
            ),
            chat_models=ChatModelsCostDTO(
                input=ChatModelsInputBreakdownDTO(total=8, direct=8, judges=None),
                cached_input=ChatModelsCachedInputBreakdownDTO(
                    total=0, direct=0, judges=None
                ),
                output=ChatModelsOutputBreakdownDTO(total=20, direct=20, judges=None),
                total=28,
            ),
            embedding_models=EmbeddingModelsCostDTO(
                input=EmbeddingInputBreakdownDTO(
                    total=0.002, embedding=0, semantic_cache=0.002
                ),
                total=0.002,
            ),
        )

        self.event_dao.get_summary_costs = MagicMock(return_value=mocked_cost_data)
        self.event_dao.get_semantic_cache_details = MagicMock(
            return_value=mocked_semantic_cache_data
        )
        self.event_dao.get_detailed_cost_breakdown = MagicMock(
            return_value=mocked_detailed_breakdown
        )

        res = event_service_with_semantic.get_summary_costs(
            route_names=['route-A'],
            _from=None,
            _to=base_time + datetime.timedelta(days=7),
            _with_saved_tokens=False,
            project_uuid=self.TEST_PROJECT_UUID,
            config=gateway_config_with_semantic,
        )

        assert res is not None
        assert res == expected

    def test_get_summary_costs_all_features_enabled(self):
        """Test CostDataDTO with all features enabled: chat models, judges, embedding models, semantic cache."""
        base_time = datetime.datetime(2025, 1, 6, 0, 0, 0, tzinfo=datetime.timezone.utc)

        # Use helper to get gateway with JUDGE guardrail and semantic caching
        gw = get_gateway_with_judge_and_semantic_cache(route_name='route-full')

        event_service_full = EventService(
            event_dao=self.event_dao,
            key_service=self.key_service,
            group_service=self.group_service,
            request_event_dao=self.request_event_dao,
        )

        # Mock cost data with cache fields
        mocked_cost_data = CostData(
            input_cost=15.0,
            output_cost=25.0,
            total_cost=40.0,
            cache_triggered=5,
            cache_saved_tokens_input=100,
            cache_saved_tokens_output=200,
            saved_amount_input=0.02,
            saved_amount_output=0.04,
            total_cached_tokens=300,
            total_saved_amount=0.06,
        )

        # Mock semantic cache data with embedding cost
        mocked_semantic_cache_data = SemanticCacheCostData(
            embedding_inference_cost=0.003,
            cache_triggered=3,
            cache_saved_tokens_input=50,
            cache_saved_tokens_output=75,
            llm_input_request_savings=0.01,
            llm_output_request_savings=0.02,
            llm_total_request_savings=0.03,
            net_savings=0.027,
        )

        # Mock detailed breakdown with ALL features populated
        mocked_detailed_breakdown = DetailedCostBreakdown(
            chat_input_direct=8.0,
            chat_input_cached=2.0,
            chat_input_judges=3.0,  # Judge input costs
            chat_input_judges_cached=1.0,  # Judge cached input costs
            chat_output_direct=20.0,
            chat_output_judges=5.0,  # Judge output costs
            embedding_input_total=0.503,  # Includes semantic cache embedding cost
            embedding_input_direct=0.5,
            embedding_input_semantic_cache=0.003,
        )

        expected = CostDataDTO(
            input_cost=15.003,  # 15.0 + embedding_inference_cost (0.003)
            output_cost=25.0,
            total_cost=40.003,  # 40.0 + embedding_inference_cost (0.003)
            cache_triggered=8,  # 5 + 3
            cache_saved_tokens_input=150,  # 100 + 50
            cache_saved_tokens_output=275,  # 200 + 75
            saved_amount_input=0.03,  # 0.02 + 0.01
            saved_amount_output=0.06,  # 0.04 + 0.02
            total_cached_tokens=300,  # From mocked_cost_data (not combined with semantic cache)
            total_saved_amount=0.087,  # 0.06 + 0.027
            total=39.503,  # chat_models.total (39) + embedding_models.total (0.503)
            totals=TotalCostDTO(
                input=11.503,  # chat_models.input.total (11) + embedding_models.input.total (0.503)
                cached_input=3.0,  # chat_models.cached_input.total (2 + 1)
                output=25.0,  # chat_models.output.total
                saved=0.087,  # total_saved_amount
            ),
            chat_models=ChatModelsCostDTO(
                input=ChatModelsInputBreakdownDTO(
                    total=11.0,
                    direct=8.0,
                    judges=3.0,  # Judges populated!
                ),
                cached_input=ChatModelsCachedInputBreakdownDTO(
                    total=3.0,
                    direct=2.0,
                    judges=1.0,  # Judges populated!
                ),
                output=ChatModelsOutputBreakdownDTO(
                    total=25.0,
                    direct=20.0,
                    judges=5.0,  # Judges populated!
                ),
                total=39.0,  # 11 + 3 + 25
            ),
            embedding_models=EmbeddingModelsCostDTO(
                input=EmbeddingInputBreakdownDTO(
                    total=0.503,
                    embedding=0.5,
                    semantic_cache=0.003,  # Semantic cache populated!
                ),
                total=0.503,
            ),
        )

        self.event_dao.get_summary_costs = MagicMock(return_value=mocked_cost_data)
        self.event_dao.get_semantic_cache_details = MagicMock(
            return_value=mocked_semantic_cache_data
        )
        self.event_dao.get_detailed_cost_breakdown = MagicMock(
            return_value=mocked_detailed_breakdown
        )

        res = event_service_full.get_summary_costs(
            route_names=['route-full'],
            _from=None,
            _to=base_time + datetime.timedelta(days=7),
            _with_saved_tokens=True,
            project_uuid=self.TEST_PROJECT_UUID,
            config=gw,
        )

        assert res is not None
        assert res == expected
        # Verify judges fields are populated (not None)
        assert res.chat_models.input.judges == 3.0
        assert res.chat_models.cached_input.judges == 1.0
        assert res.chat_models.output.judges == 5.0
        # Verify semantic_cache field is populated (not None)
        assert res.embedding_models.input.semantic_cache == 0.003

    def test_get_chart_data_multiple_models(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        mocked_chart_data = [
            CostChartDataPoint(
                bucket=base_time, group_by_value='gpt-4', total_cost=100.0
            ),
            CostChartDataPoint(
                bucket=base_time + datetime.timedelta(hours=1),
                group_by_value='gpt-4',
                total_cost=150.0,
            ),
            CostChartDataPoint(
                bucket=base_time, group_by_value='gpt-3.5-turbo', total_cost=200.0
            ),
            CostChartDataPoint(
                bucket=base_time + datetime.timedelta(hours=1),
                group_by_value='gpt-3.5-turbo',
                total_cost=250.0,
            ),
        ]

        self.event_dao.get_costs_chart_data = MagicMock(return_value=mocked_chart_data)

        res = self.event_service.get_costs_chart_data(
            route_names=['rb-gateway'],
            _from=base_time - datetime.timedelta(hours=1),
            _to=base_time + datetime.timedelta(hours=11),
            group_by='models',
            project_uuid=self.TEST_PROJECT_UUID,
        )
        expected = CostChartDataDTO(
            granularity='hours',
            timestamp=[
                int((base_time + datetime.timedelta(hours=i)).timestamp())
                for i in range(-1, 12)
            ],
            data=[
                CostChartDataSeriesDTO(
                    name='gpt-3.5-turbo',
                    data=[
                        0.0,
                        200.0,
                        250.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                    ],
                ),
                CostChartDataSeriesDTO(
                    name='gpt-4',
                    data=[
                        0.0,
                        100.0,
                        150.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                    ],
                ),
            ],
            total=700.0,
        )
        assert res == expected

    def test_get_token_chart_data(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        mocked_token_chart_data = [
            TokenChartDataPoint(
                bucket=base_time, event_type='INPUT_TOKEN_PROCESSED', total_tokens=100
            ),
            TokenChartDataPoint(
                bucket=base_time + datetime.timedelta(hours=1),
                event_type='INPUT_TOKEN_PROCESSED',
                total_tokens=150,
            ),
            TokenChartDataPoint(
                bucket=base_time, event_type='OUTPUT_TOKEN_PROCESSED', total_tokens=50
            ),
            TokenChartDataPoint(
                bucket=base_time + datetime.timedelta(hours=1),
                event_type='OUTPUT_TOKEN_PROCESSED',
                total_tokens=75,
            ),
        ]
        self.event_dao.get_token_chart_data = MagicMock(
            return_value=mocked_token_chart_data
        )

        _from = base_time
        _to = base_time + datetime.timedelta(hours=2)

        res = self.event_service.get_token_chart_data(
            self.TEST_PROJECT_UUID, ['rb-gateway'], _from, _to, 'hours'
        )

        expected = TokenChartDataDTO(
            total=375,
            granularity='hours',
            timestamp=[
                int((base_time + datetime.timedelta(hours=i)).timestamp())
                for i in range(3)
            ],
            data=[
                TokenChartDataSeriesDTO(name='INPUT', data=[100, 150, 0]),
                TokenChartDataSeriesDTO(name='OUTPUT', data=[50, 75, 0]),
            ],
        )
        assert res == expected

    def test_get_token_chart_data_empty(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        self.event_dao.get_token_chart_data = MagicMock(return_value=[])

        _from = base_time
        _to = base_time + datetime.timedelta(hours=2)

        res = self.event_service.get_token_chart_data(
            self.TEST_PROJECT_UUID, ['rb-gateway'], _from, _to, 'hours'
        )

        expected = TokenChartDataDTO(
            total=0, granularity='hours', timestamp=[], data=[]
        )
        assert res == expected

    def test_get_all_routes_costs(self):
        # Mock batch DAO methods
        mock_route_costs = [
            RouteCostData(
                route_name='route-A',
                input_cost=10.0,
                output_cost=20.0,
                total_cost=30.0,
                cache_triggered=2,
                saved_amount_input=0.05,
                saved_amount_output=0.10,
                total_saved_amount=0.15,
                cache_saved_tokens_input=0,
                cache_saved_tokens_output=0,
                total_cached_tokens=0,
            ),
            RouteCostData(
                route_name='route-B',
                input_cost=5.0,
                output_cost=10.0,
                total_cost=15.0,
                cache_triggered=0,
                saved_amount_input=0.0,
                saved_amount_output=0.0,
                total_saved_amount=0.0,
                cache_saved_tokens_input=0,
                cache_saved_tokens_output=0,
                total_cached_tokens=0,
            ),
        ]

        mock_detailed_breakdowns = [
            RouteDetailedCostBreakdown(
                route_name='route-A',
                chat_input_direct=10.0,
                chat_output_direct=20.0,
            ),
            RouteDetailedCostBreakdown(
                route_name='route-B',
                chat_input_direct=5.0,
                chat_output_direct=10.0,
            ),
        ]

        self.event_dao.get_all_routes_summary_costs = MagicMock(
            return_value=mock_route_costs
        )
        self.event_dao.get_all_routes_detailed_cost_breakdown = MagicMock(
            return_value=mock_detailed_breakdowns
        )

        res = self.event_service.get_all_routes_costs(
            _from=None,
            _to=None,
            _with_saved_tokens=False,
            project_uuid=self.TEST_PROJECT_UUID,
            config=self.gateway_config,
        )
        expected = UsageCostsDTO(
            total=45.0,
            routes=[
                RouteCostDTO(
                    route_name='route-A',
                    summary=CostDataDTO(
                        input_cost=10.0,
                        output_cost=20.0,
                        total_cost=30.0,
                        total=30.0,
                        cache_triggered=2,
                        saved_amount_input=0.05,
                        saved_amount_output=0.10,
                        total_saved_amount=0.15,
                        cache_saved_tokens_input=0,
                        cache_saved_tokens_output=0,
                        total_cached_tokens=0,
                        totals=TotalCostDTO(
                            input=10.0, cached_input=0, output=20.0, saved=0.15
                        ),
                        chat_models=ChatModelsCostDTO(
                            input=ChatModelsInputBreakdownDTO(
                                total=10.0, direct=10.0, judges=None
                            ),
                            cached_input=ChatModelsCachedInputBreakdownDTO(
                                total=0, direct=0, judges=None
                            ),
                            output=ChatModelsOutputBreakdownDTO(
                                total=20.0, direct=20.0, judges=None
                            ),
                            total=30.0,
                        ),
                        embedding_models=EmbeddingModelsCostDTO(
                            input=EmbeddingInputBreakdownDTO(
                                total=0, embedding=0, semantic_cache=None
                            ),
                            total=0,
                        ),
                    ),
                ),
                RouteCostDTO(
                    route_name='route-B',
                    summary=CostDataDTO(
                        input_cost=5.0,
                        output_cost=10.0,
                        total_cost=15.0,
                        total=15.0,
                        cache_triggered=0,
                        saved_amount_input=0.0,
                        saved_amount_output=0.0,
                        total_saved_amount=0.0,
                        cache_saved_tokens_input=0,
                        cache_saved_tokens_output=0,
                        total_cached_tokens=0,
                        totals=TotalCostDTO(
                            input=5.0, cached_input=0, output=10.0, saved=0.0
                        ),
                        chat_models=ChatModelsCostDTO(
                            input=ChatModelsInputBreakdownDTO(
                                total=5.0, direct=5.0, judges=None
                            ),
                            cached_input=ChatModelsCachedInputBreakdownDTO(
                                total=0, direct=0, judges=None
                            ),
                            output=ChatModelsOutputBreakdownDTO(
                                total=10.0, direct=10.0, judges=None
                            ),
                            total=15.0,
                        ),
                        embedding_models=EmbeddingModelsCostDTO(
                            input=EmbeddingInputBreakdownDTO(
                                total=0, embedding=0, semantic_cache=None
                            ),
                            total=0,
                        ),
                    ),
                ),
            ],
        )
        assert res == expected

    def test_get_all_routes_costs_forwards_tags_to_event_dao(self):
        self.event_dao.get_all_routes_summary_costs = MagicMock(return_value=[])
        self.event_dao.get_all_routes_detailed_cost_breakdown = MagicMock(
            return_value=[]
        )

        tags = ['env=prod', 'cost_center=retail']
        self.event_service.get_all_routes_costs(
            _from=None,
            _to=None,
            _with_saved_tokens=False,
            project_uuid=self.TEST_PROJECT_UUID,
            config=self.gateway_config,
            tags=tags,
        )

        self.event_dao.get_all_routes_summary_costs.assert_called_once_with(
            project_uuid=self.TEST_PROJECT_UUID,
            _from=None,
            _to=None,
            _with_saved_tokens=False,
            tags=tags,
        )
        self.event_dao.get_all_routes_detailed_cost_breakdown.assert_called_once_with(
            project_uuid=self.TEST_PROJECT_UUID, _from=None, _to=None, tags=tags
        )

    def test_get_total_counter_forwards_tags_to_both_daos(self):
        """get_total_counter blends EventDAO and RequestEventDAO calls; both
        must receive the same tags filter.
        """
        self.event_dao.get_all_counters = MagicMock(return_value=Counters())
        self.event_dao.get_tokens_by_model = MagicMock(return_value=[])
        self.event_dao.get_last_event = MagicMock(return_value=None)
        self.event_dao.get_routing_model_counters = MagicMock(return_value=[])
        self.request_event_dao.get_request_stats_global = MagicMock(
            return_value=RequestStats()
        )
        self.request_event_dao.get_error_breakdown = MagicMock(return_value=[])

        tags = ['env=prod', 'cost_center=retail']
        self.event_service.get_total_counter(
            project_uuid=self.TEST_PROJECT_UUID,
            config=self.gateway_config,
            _from=None,
            _to=None,
            tags=tags,
        )

        self.event_dao.get_all_counters.assert_called_once_with(
            project_uuid=self.TEST_PROJECT_UUID, _from=None, _to=None, tags=tags
        )
        self.event_dao.get_tokens_by_model.assert_called_once_with(
            project_uuid=self.TEST_PROJECT_UUID, _from=None, _to=None, tags=tags
        )
        self.request_event_dao.get_request_stats_global.assert_called_once_with(
            project_uuid=self.TEST_PROJECT_UUID, _from=None, _to=None, tags=tags
        )
        self.request_event_dao.get_error_breakdown.assert_called_once_with(
            project_uuid=self.TEST_PROJECT_UUID,
            route_name=None,
            _from=None,
            _to=None,
            tags=tags,
        )

    def test_get_all_routes_costs_empty(self):
        # Mock batch DAO methods - return empty lists (no routes with events)
        self.event_dao.get_all_routes_summary_costs = MagicMock(return_value=[])
        self.event_dao.get_all_routes_detailed_cost_breakdown = MagicMock(
            return_value=[]
        )

        res = self.event_service.get_all_routes_costs(
            _from=None,
            _to=None,
            _with_saved_tokens=False,
            project_uuid=self.TEST_PROJECT_UUID,
            config=self.gateway_config,
        )
        zero_cost_dto = CostDataDTO(
            total=0.0,
            totals=TotalCostDTO(input=0.0, cached_input=0.0, output=0.0, saved=0.0),
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
            cache_triggered=0,
            saved_amount_input=0.0,
            saved_amount_output=0.0,
            total_saved_amount=0.0,
            cache_saved_tokens_input=None,
            cache_saved_tokens_output=None,
            total_cached_tokens=None,
        )
        expected = UsageCostsDTO(
            total=0.0,
            routes=[
                RouteCostDTO(route_name='route-A', summary=zero_cost_dto),
                RouteCostDTO(route_name='route-B', summary=zero_cost_dto),
            ],
        )
        assert res == expected

    def test_get_all_routes_costs_partial_routes_with_events(self):
        """Test when some configured routes have no events"""

        # Only route-A has events, route-B doesn't
        mock_route_costs = [
            RouteCostData(
                route_name='route-A',
                input_cost=10.0,
                output_cost=20.0,
                total_cost=30.0,
                cache_triggered=2,
                saved_amount_input=0.05,
                saved_amount_output=0.10,
                total_saved_amount=0.15,
                cache_saved_tokens_input=0,
                cache_saved_tokens_output=0,
                total_cached_tokens=0,
            ),
            # route-B not in list - no events
        ]

        mock_detailed_breakdowns = [
            RouteDetailedCostBreakdown(
                route_name='route-A',
                chat_input_direct=10.0,
                chat_output_direct=20.0,
            ),
            # route-B not in list - no events
        ]

        self.event_dao.get_all_routes_summary_costs = MagicMock(
            return_value=mock_route_costs
        )
        self.event_dao.get_all_routes_detailed_cost_breakdown = MagicMock(
            return_value=mock_detailed_breakdowns
        )

        res = self.event_service.get_all_routes_costs(
            _from=None,
            _to=None,
            _with_saved_tokens=False,
            project_uuid=self.TEST_PROJECT_UUID,
            config=self.gateway_config,
        )

        # Route with events has 0 for token fields
        route_a_cost_dto = CostDataDTO(
            input_cost=10.0,
            output_cost=20.0,
            total_cost=30.0,
            total=30.0,
            cache_triggered=2,
            saved_amount_input=0.05,
            saved_amount_output=0.10,
            total_saved_amount=0.15,
            cache_saved_tokens_input=0,
            cache_saved_tokens_output=0,
            total_cached_tokens=0,
            totals=TotalCostDTO(input=10.0, cached_input=0.0, output=20.0, saved=0.15),
            chat_models=ChatModelsCostDTO(
                input=ChatModelsInputBreakdownDTO(total=10.0, direct=10.0, judges=None),
                cached_input=ChatModelsCachedInputBreakdownDTO(
                    total=0.0, direct=0.0, judges=None
                ),
                output=ChatModelsOutputBreakdownDTO(
                    total=20.0, direct=20.0, judges=None
                ),
                total=30.0,
            ),
            embedding_models=EmbeddingModelsCostDTO(
                input=EmbeddingInputBreakdownDTO(
                    total=0.0, embedding=0.0, semantic_cache=None
                ),
                total=0.0,
            ),
        )
        # Route without events has None for token fields
        route_b_cost_dto = CostDataDTO(
            total=0.0,
            totals=TotalCostDTO(input=0.0, cached_input=0.0, output=0.0, saved=0.0),
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
            cache_triggered=0,
            saved_amount_input=0.0,
            saved_amount_output=0.0,
            total_saved_amount=0.0,
            cache_saved_tokens_input=None,
            cache_saved_tokens_output=None,
            total_cached_tokens=None,
        )
        expected = UsageCostsDTO(
            total=30.0,
            routes=[
                RouteCostDTO(route_name='route-A', summary=route_a_cost_dto),
                RouteCostDTO(route_name='route-B', summary=route_b_cost_dto),
            ],
        )
        assert res == expected

    def test_get_all_routes_costs_no_routes_with_events(self):
        """Test when no routes have any events"""

        # Mock batch DAO methods - return empty lists (no routes with events)
        self.event_dao.get_all_routes_summary_costs = MagicMock(return_value=[])
        self.event_dao.get_all_routes_detailed_cost_breakdown = MagicMock(
            return_value=[]
        )

        res = self.event_service.get_all_routes_costs(
            _from=None,
            _to=None,
            _with_saved_tokens=False,
            project_uuid=self.TEST_PROJECT_UUID,
            config=self.gateway_config,
        )

        zero_cost_dto = CostDataDTO(
            total=0.0,
            totals=TotalCostDTO(input=0.0, cached_input=0.0, output=0.0, saved=0.0),
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
            cache_triggered=0,
            saved_amount_input=0.0,
            saved_amount_output=0.0,
            total_saved_amount=0.0,
            cache_saved_tokens_input=None,
            cache_saved_tokens_output=None,
            total_cached_tokens=None,
        )
        expected = UsageCostsDTO(
            total=0.0,
            routes=[
                RouteCostDTO(route_name='route-A', summary=zero_cost_dto),
                RouteCostDTO(route_name='route-B', summary=zero_cost_dto),
            ],
        )
        assert res == expected

    def test_get_all_routes_costs_with_saved_tokens_flag(self):
        """Test that _with_saved_tokens correctly populates token fields for routes without events"""

        # Only route-A has events
        mock_route_costs = [
            RouteCostData(
                route_name='route-A',
                input_cost=10.0,
                output_cost=20.0,
                total_cost=30.0,
                cache_triggered=2,
                saved_amount_input=0.05,
                saved_amount_output=0.10,
                total_saved_amount=0.15,
                cache_saved_tokens_input=100,
                cache_saved_tokens_output=200,
                total_cached_tokens=300,
            ),
            # route-B not in list - no events
        ]

        mock_detailed_breakdowns = [
            RouteDetailedCostBreakdown(
                route_name='route-A',
                chat_input_direct=10.0,
                chat_output_direct=20.0,
            ),
            # route-B not in list - no events
        ]

        self.event_dao.get_all_routes_summary_costs = MagicMock(
            return_value=mock_route_costs
        )
        self.event_dao.get_all_routes_detailed_cost_breakdown = MagicMock(
            return_value=mock_detailed_breakdowns
        )

        res = self.event_service.get_all_routes_costs(
            _from=None,
            _to=None,
            _with_saved_tokens=True,
            project_uuid=self.TEST_PROJECT_UUID,
            config=self.gateway_config,
        )

        zero_cost_dto = CostDataDTO(
            total=0.0,
            totals=TotalCostDTO(input=0, cached_input=0, output=0, saved=0),
            chat_models=ChatModelsCostDTO(
                input=ChatModelsInputBreakdownDTO(total=0, direct=0, judges=None),
                cached_input=ChatModelsCachedInputBreakdownDTO(
                    total=0, direct=0, judges=None
                ),
                output=ChatModelsOutputBreakdownDTO(total=0, direct=0, judges=None),
                total=0,
            ),
            embedding_models=EmbeddingModelsCostDTO(
                input=EmbeddingInputBreakdownDTO(
                    total=0, embedding=0, semantic_cache=None
                ),
                total=0,
            ),
            cache_triggered=0,
            saved_amount_input=0,
            saved_amount_output=0,
            total_saved_amount=0,
            cache_saved_tokens_input=0,
            cache_saved_tokens_output=0,
            total_cached_tokens=0,
        )
        expected = UsageCostsDTO(
            total=30.0,
            routes=[
                RouteCostDTO(
                    route_name='route-A',
                    summary=CostDataDTO(
                        input_cost=10.0,
                        output_cost=20.0,
                        total_cost=30.0,
                        total=30.0,
                        cache_triggered=2,
                        saved_amount_input=0.05,
                        saved_amount_output=0.10,
                        total_saved_amount=0.15,
                        cache_saved_tokens_input=100,
                        cache_saved_tokens_output=200,
                        total_cached_tokens=300,
                        totals=TotalCostDTO(
                            input=10.0, cached_input=0, output=20.0, saved=0.15
                        ),
                        chat_models=ChatModelsCostDTO(
                            input=ChatModelsInputBreakdownDTO(
                                total=10.0, direct=10.0, judges=None
                            ),
                            cached_input=ChatModelsCachedInputBreakdownDTO(
                                total=0, direct=0, judges=None
                            ),
                            output=ChatModelsOutputBreakdownDTO(
                                total=20.0, direct=20.0, judges=None
                            ),
                            total=30.0,
                        ),
                        embedding_models=EmbeddingModelsCostDTO(
                            input=EmbeddingInputBreakdownDTO(
                                total=0, embedding=0, semantic_cache=None
                            ),
                            total=0,
                        ),
                    ),
                ),
                RouteCostDTO(route_name='route-B', summary=zero_cost_dto),
            ],
        )
        assert res == expected

    def test_get_all_routes_costs_no_cache_on_route(self):
        """Test that routes without caching have None for cache fields"""
        # Create a gateway config with one route with cache and one without
        gw_with_cache = get_default_gateway_with_caching(route_name='route-with-cache')
        gw_without_cache = get_default_gateway(route_name='route-without-cache')

        gateway_config = GatewayConfig(
            chat_models=gw_with_cache.chat_models,
            embedding_models=gw_with_cache.embedding_models,
            routes={
                'route-with-cache': gw_with_cache.routes['route-with-cache'],
                'route-without-cache': gw_without_cache.routes['route-without-cache'],
            },
            guardrails=get_global_guardrails(),
            cache=get_default_cache_config(),
        )

        event_service = EventService(
            event_dao=self.event_dao,
            key_service=self.key_service,
            group_service=self.group_service,
            request_event_dao=self.request_event_dao,
        )

        # Mock batch DAO methods - return empty lists (no routes with events)
        self.event_dao.get_all_routes_summary_costs = MagicMock(return_value=[])
        self.event_dao.get_all_routes_detailed_cost_breakdown = MagicMock(
            return_value=[]
        )

        res = event_service.get_all_routes_costs(
            _from=None,
            _to=None,
            _with_saved_tokens=False,
            project_uuid=self.TEST_PROJECT_UUID,
            config=gateway_config,
        )

        route_with_cache_cost_dto = CostDataDTO(
            total=0.0,
            totals=TotalCostDTO(input=0.0, cached_input=0.0, output=0.0, saved=0.0),
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
            cache_triggered=0,
            saved_amount_input=0.0,
            saved_amount_output=0.0,
            total_saved_amount=0.0,
            cache_saved_tokens_input=None,
            cache_saved_tokens_output=None,
            total_cached_tokens=None,
        )
        route_without_cache_cost_dto = CostDataDTO(
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
            cache_triggered=None,
            saved_amount_input=None,
            saved_amount_output=None,
            total_saved_amount=None,
            cache_saved_tokens_input=None,
            cache_saved_tokens_output=None,
            total_cached_tokens=None,
        )
        expected = UsageCostsDTO(
            total=0.0,
            routes=[
                RouteCostDTO(
                    route_name='route-with-cache', summary=route_with_cache_cost_dto
                ),
                RouteCostDTO(
                    route_name='route-without-cache',
                    summary=route_without_cache_cost_dto,
                ),
            ],
        )
        assert res == expected

    def test_get_all_routes_costs_with_events_but_no_cache(self):
        """Test that routes with events but no caching have None for cache fields"""
        # Create a gateway config with one route with cache and one without
        gw_with_cache = get_default_gateway_with_caching(route_name='route-with-cache')
        gw_without_cache = get_default_gateway(route_name='route-without-cache')

        gateway_config = GatewayConfig(
            chat_models=gw_with_cache.chat_models,
            embedding_models=gw_with_cache.embedding_models,
            routes={
                'route-with-cache': gw_with_cache.routes['route-with-cache'],
                'route-without-cache': gw_without_cache.routes['route-without-cache'],
            },
            guardrails=get_global_guardrails(),
            cache=get_default_cache_config(),
        )

        event_service = EventService(
            event_dao=self.event_dao,
            key_service=self.key_service,
            group_service=self.group_service,
            request_event_dao=self.request_event_dao,
        )

        # Mock batch DAO methods - both routes have events (cost data)
        mock_route_costs = [
            RouteCostData(
                route_name='route-with-cache',
                input_cost=10.0,
                output_cost=20.0,
                total_cost=30.0,
                # DAO returns cache data even though route might not have caching
                cache_triggered=2,
                saved_amount_input=0.05,
                saved_amount_output=0.10,
                total_saved_amount=0.15,
                cache_saved_tokens_input=100,
                cache_saved_tokens_output=200,
                total_cached_tokens=300,
            ),
            RouteCostData(
                route_name='route-without-cache',
                input_cost=5.0,
                output_cost=15.0,
                total_cost=20.0,
                # DAO returns cache data, but route doesn't have caching enabled
                cache_triggered=1,
                saved_amount_input=0.02,
                saved_amount_output=0.04,
                total_saved_amount=0.06,
                cache_saved_tokens_input=50,
                cache_saved_tokens_output=100,
                total_cached_tokens=150,
            ),
        ]

        mock_detailed_breakdowns = [
            RouteDetailedCostBreakdown(
                route_name='route-with-cache',
                chat_input_direct=10.0,
                chat_output_direct=20.0,
            ),
            RouteDetailedCostBreakdown(
                route_name='route-without-cache',
                chat_input_direct=5.0,
                chat_output_direct=15.0,
            ),
        ]

        self.event_dao.get_all_routes_summary_costs = MagicMock(
            return_value=mock_route_costs
        )
        self.event_dao.get_all_routes_detailed_cost_breakdown = MagicMock(
            return_value=mock_detailed_breakdowns
        )

        res = event_service.get_all_routes_costs(
            _from=None,
            _to=None,
            _with_saved_tokens=True,
            project_uuid=self.TEST_PROJECT_UUID,
            config=gateway_config,
        )

        expected = UsageCostsDTO(
            total=50.0,
            routes=[
                RouteCostDTO(
                    route_name='route-with-cache',
                    summary=CostDataDTO(
                        input_cost=10.0,
                        output_cost=20.0,
                        total_cost=30.0,
                        total=30.0,
                        cache_triggered=2,
                        saved_amount_input=0.05,
                        saved_amount_output=0.10,
                        total_saved_amount=0.15,
                        cache_saved_tokens_input=100,
                        cache_saved_tokens_output=200,
                        total_cached_tokens=300,
                        totals=TotalCostDTO(
                            input=10.0, cached_input=0, output=20.0, saved=0.15
                        ),
                        chat_models=ChatModelsCostDTO(
                            input=ChatModelsInputBreakdownDTO(
                                total=10.0, direct=10.0, judges=None
                            ),
                            cached_input=ChatModelsCachedInputBreakdownDTO(
                                total=0, direct=0, judges=None
                            ),
                            output=ChatModelsOutputBreakdownDTO(
                                total=20.0, direct=20.0, judges=None
                            ),
                            total=30.0,
                        ),
                        embedding_models=EmbeddingModelsCostDTO(
                            input=EmbeddingInputBreakdownDTO(
                                total=0, embedding=0, semantic_cache=None
                            ),
                            total=0,
                        ),
                    ),
                ),
                RouteCostDTO(
                    route_name='route-without-cache',
                    summary=CostDataDTO(
                        input_cost=5.0,
                        output_cost=15.0,
                        total_cost=20.0,
                        total=20.0,
                        cache_triggered=None,
                        saved_amount_input=None,
                        saved_amount_output=None,
                        total_saved_amount=None,
                        cache_saved_tokens_input=None,
                        cache_saved_tokens_output=None,
                        total_cached_tokens=None,
                        totals=TotalCostDTO(
                            input=5.0, cached_input=0, output=15.0, saved=None
                        ),
                        chat_models=ChatModelsCostDTO(
                            input=ChatModelsInputBreakdownDTO(
                                total=5.0, direct=5.0, judges=None
                            ),
                            cached_input=ChatModelsCachedInputBreakdownDTO(
                                total=0, direct=0, judges=None
                            ),
                            output=ChatModelsOutputBreakdownDTO(
                                total=15.0, direct=15.0, judges=None
                            ),
                            total=20.0,
                        ),
                        embedding_models=EmbeddingModelsCostDTO(
                            input=EmbeddingInputBreakdownDTO(
                                total=0, embedding=0, semantic_cache=None
                            ),
                            total=0,
                        ),
                    ),
                ),
            ],
        )
        assert res == expected

    def test_get_invocation_chart_data_with_models(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        mocked_invocation_data = [
            InvocationChartDataPoint(bucket=base_time, group_by_value='gpt-4', value=3),
            InvocationChartDataPoint(
                bucket=base_time + datetime.timedelta(hours=1),
                group_by_value='gpt-4',
                value=5,
            ),
            InvocationChartDataPoint(
                bucket=base_time, group_by_value='gpt-3.5-turbo', value=2
            ),
            InvocationChartDataPoint(
                bucket=base_time + datetime.timedelta(hours=1),
                group_by_value='gpt-3.5-turbo',
                value=4,
            ),
        ]

        self.event_dao.get_invocation_chart_data = MagicMock(
            return_value=mocked_invocation_data
        )

        res = self.event_service.get_invocation_chart_data(
            route_names=['route-A'],
            _from=base_time - datetime.timedelta(hours=1),
            _to=base_time + datetime.timedelta(hours=11),
            granularity='hours',
            include_models=True,
            project_uuid=self.TEST_PROJECT_UUID,
        )
        expected = InvocationChartDataDTO(
            granularity='hours',
            timestamp=[
                int((base_time + datetime.timedelta(hours=i)).timestamp())
                for i in range(-1, 12)
            ],
            data=[
                ChartDataSeriesDTO(
                    name='gpt-3.5-turbo',
                    data=[0.0, 2, 4, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                ),
                ChartDataSeriesDTO(
                    name='gpt-4',
                    data=[0.0, 3, 5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                ),
            ],
            total=14,
        )
        assert res == expected

    def test_get_invocation_chart_data_without_models(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        mocked_invocation_data = [
            InvocationChartDataPoint(bucket=base_time, group_by_value='all', value=5),
            InvocationChartDataPoint(
                bucket=base_time + datetime.timedelta(hours=1),
                group_by_value='all',
                value=9,
            ),
        ]

        self.event_dao.get_invocation_chart_data = MagicMock(
            return_value=mocked_invocation_data
        )

        res = self.event_service.get_invocation_chart_data(
            route_names=['route-A'],
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=2),
            granularity='hours',
            include_models=False,
            project_uuid=self.TEST_PROJECT_UUID,
        )
        expected = InvocationChartDataDTO(
            granularity='hours',
            timestamp=[
                int((base_time + datetime.timedelta(hours=i)).timestamp())
                for i in range(3)
            ],
            data=[5.0, 9.0, 0.0],
            total=14,
        )
        assert res == expected

    def test_get_invocation_chart_data_empty(self):
        self.event_dao.get_invocation_chart_data = MagicMock(return_value=[])

        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        res = self.event_service.get_invocation_chart_data(
            route_names=['route-A'],
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=2),
            granularity='hours',
            include_models=True,
            project_uuid=self.TEST_PROJECT_UUID,
        )
        expected = InvocationChartDataDTO(
            granularity='hours', timestamp=[], data=[], total=0
        )
        assert res == expected

    def test_get_invocation_chart_data_no_from(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        mocked_invocation_data = [
            InvocationChartDataPoint(bucket=base_time, group_by_value='gpt-4', value=3),
            InvocationChartDataPoint(
                bucket=base_time + datetime.timedelta(hours=1),
                group_by_value='gpt-4',
                value=7,
            ),
        ]

        self.event_dao.get_invocation_chart_data = MagicMock(
            return_value=mocked_invocation_data
        )

        res = self.event_service.get_invocation_chart_data(
            route_names=['route-A'],
            _from=None,
            _to=base_time + datetime.timedelta(hours=1),
            granularity='hours',
            include_models=True,
            project_uuid=self.TEST_PROJECT_UUID,
        )
        expected = InvocationChartDataDTO(
            granularity='hours',
            timestamp=[
                int(base_time.timestamp()),
                int((base_time + datetime.timedelta(hours=1)).timestamp()),
            ],
            data=[
                ChartDataSeriesDTO(name='gpt-4', data=[3, 7]),
            ],
            total=10,
        )
        assert res == expected

    def test_total_counter_with_routing(self):
        self.event_dao.get_all_counters = MagicMock(
            return_value=Counters(routing_value=5)
        )
        self.event_dao.get_tokens_by_model = MagicMock(return_value=[])
        self.event_dao.get_last_event = MagicMock(return_value=None)
        self.event_dao.get_routing_model_counters = MagicMock(
            return_value=self.routing_model_counters
        )
        self.request_event_dao.get_request_stats_global = MagicMock(
            return_value=RequestStats()
        )

        res = self.event_service_routing.get_total_counter(
            _from=None,
            _to=None,
            project_uuid=self.TEST_PROJECT_UUID,
            config=self.gateway_config_with_routing,
        )

        assert res.routing is not None
        assert res.routing.value == 5
        assert len(res.routing.model_invocations) == 2
        assert (
            ModelInvocationDTO(model_id='openai', value=3)
            in res.routing.model_invocations
        )
        assert (
            ModelInvocationDTO(model_id='azure', value=2)
            in res.routing.model_invocations
        )
        assert res.fallbacks is None
        assert res.guardrails is None

    def test_total_counter_with_routing_no_events(self):
        self.event_dao.get_all_counters = MagicMock(
            return_value=Counters(routing_value=0)
        )
        self.event_dao.get_tokens_by_model = MagicMock(return_value=[])
        self.event_dao.get_last_event = MagicMock(return_value=None)
        self.event_dao.get_routing_model_counters = MagicMock(return_value=[])
        self.request_event_dao.get_request_stats_global = MagicMock(
            return_value=RequestStats()
        )

        res = self.event_service_routing.get_total_counter(
            _from=None,
            _to=None,
            project_uuid=self.TEST_PROJECT_UUID,
            config=self.gateway_config_with_routing,
        )

        assert res.routing is not None
        assert res.routing.value == 0
        assert res.routing.model_invocations == []

    def test_get_counter_per_route_with_routing(self):
        self.event_dao.get_all_counters_by_route = MagicMock(
            return_value=Counters(routing_value=5)
        )
        self.event_dao.get_tokens_by_model_per_route = MagicMock(return_value=[])
        self.event_dao.get_last_event_route = MagicMock(return_value=None)
        self.event_dao.get_routing_model_counters = MagicMock(
            return_value=self.routing_model_counters
        )
        self.request_event_dao.get_request_stats_by_route = MagicMock(
            return_value=RequestStats(
                successful_requests=10, error_requests=2, total_requests=12
            )
        )

        res = self.event_service_routing.get_counter_per_route(
            route_name='route-R',
            config=self.gateway_config_with_routing,
            include_groups=False,
            _from=None,
            _to=None,
            project_uuid=self.TEST_PROJECT_UUID,
            project_name=self.TEST_PROJECT_NAME,
        )

        assert res.metrics.routing is not None
        assert res.metrics.routing.value == 5
        assert len(res.metrics.routing.model_invocations) == 2
        assert (
            ModelInvocationDTO(model_id='openai', value=3)
            in res.metrics.routing.model_invocations
        )
        assert (
            ModelInvocationDTO(model_id='azure', value=2)
            in res.metrics.routing.model_invocations
        )
        assert res.metrics.total_requests == 12
        assert res.metrics.request_error_percentage == round(2 / 12 * 100, 2)
        assert res.metrics.fallbacks is None
        assert res.metrics.guardrails is None

    def test_get_most_expensive_route_returns_none_when_no_route(self):
        self.event_dao.get_most_expensive_route = MagicMock(return_value=None)

        res = self.event_service.get_most_expensive_route(
            _from=datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc),
            _to=datetime.datetime(2025, 1, 2, tzinfo=datetime.timezone.utc),
            project_uuid=self.TEST_PROJECT_UUID,
            config=self.gateway_config,
        )

        assert res is None

    def test_get_most_expensive_route_empty_chart_data(self):
        self.event_dao.get_most_expensive_route = MagicMock(
            return_value=MostExpensiveRoute(route_name='route-A', total_cost=100.0)
        )
        self.event_dao.get_cost_chart_data = MagicMock(return_value=[])

        _from = datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc)
        _to = datetime.datetime(2025, 1, 2, tzinfo=datetime.timezone.utc)

        res = self.event_service.get_most_expensive_route(
            _from=_from,
            _to=_to,
            project_uuid=self.TEST_PROJECT_UUID,
            config=self.gateway_config,
        )

        assert res is not None
        assert res.name == 'route-A'
        assert res.increment_percentage == 0.0
        assert res.chart.total == 100.0
        assert res.chart.timestamp == []
        assert res.chart.data == []

    def test_get_most_expensive_route_with_chart_data(self):
        self.event_dao.get_most_expensive_route = MagicMock(
            return_value=MostExpensiveRoute(route_name='route-A', total_cost=150.0)
        )

        _from = datetime.datetime(2025, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
        _to = datetime.datetime(2025, 1, 1, 3, 0, 0, tzinfo=datetime.timezone.utc)

        # 3-hour range -> granularity='hours'
        # Buckets at hour 0, 1, 2
        bucket_0 = datetime.datetime(2025, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
        bucket_1 = datetime.datetime(2025, 1, 1, 1, 0, 0, tzinfo=datetime.timezone.utc)
        bucket_2 = datetime.datetime(2025, 1, 1, 2, 0, 0, tzinfo=datetime.timezone.utc)

        chart_points = [
            MostExpensiveChartData(bucket=bucket_0, cost=50),
            MostExpensiveChartData(bucket=bucket_2, cost=100),
        ]
        self.event_dao.get_cost_chart_data = MagicMock(return_value=chart_points)

        res = self.event_service.get_most_expensive_route(
            _from=_from,
            _to=_to,
            project_uuid=self.TEST_PROJECT_UUID,
            config=self.gateway_config,
        )

        assert res is not None
        assert res.name == 'route-A'
        assert res.chart.granularity == 'hours'
        assert res.chart.total == 150
        # bucket_1 has no data -> should be 0
        assert len(res.chart.data) == len(res.chart.timestamp)
        ts_0 = int(bucket_0.timestamp())
        ts_1 = int(bucket_1.timestamp())
        ts_2 = int(bucket_2.timestamp())
        assert ts_0 in res.chart.timestamp
        assert ts_1 in res.chart.timestamp
        assert ts_2 in res.chart.timestamp
        idx_0 = res.chart.timestamp.index(ts_0)
        idx_1 = res.chart.timestamp.index(ts_1)
        idx_2 = res.chart.timestamp.index(ts_2)
        assert res.chart.data[idx_0] == 50
        assert res.chart.data[idx_1] == 0
        assert res.chart.data[idx_2] == 100

    def test_get_most_expensive_route_increment_percentage(self):
        self.event_dao.get_most_expensive_route = MagicMock(
            return_value=MostExpensiveRoute(route_name='route-B', total_cost=650.0)
        )

        _from = datetime.datetime(2025, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
        _to = datetime.datetime(2025, 1, 1, 3, 0, 0, tzinfo=datetime.timezone.utc)

        bucket_0 = datetime.datetime(2025, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
        bucket_1 = datetime.datetime(2025, 1, 1, 1, 0, 0, tzinfo=datetime.timezone.utc)
        bucket_2 = datetime.datetime(2025, 1, 1, 2, 0, 0, tzinfo=datetime.timezone.utc)
        bucket_3 = datetime.datetime(2025, 1, 1, 3, 0, 0, tzinfo=datetime.timezone.utc)

        # generate_chart_timestamps produces 4 buckets: [0h, 1h, 2h, 3h]
        # Data covers all 4 buckets so the last two are (200, 300)
        # increment = ((300 - 200) / 200) * 100 = 50.0
        chart_points = [
            MostExpensiveChartData(bucket=bucket_0, cost=100),
            MostExpensiveChartData(bucket=bucket_1, cost=50),
            MostExpensiveChartData(bucket=bucket_2, cost=200),
            MostExpensiveChartData(bucket=bucket_3, cost=300),
        ]
        self.event_dao.get_cost_chart_data = MagicMock(return_value=chart_points)

        res = self.event_service.get_most_expensive_route(
            _from=_from,
            _to=_to,
            project_uuid=self.TEST_PROJECT_UUID,
            config=self.gateway_config,
        )

        assert res is not None
        assert res.increment_percentage == 50.0
        assert res.chart.total == 650

    def test_get_most_expensive_route_no_date_filters(self):
        self.event_dao.get_most_expensive_route = MagicMock(
            return_value=MostExpensiveRoute(route_name='route-A', total_cost=50.0)
        )

        bucket = datetime.datetime(2025, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
        chart_points = [
            MostExpensiveChartData(bucket=bucket, cost=50),
        ]
        self.event_dao.get_cost_chart_data = MagicMock(return_value=chart_points)

        res = self.event_service.get_most_expensive_route(
            _from=None,
            _to=None,
            project_uuid=self.TEST_PROJECT_UUID,
            config=self.gateway_config,
        )

        assert res is not None
        assert res.name == 'route-A'
        assert res.chart.total == 50
        # Single data point -> increment_percentage should be 0.0
        assert res.increment_percentage == 0.0


class TestGetRouteLimitsProgress:
    """Unit tests for EventService.get_route_limits_progress and _get_progress_bar."""

    _RESET_TIME = 1_700_003_600

    def _make_limiter_mock(self, limit: int, remaining: int) -> MagicMock:
        m = MagicMock()
        m.get_window_stats = AsyncMock(
            return_value=WindowStats(
                remaining=remaining,
                reset_time=self._RESET_TIME,
                window_id='test-window',
                remaining_time=600,
            )
        )
        return m

    def _make_item_mock(self, limit: int, window_seconds: int) -> MagicMock:
        item = MagicMock()
        item.limit = limit
        item.window_seconds = window_seconds
        return item

    def _make_gateway_route(
        self,
        *,
        budget_limit: int | None = None,
        budget_remaining: int | None = None,
        token_input_limit: int | None = None,
        token_input_remaining: int | None = None,
        token_output_limit: int | None = None,
        token_output_remaining: int | None = None,
        rate_limit: int | None = None,
        rate_remaining: int | None = None,
        window_seconds: int = 3600,
    ) -> MagicMock:
        route = MagicMock()

        bl = MagicMock()
        if budget_limit is not None:
            bl.limiter = self._make_limiter_mock(budget_limit, budget_remaining)
            bl.item = self._make_item_mock(budget_limit, window_seconds)
        else:
            bl.limiter = None
            bl.item = None
        route.budget_limiter = bl

        tl = MagicMock()
        if token_input_limit is not None:
            tl.input_limiter = self._make_limiter_mock(
                token_input_limit, token_input_remaining
            )
            tl.input_item = self._make_item_mock(token_input_limit, window_seconds)
        else:
            tl.input_limiter = None
            tl.input_item = None
        if token_output_limit is not None:
            tl.output_limiter = self._make_limiter_mock(
                token_output_limit, token_output_remaining
            )
            tl.output_item = self._make_item_mock(token_output_limit, window_seconds)
        else:
            tl.output_limiter = None
            tl.output_item = None
        route.token_limiter = tl

        rl = MagicMock()
        if rate_limit is not None:
            rl.limiter = self._make_limiter_mock(rate_limit, rate_remaining)
            rl.item = self._make_item_mock(rate_limit, window_seconds)
        else:
            rl.limiter = None
            rl.item = None
        route.request_rate_limiter = rl

        return route

    def _make_service(self):
        return EventService(
            event_dao=MagicMock(spec_set=EventDAO),
            request_event_dao=MagicMock(spec_set=RequestEventDAO),
            key_service=MagicMock(spec_set=KeyService),
            group_service=MagicMock(spec_set=GroupService),
        )

    @pytest.mark.asyncio
    async def test_all_limiters_configured(self):
        """All four progress bars are returned when all limiters are set."""
        budget_limit = int(10.0 * BUDGET_MULTIPLIER)
        budget_remaining = int(3.0 * BUDGET_MULTIPLIER)
        routes = {
            'test/my-route': self._make_gateway_route(
                budget_limit=budget_limit,
                budget_remaining=budget_remaining,
                token_input_limit=1000,
                token_input_remaining=600,
                token_output_limit=500,
                token_output_remaining=200,
                rate_limit=100,
                rate_remaining=40,
                window_seconds=3600,
            )
        }

        result = await self._make_service().get_route_limits_progress(
            routes, 'test', None
        )

        assert len(result) == 1
        entry = result[0]
        assert entry.route_name == 'my-route'
        pb = entry.progress_bar
        assert pb is not None
        assert pb.budget.window_size == pytest.approx(10.0)
        assert pb.budget.window_filled_size == pytest.approx(7.0)
        assert pb.budget.window_filled_percentage == pytest.approx(70.0)
        assert pb.budget.window_length == 3600
        assert pb.budget.window_end_time == self._RESET_TIME
        assert pb.budget.window_start_time == self._RESET_TIME - 3600
        assert pb.token_input.window_size == 1000.0
        assert pb.token_input.window_filled_size == 400.0
        assert pb.token_input.window_filled_percentage == pytest.approx(40.0)
        assert pb.token_output.window_size == 500.0
        assert pb.token_output.window_filled_size == 300.0
        assert pb.token_output.window_filled_percentage == pytest.approx(60.0)
        assert pb.rate.window_size == 100.0
        assert pb.rate.window_filled_size == 60.0
        assert pb.rate.window_filled_percentage == pytest.approx(60.0)

    @pytest.mark.asyncio
    async def test_only_rate_limiter(self):
        """Only rate bar is non-None when only rate limiter is configured."""
        routes = {
            'test/my-route': self._make_gateway_route(rate_limit=50, rate_remaining=50)
        }
        result = await self._make_service().get_route_limits_progress(
            routes, 'test', None
        )

        pb = result[0].progress_bar
        assert pb is not None
        assert pb.rate is not None
        assert pb.budget is None
        assert pb.token_input is None
        assert pb.token_output is None

    @pytest.mark.asyncio
    async def test_no_limiters_gives_none_progress_bar(self):
        """progress_bar is None when no limiters are configured."""
        routes = {'test/my-route': self._make_gateway_route()}
        result = await self._make_service().get_route_limits_progress(
            routes, 'test', None
        )

        assert len(result) == 1
        assert result[0].route_name == 'my-route'
        assert result[0].progress_bar is None

    @pytest.mark.asyncio
    async def test_filter_by_route_names(self):
        """Only the specified route_names are included in the result."""
        routes = {
            'test/route-a': self._make_gateway_route(rate_limit=10, rate_remaining=10),
            'test/route-b': self._make_gateway_route(rate_limit=20, rate_remaining=20),
            'test/route-c': self._make_gateway_route(rate_limit=30, rate_remaining=30),
        }
        result = await self._make_service().get_route_limits_progress(
            routes, 'test', ['route-a', 'route-c']
        )

        names = {r.route_name for r in result}
        assert names == {'route-a', 'route-c'}

    @pytest.mark.asyncio
    async def test_unknown_route_name_skipped(self):
        """Unknown names in route_names filter are silently skipped."""
        routes = {
            'test/real-route': self._make_gateway_route(rate_limit=10, rate_remaining=5)
        }
        result = await self._make_service().get_route_limits_progress(
            routes, 'test', ['real-route', 'ghost-route']
        )

        assert len(result) == 1
        assert result[0].route_name == 'real-route'

    @pytest.mark.asyncio
    async def test_budget_converted_from_micro_units(self):
        """Budget values are divided by BUDGET_MULTIPLIER to give dollars."""
        max_budget = 5.0
        used = 2.5
        routes = {
            'test/r': self._make_gateway_route(
                budget_limit=int(max_budget * BUDGET_MULTIPLIER),
                budget_remaining=int((max_budget - used) * BUDGET_MULTIPLIER),
            )
        }
        result = await self._make_service().get_route_limits_progress(
            routes, 'test', None
        )

        budget = result[0].progress_bar.budget
        assert budget.window_size == pytest.approx(max_budget)
        assert budget.window_filled_size == pytest.approx(used)
        assert budget.window_filled_percentage == pytest.approx(50.0)

    @pytest.mark.asyncio
    async def test_filter_window_statuses_none_returns_all(self):
        """window_statuses=None returns all routes unchanged."""
        routes = {
            'test/route-a': self._make_gateway_route(
                rate_limit=100, rate_remaining=100
            ),
            'test/route-b': self._make_gateway_route(),
        }
        result = await self._make_service().get_route_limits_progress(
            routes, 'test', None, window_statuses=None
        )
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_filter_window_statuses_ok_includes_no_progress_bar(self):
        """Routes with no progress_bar are included when window_statuses=[ok]."""
        routes = {'test/route-a': self._make_gateway_route()}
        result = await self._make_service().get_route_limits_progress(
            routes, 'test', None, window_statuses=[WindowStatus.OK]
        )
        assert len(result) == 1
        assert result[0].route_name == 'route-a'
        assert result[0].progress_bar is None

    @pytest.mark.asyncio
    async def test_filter_window_statuses_ok_includes_all_ok_windows(self):
        """Routes where all windows are OK pass the ok filter."""
        # 70% filled → OK (≤70%)
        routes = {
            'test/route-a': self._make_gateway_route(rate_limit=100, rate_remaining=30)
        }
        result = await self._make_service().get_route_limits_progress(
            routes, 'test', None, window_statuses=[WindowStatus.OK]
        )
        assert len(result) == 1
        assert result[0].progress_bar.rate.window_status == WindowStatus.OK

    @pytest.mark.asyncio
    async def test_filter_window_statuses_ok_excludes_warning_route(self):
        """Routes with a WARNING window are excluded when only ok is requested."""
        # 80% filled → WARNING (70 < x ≤ 90%)
        routes = {
            'test/route-a': self._make_gateway_route(rate_limit=100, rate_remaining=20)
        }
        result = await self._make_service().get_route_limits_progress(
            routes, 'test', None, window_statuses=[WindowStatus.OK]
        )
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_filter_window_statuses_warning_includes_warning_route(self):
        """Routes with at least one WARNING window are included."""
        # 80% filled → WARNING
        routes = {
            'test/route-a': self._make_gateway_route(rate_limit=100, rate_remaining=20)
        }
        result = await self._make_service().get_route_limits_progress(
            routes, 'test', None, window_statuses=[WindowStatus.WARNING]
        )
        assert len(result) == 1
        assert result[0].progress_bar.rate.window_status == WindowStatus.WARNING

    @pytest.mark.asyncio
    async def test_filter_window_statuses_warning_excludes_no_progress_bar(self):
        """Routes with no progress_bar are excluded when only warning is requested."""
        routes = {'test/route-a': self._make_gateway_route()}
        result = await self._make_service().get_route_limits_progress(
            routes, 'test', None, window_statuses=[WindowStatus.WARNING]
        )
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_filter_window_statuses_critical_includes_critical_route(self):
        """Routes with at least one CRITICAL window are included."""
        # 95% filled → CRITICAL (>90%)
        routes = {
            'test/route-a': self._make_gateway_route(rate_limit=100, rate_remaining=5)
        }
        result = await self._make_service().get_route_limits_progress(
            routes, 'test', None, window_statuses=[WindowStatus.CRITICAL]
        )
        assert len(result) == 1
        assert result[0].progress_bar.rate.window_status == WindowStatus.CRITICAL

    @pytest.mark.asyncio
    async def test_filter_window_statuses_critical_excludes_ok_route(self):
        """Routes with only OK windows are excluded when only critical is requested."""
        routes = {
            'test/route-a': self._make_gateway_route(rate_limit=100, rate_remaining=50)
        }
        result = await self._make_service().get_route_limits_progress(
            routes, 'test', None, window_statuses=[WindowStatus.CRITICAL]
        )
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_filter_window_statuses_multiple_values_union(self):
        """[ok, warning] returns routes matching either condition."""
        routes = {
            'test/ok-route': self._make_gateway_route(),  # no progress_bar → ok
            'test/warning-route': self._make_gateway_route(
                rate_limit=100, rate_remaining=20
            ),  # 80% → WARNING
            'test/critical-route': self._make_gateway_route(
                rate_limit=100, rate_remaining=5
            ),  # 95% → CRITICAL
        }
        result = await self._make_service().get_route_limits_progress(
            routes,
            'test',
            None,
            window_statuses=[WindowStatus.OK, WindowStatus.WARNING],
        )
        names = {r.route_name for r in result}
        assert 'ok-route' in names
        assert 'warning-route' in names
        assert 'critical-route' not in names
