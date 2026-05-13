"""Tests for Gemini support in ChatModelInvoker and EmbeddingModelInvoker."""

from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage
from pydantic import ValidationError
import pytest

from radicalbit_ai_gateway.invocation.chat_model_invoker import ChatModelInvoker
from radicalbit_ai_gateway.invocation.embedding_model_invoker import (
    EmbeddingModelInvoker,
)
from radicalbit_ai_gateway.models.credentials import Credentials
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.services.cost_service import CostService


class TestGeminiChatModelInvoker:
    """Tests for ChatModelInvoker with Gemini provider."""

    @patch('radicalbit_ai_gateway.invocation.chat_model_invoker.init_chat_model')
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

    @patch('radicalbit_ai_gateway.invocation.chat_model_invoker.init_chat_model')
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
        # ValueError from pydantic model if credentials are missing
        with pytest.raises(ValidationError):
            ChatModelInvoker([model], cost_service, None)

    @patch('radicalbit_ai_gateway.invocation.chat_model_invoker.init_chat_model')
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


class TestGeminiRuntimeParamNormalization:
    """Tests for _normalize_kwargs_for_model per-provider kwarg translation."""

    def _make_model(self, provider_model: str) -> Model:
        return Model(model_id='test', model=provider_model)

    def test_normalize_google_genai(self):
        model = self._make_model('google-genai/gemini-1.5-pro')
        result = ChatModelInvoker._normalize_kwargs_for_model(
            model, {'max_completion_tokens': 512, 'temperature': 0.5}
        )
        assert 'max_output_tokens' in result
        assert result['max_output_tokens'] == 512
        assert 'max_completion_tokens' not in result
        assert result['temperature'] == 0.5

    def test_normalize_anthropic(self):
        model = self._make_model('anthropic/claude-3-5-haiku')
        result = ChatModelInvoker._normalize_kwargs_for_model(
            model, {'max_completion_tokens': 1024}
        )
        assert 'max_tokens' in result
        assert result['max_tokens'] == 1024
        assert 'max_completion_tokens' not in result

    def test_normalize_openai_passthrough(self):
        model = self._make_model('openai/gpt-4o')
        result = ChatModelInvoker._normalize_kwargs_for_model(
            model, {'max_completion_tokens': 256}
        )
        assert result['max_completion_tokens'] == 256
        assert 'max_output_tokens' not in result
        assert 'max_tokens' not in result

    def test_normalize_no_max_completion_tokens(self):
        model = self._make_model('google-genai/gemini-1.5-pro')
        original = {'temperature': 0.7}
        result = ChatModelInvoker._normalize_kwargs_for_model(model, original)
        assert result == original

    @patch('radicalbit_ai_gateway.invocation.chat_model_invoker.init_chat_model')
    @pytest.mark.asyncio
    async def test_complete_passes_max_output_tokens_to_gemini(
        self, mock_init_chat_model
    ):
        """ainvoke() must receive max_output_tokens, not max_completion_tokens, for Gemini."""
        mock_chat_model = MagicMock()

        mock_chat_model.ainvoke = AsyncMock(
            return_value=AIMessage(
                content='hello',
                usage_metadata={
                    'input_tokens': 10,
                    'output_tokens': 5,
                    'total_tokens': 15,
                },
            )
        )
        mock_init_chat_model.return_value = mock_chat_model

        cost_service = MagicMock(spec_set=CostService)
        model = Model(
            model_id='gemini-test',
            model='google-genai/gemini-1.5-pro',
            credentials=Credentials(api_key='test-key'),
        )
        invoker = ChatModelInvoker(
            models=[model], cost_service=cost_service, fallbacks=None
        )

        await invoker.complete(
            request_uuid='uuid',
            api_key_uuid='ak-uuid',
            group_uuid='g-uuid',
            api_key_name='key',
            group_name='group',
            route_name='route',
            messages=[],
            model_id='gemini-test',
            tools=None,
            tool_choice=None,
            max_completion_tokens=512,
        )

        call_kwargs = mock_chat_model.ainvoke.call_args[1]
        assert 'max_output_tokens' in call_kwargs
        assert call_kwargs['max_output_tokens'] == 512
        assert 'max_completion_tokens' not in call_kwargs


class TestGeminiEmbeddingModelInvoker:
    """Tests for EmbeddingModelInvoker with Gemini provider."""

    @patch('radicalbit_ai_gateway.invocation.embedding_model_invoker.init_embeddings')
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

    @patch('radicalbit_ai_gateway.invocation.embedding_model_invoker.init_embeddings')
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

    @patch('radicalbit_ai_gateway.invocation.embedding_model_invoker.init_embeddings')
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
        # init_embeddings doesn't support google_genai provider, raises ValueError
        with pytest.raises(ValueError) as exc_info:
            EmbeddingModelInvoker([model], cost_service, None)
        assert 'value error' in str(exc_info.value).lower()
