import os
import unittest
from unittest.mock import MagicMock
from uuid import UUID

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from starlette.testclient import TestClient

from radicalbit_ai_gateway.db.models.event import CostData, DetailedCostBreakdown
from radicalbit_ai_gateway.models.event_dto import (
    CostDataDTO,
    RouteCostDTO,
    UsageCostsDTO,
)
from radicalbit_ai_gateway.routes.usage_route import UsageRoute
from radicalbit_ai_gateway.services.event_service import EventService
from radicalbit_ai_gateway.services.project_service import ProjectService

PROJECT_UUID = UUID('22222222-2222-2222-2222-222222222222')
PROJECT_NAME = 'test-project'


class TestUsageRoute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prefix = '/public/api/v1'
        cls.event_service: EventService = MagicMock(spec_set=EventService)
        cls.project_service: ProjectService = MagicMock(spec_set=ProjectService)
        os.environ['ENABLED_PLUGINS'] = 'registry_oidc_auth,keycloak_idp'

        project_mock = MagicMock()
        project_mock.name = PROJECT_NAME
        cls.project_service.get_by_uuid = MagicMock(return_value=project_mock)

        project_entry_mock = MagicMock()
        project_entry_mock.config.routes = {
            'route-A': MagicMock(),
            'route-B': MagicMock(),
        }

        router = UsageRoute.get_usage_router(
            event_service=cls.event_service,
            project_service=cls.project_service,
        )
        app = FastAPI(title='AI Gateway', debug=True)
        app.state.project_configs = {PROJECT_NAME: project_entry_mock}
        app.include_router(router, prefix=cls.prefix)
        cls.client = TestClient(app)
        cls.project_path = f'{cls.prefix}/projects/{PROJECT_UUID}'

    def test_usage_costs_endpoint(self):
        cost_data_route_a = CostDataDTO.from_dao(
            CostData(
                input_cost=10.5,
                output_cost=20.3,
                total_cost=30.8,
                cache_triggered=0,
                cache_saved_tokens_input=0,
                cache_saved_tokens_output=0,
                saved_amount_input=0.0,
                saved_amount_output=0.0,
                total_cached_tokens=0,
                total_saved_amount=0.0,
            ),
            None,
            DetailedCostBreakdown(
                chat_input_direct=10.5,
                chat_output_direct=20.3,
            ),
        )
        cost_data_route_b = CostDataDTO.from_dao(
            CostData(
                input_cost=5.0,
                output_cost=10.0,
                total_cost=15.0,
                cache_triggered=0,
                cache_saved_tokens_input=0,
                cache_saved_tokens_output=0,
                saved_amount_input=0.0,
                saved_amount_output=0.0,
                total_cached_tokens=0,
                total_saved_amount=0.0,
            ),
            None,
            DetailedCostBreakdown(
                chat_input_direct=5.0,
                chat_output_direct=10.0,
            ),
        )

        expected = UsageCostsDTO(
            total=45.8,
            routes=[
                RouteCostDTO(route_name='route-A', summary=cost_data_route_a),
                RouteCostDTO(route_name='route-B', summary=cost_data_route_b),
            ],
        )
        self.event_service.get_all_routes_costs = MagicMock(return_value=expected)
        response = self.client.get(f'{self.project_path}/usage/costs')
        assert response.status_code == 200
        response_json = response.json()

        assert response_json['routes'][0]['summary']['inputCost'] == 10.5
        assert response_json['routes'][0]['summary']['outputCost'] == 20.3
        assert response_json['routes'][0]['summary']['totalCost'] == 30.8
        assert 'total' in response_json['routes'][0]['summary']
        assert 'totals' in response_json['routes'][0]['summary']
        assert 'chatModels' in response_json['routes'][0]['summary']
        assert response_json['routes'][0]['summary']['total'] == 30.8

        call_kwargs = self.event_service.get_all_routes_costs.call_args.kwargs
        assert call_kwargs['project_uuid'] == PROJECT_UUID

    def test_usage_costs_with_time_range(self):
        expected = UsageCostsDTO(total=0.0, routes=[])
        self.event_service.get_all_routes_costs = MagicMock(return_value=expected)
        response = self.client.get(
            f'{self.project_path}/usage/costs?_from=1736208000&_to=1736380800'
        )
        assert response.status_code == 200
        assert response.json() == jsonable_encoder(expected, by_alias=True)

        call_kwargs = self.event_service.get_all_routes_costs.call_args.kwargs
        assert call_kwargs['_from'] is not None
        assert call_kwargs['_to'] is not None

    def test_usage_costs_empty_routes(self):
        expected = UsageCostsDTO(total=0.0, routes=[])
        self.event_service.get_all_routes_costs = MagicMock(return_value=expected)
        response = self.client.get(f'{self.project_path}/usage/costs')
        assert response.status_code == 200
        data = response.json()
        assert data['total'] == 0.0
        assert data['routes'] == []

    def test_usage_costs_includes_none_fields(self):
        cost_data = CostDataDTO.from_dao(
            CostData(
                input_cost=4.0,
                output_cost=6.0,
                total_cost=10.0,
                cache_saved_tokens_input=0,
                cache_saved_tokens_output=0,
                total_cached_tokens=0,
            ),
            None,
            None,
        )
        expected = UsageCostsDTO(
            total=10.0,
            routes=[RouteCostDTO(route_name='route-A', summary=cost_data)],
        )
        self.event_service.get_all_routes_costs = MagicMock(return_value=expected)
        response = self.client.get(f'{self.project_path}/usage/costs')
        assert response.status_code == 200
        summary = response.json()['routes'][0]['summary']
        assert 'cache_triggered' not in summary
        assert 'saved_amount_input' not in summary

    def test_usage_costs_returns_empty_when_no_active_config(self):
        app = self.client.app
        original = app.state.project_configs
        app.state.project_configs = {}
        try:
            response = self.client.get(f'{self.project_path}/usage/costs')
            assert response.status_code == 200
            assert response.json() == {'total': 0.0, 'routes': []}
        finally:
            app.state.project_configs = original
