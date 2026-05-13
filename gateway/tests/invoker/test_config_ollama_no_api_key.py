from unittest.mock import MagicMock, patch

from tests.common.mocked_gateway_config_openai import get_gateway_ollama_no_api_key
from tests.common.resolve_route_models import resolve_route_models

from radicalbit_ai_gateway.invocation.chat_model_invoker import ChatModelInvoker
from radicalbit_ai_gateway.models.credentials import Credentials
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.services.cost_service import CostService


class TestConfigOllamaNoApiKey:
    @patch('radicalbit_ai_gateway.invocation.chat_model_invoker.init_chat_model')
    def test_config_ollama_no_api_key_works(self, mock_init_chat_model):
        mock_init_chat_model.return_value = MagicMock()
        gateway_config = get_gateway_ollama_no_api_key()
        route_config = gateway_config.routes['rb-gateway']
        _, chat_models, _ = resolve_route_models(gateway_config, 'rb-gateway')
        fallbacks = route_config.fallback
        cost_service: CostService = MagicMock(spec_set=CostService)
        invoker = ChatModelInvoker(
            models=chat_models, fallbacks=fallbacks, cost_service=cost_service
        )
        assert 'qwen' in invoker.model_map
        mock_init_chat_model.assert_called_once()
        call_args = mock_init_chat_model.call_args
        assert call_args[1]['api_key'] == 'dummy-api-key'
        assert call_args[1]['base_url'] == 'http://host.docker.internal:11434/v1'
        assert call_args[1]['temperature'] == 0.7
        assert call_args[1]['top_p'] == 0.9

    @patch('radicalbit_ai_gateway.invocation.chat_model_invoker.init_chat_model')
    def test_config_with_real_openai_with_api_key_works(self, mock_init_chat_model):
        mock_init_chat_model.return_value = MagicMock()
        cost_service: CostService = MagicMock(spec_set=CostService)
        model = Model(
            model_id='qwen',
            model='openai/qwen2.5:3b',
            credentials=Credentials(api_key='sk-real-key'),
            params={'temperature': 0.7, 'top_p': 0.9},
        )
        invoker = ChatModelInvoker(
            models=[model], fallbacks=None, cost_service=cost_service
        )
        assert 'qwen' in invoker.model_map
        mock_init_chat_model.assert_called_once()
        call_args = mock_init_chat_model.call_args
        assert call_args[1]['api_key'] == 'sk-real-key'
        assert 'base_url' not in call_args[1] or call_args[1]['base_url'] is None
