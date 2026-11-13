import datetime
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
from uuid import UUID

import pytest

from tests.common import db_mock
from tests.common.mocked_gateway_config import (
    get_default_cache_config,
    get_default_gateway,
    get_default_gateway_with_caching,
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
    EventDetails,
    InvocationChartDataPoint,
    LastEventFallback,
    LastEventGuardrail,
    ModelInvocationCounter,
    MostExpensiveChartData,
    MostExpensiveRoute,
    RequestStats,
    RouteCostData,
    RouteDetailedCostBreakdown,
    TokenChartDataPoint,
    TokensCounter,
)
from radicalbit_ai_gateway.limiter import ScenarioType, WindowConfig
from radicalbit_ai_gateway.limiter.window_config import WindowStats
from radicalbit_ai_gateway.limiting.limits import RouteLimits
from radicalbit_ai_gateway.limiting.windows import Category, Window
from radicalbit_ai_gateway.models.auth_dto import KeyOut
from radicalbit_ai_gateway.models.credentials import Credentials
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
    DurationLimitEventDetailDTO,
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
    LimitEventDetailDTO,
    ModelInvocationDTO,
    RateLimitEventDetailDTO,
    RouteCostDTO,
    TokenChartDataDTO,
    TokenChartDataSeriesDTO,
    TotalCostDTO,
    UsageCostsDTO,
    WindowStatus,
)
from radicalbit_ai_gateway.models.event_payload import LimitScope
from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.models.gateway_route_out import GatewayRouteOut
from radicalbit_ai_gateway.models.limiting import AudioDurationLimiting
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.services.event_service import EventService
from radicalbit_ai_gateway.services.group_service import GroupService
from radicalbit_ai_gateway.services.key_service import KeyService
from radicalbit_ai_gateway.utils import BUDGET_MULTIPLIER


