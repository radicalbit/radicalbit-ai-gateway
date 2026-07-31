import copy
import datetime
import os
import unittest
from unittest.mock import MagicMock
import uuid
from uuid import UUID

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from starlette.testclient import TestClient

from tests.common import db_mock
from tests.common.mocked_gateway_config_openai import (
    get_gateway_dashboard_test_config,
    get_gateway_routing_text_classification,
)

from radicalbit_ai_gateway.db.models.event import (
    CostData,
    DetailedCostBreakdown,
    LastEventFallback,
    LastEventGuardrail,
)
from radicalbit_ai_gateway.models.event_dto import (
    CacheHitEventDetailDTO,
    ChartDataSeriesDTO,
    CostChartDataDTO,
    CostChartDataSeriesDTO,
    CostDataDTO,
    EventsDTO,
    Fallback,
    FallbackEventDetailDTO,
    Guardrail,
    GuardrailEventDetailDTO,
    InvocationChartDataDTO,
    LastNEvents,
    ModelCostDTO,
    RateLimitEventDetailDTO,
    RequestChartDataDTO,
    RequestGroupedChartDataDTO,
    TokenChartDataDTO,
    TokenChartDataSeriesDTO,
)
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.gateway_config_out import GatewayRouteConfigOut
from radicalbit_ai_gateway.models.gateway_route_out import GatewayRouteOut
from radicalbit_ai_gateway.models.guardrails import (
    Guardrail as GuardrailConfig,
    GuardrailType,
    JudgeParameter,
)
from radicalbit_ai_gateway.models.prompt_dto import PromptCategory
from radicalbit_ai_gateway.models.routing import (
    DeterministicRoutingConfig,
    RoutingRuleType,
    TextClassificationRoutingConfig,
)
from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.routes.dashboard_route import DashboardRoute
from radicalbit_ai_gateway.services.event_service import EventService
from radicalbit_ai_gateway.services.project_service import ProjectService
from radicalbit_ai_gateway.services.request_event_service import RequestEventService
from radicalbit_ai_gateway.utils.app_config import PromptManagerConfig
from radicalbit_ai_gateway.utils.exceptions import (
    GatewayError,
    gateway_exception_handler,
)

PROJECT_UUID = UUID('33333333-3333-3333-3333-333333333333')
PROJECT_NAME = 'test-project'


