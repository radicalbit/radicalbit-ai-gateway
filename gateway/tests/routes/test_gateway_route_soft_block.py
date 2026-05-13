import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from openai.types.chat.chat_completion import ChatCompletion, Choice
from openai.types.chat.chat_completion_message import ChatCompletionMessage
from openai.types.completion_usage import CompletionUsage

from tests.common.db_mock import PLAIN_KEY, get_sample_key_with_group
from tests.common.resolve_route_models import resolve_route_models

from radicalbit_ai_gateway.ai_gateway import GatewayRoute
from radicalbit_ai_gateway.guardrails.guardrail_engine import GuardrailEngine
from radicalbit_ai_gateway.guardrails.judges.judge_engine import JudgeEngine
from radicalbit_ai_gateway.guardrails.presidio import PresidioEngine
from radicalbit_ai_gateway.models.credentials import Credentials
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.models.guardrails import (
    CheckParameter,
    Guardrail,
    GuardrailBehaviorType,
    GuardrailType,
    GuardrailWhereType,
)
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.server import app, group_service, key_service
from radicalbit_ai_gateway.services.cost_service import CostService


class TestGatewayRouteSoftBlockHTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.route_name = 'test-route'
        cls.cost_service: CostService = MagicMock(spec_set=CostService)
        cls.prompt_manager: PromptManager = MagicMock(spec_set=PromptManager)
        cls.input_soft_block_guardrail = Guardrail(
            name='soft_block_input_hello',
            type=GuardrailType.STARTS_WITH,
            behavior=GuardrailBehaviorType.SOFT_BLOCK,
            where=GuardrailWhereType.INPUT,
            parameters=CheckParameter(values=['Hello']),
            response_message='Custom message for input soft block',
        )
        cls.output_soft_block_guardrail = Guardrail(
            name='soft_block_output_sensitive',
            type=GuardrailType.CONTAINS,
            behavior=GuardrailBehaviorType.SOFT_BLOCK,
            where=GuardrailWhereType.OUTPUT,
            parameters=CheckParameter(values=['sensitive']),
        )
        all_guardrails = [
            cls.input_soft_block_guardrail,
            cls.output_soft_block_guardrail,
        ]

        chat_registry = [
            Model(
                model_id='test-model',
                model='openai/gpt-3.5-turbo',
                credentials=Credentials(api_key='fake-api-key-for-testing'),
            )
        ]
        embedding_registry = []

        route_cfg = GatewayRouteConfig(
            route_name=cls.route_name,
            chat_models=['test-model'],
            embedding_models=None,
            guardrails=[g.name for g in all_guardrails],
        )

        gateway_config = GatewayConfig(
            chat_models=chat_registry,
            embedding_models=embedding_registry,
            routes={cls.route_name: route_cfg},
            guardrails=all_guardrails,
            cache=None,
        )

        resolved_route_cfg, chat_models, embedding_models = resolve_route_models(
            gateway_config, cls.route_name
        )

        # Setup guardrail engine and gateway route
        guardrail_engine = GuardrailEngine(
            presidio_engine=PresidioEngine(),
            judge_engine=JudgeEngine(prompt_manager=cls.prompt_manager),
            cost_service=cls.cost_service,
            guardrails=all_guardrails,
        )
        cls.gateway_route = GatewayRoute(
            gateway_route_config=resolved_route_cfg,
            chat_models=chat_models,
            embedding_models=embedding_models,
            guardrail_engine=guardrail_engine,
            gateway_cache=None,
            cost_service=cls.cost_service,
        )

        # Setup FastAPI test client
        app.state.routes = {cls.route_name: cls.gateway_route}
        app.state.limiter = MagicMock()
        cls.client = TestClient(app)
        cls.headers = {'Authorization': f'Bearer {PLAIN_KEY}'}

        # Mock authentication
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)
        api_key = get_sample_key_with_group()
        key_service.get_key_by_hashed_key = MagicMock(return_value=api_key)
        cls.celery_send_task_patcher = patch(
            'radicalbit_ai_gateway.events.buffer.celery_app.send_task',
            autospec=True,
        )
        cls.celery_send_task_patcher.start()

    @classmethod
    def tearDownClass(cls):
        cls.celery_send_task_patcher.stop()

    def test_input_soft_block_returns_error_response_without_model_invocation(self):
        """Test that input SOFT_BLOCK returns error response without calling model via HTTP."""
        request_data = {
            'model': self.route_name,
            'messages': [{'role': 'user', 'content': 'Hello, how are you?'}],
        }

        # Mock the invoker to ensure it's not called
        self.gateway_route.chat_invoker.complete = MagicMock()

        response = self.client.post(
            '/v1/chat/completions', json=request_data, headers=self.headers
        )

        # Ensure model was not called
        self.gateway_route.chat_invoker.complete.assert_not_called()

        # Check HTTP response
        assert response.status_code == 200
        response_data = response.json()

        # Check response format
        assert (
            response_data['choices'][0]['message']['content']
            == 'Custom message for input soft block'
        )
        assert response_data['model'] == self.route_name
        assert response_data['choices'][0]['finish_reason'] == 'stop'

        # No tokens used for input soft blocks
        assert response_data['usage']['prompt_tokens'] == 0
        assert response_data['usage']['completion_tokens'] == 0
        assert response_data['usage']['total_tokens'] == 0

    def test_output_soft_block_replaces_response_content_preserves_usage(self):
        """Test that output SOFT_BLOCK replaces model response content while preserving usage via HTTP."""
        request_data = {
            'model': self.route_name,
            'messages': [{'role': 'user', 'content': 'Tell me something'}],
        }

        # Mock model response with sensitive content
        mock_response = ChatCompletion(
            id='test-id',
            object='chat.completion',
            created=1234567890,
            model='test-model',
            choices=[
                Choice(
                    index=0,
                    message=ChatCompletionMessage(
                        role='assistant',
                        content='This response contains sensitive information',
                    ),
                    finish_reason='stop',
                )
            ],
            usage=CompletionUsage(
                prompt_tokens=100, completion_tokens=50, total_tokens=150
            ),
        )

        self.gateway_route.chat_invoker.complete = AsyncMock(return_value=mock_response)

        response = self.client.post(
            '/v1/chat/completions', json=request_data, headers=self.headers
        )

        # Check HTTP response
        assert response.status_code == 200
        response_data = response.json()

        # Check that response content was replaced
        assert (
            response_data['choices'][0]['message']['content']
            == 'This response has been blocked due to policy violation: soft_block_output_sensitive'
        )
        assert response_data['model'] == self.route_name

        # Usage should be preserved from original model response
        assert response_data['usage']['prompt_tokens'] == 100
        assert response_data['usage']['completion_tokens'] == 50
        assert response_data['usage']['total_tokens'] == 150

    def test_normal_flow_without_soft_block_interference(self):
        """Test that normal messages flow through without soft block interference via HTTP."""
        request_data = {
            'model': self.route_name,
            'messages': [{'role': 'user', 'content': 'What is the weather today?'}],
        }

        # Mock normal model response
        mock_response = ChatCompletion(
            id='test-id',
            object='chat.completion',
            created=1234567890,
            model='test-model',
            choices=[
                Choice(
                    index=0,
                    message=ChatCompletionMessage(
                        role='assistant', content='The weather is sunny today'
                    ),
                    finish_reason='stop',
                )
            ],
            usage=CompletionUsage(
                prompt_tokens=75, completion_tokens=25, total_tokens=100
            ),
        )

        self.gateway_route.chat_invoker.complete = AsyncMock(return_value=mock_response)

        response = self.client.post(
            '/v1/chat/completions', json=request_data, headers=self.headers
        )

        # Check HTTP response
        assert response.status_code == 200
        response_data = response.json()

        # Check that response content was not modified
        assert (
            response_data['choices'][0]['message']['content']
            == 'The weather is sunny today'
        )
        assert response_data['model'] == self.route_name

        # Usage should be preserved from original model response
        assert response_data['usage']['prompt_tokens'] == 75
        assert response_data['usage']['completion_tokens'] == 25
        assert response_data['usage']['total_tokens'] == 100

    def test_soft_block_responses_not_cached(self):
        """Test that soft block responses are not cached via HTTP."""
        request_data = {
            'model': self.route_name,
            'messages': [{'role': 'user', 'content': 'Hello, test caching'}],
        }

        # Mock cache to ensure it's not called for soft block
        mock_cache = MagicMock()
        mock_cache.get.return_value = None  # No cached response
        self.gateway_route.gateway_cache = mock_cache

        response = self.client.post(
            '/v1/chat/completions', json=request_data, headers=self.headers
        )

        # Check HTTP response
        assert response.status_code == 200
        response_data = response.json()

        # Verify soft block response
        assert (
            response_data['choices'][0]['message']['content']
            == 'Custom message for input soft block'
        )

        # No tokens used for input soft blocks
        assert response_data['usage']['prompt_tokens'] == 0
        assert response_data['usage']['completion_tokens'] == 0
        assert response_data['usage']['total_tokens'] == 0

        # Ensure cache.set was not called for soft block response
        mock_cache.set.assert_not_called()

    def test_soft_block_precedence_over_warn_guardrails(self):
        """Test that SOFT_BLOCK takes precedence over WARN in mixed scenarios via HTTP."""
        # Add a WARN guardrail that would also trigger
        warn_guardrail = Guardrail(
            name='warn_contains_hello',
            type=GuardrailType.CONTAINS,
            behavior=GuardrailBehaviorType.WARN,
            where=GuardrailWhereType.INPUT,
            parameters=CheckParameter(values=['Hello']),
        )

        all_guardrails = [
            self.input_soft_block_guardrail,
            self.output_soft_block_guardrail,
            warn_guardrail,
        ]

        chat_registry = [
            Model(
                model_id='test-model',
                model='openai/gpt-3.5-turbo',
                credentials=Credentials(api_key='fake-api-key-for-testing'),
            )
        ]
        route_cfg = GatewayRouteConfig(
            route_name=self.route_name,
            chat_models=['test-model'],
            embedding_models=None,
            guardrails=[g.name for g in all_guardrails],
        )
        gateway_config = GatewayConfig(
            chat_models=chat_registry,
            embedding_models=[],
            routes={self.route_name: route_cfg},
            guardrails=all_guardrails,
            cache=None,
        )
        resolved_route_cfg, chat_models, embedding_models = resolve_route_models(
            gateway_config, self.route_name
        )

        guardrail_engine = GuardrailEngine(
            presidio_engine=PresidioEngine(),
            judge_engine=JudgeEngine(prompt_manager=self.prompt_manager),
            cost_service=self.cost_service,
            guardrails=all_guardrails,
        )

        gateway_route = GatewayRoute(
            gateway_route_config=resolved_route_cfg,
            chat_models=chat_models,
            embedding_models=embedding_models,
            guardrail_engine=guardrail_engine,
            gateway_cache=None,
            cost_service=self.cost_service,
        )

        app.state.routes[self.route_name] = gateway_route

        request_data = {
            'model': self.route_name,
            'messages': [
                {'role': 'user', 'content': 'Hello, this should trigger both'}
            ],
        }

        self.gateway_route.chat_invoker.complete = AsyncMock()

        response = self.client.post(
            '/v1/chat/completions', json=request_data, headers=self.headers
        )

        # Should return soft block response (not call model)
        self.gateway_route.chat_invoker.complete.assert_not_called()

        # Check HTTP response
        assert response.status_code == 200
        response_data = response.json()

        assert (
            response_data['choices'][0]['message']['content']
            == 'Custom message for input soft block'
        )

        # No tokens used for input soft blocks
        assert response_data['usage']['prompt_tokens'] == 0
        assert response_data['usage']['completion_tokens'] == 0
        assert response_data['usage']['total_tokens'] == 0

    def test_soft_block_input_guardrail_only_for_specific_where_condition(self):
        """Test that INPUT SOFT_BLOCK guardrail only triggers for INPUT, not OUTPUT via HTTP."""
        # Create config with only INPUT guardrail
        input_guardrail = Guardrail(
            name='soft_block_input_hello',
            type=GuardrailType.STARTS_WITH,
            behavior=GuardrailBehaviorType.SOFT_BLOCK,
            where=GuardrailWhereType.INPUT,
            parameters=CheckParameter(values=['Hello']),
        )

        route_name = 'test-route-input-only'
        chat_registry = [
            Model(
                model_id='test-model',
                model='openai/gpt-3.5-turbo',
                credentials=Credentials(api_key='fake-api-key-for-testing'),
            )
        ]
        embedding_registry = []

        route_cfg = GatewayRouteConfig(
            route_name=route_name,
            chat_models=['test-model'],
            embedding_models=None,
            guardrails=[input_guardrail.name],
        )

        gateway_config = GatewayConfig(
            chat_models=chat_registry,
            embedding_models=embedding_registry,
            routes={route_name: route_cfg},
            guardrails=[input_guardrail],
            cache=None,
        )

        resolved_route_cfg, chat_models, embedding_models = resolve_route_models(
            gateway_config, route_name
        )

        gateway_route = GatewayRoute(
            gateway_route_config=resolved_route_cfg,
            chat_models=chat_models,
            embedding_models=embedding_models,
            guardrail_engine=GuardrailEngine(
                presidio_engine=PresidioEngine(),
                judge_engine=JudgeEngine(prompt_manager=self.prompt_manager),
                cost_service=self.cost_service,
                guardrails=[input_guardrail],
            ),
            gateway_cache=None,
            cost_service=self.cost_service,
        )

        # Update app state with new route
        app.state.routes[route_name] = gateway_route

        # Test with content that would trigger if it were an OUTPUT guardrail
        request_data = {
            'model': route_name,
            'messages': [{'role': 'user', 'content': 'Normal message'}],
        }

        # Mock model response with "Hello" content
        mock_response = ChatCompletion(
            id='test-id',
            object='chat.completion',
            created=1234567890,
            model='test-model',
            choices=[
                Choice(
                    index=0,
                    message=ChatCompletionMessage(
                        role='assistant',
                        content='Hello there!',  # This should NOT trigger INPUT guardrail
                    ),
                    finish_reason='stop',
                )
            ],
            usage=CompletionUsage(
                prompt_tokens=50, completion_tokens=25, total_tokens=75
            ),
        )

        gateway_route.chat_invoker.complete = AsyncMock(return_value=mock_response)

        response = self.client.post(
            '/v1/chat/completions', json=request_data, headers=self.headers
        )

        # Check HTTP response
        assert response.status_code == 200
        response_data = response.json()

        # Should NOT be soft blocked since it's an INPUT guardrail applied to OUTPUT
        assert response_data['choices'][0]['message']['content'] == 'Hello there!'
        assert response_data['usage']['prompt_tokens'] == 50
        assert response_data['usage']['completion_tokens'] == 25
        assert response_data['usage']['total_tokens'] == 75

    def test_soft_block_io_guardrail_applies_to_both_input_and_output(self):
        """Test that IO SOFT_BLOCK guardrail applies to both INPUT and OUTPUT via HTTP."""
        # Create config with IO guardrail
        io_guardrail = Guardrail(
            name='soft_block_io_contains_test',
            type=GuardrailType.CONTAINS,
            behavior=GuardrailBehaviorType.SOFT_BLOCK,
            where=GuardrailWhereType.IO,
            parameters=CheckParameter(values=['blocked']),
        )

        chat_registry = [
            Model(
                model_id='test-model',
                model='openai/gpt-3.5-turbo',
                credentials=Credentials(api_key='fake-api-key-for-testing'),
            )
        ]
        embedding_registry = []

        route_name = 'test-route-io'
        route_cfg = GatewayRouteConfig(
            route_name=route_name,
            chat_models=['test-model'],
            embedding_models=None,
            guardrails=[io_guardrail.name],
        )

        gateway_config = GatewayConfig(
            chat_models=chat_registry,
            embedding_models=embedding_registry,
            routes={route_name: route_cfg},
            guardrails=[io_guardrail],
            cache=None,
        )

        resolved_route_cfg, chat_models, embedding_models = resolve_route_models(
            gateway_config, route_name
        )

        gateway_route = GatewayRoute(
            gateway_route_config=resolved_route_cfg,
            chat_models=chat_models,
            embedding_models=embedding_models,
            guardrail_engine=GuardrailEngine(
                presidio_engine=PresidioEngine(),
                judge_engine=JudgeEngine(prompt_manager=self.prompt_manager),
                cost_service=self.cost_service,
                guardrails=[io_guardrail],
            ),
            gateway_cache=None,
            cost_service=self.cost_service,
        )

        # Update app state with new route
        app.state.routes[route_name] = gateway_route

        # Test INPUT blocking
        input_request_data = {
            'model': route_name,
            'messages': [
                {'role': 'user', 'content': 'This message contains blocked content'}
            ],
        }

        gateway_route.chat_invoker.complete = AsyncMock()

        input_response = self.client.post(
            '/v1/chat/completions', json=input_request_data, headers=self.headers
        )

        # Should be soft blocked at input level
        gateway_route.chat_invoker.complete.assert_not_called()

        # Check HTTP response
        assert input_response.status_code == 200
        input_response_data = input_response.json()

        assert (
            input_response_data['choices'][0]['message']['content']
            == 'I cannot process this request as it violates content policy: soft_block_io_contains_test'
        )
        assert input_response_data['usage']['total_tokens'] == 0

        # Test OUTPUT blocking
        output_request_data = {
            'model': 'test-route-io',
            'messages': [{'role': 'user', 'content': 'Normal input message'}],
        }

        mock_response = ChatCompletion(
            id='test-id',
            object='chat.completion',
            created=1234567890,
            model='test-model',
            choices=[
                Choice(
                    index=0,
                    message=ChatCompletionMessage(
                        role='assistant', content='This output is blocked content'
                    ),
                    finish_reason='stop',
                )
            ],
            usage=CompletionUsage(
                prompt_tokens=30, completion_tokens=15, total_tokens=45
            ),
        )

        gateway_route.chat_invoker.complete = AsyncMock(return_value=mock_response)

        output_response = self.client.post(
            '/v1/chat/completions', json=output_request_data, headers=self.headers
        )

        # Check HTTP response
        assert output_response.status_code == 200
        output_response_data = output_response.json()

        # Should be soft blocked at output level
        assert (
            output_response_data['choices'][0]['message']['content']
            == 'This response has been blocked due to policy violation: soft_block_io_contains_test'
        )
        # Usage should be preserved from original response
        assert output_response_data['usage']['prompt_tokens'] == 30
        assert output_response_data['usage']['completion_tokens'] == 15
        assert output_response_data['usage']['total_tokens'] == 45