class EventServiceTest(unittest.TestCase):
    def setUp(self):
        self.event_dao: EventDAO = MagicMock(spec_set=EventDAO)
        self.request_event_dao: RequestEventDAO = MagicMock(spec_set=RequestEventDAO)
        self.key_service: KeyService = MagicMock(spec_set=KeyService)
        self.group_service: GroupService = MagicMock(spec_set=GroupService)

        global_guardrails = get_global_guardrails()

        gw_a = get_default_gateway_with_caching(route_name='route-A')
        gw_b = get_default_gateway_with_caching(route_name='route-B')

        self.gateway_config = GatewayConfig(
            chat_models=gw_a.chat_models,
            embedding_models=gw_a.embedding_models,
            routes={
                'route-A': gw_a.routes['route-A'],
                'route-B': gw_b.routes['route-B'],
            },
            guardrails=global_guardrails,
            cache=get_default_cache_config(),
        )

        self.TEST_PROJECT_UUID = uuid.UUID('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
        self.TEST_PROJECT_NAME = 'test'

        self.event_service = EventService(
            event_dao=self.event_dao,
            request_event_dao=self.request_event_dao,
            key_service=self.key_service,
            group_service=self.group_service,
        )

        self.gateway_config_with_routing = get_gateway_with_routing(
            route_name='route-R'
        )
        self.event_service_routing = EventService(
            event_dao=self.event_dao,
            request_event_dao=self.request_event_dao,
            key_service=self.key_service,
            group_service=self.group_service,
        )
        self.routing_model_counters = [
            ModelInvocationCounter(model_id='openai', value=3),
            ModelInvocationCounter(model_id='azure', value=2),
        ]

        self.dev_key_uuid = uuid.uuid4()
        self.data_key_uuid = uuid.uuid4()
        self.counters = Counters(
            guardrail_value=2,
            fallback_value=3,
            rate_limit_triggered=2,
            token_input_limit_triggered=0,
            token_output_limit_triggered=0,
            cache_triggered=1,
        )
        self.counters_per_route = Counters(
            guardrail_value=4,
            fallback_value=1,
            rate_limit_triggered=2,
            token_input_limit_triggered=0,
            token_output_limit_triggered=0,
            cache_triggered=3,
        )
        self.tokens_counter = [
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
        self.get_last_event_details_fallback = LastEventFallback(
            route_name='route-A',
            target='gpt-4.1',
            fallback='llama3.1',
            timestamp=datetime.datetime(
                2025, 10, 14, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
            ),
            api_key_uuid=self.dev_key_uuid,
            api_key_name='dev',
        )
        self.get_last_event_details_guardrail = LastEventGuardrail(
            route_name='route-A',
            name='PRESIDIO',
            where='INPUT',
            type='READACT',
            behavior='BLOCK',
            timestamp=datetime.datetime(
                2025, 10, 14, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
            ),
            api_key_uuid=self.data_key_uuid,
            api_key_name='data',
        )
        self.mocks = [self.event_dao]

    def test_total_counter(self):
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
        self.event_dao.get_last_events = MagicMock(
            return_value={
                EventType.GUARDRAIL: self.get_last_event_details_guardrail,
                EventType.FALLBACK: self.get_last_event_details_fallback,
            }
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

    def _mock_route_metrics(
        self,
        route_name,
        counters=None,
        tokens=(),
        last_events=None,
        routing=(),
        request_stats=None,
    ):
        """Make the DAOs answer the per-route metric reads for one route."""
        self.event_dao.get_counters_of_routes = MagicMock(
            return_value={route_name: counters} if counters else {}
        )
        self.event_dao.get_tokens_by_model_of_routes = MagicMock(
            return_value=list(tokens)
        )
        self.event_dao.get_last_events_of_routes = MagicMock(
            return_value={
                (route_name, event_type): event
                for event_type, event in (last_events or {}).items()
            }
        )
        self.event_dao.get_routing_model_counters_of_routes = MagicMock(
            return_value={route_name: list(routing)} if routing else {}
        )
        self.request_event_dao.get_request_stats_of_routes = MagicMock(
            return_value={route_name: request_stats} if request_stats else {}
        )
        self.request_event_dao.get_error_breakdown_of_routes = MagicMock(
            return_value={}
        )

    def test_get_total_counter_per_route(self):
        self._mock_route_metrics(
            'route-A',
            counters=self.counters_per_route,
            tokens=self.tokens_counter,
            last_events={
                EventType.GUARDRAIL: self.get_last_event_details_guardrail,
                EventType.FALLBACK: self.get_last_event_details_fallback,
            },
            request_stats=RequestStats(
                successful_requests=10, error_requests=1, total_requests=11
            ),
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
        self._mock_route_metrics(
            'route-A',
            counters=self.counters_per_route,
            tokens=self.tokens_counter,
            last_events={
                EventType.GUARDRAIL: self.get_last_event_details_guardrail,
                EventType.FALLBACK: self.get_last_event_details_fallback,
            },
            request_stats=RequestStats(
                successful_requests=10, error_requests=1, total_requests=11
            ),
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
            duration_limit=None,
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
            limits=[
                LimitEventDetailDTO(
                    timestamp=datetime.datetime(
                        2025, 10, 13, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
                    ),
                    api_key_uuid=api_key_uuid,
                    route_name='route-A',
                    api_key_name='fake-name',
                    event_type='RATE_LIMIT',
                    limit_scope='route',
                    category='request_rate',
                )
            ],
        )
        assert res == expected

    def test_get_latest_n_per_event_type_lists_limit_blocks_newest_first(self):
        """Every limit block, whatever its scope, lands in `limits`, newest
        first and capped at n. A row recorded before limits named their
        scope gets it, and its category, from the event type.
        """
        key = uuid.UUID(int=7)

        def at(hour: int) -> datetime.datetime:
            return datetime.datetime(2025, 10, 13, hour, tzinfo=datetime.timezone.utc)

        def row(event_type: str, hour: int, **limit) -> EventDetails:
            return EventDetails(
                timestamp=at(hour),
                api_key_uuid=key,
                route_name='route-A',
                event_type=event_type,
                **limit,
            )

        budget = {'window_seconds': 86400, 'maximum': 40.0, 'consumption': 40.5}
        self.event_dao.get_latest_n_per_event_type = MagicMock(
            return_value=[
                row('GUARDRAIL', 13),
                row(
                    'CREDENTIAL_BUDGET_LIMIT',
                    12,
                    limit_scope='credential',
                    category='budget',
                    **budget,
                ),
                row('RATE_LIMIT', 11),
                row(
                    'PROJECT_BUDGET_LIMIT',
                    14,
                    limit_scope='project',
                    category='budget',
                    **budget,
                ),
                row(
                    'BUDGET_LIMIT',
                    9,
                    limit_scope='route',
                    category='budget',
                    **budget,
                ),
            ]
        )
        self.key_service.get_names_by_uuids = MagicMock(return_value={key: 'alice'})

        res = self.event_service.get_latest_n_per_event_type(
            self.TEST_PROJECT_UUID, self.gateway_config, 'route-A', 3, None, None
        )

        def block(event_type: str, hour: int, **limit) -> LimitEventDetailDTO:
            return LimitEventDetailDTO(
                timestamp=at(hour),
                api_key_uuid=key,
                route_name='route-A',
                api_key_name='alice',
                event_type=event_type,
                **limit,
            )

        assert res.limits == [
            block(
                'PROJECT_BUDGET_LIMIT',
                14,
                limit_scope='project',
                category='budget',
                **budget,
            ),
            block(
                'CREDENTIAL_BUDGET_LIMIT',
                12,
                limit_scope='credential',
                category='budget',
                **budget,
            ),
            block('RATE_LIMIT', 11, limit_scope='route', category='request_rate'),
        ]

    def test_get_latest_n_per_event_type_limits_present_without_route_limiting(self):
        """Credential and project limits apply whatever the route config
        says, so `limits` is a list even when the route limits nothing.
        """
        self.event_dao.get_latest_n_per_event_type = MagicMock(return_value=[])
        self.key_service.get_names_by_uuids = MagicMock(return_value={})

        res = self.event_service.get_latest_n_per_event_type(
            self.TEST_PROJECT_UUID, self.gateway_config, 'route-A', 10, None, None
        )

        assert res.limits == []
        assert res.model_dump(by_alias=True, exclude_none=True)['limits'] == []

    def test_get_latest_n_per_event_type_duration_limit(self):
        """AUDIO_DURATION_LIMIT events populate duration_limit when the route
        has duration_limiting configured.
        """
        transcription_model = Model(
            model_id='whisper',
            model='openai/whisper-1',
            credentials=Credentials(api_key='sk-123'),
        )
        route = GatewayRouteConfig(
            route_name='route-duration',
            transcription_models=['whisper'],
            duration_limiting=AudioDurationLimiting(
                max_duration_seconds=10, window_size='1 minute'
            ),
        )
        config = GatewayConfig(
            transcription_models=[transcription_model],
            routes={'route-duration': route},
        )

        api_key_uuid = uuid.UUID('00000000-0000-0000-0000-000000000000')
        mocked_events = [
            db_mock.get_event_detail(
                timestamp=datetime.datetime(
                    2025, 10, 13, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
                ),
                route_name='route-duration',
                event_type='AUDIO_DURATION_LIMIT',
            ),
        ]
        self.event_dao.get_latest_n_per_event_type = MagicMock(
            return_value=mocked_events
        )
        self.key_service.get_names_by_uuids = MagicMock(
            return_value={api_key_uuid: 'fake-name'}
        )

        res = self.event_service.get_latest_n_per_event_type(
            self.TEST_PROJECT_UUID,
            config,
            'route-duration',
            10,
            None,
            None,
        )

        assert res.duration_limit == [
            DurationLimitEventDetailDTO(
                timestamp=datetime.datetime(
                    2025, 10, 13, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=api_key_uuid,
                route_name='route-duration',
                api_key_name='fake-name',
                event_type='AUDIO_DURATION_LIMIT',
            )
        ]

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
            route_names=['route-A', 'route-B'],
            _from=base_time - datetime.timedelta(hours=1),
            _to=base_time + datetime.timedelta(hours=2),
            project_uuid=self.TEST_PROJECT_UUID,
        )

        self.event_dao.get_costs_chart_data_by_route.assert_called_once_with(
            project_uuid=self.TEST_PROJECT_UUID,
            entity_column='API_KEY_UUID',
            entity_value=key_uuid,
            route_names=['route-A', 'route-B'],
            _from=base_time - datetime.timedelta(hours=1),
            _to=base_time + datetime.timedelta(hours=2),
            granularity='hours',
            timezone_offset_seconds=0,
            tags=None,
        )

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

    def test_get_total_counter_forwards_tags_to_both_daos(self):
        """get_total_counter blends EventDAO and RequestEventDAO calls; both
        must receive the same tags filter.
        """
        self.event_dao.get_all_counters = MagicMock(return_value=Counters())
        self.event_dao.get_tokens_by_model = MagicMock(return_value=[])
        self.event_dao.get_last_events = MagicMock(return_value={})
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

        tags = ['env=prod', 'cost_center=retail']
        res = self.event_service.get_all_routes_costs(
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
        self.event_dao.get_last_events = MagicMock(return_value={})
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
        self.event_dao.get_last_events = MagicMock(return_value={})
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

        assert res.routing.value == 0
        assert res.routing.model_invocations == []

    def test_get_counter_per_route_with_routing(self):
        self._mock_route_metrics(
            'route-R',
            counters=Counters(routing_value=5),
            routing=self.routing_model_counters,
            request_stats=RequestStats(
                successful_requests=10, error_requests=2, total_requests=12
            ),
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
        with pytest.deprecated_call():
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

        assert res.name == 'route-A'
        assert res.increment_percentage == 0.0
        assert res.chart.total == 100.0
        assert res.chart.timestamp == []
        assert res.chart.data == []

    def test_get_most_expensive_route_with_chart_data(self):
        self.event_dao.get_most_expensive_route = MagicMock(
            return_value=MostExpensiveRoute(route_name='route-A', total_cost=600.0)
        )

        _from = datetime.datetime(2025, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
        _to = datetime.datetime(2025, 1, 1, 3, 0, 0, tzinfo=datetime.timezone.utc)
        buckets = [_from + datetime.timedelta(hours=h) for h in range(4)]

        # 3-hour range -> granularity='hours', 4 buckets; bucket 1 has no data.
        # increment = ((300 - 200) / 200) * 100 = 50.0 over the last two buckets
        self.event_dao.get_cost_chart_data = MagicMock(
            return_value=[
                MostExpensiveChartData(bucket=buckets[0], cost=100),
                MostExpensiveChartData(bucket=buckets[2], cost=200),
                MostExpensiveChartData(bucket=buckets[3], cost=300),
            ]
        )

        res = self.event_service.get_most_expensive_route(
            _from=_from,
            _to=_to,
            project_uuid=self.TEST_PROJECT_UUID,
            config=self.gateway_config,
        )

        assert res.name == 'route-A'
        assert res.chart.granularity == 'hours'
        assert res.chart.total == 600
        assert res.chart.timestamp == [int(b.timestamp()) for b in buckets]
        assert res.chart.data == [100, 0, 200, 300]
        assert res.increment_percentage == 50.0

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

    @pytest.fixture(autouse=True)
    def _limiters(self):
        """Give each window the limiter mock made for it."""
        # Keyed by the route name: each window gets a unique one.
        self._limiter_by_key = {}
        with patch.object(
            Window,
            'limiter',
            autospec=True,
            side_effect=lambda window, storage: self._limiter_by_key[
                window.config.route_name
            ],
        ):
            yield

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
        duration_limit: int | None = None,
        duration_remaining: int | None = None,
        window_seconds: int = 3600,
    ) -> MagicMock:
        windows = []
        for category, limit, remaining in (
            (Category.COST, budget_limit, budget_remaining),
            (Category.INPUT_TOKENS, token_input_limit, token_input_remaining),
            (Category.OUTPUT_TOKENS, token_output_limit, token_output_remaining),
            (Category.REQUESTS, rate_limit, rate_remaining),
            (Category.AUDIO_SECONDS, duration_limit, duration_remaining),
        ):
            if limit is None:
                continue
            window = Window(
                scope=LimitScope.ROUTE,
                category=category,
                config=WindowConfig.from_parts(
                    limit=limit,
                    window=window_seconds,
                    project_uuid='project',
                    route_name=uuid.uuid4().hex,
                    scenario_type=ScenarioType(category.value),
                ),
                aligned=False,
                shown_value=limit,
                shown_window=window_seconds,
            )
            self._limiter_by_key[window.config.route_name] = self._make_limiter_mock(
                limit, remaining
            )
            windows.append(window)
        route = MagicMock()
        route.route_limits = RouteLimits(tuple(windows))
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
        """All five progress bars are returned when all limiters are set."""
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
                duration_limit=300,
                duration_remaining=150,
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
        assert pb.duration.window_size == 300.0
        assert pb.duration.window_filled_size == 150.0
        assert pb.duration.window_filled_percentage == pytest.approx(50.0)

    @pytest.mark.asyncio
    async def test_filter_by_route_names(self):
        """Only the specified route_names are included; unknown ones are skipped."""
        routes = {
            'test/route-a': self._make_gateway_route(rate_limit=10, rate_remaining=10),
            'test/route-b': self._make_gateway_route(rate_limit=20, rate_remaining=20),
            'test/route-c': self._make_gateway_route(rate_limit=30, rate_remaining=30),
        }
        result = await self._make_service().get_route_limits_progress(
            routes, 'test', ['route-a', 'route-c', 'ghost-route']
        )

        assert sorted(r.route_name for r in result) == ['route-a', 'route-c']

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

    # Each route is None (no limiter, so no progress_bar) or (rate_remaining,
    # expected rate window_status) on a 100-request window:
    # <=70% filled is OK, <=90% WARNING, above CRITICAL.
    @pytest.mark.parametrize(
        ('window_statuses', 'routes', 'expected'),
        [
            (None, {'a': (100, WindowStatus.OK), 'b': None}, {'a', 'b'}),
            ([WindowStatus.OK], {'a': None}, {'a'}),
            ([WindowStatus.OK], {'a': (30, WindowStatus.OK)}, {'a'}),
            ([WindowStatus.OK], {'a': (20, WindowStatus.WARNING)}, set()),
            ([WindowStatus.WARNING], {'a': (20, WindowStatus.WARNING)}, {'a'}),
            ([WindowStatus.WARNING], {'a': None}, set()),
            ([WindowStatus.CRITICAL], {'a': (5, WindowStatus.CRITICAL)}, {'a'}),
            ([WindowStatus.CRITICAL], {'a': (50, WindowStatus.OK)}, set()),
            (
                [WindowStatus.OK, WindowStatus.WARNING],
                {
                    'ok': None,
                    'warning': (20, WindowStatus.WARNING),
                    'critical': (5, WindowStatus.CRITICAL),
                },
                {'ok', 'warning'},
            ),
        ],
    )
    async def test_filter_window_statuses(self, window_statuses, routes, expected):
        gateway_routes = {
            f'test/{name}': self._make_gateway_route()
            if spec is None
            else self._make_gateway_route(rate_limit=100, rate_remaining=spec[0])
            for name, spec in routes.items()
        }

        result = await self._make_service().get_route_limits_progress(
            gateway_routes, 'test', None, window_statuses=window_statuses
        )

        assert {r.route_name for r in result} == expected
        for r in result:
            spec = routes[r.route_name]
            if spec is None:
                assert r.progress_bar is None
            else:
                pb = r.progress_bar
                assert pb.rate.window_status == spec[1]
                # Only the configured limiter has a bar
                assert (pb.budget, pb.token_input, pb.token_output, pb.duration) == (
                    None,
                    None,
                    None,
                    None,
                )


class TestDecisionModelsUsage:
    """Usage shows decision spend only on routes with decision models."""

    @staticmethod
    def _config() -> GatewayConfig:
        return GatewayConfig.model_validate(
            {
                'chat_models': [{'model_id': 'gpt', 'model': 'openai/gpt-4o-mini'}],
                'decision_models': [
                    {
                        'model_id': 'jev',
                        'model': 'typesafe/jev-latest',
                        'credentials': {'api_key': 'ts-dummy'},
                    }
                ],
                'routes': {
                    'agent': {'chat_models': ['gpt'], 'decision_models': ['jev']},
                    'chat': {'chat_models': ['gpt']},
                },
            }
        )

    @staticmethod
    def _service(event_dao) -> EventService:
        return EventService(
            event_dao=event_dao,
            request_event_dao=MagicMock(spec_set=RequestEventDAO),
            key_service=MagicMock(spec_set=KeyService),
            group_service=MagicMock(spec_set=GroupService),
        )

    def test_summary_costs_without_decision_routes_have_no_decision_breakdown(self):
        event_dao = MagicMock(spec_set=EventDAO)
        event_dao.get_summary_costs.return_value = CostData(
            input_cost=0.0, output_cost=0.0, total_cost=0.0
        )
        event_dao.get_detailed_cost_breakdown.return_value = DetailedCostBreakdown(
            chat_input_direct=1.0
        )

        res = self._service(event_dao).get_summary_costs(
            project_uuid=uuid.uuid4(),
            config=self._config(),
            route_names=['chat'],
        )

        assert res.decision_models is None

    @pytest.mark.parametrize('spend', [0.0, 0.25])
    def test_all_routes_costs_show_decision_spend_only_where_configured(self, spend):
        event_dao = MagicMock(spec_set=EventDAO)
        event_dao.get_all_routes_summary_costs.return_value = []
        event_dao.get_all_routes_detailed_cost_breakdown.return_value = (
            [RouteDetailedCostBreakdown(route_name='agent', decision_input=spend)]
            if spend
            else []
        )

        res = self._service(event_dao).get_all_routes_costs(
            project_uuid=uuid.uuid4(), config=self._config()
        )

        by_route = {r.route_name: r.summary for r in res.routes}
        assert by_route['agent'].decision_models.input == spend
        assert by_route['agent'].decision_models.total == spend
        assert by_route['chat'].decision_models is None
        # Decision spend is part of the grand total
        assert res.total == spend