class TestDashboardRoute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prefix = '/public/api/v1'
        cls.event_service: EventService = MagicMock(spec_set=EventService)
        cls.request_event_service: RequestEventService = MagicMock(
            spec_set=RequestEventService
        )
        cls.project_service: ProjectService = MagicMock(spec_set=ProjectService)
        os.environ['ENABLED_PLUGINS'] = 'registry_oidc_auth,keycloak_idp'
        router = DashboardRoute.get_dashboard_router(
            event_service=cls.event_service,
            request_event_service=cls.request_event_service,
            project_service=cls.project_service,
        )
        app = FastAPI(title='AI Gateway', debug=True)
        app.add_exception_handler(GatewayError, gateway_exception_handler)
        app.include_router(router, prefix=cls.prefix)

        cls.gateway_config = get_gateway_dashboard_test_config()

        cls.project_entry_mock = MagicMock()
        cls.project_entry_mock.config = cls.gateway_config

        app.state.project_configs = {PROJECT_NAME: cls.project_entry_mock}
        app.state.routes = {}

        cls.client = TestClient(app)
        cls.project_path = f'{cls.prefix}/projects/{PROJECT_UUID}'

    def setUp(self):
        project_mock = MagicMock()
        project_mock.name = PROJECT_NAME
        self.project_service.get_by_uuid = MagicMock(return_value=project_mock)
        self.project_entry_mock.config = self.gateway_config

    def test_metrics_endpoint(self):
        mock_metric_dto = EventsDTO(
            fallbacks=Fallback(
                value=1,
                last_event=LastEventFallback(
                    route_name='route-A',
                    timestamp=datetime.datetime(
                        2025, 10, 14, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
                    ),
                    api_key_uuid=uuid.UUID('a45cbeeb-acbe-485b-b619-1b70361bddc6'),
                    target='gpt-4.1',
                    fallback='llama3.1',
                    api_key_name='dev',
                ),
            ),
            guardrails=Guardrail(
                value=4,
                last_event=LastEventGuardrail(
                    route_name='route-A',
                    timestamp=datetime.datetime(
                        2025, 10, 14, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
                    ),
                    api_key_uuid=uuid.UUID('28f5ede1-3d66-40c2-ac78-7aeedb5a5c92'),
                    name='PRESIDIO',
                    where='INPUT',
                    type='READACT',
                    behavior='BLOCK',
                    api_key_name='data',
                ),
            ),
            total_input_token_processed=250,
            total_output_token_processed=150,
            rate_limit_triggered=2,
            token_input_limit_triggered=0,
            token_output_limit_triggered=0,
            cache_triggered=3,
            cache_saved_tokens_input=47,
            cache_saved_tokens_output=60,
            saved_amount_input=1.4099999999999999e-05,
            saved_amount_output=0.0,
            input_cost=7.5e-05,
            output_cost=0.0,
        )
        self.event_service.get_total_counter = MagicMock(return_value=mock_metric_dto)
        response = self.client.get(f'{self.project_path}/metrics')
        assert response.status_code == 200
        assert response.json() == jsonable_encoder(mock_metric_dto, exclude_none=True)

    def test_routes_endpoint(self):
        metrics = EventsDTO(
            fallbacks=None,
            guardrails=None,
            total_input_token_processed=10,
            total_output_token_processed=45,
            rate_limit_triggered=4,
            token_input_limit_triggered=5,
            token_output_limit_triggered=76,
            cache_triggered=20,
            input_cost=0.66326,
            output_cost=0.66326,
            cache_saved_tokens_input=None,
            cache_saved_tokens_output=None,
            saved_amount_input=None,
            saved_amount_output=None,
        )
        expected_response: list[GatewayRouteOut] = []
        for route_name, route_config in self.gateway_config.routes.items():
            configuration = self._build_route_config_out(route_config)
            expected_response.append(
                GatewayRouteOut(
                    route_name=route_name,
                    configuration=configuration,
                    metrics=metrics,
                    groups=None,
                )
            )
        self.event_service.get_total_counter_per_route = MagicMock(
            return_value=expected_response
        )
        response = self.client.get(f'{self.project_path}/routes')
        assert response.status_code == 200
        assert response.json() == jsonable_encoder(expected_response, exclude_none=True)

    def test_get_routes_include_groups(self):
        metrics = EventsDTO(
            fallbacks=None,
            guardrails=None,
            total_input_token_processed=10,
            total_output_token_processed=45,
            rate_limit_triggered=4,
            token_input_limit_triggered=5,
            token_output_limit_triggered=76,
            cache_triggered=20,
            input_cost=0.66326,
            output_cost=0.66326,
            cache_saved_tokens_input=None,
            cache_saved_tokens_output=None,
            saved_amount_input=None,
            saved_amount_output=None,
        )
        expected_response: list[GatewayRouteOut] = []
        groups = [
            db_mock.get_sample_group_full_out(uuid=uuid.uuid4(), name='dev'),
            db_mock.get_sample_group_full_out(uuid=uuid.uuid4(), name='admin'),
        ]
        for route_name, route_config in self.gateway_config.routes.items():
            configuration = self._build_route_config_out(route_config)
            expected_response.append(
                GatewayRouteOut(
                    route_name=route_name,
                    configuration=configuration,
                    metrics=metrics,
                    groups=groups,
                )
            )
        self.event_service.get_total_counter_per_route = MagicMock(
            return_value=expected_response
        )
        response = self.client.get(f'{self.project_path}/routes?include_groups=true')

        assert response.status_code == 200
        assert response.json() == jsonable_encoder(expected_response, exclude_none=True)

    def test_get_single_route(self):
        metrics = EventsDTO(
            fallbacks=None,
            guardrails=None,
            total_input_token_processed=10,
            total_output_token_processed=45,
            rate_limit_triggered=4,
            token_input_limit_triggered=5,
            token_output_limit_triggered=76,
            cache_triggered=20,
            input_cost=0.66326,
            output_cost=0.66326,
            cache_saved_tokens_input=None,
            cache_saved_tokens_output=None,
            saved_amount_input=None,
            saved_amount_output=None,
        )
        route_name = 'rb-gateway'
        route_config = [
            v for k, v in self.gateway_config.routes.items() if k == route_name
        ][0]
        configuration = self._build_route_config_out(route_config)
        expected_response = GatewayRouteOut(
            route_name=route_name,
            configuration=configuration,
            metrics=metrics,
            groups=None,
        )
        self.event_service.get_counter_per_route = MagicMock(
            return_value=expected_response
        )
        response = self.client.get(f'{self.project_path}/routes/{route_name}')
        assert response.status_code == 200
        assert response.json() == jsonable_encoder(expected_response, exclude_none=True)

    def test_get_n_last_events(self):
        api_key_uuid = uuid.UUID('00000000-0000-0000-0000-000000000000')
        expected_response = LastNEvents(
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
        )
        route_name = 'rb-gateway'
        self.event_service.get_latest_n_per_event_type = MagicMock(
            return_value=expected_response
        )
        response = self.client.get(
            f'{self.project_path}/routes/{route_name}/events?n=10&_from=1760356716&_to=1760450316'
        )
        assert response.status_code == 200
        assert response.json() == jsonable_encoder(expected_response, exclude_none=True)

    def test_get_chart_data_hourly(self):
        route_name = 'rb-gateway'
        _from = '2025-01-08T00:00:00Z'
        _to = '2025-01-09T00:00:00Z'
        expected_response = CostChartDataDTO(
            granularity='hours',
            timestamp=[1736330400, 1736334000, 1736337600],
            data=[
                CostChartDataSeriesDTO(name='group-1', data=[100.5, 150.0, 200.25]),
                CostChartDataSeriesDTO(name='group-2', data=[50.0, 75.5, 100.0]),
            ],
            total=676.25,
        )
        self.event_service.get_costs_chart_data = MagicMock(
            return_value=expected_response
        )
        response = self.client.get(
            f'{self.project_path}/routes/{route_name}/costs/chart?_from={_from}&_to={_to}&group_by=groups'
        )
        assert response.status_code == 200
        assert response.json() == jsonable_encoder(expected_response, exclude_none=True)

    def test_get_chart_data_daily(self):
        route_name = 'rb-gateway'
        _from = '2025-01-06T00:00:00Z'
        _to = '2025-01-16T00:00:00Z'
        expected_response = CostChartDataDTO(
            granularity='days',
            timestamp=[1736208000, 1736294400, 1736380800],
            data=[
                CostChartDataSeriesDTO(name='api-key-1', data=[500.0, 600.0, 700.0]),
                CostChartDataSeriesDTO(name='api-key-2', data=[300.0, 400.0, 500.0]),
            ],
            total=3000.0,
        )
        self.event_service.get_costs_chart_data = MagicMock(
            return_value=expected_response
        )
        response = self.client.get(
            f'{self.project_path}/routes/{route_name}/costs/chart?_from={_from}&_to={_to}&group_by=keys'
        )
        assert response.status_code == 200
        assert response.json() == jsonable_encoder(expected_response, exclude_none=True)

    def test_get_chart_data_weekly(self):
        route_name = 'rb-gateway'
        _from = '2025-01-01T00:00:00Z'
        _to = '2025-03-02T00:00:00Z'
        expected_response = CostChartDataDTO(
            granularity='weeks',
            timestamp=[1735603200, 1736208000],
            data=[
                CostChartDataSeriesDTO(name='group-1', data=[1500.0, 2000.0]),
            ],
            total=3500.0,
        )
        self.event_service.get_costs_chart_data = MagicMock(
            return_value=expected_response
        )
        response = self.client.get(
            f'{self.project_path}/routes/{route_name}/costs/chart?_from={_from}&_to={_to}&group_by=groups'
        )
        assert response.status_code == 200
        assert response.json() == jsonable_encoder(expected_response, exclude_none=True)

    def test_get_chart_data_monthly(self):
        route_name = 'rb-gateway'
        _from = '2025-01-01T00:00:00Z'
        _to = '2026-02-15T00:00:00Z'
        expected_response = CostChartDataDTO(
            granularity='months',
            timestamp=[1735603200, 1738195200],
            data=[
                CostChartDataSeriesDTO(name='group-1', data=[5000.0, 6000.0]),
            ],
            total=11000.0,
        )
        self.event_service.get_costs_chart_data = MagicMock(
            return_value=expected_response
        )
        response = self.client.get(
            f'{self.project_path}/routes/{route_name}/costs/chart?_from={_from}&_to={_to}&group_by=groups'
        )
        assert response.status_code == 200
        assert response.json() == jsonable_encoder(expected_response, exclude_none=True)

    def test_get_chart_data_route_not_found(self):
        route_name = 'non-existent-route'
        response = self.client.get(
            f'{self.project_path}/routes/{route_name}/costs/chart?_from=2025-01-06T00:00:00Z&_to=2025-01-08T00:00:00Z&group_by=groups'
        )
        assert response.status_code == 404

    def test_get_chart_data_monthly_timezone_aware(self):
        """Test that monthly buckets respect user's timezone."""
        route_name = 'rb-gateway'
        _from = '2026-01-01T00:00:00%2B01:00'
        _to = '2026-02-01T00:00:00%2B01:00'
        expected_response = CostChartDataDTO(
            granularity='months',
            timestamp=[1735689600, 1738368000],
            data=[
                CostChartDataSeriesDTO(name='group-1', data=[5000.0, 6000.0]),
            ],
            total=11000.0,
        )
        self.event_service.get_costs_chart_data = MagicMock(
            return_value=expected_response
        )
        response = self.client.get(
            f'{self.project_path}/routes/{route_name}/costs/chart?_from={_from}&_to={_to}&group_by=groups'
        )
        assert response.status_code == 200
        assert response.json() == jsonable_encoder(expected_response, exclude_none=True)

    def test_get_chart_data_daily_timezone_aware(self):
        """Test that daily buckets respect user's timezone."""
        route_name = 'rb-gateway'
        _from = '2026-01-01T00:00:00%2B05:00'
        _to = '2026-01-03T00:00:00%2B05:00'
        expected_response = CostChartDataDTO(
            granularity='days',
            timestamp=[1735660800, 1735747200, 1735833600],
            data=[
                CostChartDataSeriesDTO(name='group-1', data=[100.0, 200.0, 300.0]),
            ],
            total=600.0,
        )
        self.event_service.get_costs_chart_data = MagicMock(
            return_value=expected_response
        )
        response = self.client.get(
            f'{self.project_path}/routes/{route_name}/costs/chart?_from={_from}&_to={_to}&group_by=groups'
        )
        assert response.status_code == 200
        assert response.json() == jsonable_encoder(expected_response, exclude_none=True)

    def test_get_chart_data_weekly_timezone_aware(self):
        """Test that weekly buckets respect user's timezone."""
        route_name = 'rb-gateway'
        _from = '2026-01-08T00:00:00-08:00'
        _to = '2026-01-22T00:00:00-08:00'
        expected_response = CostChartDataDTO(
            granularity='weeks',
            timestamp=[1736078400, 1736683200],
            data=[
                CostChartDataSeriesDTO(name='group-1', data=[1500.0, 2000.0]),
            ],
            total=3500.0,
        )
        self.event_service.get_costs_chart_data = MagicMock(
            return_value=expected_response
        )
        response = self.client.get(
            f'{self.project_path}/routes/{route_name}/costs/chart?_from={_from}&_to={_to}&group_by=groups'
        )
        assert response.status_code == 200
        assert response.json() == jsonable_encoder(expected_response, exclude_none=True)

    def test_get_chart_data_hourly_with_models(self):
        route_name = 'rb-gateway'
        _from = '2025-01-08T00:00:00Z'
        _to = '2025-01-09T00:00:00Z'
        expected_response = CostChartDataDTO(
            granularity='hours',
            timestamp=[1736330400, 1736334000, 1736337600],
            data=[
                CostChartDataSeriesDTO(name='gpt-4', data=[100.5, 150.0, 200.25]),
                CostChartDataSeriesDTO(name='gpt-3.5-turbo', data=[50.0, 75.5, 100.0]),
            ],
            total=676.25,
        )
        self.event_service.get_costs_chart_data = MagicMock(
            return_value=expected_response
        )
        response = self.client.get(
            f'{self.project_path}/routes/{route_name}/costs/chart?_from={_from}&_to={_to}&group_by=models'
        )
        assert response.status_code == 200
        assert response.json() == jsonable_encoder(expected_response, exclude_none=True)

    def test_get_chart_data_daily_with_models(self):
        route_name = 'rb-gateway'
        _from = '2025-01-07T00:00:00Z'
        _to = '2025-01-17T00:00:00Z'
        expected_response = CostChartDataDTO(
            granularity='days',
            timestamp=[1736208000, 1736294400, 1736380800],
            data=[
                CostChartDataSeriesDTO(name='gpt-4', data=[500.0, 600.0, 700.0]),
                CostChartDataSeriesDTO(
                    name='gpt-3.5-turbo', data=[300.0, 400.0, 500.0]
                ),
            ],
            total=3000.0,
        )
        self.event_service.get_costs_chart_data = MagicMock(
            return_value=expected_response
        )
        response = self.client.get(
            f'{self.project_path}/routes/{route_name}/costs/chart?_from={_from}&_to={_to}&group_by=models'
        )
        assert response.status_code == 200
        assert response.json() == jsonable_encoder(expected_response, exclude_none=True)

    def test_get_chart_data_weekly_with_models(self):
        route_name = 'rb-gateway'
        _from = '2025-01-01T00:00:00Z'
        _to = '2025-03-02T00:00:00Z'
        expected_response = CostChartDataDTO(
            granularity='weeks',
            timestamp=[1735603200, 1736208000],
            data=[
                CostChartDataSeriesDTO(name='gpt-4', data=[1500.0, 2000.0]),
                CostChartDataSeriesDTO(name='gpt-3.5-turbo', data=[1000.0, 1500.0]),
            ],
            total=6000.0,
        )
        self.event_service.get_costs_chart_data = MagicMock(
            return_value=expected_response
        )
        response = self.client.get(
            f'{self.project_path}/routes/{route_name}/costs/chart?_from={_from}&_to={_to}&group_by=models'
        )
        assert response.status_code == 200
        assert response.json() == jsonable_encoder(expected_response, exclude_none=True)

    def test_get_summary_costs_without_saved_tokens(self):
        route_name = 'rb-gateway'
        _from = 1736208000
        _to = 1736380800
        expected_response = CostData(
            input_cost=10.5,
            output_cost=20.3,
            total_cost=30.8,
        )
        self.event_service.get_summary_costs = MagicMock(return_value=expected_response)
        response = self.client.get(
            f'{self.project_path}/routes/{route_name}/costs/summary?_from={_from}&_to={_to}&_with_saved_tokens=false'
        )
        assert response.status_code == 200
        assert response.json() == jsonable_encoder(expected_response, exclude_none=True)
        self.event_service.get_summary_costs.assert_called_once()

    def test_get_summary_costs_with_saved_tokens(self):
        route_name = 'rb-gateway'
        _from = 1736208000
        _to = 1736380800
        expected_response = CostData(
            input_cost=10.5,
            output_cost=20.3,
            total_cost=30.8,
            cache_saved_tokens_input=100,
            cache_saved_tokens_output=200,
            saved_amount_input=0.05,
            saved_amount_output=0.10,
            total_cached_tokens=300,
            total_saved_amount=0.15,
        )
        self.event_service.get_summary_costs = MagicMock(return_value=expected_response)
        response = self.client.get(
            f'{self.project_path}/routes/{route_name}/costs/summary?_from={_from}&_to={_to}&_with_saved_tokens=true'
        )
        assert response.status_code == 200
        assert response.json() == jsonable_encoder(expected_response, exclude_none=True)
        self.event_service.get_summary_costs.assert_called_once()

    def test_get_summary_costs_without_timestamps(self):
        route_name = 'rb-gateway'
        expected_response = CostData(
            input_cost=5.0,
            output_cost=10.0,
            total_cost=15.0,
        )
        self.event_service.get_summary_costs = MagicMock(return_value=expected_response)
        response = self.client.get(
            f'{self.project_path}/routes/{route_name}/costs/summary?_with_saved_tokens=false'
        )
        assert response.status_code == 200
        assert response.json() == jsonable_encoder(expected_response, exclude_none=True)

    def test_get_summary_costs_route_not_found(self):
        route_name = 'non-existent-route'
        response = self.client.get(
            f'{self.project_path}/routes/{route_name}/costs/summary?_with_saved_tokens=false'
        )
        assert response.status_code == 404

    def test_get_summary_costs_with_detailed_breakdown(self):
        route_name = 'rb-gateway'
        expected_response = CostData(
            input_cost=5.0,
            output_cost=10.0,
            total_cost=15.0,
            total_saved_amount=2.5,
        )
        detailed_breakdown = DetailedCostBreakdown(
            chat_input_direct=2.0,
            chat_input_cached=1.0,
            chat_input_judges=0.5,
            chat_input_judges_cached=0.2,
            chat_output_direct=10.0,
            chat_output_judges=2.0,
            embedding_input_total=1.0,
            embedding_input_direct=0.7,
            embedding_input_semantic_cache=0.3,
        )
        self.event_service.get_summary_costs = MagicMock(
            return_value=CostDataDTO.from_dao(
                expected_response,
                None,
                detailed_breakdown,
                has_chat_models=True,
                has_judges=True,
                has_embedding_models=True,
                has_semantic_cache=True,
            )
        )
        response = self.client.get(
            f'{self.project_path}/routes/{route_name}/costs/summary?_with_saved_tokens=false'
        )
        assert response.status_code == 200
        data = response.json()
        assert 'inputCost' in data
        assert 'outputCost' in data
        assert 'totalCost' in data
        assert data['inputCost'] == 5.0
        assert data['outputCost'] == 10.0
        assert data['totalCost'] == 15.0
        assert 'total' in data
        assert 'totals' in data
        assert 'chatModels' in data
        assert 'embeddingModels' in data
        assert data['totals']['input'] == 3.5
        assert data['totals']['cachedInput'] == 1.2
        assert data['chatModels']['input']['total'] == 2.5
        assert data['chatModels']['input']['direct'] == 2.0
        assert data['chatModels']['input']['judges'] == 0.5
        assert data['chatModels']['cachedInput']['total'] == 1.2
        assert data['chatModels']['cachedInput']['direct'] == 1.0
        assert data['chatModels']['cachedInput']['judges'] == 0.2
        assert data['chatModels']['output']['total'] == 12.0
        assert data['chatModels']['output']['direct'] == 10.0
        assert data['chatModels']['output']['judges'] == 2.0
        assert data['embeddingModels']['input']['total'] == 1.0
        assert data['embeddingModels']['input']['embedding'] == 0.7
        assert data['embeddingModels']['input']['semanticCache'] == 0.3

    def test_get_summary_costs_backward_compatibility(self):
        route_name = 'rb-gateway'
        expected_response = CostData(
            input_cost=5.0,
            output_cost=10.0,
            total_cost=15.0,
        )
        self.event_service.get_summary_costs = MagicMock(
            return_value=CostDataDTO.from_dao(expected_response, None, None)
        )
        response = self.client.get(
            f'{self.project_path}/routes/{route_name}/costs/summary?_with_saved_tokens=false'
        )
        assert response.status_code == 200
        data = response.json()
        assert 'inputCost' in data
        assert 'outputCost' in data
        assert 'totalCost' in data
        assert data['inputCost'] == 5.0
        assert data['outputCost'] == 10.0
        assert data['totalCost'] == 15.0
        assert 'input' not in data
        assert 'output' not in data
        assert 'savings' not in data
        assert 'chatModels' not in data
        assert 'embeddingModels' not in data

    def _build_route_config_out(self, route_config) -> GatewayRouteConfigOut:
        route_dict = route_config.model_dump()
        gw_cfg = getattr(self, 'gateway_config', None)
        if gw_cfg is None:
            raise RuntimeError('Test setup error: self.gateway_config is missing')

        chat_ids = route_dict.get('chat_models')
        chat_registry = {m.model_id: m for m in gw_cfg.chat_models}
        route_dict['chat_models'] = [
            chat_registry[mid].model_dump() for mid in chat_ids
        ]

        emb_ids = route_dict.get('embedding_models')
        if emb_ids is None:
            route_dict['embedding_models'] = []
        else:
            emb_registry = {m.model_id: m for m in (gw_cfg.embedding_models or [])}
            route_dict['embedding_models'] = (
                [emb_registry[mid].model_dump() for mid in (emb_ids or [])]
                if emb_ids is not None
                else None
            )

        guardrails = route_dict.get('guardrails')

        if not guardrails:
            return GatewayRouteConfigOut(**route_dict)
        if guardrails and not isinstance(guardrails[0], str):
            return GatewayRouteConfigOut(**route_dict)

        global_guardrails = getattr(self, 'gateway_config', None)
        global_list = (
            getattr(global_guardrails, 'guardrails', None)
            if global_guardrails
            else None
        )
        if not global_list:
            route_dict['guardrails'] = []
            return GatewayRouteConfigOut(**route_dict)

        by_name = {g.name: g for g in global_list}
        resolved: list[dict] = []
        for name in guardrails:
            gr = by_name.get(name)
            if gr is not None:
                resolved.append(gr.model_dump())

        route_dict['guardrails'] = resolved

        routing_name = route_dict.get('routing')
        if routing_name:
            routing_cfg = gw_cfg.routing_by_name.get(routing_name)
            route_dict['routing'] = routing_cfg.model_dump() if routing_cfg else None
        else:
            route_dict['routing'] = None

        return GatewayRouteConfigOut(**route_dict)

    def test_token_chart_endpoint(self):
        route_name = 'rb-gateway'
        _from = '2025-01-08T00:00:00Z'
        _to = '2025-01-09T00:00:00Z'
        expected_response = TokenChartDataDTO(
            total=375,
            granularity='hours',
            timestamp=[1736330400, 1736334000, 1736337600],
            data=[
                TokenChartDataSeriesDTO(name='INPUT', data=[100, 150, 0]),
                TokenChartDataSeriesDTO(name='OUTPUT', data=[50, 75, 0]),
            ],
        )
        self.event_service.get_token_chart_data = MagicMock(
            return_value=expected_response
        )
        response = self.client.get(
            f'{self.project_path}/routes/{route_name}/tokens/chart',
            params={'_from': _from, '_to': _to},
        )
        assert response.status_code == 200
        assert response.json() == jsonable_encoder(expected_response, exclude_none=True)
        call_kwargs = self.event_service.get_token_chart_data.call_args[1]
        assert call_kwargs['route_names'] == [route_name]

    def test_token_chart_endpoint_not_found(self):
        response = self.client.get(
            f'{self.project_path}/routes/non-existent/tokens/chart'
        )
        assert response.status_code == 404

    def test_token_chart_endpoint_granularity_hours(self):
        route_name = 'rb-gateway'
        _from = '2025-01-08T00:00:00Z'
        _to = '2025-01-08T23:59:59Z'
        expected_response = TokenChartDataDTO(
            total=100,
            granularity='hours',
            timestamp=[1736330400],
            data=[TokenChartDataSeriesDTO(name='INPUT', data=[100])],
        )
        self.event_service.get_token_chart_data = MagicMock(
            return_value=expected_response
        )
        response = self.client.get(
            f'{self.project_path}/routes/{route_name}/tokens/chart',
            params={'_from': _from, '_to': _to},
        )
        assert response.status_code == 200
        called_granularity = self.event_service.get_token_chart_data.call_args[1][
            'granularity'
        ]
        assert called_granularity == 'hours'

    def test_token_chart_endpoint_granularity_days(self):
        route_name = 'rb-gateway'
        _from = '2025-01-08T00:00:00Z'
        _to = '2025-01-15T23:59:59Z'
        expected_response = TokenChartDataDTO(
            total=100,
            granularity='days',
            timestamp=[1736330400],
            data=[TokenChartDataSeriesDTO(name='INPUT', data=[100])],
        )
        self.event_service.get_token_chart_data = MagicMock(
            return_value=expected_response
        )
        response = self.client.get(
            f'{self.project_path}/routes/{route_name}/tokens/chart',
            params={'_from': _from, '_to': _to},
        )
        assert response.status_code == 200
        called_granularity = self.event_service.get_token_chart_data.call_args[1][
            'granularity'
        ]
        assert called_granularity == 'days'

    def test_request_chart_endpoint(self):
        route_name = 'rb-gateway'
        _from = '2025-01-08T00:00:00Z'
        _to = '2025-01-09T00:00:00Z'
        expected_response = RequestChartDataDTO(
            total=5,
            granularity='hours',
            timestamp=[1736330400, 1736334000, 1736337600],
            data=[2, 3, 0],
        )
        self.request_event_service.get_request_chart_data = MagicMock(
            return_value=expected_response
        )
        response = self.client.get(
            f'{self.project_path}/routes/{route_name}/requests/chart',
            params={'_from': _from, '_to': _to},
        )
        assert response.status_code == 200
        assert response.json() == jsonable_encoder(expected_response, exclude_none=True)
        self.request_event_service.get_request_chart_data.assert_called_once()

    def test_request_chart_endpoint_not_found(self):
        response = self.client.get(
            f'{self.project_path}/routes/non-existent/requests/chart'
        )
        assert response.status_code == 404

    def test_request_chart_endpoint_granularity_hours(self):
        route_name = 'rb-gateway'
        _from = '2025-01-08T00:00:00Z'
        _to = '2025-01-08T23:59:59Z'
        expected_response = RequestChartDataDTO(
            total=2,
            granularity='hours',
            timestamp=[1736330400],
            data=[2],
        )
        self.request_event_service.get_request_chart_data = MagicMock(
            return_value=expected_response
        )
        response = self.client.get(
            f'{self.project_path}/routes/{route_name}/requests/chart',
            params={'_from': _from, '_to': _to},
        )
        assert response.status_code == 200
        called_granularity = (
            self.request_event_service.get_request_chart_data.call_args[1][
                'granularity'
            ]
        )
        assert called_granularity == 'hours'

    def test_request_chart_endpoint_granularity_days(self):
        route_name = 'rb-gateway'
        _from = '2025-01-08T00:00:00Z'
        _to = '2025-01-15T23:59:59Z'
        expected_response = RequestChartDataDTO(
            total=3,
            granularity='days',
            timestamp=[1736330400],
            data=[3],
        )
        self.request_event_service.get_request_chart_data = MagicMock(
            return_value=expected_response
        )
        response = self.client.get(
            f'{self.project_path}/routes/{route_name}/requests/chart',
            params={'_from': _from, '_to': _to},
        )
        assert response.status_code == 200
        called_granularity = (
            self.request_event_service.get_request_chart_data.call_args[1][
                'granularity'
            ]
        )
        assert called_granularity == 'days'

    def test_request_chart_endpoint_show_errors(self):
        route_name = 'rb-gateway'
        _from = '2025-01-08T00:00:00Z'
        _to = '2025-01-09T00:00:00Z'
        expected_response = RequestGroupedChartDataDTO(
            total=6,
            granularity='hours',
            timestamp=[1736330400, 1736334000, 1736337600],
            data=[
                ChartDataSeriesDTO(name='success', data=[2.0, 3.0, 0.0]),
                ChartDataSeriesDTO(name='error', data=[1.0, 0.0, 0.0]),
            ],
        )
        self.request_event_service.get_request_grouped_chart_data = MagicMock(
            return_value=expected_response
        )
        response = self.client.get(
            f'{self.project_path}/routes/{route_name}/requests/chart',
            params={'_from': _from, '_to': _to, 'show_errors': True},
        )
        assert response.status_code == 200
        assert response.json() == jsonable_encoder(expected_response, exclude_none=True)
        self.request_event_service.get_request_grouped_chart_data.assert_called_once()

    def test_request_chart_endpoint_show_errors_false_uses_original(self):
        route_name = 'rb-gateway'
        _from = '2025-01-08T00:00:00Z'
        _to = '2025-01-09T00:00:00Z'
        expected_response = RequestChartDataDTO(
            total=5,
            granularity='hours',
            timestamp=[1736330400, 1736334000, 1736337600],
            data=[2, 3, 0],
        )
        self.request_event_service.get_request_chart_data = MagicMock(
            return_value=expected_response
        )
        response = self.client.get(
            f'{self.project_path}/routes/{route_name}/requests/chart',
            params={'_from': _from, '_to': _to, 'show_errors': False},
        )
        assert response.status_code == 200
        assert response.json() == jsonable_encoder(expected_response, exclude_none=True)
        self.request_event_service.get_request_chart_data.assert_called_once()

    def test_invocation_chart_endpoint(self):
        route_name = 'rb-gateway'
        _from = '2025-01-08T00:00:00Z'
        _to = '2025-01-09T00:00:00Z'
        expected_response = InvocationChartDataDTO(
            granularity='hours',
            timestamp=[1736330400, 1736334000, 1736337600],
            data=[
                ChartDataSeriesDTO(name='model-a', data=[3.0, 5.0, 0.0]),
                ChartDataSeriesDTO(name='model-b', data=[1.0, 2.0, 4.0]),
            ],
            total=15,
        )
        self.event_service.get_invocation_chart_data = MagicMock(
            return_value=expected_response
        )
        response = self.client.get(
            f'{self.project_path}/routes/{route_name}/invocations/chart',
            params={'_from': _from, '_to': _to},
        )
        assert response.status_code == 200
        assert response.json() == jsonable_encoder(expected_response, exclude_none=True)
        call_kwargs = self.event_service.get_invocation_chart_data.call_args[1]
        assert call_kwargs['route_names'] == [route_name]

    def test_invocation_chart_endpoint_include_models_true(self):
        route_name = 'rb-gateway'
        _from = '2025-01-08T00:00:00Z'
        _to = '2025-01-09T00:00:00Z'
        expected_response = InvocationChartDataDTO(
            granularity='hours',
            timestamp=[1736330400],
            data=[
                ChartDataSeriesDTO(name='gpt-4', data=[5.0]),
            ],
            total=5,
        )
        self.event_service.get_invocation_chart_data = MagicMock(
            return_value=expected_response
        )
        response = self.client.get(
            f'{self.project_path}/routes/{route_name}/invocations/chart',
            params={'_from': _from, '_to': _to, 'include_models': True},
        )
        assert response.status_code == 200
        call_kwargs = self.event_service.get_invocation_chart_data.call_args[1]
        assert call_kwargs['include_models'] is True

    def test_invocation_chart_endpoint_include_models_false(self):
        route_name = 'rb-gateway'
        _from = '2025-01-08T00:00:00Z'
        _to = '2025-01-09T00:00:00Z'
        expected_response = InvocationChartDataDTO(
            granularity='hours',
            timestamp=[1736330400],
            data=[10.0],
            total=10,
        )
        self.event_service.get_invocation_chart_data = MagicMock(
            return_value=expected_response
        )
        response = self.client.get(
            f'{self.project_path}/routes/{route_name}/invocations/chart',
            params={'_from': _from, '_to': _to, 'include_models': False},
        )
        assert response.status_code == 200
        assert response.json() == jsonable_encoder(expected_response, exclude_none=True)
        call_kwargs = self.event_service.get_invocation_chart_data.call_args[1]
        assert call_kwargs['include_models'] is False

    def test_invocation_chart_endpoint_default_include_models(self):
        route_name = 'rb-gateway'
        _from = '2025-01-08T00:00:00Z'
        _to = '2025-01-09T00:00:00Z'
        expected_response = InvocationChartDataDTO(
            granularity='hours', timestamp=[], data=[], total=0
        )
        self.event_service.get_invocation_chart_data = MagicMock(
            return_value=expected_response
        )
        response = self.client.get(
            f'{self.project_path}/routes/{route_name}/invocations/chart',
            params={'_from': _from, '_to': _to},
        )
        assert response.status_code == 200
        call_kwargs = self.event_service.get_invocation_chart_data.call_args[1]
        assert call_kwargs['include_models'] is False

    def test_invocation_chart_endpoint_granularity_days(self):
        route_name = 'rb-gateway'
        _from = '2025-01-08T00:00:00Z'
        _to = '2025-01-15T23:59:59Z'
        expected_response = InvocationChartDataDTO(
            granularity='days',
            timestamp=[1736330400],
            data=[3.0],
            total=3,
        )
        self.event_service.get_invocation_chart_data = MagicMock(
            return_value=expected_response
        )
        response = self.client.get(
            f'{self.project_path}/routes/{route_name}/invocations/chart',
            params={'_from': _from, '_to': _to},
        )
        assert response.status_code == 200
        called_granularity = self.event_service.get_invocation_chart_data.call_args[1][
            'granularity'
        ]
        assert called_granularity == 'days'

    def test_invocation_chart_endpoint_not_found(self):
        response = self.client.get(
            f'{self.project_path}/routes/non-existent/invocations/chart'
        )
        assert response.status_code == 404

    def test_get_route_prompts_chat_models(self):
        route_name = 'rb-gateway'
        response = self.client.get(f'{self.project_path}/routes/{route_name}/prompts')
        assert response.status_code == 200
        data = response.json()
        assert data['routeName'] == route_name
        prompts = data['prompts']
        assert len(prompts) == 3
        model_ids = [p['modelId'] for p in prompts]
        assert model_ids == ['openai', 'llama3', 'qwen']
        for p in prompts:
            assert p['category'] == PromptCategory.CHAT_MODEL.value
            assert p['prompt'] is not None
            assert p['tokens'] > 0

    def test_get_route_prompts_no_prompt(self):
        """Model without a prompt should return prompt=null, tokens=0."""
        config = copy.deepcopy(self.gateway_config)
        model = config.chat_models_by_id['openai']
        object.__setattr__(model, 'prompt', None)
        object.__setattr__(model, 'prompt_ref', None)
        self.client.app.state.project_configs[PROJECT_NAME].config = config

        response = self.client.get(f'{self.project_path}/routes/rb-gateway/prompts')
        assert response.status_code == 200
        prompts = response.json()['prompts']
        openai_prompt = next(p for p in prompts if p['modelId'] == 'openai')
        assert openai_prompt.get('prompt') is None
        assert openai_prompt['tokens'] == 0

        self.client.app.state.project_configs[PROJECT_NAME].config = self.gateway_config

    def test_get_route_prompts_not_found(self):
        response = self.client.get(
            f'{self.project_path}/routes/non-existent-route/prompts'
        )
        assert response.status_code == 404

    def test_get_route_prompts_with_judge(self):
        """Route with a JUDGE guardrail should include guardrail-judge items."""
        pm = PromptManager(conf=PromptManagerConfig())
        PromptManager.set_global(pm)

        config = copy.deepcopy(self.gateway_config)

        judge_guardrail = GuardrailConfig(
            name='injection_check',
            type=GuardrailType.JUDGE,
            where='INPUT',
            behavior='BLOCK',
            parameters=JudgeParameter(
                prompt_ref='prompt_injection_check.md',
                model_id='openai',
            ),
        )
        if config.guardrails is None:
            config.guardrails = []
        config.guardrails.append(judge_guardrail)

        route = config.routes['rb-gateway']
        if route.guardrails is None:
            route.guardrails = []
        route.guardrails.append('injection_check')

        self.client.app.state.project_configs[PROJECT_NAME].config = config

        response = self.client.get(f'{self.project_path}/routes/rb-gateway/prompts')
        assert response.status_code == 200
        prompts = response.json()['prompts']
        judge_items = [
            p for p in prompts if p['category'] == PromptCategory.GUARDRAIL_JUDGE.value
        ]
        assert len(judge_items) == 1
        judge = judge_items[0]
        assert judge['guardrailName'] == 'injection_check'
        assert judge['modelId'] == 'openai'
        assert judge['modelName'] == 'openai/gpt-4o'
        assert judge['prompt'] is not None
        assert judge['tokens'] > 0

        self.client.app.state.project_configs[PROJECT_NAME].config = self.gateway_config
        PromptManager._global_instance = None

    def test_get_route_prompts_camel_case(self):
        """Verify all response keys are camelCase."""
        response = self.client.get(f'{self.project_path}/routes/rb-gateway/prompts')
        assert response.status_code == 200
        data = response.json()
        assert 'routeName' in data
        assert 'route_name' not in data
        prompt = data['prompts'][0]
        assert 'modelId' in prompt
        assert 'modelName' in prompt
        assert 'tokens' in prompt
        assert 'model_id' not in prompt
        assert 'model_name' not in prompt

    def test_build_route_config_out_text_classification_routing(self):
        """Routing field is resolved to the full TextClassificationRoutingConfig."""
        config = get_gateway_routing_text_classification()
        route_config = config.routes['support_route']

        out = EventService._build_route_config_out(route_config, config)

        assert isinstance(out.routing, TextClassificationRoutingConfig)
        assert out.routing.name == 'intent_routing'
        assert out.routing.url == 'http://text-classifier:8888'
        assert out.routing.default_model_id == 'general_queue'
        assert len(out.routing.output_mapping) == 2

    def test_build_route_config_out_deterministic_routing(self):
        """Routing field is resolved to the full DeterministicRoutingConfig."""

        raw = {
            'chat_models': [
                {
                    'model_id': 'billing_model',
                    'model': 'openai/gpt-4o',
                    'credentials': {'api_key': 'sk-dummy'},
                },
                {
                    'model_id': 'tech_model',
                    'model': 'openai/gpt-4o-mini',
                    'credentials': {'api_key': 'sk-dummy'},
                },
                {
                    'model_id': 'default_model',
                    'model': 'openai/gpt-3.5-turbo',
                    'credentials': {'api_key': 'sk-dummy'},
                },
            ],
            'routing': [
                {
                    'name': 'kw_routing',
                    'type': 'deterministic',
                    'rule': 'keyword',
                    'default_model_id': 'default_model',
                    'output_mapping': [
                        {
                            'model_id': 'billing_model',
                            'conditions': ['billing', 'invoice'],
                        },
                        {'model_id': 'tech_model', 'conditions': ['error', 'bug']},
                    ],
                }
            ],
            'routes': {
                'kw_route': {
                    'chat_models': ['billing_model', 'tech_model', 'default_model'],
                    'routing': 'kw_routing',
                }
            },
        }
        config = GatewayConfig.model_validate(raw)
        route_config = config.routes['kw_route']

        out = EventService._build_route_config_out(route_config, config)

        assert isinstance(out.routing, DeterministicRoutingConfig)
        assert out.routing.name == 'kw_routing'
        assert out.routing.rule == RoutingRuleType.KEYWORD
        assert out.routing.default_model_id == 'default_model'
        assert len(out.routing.output_mapping) == 2

    def test_build_route_config_out_no_routing(self):
        """Routing field is None when the route has no routing configured."""
        route_config = list(self.gateway_config.routes.values())[0]
        out = EventService._build_route_config_out(route_config, self.gateway_config)
        assert out.routing is None

    def test_build_route_config_out_resolves_mcp_servers(self):
        """mcp_servers aliases are resolved to full server objects, secrets masked."""
        raw = {
            'chat_models': [
                {
                    'model_id': 'default_model',
                    'model': 'openai/gpt-4o',
                    'credentials': {'api_key': 'sk-dummy'},
                },
            ],
            'mcp_servers': [
                {
                    'alias': 'github',
                    'transport': 'streamable_http',
                    'url': 'https://api.githubcopilot.com/mcp/',
                    'headers': {'authorization': 'Bearer sk-super-secret'},
                },
                {
                    'alias': 'local-tools',
                    'transport': 'stdio',
                    'command': 'python',
                    'args': ['-m', 'tools'],
                    'env': {'API_KEY': 'sk-another-secret'},
                },
            ],
            'routes': {
                'mcp_route': {
                    'chat_models': ['default_model'],
                    'mcp_servers': ['github', 'local-tools'],
                },
                'plain_route': {'chat_models': ['default_model']},
            },
        }
        config = GatewayConfig.model_validate(raw)

        out = EventService._build_route_config_out(
            config.routes['mcp_route'], config
        )
        assert len(out.mcp_servers) == 2
        http_server, stdio_server = out.mcp_servers
        assert http_server.alias == 'github'
        assert http_server.url == 'https://api.githubcopilot.com/mcp/'
        assert str(http_server.headers['authorization']) == '**********'
        assert (
            http_server.headers['authorization'].get_secret_value()
            == 'Bearer sk-super-secret'
        )
        assert stdio_server.alias == 'local-tools'
        assert stdio_server.command == 'python'
        assert str(stdio_server.env['API_KEY']) == '**********'

        out_no_mcp = EventService._build_route_config_out(
            config.routes['plain_route'], config
        )
        assert out_no_mcp.mcp_servers is None

    def test_get_cost_breakdown_by_model(self):
        model_id = 'gpt-4'
        timestamp = 1736208000
        expected_response = [
            ModelCostDTO(route_name='route-a', cost=12.5),
            ModelCostDTO(route_name='route-b', cost=7.0),
        ]
        self.event_service.get_cost_breakdown = MagicMock(
            return_value=expected_response
        )
        response = self.client.get(
            f'{self.project_path}/routes/costs/model/{model_id}/breakdown?timestamp={timestamp}&granularity=days'
        )
        assert response.status_code == 200
        assert response.json() == [
            {'routeName': 'route-a', 'cost': 12.5},
            {'routeName': 'route-b', 'cost': 7.0},
        ]
        self.event_service.get_cost_breakdown.assert_called_once_with(
            project_uuid=PROJECT_UUID,
            entity_column='MODEL_ID',
            entity_value=model_id,
            timestamp=timestamp,
            granularity='days',
            routes=None,
        )

    def test_get_cost_breakdown_by_model_with_routes_filter(self):
        model_id = 'gpt-4'
        timestamp = 1736208000
        expected_response = [ModelCostDTO(route_name='route-a', cost=12.5)]
        self.event_service.get_cost_breakdown = MagicMock(
            return_value=expected_response
        )
        response = self.client.get(
            f'{self.project_path}/routes/costs/model/{model_id}/breakdown?timestamp={timestamp}&granularity=hours&routes=route-a'
        )
        assert response.status_code == 200
        self.event_service.get_cost_breakdown.assert_called_once_with(
            project_uuid=PROJECT_UUID,
            entity_column='MODEL_ID',
            entity_value=model_id,
            timestamp=timestamp,
            granularity='hours',
            routes=['route-a'],
        )

    def test_get_cost_breakdown_by_key(self):
        key_uuid = uuid.UUID('00000000-0000-0000-0000-000000000001')
        timestamp = 1736208000
        expected_response = [ModelCostDTO(route_name='route-a', cost=5.0)]
        self.event_service.get_cost_breakdown = MagicMock(
            return_value=expected_response
        )
        response = self.client.get(
            f'{self.project_path}/routes/costs/key/{key_uuid}/breakdown?timestamp={timestamp}&granularity=weeks'
        )
        assert response.status_code == 200
        assert response.json() == [{'routeName': 'route-a', 'cost': 5.0}]
        self.event_service.get_cost_breakdown.assert_called_once_with(
            project_uuid=PROJECT_UUID,
            entity_column='API_KEY_UUID',
            entity_value=str(key_uuid),
            timestamp=timestamp,
            granularity='weeks',
            routes=None,
        )

    def test_get_cost_breakdown_by_group(self):
        group_uuid = uuid.UUID('00000000-0000-0000-0000-000000000002')
        timestamp = 1736208000
        expected_response = [ModelCostDTO(route_name='route-a', cost=3.25)]
        self.event_service.get_cost_breakdown = MagicMock(
            return_value=expected_response
        )
        response = self.client.get(
            f'{self.project_path}/routes/costs/group/{group_uuid}/breakdown?timestamp={timestamp}&granularity=months'
        )
        assert response.status_code == 200
        assert response.json() == [{'routeName': 'route-a', 'cost': 3.25}]
        self.event_service.get_cost_breakdown.assert_called_once_with(
            project_uuid=PROJECT_UUID,
            entity_column='GROUP_UUID',
            entity_value=str(group_uuid),
            timestamp=timestamp,
            granularity='months',
            routes=None,
        )


