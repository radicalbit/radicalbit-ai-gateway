import os
import unittest
from unittest.mock import MagicMock
from uuid import UUID

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi_pagination import Page, Params
from starlette.testclient import TestClient

from radicalbit_ai_gateway.db.models.event import CostData, DetailedCostBreakdown
from radicalbit_ai_gateway.models.event_dto import (
    CostDataDTO,
    RouteCostDTO,
    UsageCostsDTO,
)
from radicalbit_ai_gateway.models.mcp_usage_dto import McpKeyUsageDTO
from radicalbit_ai_gateway.routes.usage_route import UsageRoute
from radicalbit_ai_gateway.services.event_service import EventService
from radicalbit_ai_gateway.services.mcp_usage_service import McpUsageService
from radicalbit_ai_gateway.services.project_service import ProjectService
from radicalbit_ai_gateway.utils.exceptions import (
    GatewayError,
    GatewayNotFoundError,
    gateway_exception_handler,
)

PROJECT_UUID = UUID('22222222-2222-2222-2222-222222222222')
PROJECT_NAME = 'test-project'
KEY_UUID = UUID('660e8400-e29b-41d4-a716-446655440003')
GROUP_UUID = UUID('550e8400-e29b-41d4-a716-446655440003')


class TestUsageRoute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prefix = '/public/api/v1'
        cls.event_service: EventService = MagicMock(spec_set=EventService)
        cls.project_service: ProjectService = MagicMock(spec_set=ProjectService)
        cls.mcp_usage_service: McpUsageService = MagicMock(spec_set=McpUsageService)
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
            mcp_usage_service=cls.mcp_usage_service,
        )
        app = FastAPI(title='AI Gateway', debug=True)
        app.add_exception_handler(GatewayError, gateway_exception_handler)
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

    def test_usage_costs_with_tags(self):
        expected = UsageCostsDTO(total=0.0, routes=[])
        self.event_service.get_all_routes_costs = MagicMock(return_value=expected)
        response = self.client.get(
            f'{self.project_path}/usage/costs'
            '?tags=env=prod&tags=env=staging&tags=cost_center=retail'
        )
        assert response.status_code == 200

        call_kwargs = self.event_service.get_all_routes_costs.call_args.kwargs
        assert call_kwargs['tags'] == [
            'env=prod',
            'env=staging',
            'cost_center=retail',
        ]

    def test_usage_costs_with_malformed_tag_returns_400(self):
        response = self.client.get(f'{self.project_path}/usage/costs?tags=not-a-tag')
        assert response.status_code == 400

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

    def _mcp_key_usage_page(self, params: Params = Params(page=1, size=50)):
        return Page.create(
            [
                McpKeyUsageDTO(
                    key_name='my-key',
                    key_uuid=KEY_UUID,
                    group_name='my-group',
                    group_uuid=GROUP_UUID,
                    counter=12,
                    last_call=1736330400,
                )
            ],
            params,
            total=1,
        )

    def test_mcp_key_usage_endpoint(self):
        self.mcp_usage_service.get_mcp_key_usage = MagicMock(
            return_value=self._mcp_key_usage_page()
        )

        response = self.client.get(f'{self.project_path}/usage/mcp/keys')

        assert response.status_code == 200
        body = response.json()
        assert body['total'] == 1
        assert body['items'] == [
            {
                'keyName': 'my-key',
                'keyUuid': str(KEY_UUID),
                'groupName': 'my-group',
                'groupUuid': str(GROUP_UUID),
                'counter': 12,
                'lastCall': 1736330400,
            }
        ]

    def test_mcp_key_usage_defaults_to_no_filters(self):
        self.mcp_usage_service.get_mcp_key_usage = MagicMock(
            return_value=self._mcp_key_usage_page()
        )

        response = self.client.get(f'{self.project_path}/usage/mcp/keys')

        assert response.status_code == 200
        call_kwargs = self.mcp_usage_service.get_mcp_key_usage.call_args.kwargs
        assert call_kwargs['project_uuid'] == PROJECT_UUID
        assert call_kwargs['route_names'] is None
        assert call_kwargs['_from'] is None
        assert call_kwargs['_to'] is None
        assert call_kwargs['tags'] is None
        assert call_kwargs['params'] == Params(page=1, size=50)

    def test_mcp_key_usage_passes_every_filter_on(self):
        self.mcp_usage_service.get_mcp_key_usage = MagicMock(
            return_value=self._mcp_key_usage_page(Params(page=2, size=10))
        )

        response = self.client.get(
            f'{self.project_path}/usage/mcp/keys'
            '?routes=agents&routes=chat'
            '&_from=1736208000&_to=1736380800'
            '&tags=env=prod&tags=env=staging&tags=cost_center=retail'
            '&_page=2&_limit=10'
        )

        assert response.status_code == 200
        call_kwargs = self.mcp_usage_service.get_mcp_key_usage.call_args.kwargs
        assert call_kwargs['route_names'] == ['agents', 'chat']
        assert call_kwargs['_from'].timestamp() == 1736208000
        assert call_kwargs['_to'].timestamp() == 1736380800
        assert call_kwargs['tags'] == [
            'env=prod',
            'env=staging',
            'cost_center=retail',
        ]
        assert call_kwargs['params'] == Params(page=2, size=10)

    def test_mcp_key_usage_with_no_traffic_returns_an_empty_page(self):
        self.mcp_usage_service.get_mcp_key_usage = MagicMock(
            return_value=Page.create([], Params(page=1, size=50), total=0)
        )

        response = self.client.get(f'{self.project_path}/usage/mcp/keys')

        assert response.status_code == 200
        assert response.json()['items'] == []
        assert response.json()['total'] == 0

    def test_mcp_key_usage_unknown_project_returns_404(self):
        self.project_service.validate_exists = MagicMock(
            side_effect=GatewayNotFoundError('Project not found')
        )
        try:
            response = self.client.get(f'{self.project_path}/usage/mcp/keys')
            assert response.status_code == 404
        finally:
            self.project_service.validate_exists = MagicMock()

    def test_mcp_key_usage_with_malformed_tag_returns_400(self):
        response = self.client.get(f'{self.project_path}/usage/mcp/keys?tags=not-a-tag')
        assert response.status_code == 400

    def test_mcp_key_usage_limit_is_bounded(self):
        response = self.client.get(f'{self.project_path}/usage/mcp/keys?_limit=101')
        assert response.status_code == 422
