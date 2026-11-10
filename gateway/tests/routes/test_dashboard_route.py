import copy
import datetime
import os
import unittest
from unittest.mock import MagicMock
import uuid
from uuid import UUID

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
import pytest
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
from radicalbit_ai_gateway.services.mcp_usage_service import McpUsageService
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
        cls.mcp_usage_service: McpUsageService = MagicMock(spec_set=McpUsageService)
        os.environ['ENABLED_PLUGINS'] = 'registry_oidc_auth,keycloak_idp'
        router = DashboardRoute.get_dashboard_router(
            event_service=cls.event_service,
            request_event_service=cls.request_event_service,
            project_service=cls.project_service,
            mcp_usage_service=cls.mcp_usage_service,
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
        response = self.client.get(
            f'{self.project_path}/metrics'
            '?tags=env=prod&tags=env=staging&tags=cost_center=retail'
        )
        assert response.status_code == 200
        assert response.json() == jsonable_encoder(mock_metric_dto, exclude_none=True)
        call_kwargs = self.event_service.get_total_counter.call_args.kwargs
        assert call_kwargs['tags'] == ['env=prod', 'env=staging', 'cost_center=retail']

    def test_metrics_endpoint_with_malformed_tag_returns_400(self):
        response = self.client.get(f'{self.project_path}/metrics?tags=not-a-tag')
        assert response.status_code == 400

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
        call_kwargs = self.event_service.get_total_counter_per_route.call_args.kwargs
        assert call_kwargs['include_groups'] is True
        assert call_kwargs['project_name'] == PROJECT_NAME

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

    def test_get_route_prompts_chat_models(self):
        route_name = 'rb-gateway'
        response = self.client.get(f'{self.project_path}/routes/{route_name}/prompts')
        assert response.status_code == 200
        data = response.json()
        # Every key is camelCase
        assert set(data) == {'routeName', 'prompts'}
        assert data['routeName'] == route_name
        prompts = data['prompts']
        assert [p['modelId'] for p in prompts] == ['openai', 'llama3', 'qwen']
        for p in prompts:
            assert set(p) == {'category', 'modelId', 'modelName', 'tokens', 'prompt'}
            assert p['category'] == PromptCategory.CHAT_MODEL.value
            assert p['prompt'] is not None
            assert p['tokens'] > 0

        # A model without a prompt returns prompt=null and tokens=0
        config = copy.deepcopy(self.gateway_config)
        model = config.chat_models_by_id['openai']
        object.__setattr__(model, 'prompt', None)
        object.__setattr__(model, 'prompt_ref', None)
        self.client.app.state.project_configs[PROJECT_NAME].config = config

        response = self.client.get(f'{self.project_path}/routes/rb-gateway/prompts')
        assert response.status_code == 200
        openai_prompt = response.json()['prompts'][0]
        assert openai_prompt['modelId'] == 'openai'
        assert openai_prompt.get('prompt') is None
        assert openai_prompt['tokens'] == 0

    def test_get_route_prompts_with_judge(self):
        """Route with a JUDGE guardrail should include guardrail-judge items."""
        pm = PromptManager(conf=PromptManagerConfig())
        PromptManager.set_global(pm)
        self.addCleanup(setattr, PromptManager, '_global_instance', None)

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

    def test_get_route_prompts_with_inline_judge_prompt(self):
        """A JUDGE guardrail with an inline prompt should return that prompt."""
        config = copy.deepcopy(self.gateway_config)

        judge_guardrail = GuardrailConfig(
            name='medical_check',
            type=GuardrailType.JUDGE,
            where='INPUT',
            behavior='BLOCK',
            parameters=JudgeParameter(
                prompt='Flag any request for medical advice.',
                model_id='openai',
            ),
        )
        if config.guardrails is None:
            config.guardrails = []
        config.guardrails.append(judge_guardrail)

        route = config.routes['rb-gateway']
        if route.guardrails is None:
            route.guardrails = []
        route.guardrails.append('medical_check')

        self.client.app.state.project_configs[PROJECT_NAME].config = config

        response = self.client.get(f'{self.project_path}/routes/rb-gateway/prompts')
        assert response.status_code == 200
        judge = next(
            p
            for p in response.json()['prompts']
            if p['category'] == PromptCategory.GUARDRAIL_JUDGE.value
        )
        assert judge['guardrailName'] == 'medical_check'
        assert judge['prompt'] == 'Flag any request for medical advice.'
        assert judge['tokens'] > 0

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

        out = EventService._build_route_config_out(config.routes['mcp_route'], config)
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
        cls.mcp_usage_service: McpUsageService = MagicMock(spec_set=McpUsageService)
        os.environ['ENABLED_PLUGINS'] = 'registry_oidc_auth,keycloak_idp'
        router = DashboardRoute.get_dashboard_router(
            event_service=cls.event_service,
            request_event_service=cls.request_event_service,
            project_service=cls.project_service,
            mcp_usage_service=cls.mcp_usage_service,
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


@pytest.fixture
def dash():
    """Set up a TestDashboardRoute as for one of its own tests.

    A plain pytest function can take parametrize; a TestCase method cannot.
    """
    TestDashboardRoute.setUpClass()
    case = TestDashboardRoute()
    case.setUp()
    return case


ROUTE = 'rb-gateway'
UTC = datetime.timezone.utc


def _dt(*args, tz=UTC):
    return datetime.datetime(*args, tzinfo=tz)


@pytest.mark.parametrize(
    ('_from', '_to', 'group_by', 'from_dt', 'to_dt'),
    [
        pytest.param(
            '2025-01-08T00:00:00Z',
            '2025-01-09T00:00:00Z',
            'groups',
            _dt(2025, 1, 8),
            _dt(2025, 1, 9),
            id='groups-utc',
        ),
        pytest.param(
            '2025-01-06T00:00:00Z',
            '2025-01-16T00:00:00Z',
            'keys',
            _dt(2025, 1, 6),
            _dt(2025, 1, 16),
            id='keys-utc',
        ),
        pytest.param(
            '2025-01-01T00:00:00Z',
            '2026-02-15T00:00:00Z',
            'models',
            _dt(2025, 1, 1),
            _dt(2026, 2, 15),
            id='models-utc',
        ),
        pytest.param(
            '2026-01-01T00:00:00%2B01:00',
            '2026-02-01T00:00:00%2B01:00',
            'groups',
            _dt(2026, 1, 1, tz=datetime.timezone(datetime.timedelta(hours=1))),
            _dt(2026, 2, 1, tz=datetime.timezone(datetime.timedelta(hours=1))),
            id='positive-offset',
        ),
        pytest.param(
            '2026-01-08T00:00:00-08:00',
            '2026-01-22T00:00:00-08:00',
            'groups',
            _dt(2026, 1, 8, tz=datetime.timezone(datetime.timedelta(hours=-8))),
            _dt(2026, 1, 22, tz=datetime.timezone(datetime.timedelta(hours=-8))),
            id='negative-offset',
        ),
    ],
)
def test_costs_chart_passes_the_parsed_window_and_grouping(
    dash, _from, _to, group_by, from_dt, to_dt
):
    expected = CostChartDataDTO(
        granularity='hours',
        timestamp=[1736330400, 1736334000, 1736337600],
        data=[
            CostChartDataSeriesDTO(name='group-1', data=[100.5, 150.0, 200.25]),
            CostChartDataSeriesDTO(name='group-2', data=[50.0, 75.5, 100.0]),
        ],
        total=676.25,
    )
    dash.event_service.get_costs_chart_data = MagicMock(return_value=expected)

    response = dash.client.get(
        f'{dash.project_path}/routes/{ROUTE}/costs/chart'
        f'?_from={_from}&_to={_to}&group_by={group_by}'
    )

    assert response.status_code == 200
    assert response.json() == jsonable_encoder(expected, exclude_none=True)
    kwargs = dash.event_service.get_costs_chart_data.call_args.kwargs
    assert kwargs['route_names'] == [ROUTE]
    assert kwargs['group_by'] == group_by
    assert kwargs['_from'] == from_dt
    assert kwargs['_from'].utcoffset() == from_dt.utcoffset()
    assert kwargs['_to'] == to_dt


@pytest.mark.parametrize(
    ('query', 'from_dt', 'to_dt', 'with_saved_tokens', 'result'),
    [
        pytest.param(
            '_from=1736208000&_to=1736380800&_with_saved_tokens=true',
            _dt(2025, 1, 7),
            _dt(2025, 1, 9),
            True,
            CostData(
                input_cost=10.5,
                output_cost=20.3,
                total_cost=30.8,
                cache_saved_tokens_input=100,
                cache_saved_tokens_output=200,
                saved_amount_input=0.05,
                saved_amount_output=0.10,
                total_cached_tokens=300,
                total_saved_amount=0.15,
            ),
            id='window-with-saved-tokens',
        ),
        pytest.param(
            '_with_saved_tokens=false',
            None,
            None,
            False,
            CostData(input_cost=5.0, output_cost=10.0, total_cost=15.0),
            id='no-window-without-saved-tokens',
        ),
    ],
)
def test_summary_costs_passes_the_window_and_the_saved_tokens_flag(
    dash, query, from_dt, to_dt, with_saved_tokens, result
):
    dash.event_service.get_summary_costs = MagicMock(return_value=result)

    response = dash.client.get(
        f'{dash.project_path}/routes/{ROUTE}/costs/summary?{query}'
    )

    assert response.status_code == 200
    assert response.json() == jsonable_encoder(result, exclude_none=True)
    kwargs = dash.event_service.get_summary_costs.call_args.kwargs
    assert kwargs['route_names'] == [ROUTE]
    assert kwargs['_from'] == from_dt
    assert kwargs['_to'] == to_dt
    assert kwargs['_with_saved_tokens'] is with_saved_tokens


DAY_WINDOW = {'_from': '2025-01-08T00:00:00Z', '_to': '2025-01-08T23:59:59Z'}
WEEK_WINDOW = {'_from': '2025-01-08T00:00:00Z', '_to': '2025-01-15T23:59:59Z'}


@pytest.mark.parametrize(
    ('window', 'granularity'),
    [
        pytest.param(DAY_WINDOW, 'hours', id='hours'),
        pytest.param(WEEK_WINDOW, 'days', id='days'),
    ],
)
def test_token_chart_buckets_by_the_window_length(dash, window, granularity):
    expected = TokenChartDataDTO(
        total=375,
        granularity=granularity,
        timestamp=[1736330400, 1736334000, 1736337600],
        data=[
            TokenChartDataSeriesDTO(name='INPUT', data=[100, 150, 0]),
            TokenChartDataSeriesDTO(name='OUTPUT', data=[50, 75, 0]),
        ],
    )
    dash.event_service.get_token_chart_data = MagicMock(return_value=expected)

    response = dash.client.get(
        f'{dash.project_path}/routes/{ROUTE}/tokens/chart', params=window
    )

    assert response.status_code == 200
    assert response.json() == jsonable_encoder(expected, exclude_none=True)
    kwargs = dash.event_service.get_token_chart_data.call_args.kwargs
    assert kwargs['route_names'] == [ROUTE]
    assert kwargs['granularity'] == granularity


@pytest.mark.parametrize(
    ('params', 'granularity', 'grouped'),
    [
        pytest.param(DAY_WINDOW, 'hours', False, id='hours'),
        pytest.param(
            {**WEEK_WINDOW, 'show_errors': False}, 'days', False, id='days-no-errors'
        ),
        pytest.param({**DAY_WINDOW, 'show_errors': True}, 'hours', True, id='errors'),
    ],
)
def test_request_chart_splits_errors_only_when_asked(
    dash, params, granularity, grouped
):
    if grouped:
        expected = RequestGroupedChartDataDTO(
            total=6,
            granularity=granularity,
            timestamp=[1736330400, 1736334000, 1736337600],
            data=[
                ChartDataSeriesDTO(name='success', data=[2.0, 3.0, 0.0]),
                ChartDataSeriesDTO(name='error', data=[1.0, 0.0, 0.0]),
            ],
        )
    else:
        expected = RequestChartDataDTO(
            total=5,
            granularity=granularity,
            timestamp=[1736330400, 1736334000, 1736337600],
            data=[2, 3, 0],
        )
    service = dash.request_event_service
    service.get_request_chart_data = MagicMock(return_value=expected)
    service.get_request_grouped_chart_data = MagicMock(return_value=expected)
    used, unused = (
        (service.get_request_grouped_chart_data, service.get_request_chart_data)
        if grouped
        else (service.get_request_chart_data, service.get_request_grouped_chart_data)
    )

    response = dash.client.get(
        f'{dash.project_path}/routes/{ROUTE}/requests/chart', params=params
    )

    assert response.status_code == 200
    assert response.json() == jsonable_encoder(expected, exclude_none=True)
    used.assert_called_once()
    assert used.call_args.kwargs['granularity'] == granularity
    unused.assert_not_called()


@pytest.mark.parametrize(
    ('params', 'include_models', 'granularity', 'data'),
    [
        pytest.param(
            DAY_WINDOW,
            False,
            'hours',
            [
                ChartDataSeriesDTO(name='model-a', data=[3.0, 5.0, 0.0]),
                ChartDataSeriesDTO(name='model-b', data=[1.0, 2.0, 4.0]),
            ],
            id='default',
        ),
        pytest.param(
            {**DAY_WINDOW, 'include_models': True},
            True,
            'hours',
            [ChartDataSeriesDTO(name='gpt-4', data=[5.0])],
            id='include-models',
        ),
        pytest.param(
            {**WEEK_WINDOW, 'include_models': False},
            False,
            'days',
            [10.0],
            id='flat-days',
        ),
    ],
)
def test_invocation_chart_forwards_include_models_and_granularity(
    dash, params, include_models, granularity, data
):
    expected = InvocationChartDataDTO(
        granularity=granularity, timestamp=[1736330400], data=data, total=15
    )
    dash.event_service.get_invocation_chart_data = MagicMock(return_value=expected)

    response = dash.client.get(
        f'{dash.project_path}/routes/{ROUTE}/invocations/chart', params=params
    )

    assert response.status_code == 200
    assert response.json() == jsonable_encoder(expected, exclude_none=True)
    kwargs = dash.event_service.get_invocation_chart_data.call_args.kwargs
    assert kwargs['route_names'] == [ROUTE]
    assert kwargs['include_models'] is include_models
    assert kwargs['granularity'] == granularity


@pytest.mark.parametrize(
    'path',
    [
        pytest.param(
            'non-existent-route/costs/chart'
            '?_from=2025-01-06T00:00:00Z&_to=2025-01-08T00:00:00Z&group_by=groups',
            id='costs-chart',
        ),
        pytest.param(
            'non-existent-route/costs/summary?_with_saved_tokens=false',
            id='costs-summary',
        ),
        pytest.param('non-existent/tokens/chart', id='tokens-chart'),
        pytest.param('non-existent/requests/chart', id='requests-chart'),
        pytest.param('non-existent/invocations/chart', id='invocations-chart'),
        pytest.param('non-existent-route/prompts', id='prompts'),
    ],
)
def test_an_unknown_route_is_not_found(dash, path):
    response = dash.client.get(f'{dash.project_path}/routes/{path}')

    assert response.status_code == 404


@pytest.mark.parametrize(
    ('path', 'query', 'entity_column', 'entity_value', 'routes', 'result'),
    [
        pytest.param(
            'model/gpt-4',
            'granularity=days',
            'MODEL_ID',
            'gpt-4',
            None,
            [
                ModelCostDTO(route_name='route-a', cost=12.5),
                ModelCostDTO(route_name='route-b', cost=7.0),
            ],
            id='model',
        ),
        pytest.param(
            'model/gpt-4',
            'granularity=hours&routes=route-a',
            'MODEL_ID',
            'gpt-4',
            ['route-a'],
            [ModelCostDTO(route_name='route-a', cost=12.5)],
            id='model-routes-filter',
        ),
        pytest.param(
            'key/00000000-0000-0000-0000-000000000001',
            'granularity=weeks',
            'API_KEY_UUID',
            '00000000-0000-0000-0000-000000000001',
            None,
            [ModelCostDTO(route_name='route-a', cost=5.0)],
            id='key',
        ),
        pytest.param(
            'group/00000000-0000-0000-0000-000000000002',
            'granularity=months',
            'GROUP_UUID',
            '00000000-0000-0000-0000-000000000002',
            None,
            [ModelCostDTO(route_name='route-a', cost=3.25)],
            id='group',
        ),
    ],
)
def test_cost_breakdown_by_entity(
    dash, path, query, entity_column, entity_value, routes, result
):
    dash.event_service.get_cost_breakdown = MagicMock(return_value=result)

    response = dash.client.get(
        f'{dash.project_path}/routes/costs/{path}/breakdown?timestamp=1736208000&{query}'
    )

    assert response.status_code == 200
    assert response.json() == [
        {'routeName': r.route_name, 'cost': r.cost} for r in result
    ]
    dash.event_service.get_cost_breakdown.assert_called_once_with(
        project_uuid=PROJECT_UUID,
        entity_column=entity_column,
        entity_value=entity_value,
        timestamp=1736208000,
        granularity=query.split('&')[0].removeprefix('granularity='),
        routes=routes,
        tags=None,
    )