class TestDashboardRouteNoActiveConfig(unittest.TestCase):
    """Endpoints that return lists or aggregates must return empty data (not 404)
    when the project exists in the DB but has no actively served config.
    """

    @classmethod
    def setUpClass(cls):
        cls.prefix = '/public/api/v1'
        cls.event_service: EventService = MagicMock(spec_set=EventService)
        cls.request_event_service: RequestEventService = MagicMock(
            spec_set=RequestEventService
        )
        cls.project_service: ProjectService = MagicMock(spec_set=ProjectService)
        os.environ['ENABLED_PLUGINS'] = 'registry_oidc_auth,keycloak_idp'
        router = DashboardRoute.get_dashboard_router(
            event_service=cls.event_service,
            request_event_service=cls.request_event_service,
            project_service=cls.project_service,
        )
        app = FastAPI(title='AI Gateway', debug=True)
        app.add_exception_handler(GatewayError, gateway_exception_handler)
        app.include_router(router, prefix=cls.prefix)
        app.state.project_configs = {}
        app.state.routes = {}
        cls.client = TestClient(app)
        cls.project_path = f'{cls.prefix}/projects/{PROJECT_UUID}'

    def setUp(self):
        project_mock = MagicMock()
        project_mock.name = PROJECT_NAME
        self.project_service.get_by_uuid = MagicMock(return_value=project_mock)

    def test_routes_returns_empty_list_when_no_active_config(self):
        response = self.client.get(f'{self.project_path}/routes')
        assert response.status_code == 200
        assert response.json() == []

    def test_metrics_returns_empty_dto_when_no_active_config(self):
        response = self.client.get(f'{self.project_path}/metrics')
        assert response.status_code == 200
        data = response.json()
        assert data['totalRequests'] == 0
        assert data['totalInputTokenProcessed'] == 0
        assert data['totalOutputTokenProcessed'] == 0
