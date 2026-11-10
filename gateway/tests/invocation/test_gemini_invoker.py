"""Tests for Gemini support in ChatModelInvoker and EmbeddingModelInvoker."""

from unittest.mock import MagicMock, patch

import pytest

from radicalbit_ai_gateway.invocation.chat_model_invoker import ChatModelInvoker
from radicalbit_ai_gateway.invocation.embedding_model_invoker import (
    EmbeddingModelInvoker,
)
from radicalbit_ai_gateway.llm.factory import build_chat_model
from radicalbit_ai_gateway.models.credentials import Credentials
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.services.cost_service import CostService


class TestGeminiChatModelInvoker:
    """Tests for ChatModelInvoker with Gemini provider."""

    @patch('radicalbit_ai_gateway.llm.factory.init_chat_model')
    def test_gemini_chat_model_with_api_key(self, mock_init_chat_model):
        """Test that a Gemini model is correctly initialized with api_key via init_chat_model."""
        mock_init_chat_model.return_value = MagicMock()
        cost_service: CostService = MagicMock(spec_set=CostService)
        model = Model(
            model_id='gemini-test',
            model='google-genai/gemini-1.5-pro',
            credentials=Credentials(api_key='test-api-key'),
        )
        invoker = ChatModelInvoker(
            models=[model], cost_service=cost_service, fallbacks=None
        )
        assert 'gemini-test' in invoker.model_map
        mock_init_chat_model.assert_called_once()
        call_kwargs = mock_init_chat_model.call_args[1]
        # Verify that init_chat_model is called with google_genai provider (underscore)
        assert call_kwargs['model'] == 'google_genai:gemini-1.5-pro'
        # Verify that api_key is passed directly (LangChain accepts it as alias for google_api_key)
        assert call_kwargs['api_key'] == 'test-api-key'

    @patch('radicalbit_ai_gateway.llm.factory.init_chat_model')
    def test_gemini_chat_model_uses_init_chat_model(self, mock_init_chat_model):
        """Test that init_chat_model is called for Gemini models."""
        mock_init_chat_model.return_value = MagicMock()
        cost_service: CostService = MagicMock(spec_set=CostService)
        model = Model(
            model_id='gemini-test',
            model='google-genai/gemini-1.5-pro',
            credentials=Credentials(api_key='test-api-key'),
        )
        invoker = ChatModelInvoker(
            models=[model], cost_service=cost_service, fallbacks=None
        )
        assert 'gemini-test' in invoker.model_map
        mock_init_chat_model.assert_called_once()

    def test_gemini_chat_model_without_api_key_raises_error(self):
        """Test that a Gemini model without api_key raises an error."""

        model = Model(
            model_id='gemini-test',
            model='google-genai/gemini-1.5-pro',
            credentials=Credentials(),
        )
        cost_service: CostService = MagicMock(spec_set=CostService)
        with pytest.raises(ValueError, match='API key required'):
            ChatModelInvoker([model], cost_service, None)

    @patch('radicalbit_ai_gateway.llm.factory.init_chat_model')
    def test_gemini_chat_model_with_params(self, mock_init_chat_model):
        """Test that parameters are correctly passed to the Gemini model via init_chat_model."""
        mock_init_chat_model.return_value = MagicMock()
        cost_service: CostService = MagicMock(spec_set=CostService)
        model = Model(
            model_id='gemini-test',
            model='google-genai/gemini-1.5-pro',
            credentials=Credentials(api_key='test-api-key'),
            params={'temperature': 0.7, 'max_output_tokens': 1024},
        )
        invoker = ChatModelInvoker(
            models=[model], cost_service=cost_service, fallbacks=None
        )
        assert 'gemini-test' in invoker.model_map
        call_kwargs = mock_init_chat_model.call_args[1]
        assert call_kwargs['model'] == 'google_genai:gemini-1.5-pro'
        assert call_kwargs['temperature'] == 0.7
        assert call_kwargs['max_output_tokens'] == 1024
        assert call_kwargs['api_key'] == 'test-api-key'


