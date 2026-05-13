from unittest.mock import MagicMock, patch

from radicalbit_ai_gateway.invocation.chat_model_invoker import ChatModelInvoker
from radicalbit_ai_gateway.models.credentials import Credentials
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.services.cost_service import CostService


class TestModelInvokerApiKey:
    @patch('radicalbit_ai_gateway.invocation.chat_model_invoker.init_chat_model')
    def test_openai_without_base_url_with_api_key_works(self, mock_init_chat_model):
        mock_init_chat_model.return_value = MagicMock()
        model = Model(
            model_id='openai-test',
            model='openai/gpt-4o',
            credentials=Credentials(api_key='sk-real-key'),
        )
        cost_service: CostService = MagicMock(spec_set=CostService)
        invoker = ChatModelInvoker(
            models=[model], cost_service=cost_service, fallbacks=None
        )
        assert 'openai-test' in invoker.model_map
        mock_init_chat_model.assert_called_once()
        call_args = mock_init_chat_model.call_args
        assert call_args[1]['api_key'] == 'sk-real-key'

    @patch('radicalbit_ai_gateway.invocation.chat_model_invoker.init_chat_model')
    def test_openai_with_base_url_without_api_key_gets_dummy_key(
        self, mock_init_chat_model
    ):
        mock_init_chat_model.return_value = MagicMock()
        cost_service: CostService = MagicMock(spec_set=CostService)
        model = Model(
            model_id='openai-ollama',
            model='openai/llama3',
            credentials=Credentials(base_url='http://localhost:11434/v1'),
        )
        invoker = ChatModelInvoker(
            models=[model], cost_service=cost_service, fallbacks=None
        )
        assert 'openai-ollama' in invoker.model_map
        mock_init_chat_model.assert_called_once()
        call_args = mock_init_chat_model.call_args
        assert call_args[1]['api_key'] == 'dummy-api-key'
        assert call_args[1]['base_url'] == 'http://localhost:11434/v1'

    @patch('radicalbit_ai_gateway.invocation.chat_model_invoker.init_chat_model')
    def test_openai_with_base_url_with_api_key_preserves_api_key(
        self, mock_init_chat_model
    ):
        mock_init_chat_model.return_value = MagicMock()
        model = Model(
            model_id='openai-custom',
            model='openai/custom-model',
            credentials=Credentials(
                base_url='http://custom.endpoint/v1', api_key='custom-key'
            ),
        )
        cost_service: CostService = MagicMock(spec_set=CostService)
        invoker = ChatModelInvoker(
            models=[model], cost_service=cost_service, fallbacks=None
        )
        assert 'openai-custom' in invoker.model_map
        mock_init_chat_model.assert_called_once()
        call_args = mock_init_chat_model.call_args
        assert call_args[1]['api_key'] == 'custom-key'
        assert call_args[1]['base_url'] == 'http://custom.endpoint/v1'

    @patch('radicalbit_ai_gateway.invocation.chat_model_invoker.init_chat_model')
    def test_non_openai_provider_without_api_key_works(self, mock_init_chat_model):
        mock_init_chat_model.return_value = MagicMock()
        model = Model(
            model_id='anthropic-test',
            model='anthropic/claude-3',
            credentials=Credentials(),
        )
        cost_service: CostService = MagicMock(spec_set=CostService)
        invoker = ChatModelInvoker(
            models=[model], cost_service=cost_service, fallbacks=None
        )
        assert 'anthropic-test' in invoker.model_map
        mock_init_chat_model.assert_called_once()
        call_args = mock_init_chat_model.call_args
        assert 'api_key' not in call_args[1] or call_args[1].get('api_key') is None

    @patch('radicalbit_ai_gateway.invocation.chat_model_invoker.init_chat_model')
    def test_model_without_credentials_works_for_non_openai(self, mock_init_chat_model):
        mock_init_chat_model.return_value = MagicMock()
        model = Model(
            model_id='azure-test',
            model='azure/gpt-4',
            credentials=None,
        )
        cost_service: CostService = MagicMock(spec_set=CostService)
        invoker = ChatModelInvoker(
            models=[model], cost_service=cost_service, fallbacks=None
        )
        assert 'azure-test' in invoker.model_map
        mock_init_chat_model.assert_called_once()