class TestRuntimeParamAdaptation:
    """Each chat model takes the OpenAI-style kwargs as its provider names them."""

    def _model(self, provider_model: str):
        return build_chat_model(
            Model(
                model_id='test',
                model=provider_model,
                credentials=Credentials(api_key='test-key'),
            )
        )

    def test_adapt_google_genai(self):
        result = self._model('google-genai/gemini-1.5-pro')._adapt_kwargs(
            {'max_completion_tokens': 512, 'temperature': 0.5}
        )
        assert result == {'temperature': 0.5, 'max_output_tokens': 512}

    def test_adapt_anthropic(self):
        result = self._model('anthropic/claude-3-5-haiku')._adapt_kwargs(
            {'max_completion_tokens': 1024, 'stream_options': {'include_usage': True}}
        )
        assert result == {'max_tokens': 1024}

    @pytest.mark.parametrize(
        'provider_model',
        ['openai/gpt-4o', 'mistralai/mistral-small-latest', 'deepseek/deepseek-chat'],
    )
    def test_adapt_passthrough(self, provider_model):
        kwargs = {
            'max_completion_tokens': 256,
            'stream_options': {'include_usage': True},
        }
        assert self._model(provider_model)._adapt_kwargs(kwargs) == kwargs

    def test_adapt_no_max_completion_tokens(self):
        original = {'temperature': 0.7}
        result = self._model('google-genai/gemini-1.5-pro')._adapt_kwargs(original)
        assert result == original


class TestGeminiEmbeddingModelInvoker:
    """Tests for EmbeddingModelInvoker with Gemini provider."""

    @patch('radicalbit_ai_gateway.llm.factory.init_embeddings')
    def test_gemini_embedding_model_with_api_key(self, mock_init_embeddings):
        """Test that a Gemini embedding model is correctly initialized with api_key via init_embeddings."""
        mock_init_embeddings.return_value = MagicMock()
        cost_service: CostService = MagicMock(spec_set=CostService)
        model = Model(
            model_id='gemini-embed-test',
            model='google-genai/models/gemini-embedding-001',
            credentials=Credentials(api_key='test-api-key'),
        )
        invoker = EmbeddingModelInvoker(
            models=[model], cost_service=cost_service, fallbacks=None
        )
        assert 'gemini-embed-test' in invoker.model_map
        mock_init_embeddings.assert_called_once()
        call_kwargs = mock_init_embeddings.call_args[1]
        # Verify that init_embeddings is called with google_genai provider (underscore)
        assert call_kwargs['provider'] == 'google_genai'
        assert call_kwargs['model'] == 'models/gemini-embedding-001'
        # Verify that api_key is passed directly (LangChain accepts it as alias for google_api_key)
        assert call_kwargs['api_key'] == 'test-api-key'

    @patch('radicalbit_ai_gateway.llm.factory.init_embeddings')
    def test_gemini_embedding_model_with_task_type(self, mock_init_embeddings):
        """Test that task_type is correctly passed to the Gemini embedding model via init_embeddings."""
        mock_init_embeddings.return_value = MagicMock()
        cost_service: CostService = MagicMock(spec_set=CostService)
        model = Model(
            model_id='gemini-embed-test',
            model='google-genai/models/gemini-embedding-001',
            credentials=Credentials(api_key='test-api-key'),
            params={'task_type': 'RETRIEVAL_QUERY'},
        )
        invoker = EmbeddingModelInvoker(
            models=[model], cost_service=cost_service, fallbacks=None
        )
        assert 'gemini-embed-test' in invoker.model_map
        call_kwargs = mock_init_embeddings.call_args[1]
        assert call_kwargs['provider'] == 'google_genai'
        assert call_kwargs['task_type'] == 'RETRIEVAL_QUERY'
        assert call_kwargs['api_key'] == 'test-api-key'

    @patch('radicalbit_ai_gateway.llm.factory.init_embeddings')
    def test_gemini_embedding_model_uses_init_embeddings(self, mock_init_embeddings):
        """Test that init_embeddings is called for Gemini embedding models."""
        mock_init_embeddings.return_value = MagicMock()
        cost_service: CostService = MagicMock(spec_set=CostService)
        model = Model(
            model_id='gemini-embed-test',
            model='google-genai/models/gemini-embedding-001',
            credentials=Credentials(api_key='test-api-key'),
        )
        invoker = EmbeddingModelInvoker(
            models=[model], cost_service=cost_service, fallbacks=None
        )
        assert 'gemini-embed-test' in invoker.model_map
        mock_init_embeddings.assert_called_once()

    def test_gemini_embedding_model_without_api_key_raises_error(self):
        """Test that a Gemini embedding model without api_key raises an error."""
        model = Model(
            model_id='gemini-embed-test',
            model='google-genai/models/gemini-embedding-001',
            credentials=Credentials(),
        )
        cost_service: CostService = MagicMock(spec_set=CostService)
        with pytest.raises(ValueError, match='API key required'):
            EmbeddingModelInvoker([model], cost_service, None)
