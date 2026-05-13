"""Tests for Anthropic prompt cache token extraction in ChatModelInvoker."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, AIMessageChunk
import pytest

from tests.common.db_mock import API_KEY_UUID, GROUP_UUID, REQUEST_UUID

from radicalbit_ai_gateway.invocation.chat_model_invoker import ChatModelInvoker
from radicalbit_ai_gateway.models.credentials import Credentials
from radicalbit_ai_gateway.models.event_payload import InputTokenProcessedPayload
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.services.cost_service import CostService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_COMMON_INVOKE_KWARGS = {
    'request_uuid': str(REQUEST_UUID),
    'api_key_uuid': str(API_KEY_UUID),
    'group_uuid': str(GROUP_UUID),
    'api_key_name': 'rb-key',
    'group_name': 'test-group',
    'route_name': 'test-route',
    'messages': [],
    'model_id': 'claude-sonnet',
    'tools': None,
    'tool_choice': None,
}


def _make_model() -> Model:
    return Model(
        model_id='claude-sonnet',
        model='anthropic/claude-3-5-sonnet-latest',
        credentials=Credentials(api_key='sk-ant-test'),
        input_cost_per_million_tokens=Decimal('3'),
        output_cost_per_million_tokens=Decimal('15'),
        input_cached_cost_per_million_tokens=Decimal('0.3'),
        input_cache_creation_5m_cost_per_million_tokens=Decimal('3.75'),
        input_cache_creation_1h_cost_per_million_tokens=Decimal('6'),
    )


def _make_invoker(mock_chat_model) -> tuple[ChatModelInvoker, MagicMock]:
    cost_service = MagicMock(spec_set=CostService)
    cost_service.compute_cost.return_value = Decimal('0.001')

    with patch(
        'radicalbit_ai_gateway.invocation.chat_model_invoker.init_chat_model',
        return_value=mock_chat_model,
    ):
        invoker = ChatModelInvoker(
            models=[_make_model()],
            cost_service=cost_service,
            fallbacks=None,
        )
    return invoker, cost_service


# ---------------------------------------------------------------------------
# Non-streaming tests
# ---------------------------------------------------------------------------


class TestAnthropicCacheTokensNonStreaming:
    """Verify cache_creation and cache_read token extraction in complete()."""

    @patch('radicalbit_ai_gateway.invocation.model_invoker.emit_event', autospec=True)
    @pytest.mark.asyncio
    async def test_both_cache_types_extracted(self, mock_emit):
        """cache_creation + cache_read tokens are extracted and input tokens reduced."""
        response = AIMessage(
            content='Hello',
            usage_metadata={
                'input_tokens': 1000,
                'output_tokens': 50,
                'total_tokens': 1050,
                'input_token_details': {
                    'cache_read': 200,
                    'cache_creation': 300,
                },
            },
        )
        mock_chat = MagicMock()
        mock_chat.ainvoke = AsyncMock(return_value=response)

        invoker, cost_service = _make_invoker(mock_chat)
        await invoker.complete(**_COMMON_INVOKE_KWARGS)

        compute_calls = cost_service.compute_cost.call_args_list
        where_args = {c.kwargs['where'] for c in compute_calls}
        assert 'input' in where_args
        assert 'cached' in where_args
        assert 'cached_creation' in where_args
        assert 'output' in where_args

        input_call = next(c for c in compute_calls if c.kwargs['where'] == 'input')
        assert input_call.kwargs['token_processed'] == 500  # 1000 - 200 - 300

        cached_call = next(c for c in compute_calls if c.kwargs['where'] == 'cached')
        assert cached_call.kwargs['token_processed'] == 200

        creation_call = next(
            c for c in compute_calls if c.kwargs['where'] == 'cached_creation'
        )
        assert creation_call.kwargs['token_processed'] == 300

    @patch('radicalbit_ai_gateway.invocation.model_invoker.emit_event', autospec=True)
    @pytest.mark.asyncio
    async def test_cache_read_only(self, mock_emit):
        """Only cache_read present (no creation) — no cached_creation event emitted."""
        response = AIMessage(
            content='Hello',
            usage_metadata={
                'input_tokens': 500,
                'output_tokens': 20,
                'total_tokens': 520,
                'input_token_details': {'cache_read': 100},
            },
        )
        mock_chat = MagicMock()
        mock_chat.ainvoke = AsyncMock(return_value=response)

        invoker, cost_service = _make_invoker(mock_chat)
        await invoker.complete(**_COMMON_INVOKE_KWARGS)

        compute_calls = cost_service.compute_cost.call_args_list
        where_args = {c.kwargs['where'] for c in compute_calls}
        assert 'cached_creation' not in where_args
        assert 'cached' in where_args

        input_call = next(c for c in compute_calls if c.kwargs['where'] == 'input')
        assert input_call.kwargs['token_processed'] == 400  # 500 - 100

    @patch('radicalbit_ai_gateway.invocation.model_invoker.emit_event', autospec=True)
    @pytest.mark.asyncio
    async def test_openai_legacy_format_still_works(self, mock_emit):
        """OpenAI legacy response_metadata format is handled as a fallback."""
        response = AIMessage(
            content='Hello',
            usage_metadata={
                'input_tokens': 300,
                'output_tokens': 10,
                'total_tokens': 310,
            },
            response_metadata={
                'token_usage': {
                    'prompt_tokens_details': {'cached_tokens': 50},
                }
            },
        )
        mock_chat = MagicMock()
        mock_chat.ainvoke = AsyncMock(return_value=response)

        invoker, cost_service = _make_invoker(mock_chat)
        await invoker.complete(**_COMMON_INVOKE_KWARGS)

        compute_calls = cost_service.compute_cost.call_args_list
        where_args = {c.kwargs['where'] for c in compute_calls}
        assert 'cached' in where_args
        assert 'cached_creation' not in where_args

        input_call = next(c for c in compute_calls if c.kwargs['where'] == 'input')
        assert input_call.kwargs['token_processed'] == 250  # 300 - 50

    @patch('radicalbit_ai_gateway.invocation.model_invoker.emit_event', autospec=True)
    @pytest.mark.asyncio
    async def test_1h_and_5m_cache_creation_extracted_separately(self, mock_emit):
        """ephemeral_5m and ephemeral_1h tokens are split into separate cost buckets."""
        response = AIMessage(
            content='Hello',
            usage_metadata={
                'input_tokens': 1200,
                'output_tokens': 40,
                'total_tokens': 1240,
                'input_token_details': {
                    'cache_read': 100,
                    'ephemeral_5m_input_tokens': 300,
                    'ephemeral_1h_input_tokens': 200,
                },
            },
        )
        mock_chat = MagicMock()
        mock_chat.ainvoke = AsyncMock(return_value=response)

        invoker, cost_service = _make_invoker(mock_chat)
        await invoker.complete(**_COMMON_INVOKE_KWARGS)

        compute_calls = cost_service.compute_cost.call_args_list
        where_args = {c.kwargs['where'] for c in compute_calls}
        assert 'input' in where_args
        assert 'cached' in where_args
        assert 'cached_creation' in where_args
        assert 'cached_creation_1h' in where_args

        input_call = next(c for c in compute_calls if c.kwargs['where'] == 'input')
        assert input_call.kwargs['token_processed'] == 600  # 1200 - 100 - 300 - 200

        creation_5m_call = next(
            c for c in compute_calls if c.kwargs['where'] == 'cached_creation'
        )
        assert creation_5m_call.kwargs['token_processed'] == 300

        creation_1h_call = next(
            c for c in compute_calls if c.kwargs['where'] == 'cached_creation_1h'
        )
        assert creation_1h_call.kwargs['token_processed'] == 200

    @patch('radicalbit_ai_gateway.invocation.model_invoker.emit_event', autospec=True)
    @pytest.mark.asyncio
    async def test_cache_type_set_correctly_on_events(self, mock_emit):
        """InputTokenProcessedPayload carries cache_type='read' or 'creation'."""
        response = AIMessage(
            content='Hi',
            usage_metadata={
                'input_tokens': 800,
                'output_tokens': 30,
                'total_tokens': 830,
                'input_token_details': {
                    'cache_read': 100,
                    'cache_creation': 200,
                },
            },
        )
        mock_chat = MagicMock()
        mock_chat.ainvoke = AsyncMock(return_value=response)

        invoker, _ = _make_invoker(mock_chat)
        await invoker.complete(**_COMMON_INVOKE_KWARGS)

        emitted_payloads = [c.args[0] for c in mock_emit.call_args_list]
        input_payloads = [
            p for p in emitted_payloads if isinstance(p, InputTokenProcessedPayload)
        ]

        cache_types = {p.cache_type for p in input_payloads if p.is_cached_tokens}
        assert 'read' in cache_types
        assert 'creation' in cache_types


# ---------------------------------------------------------------------------
# Streaming tests
# ---------------------------------------------------------------------------


def _make_usage_chunk(
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read: int = 0,
    cache_creation: int = 0,
    ephemeral_5m: int = 0,
    ephemeral_1h: int = 0,
) -> AIMessageChunk:
    input_token_details = {}
    if cache_read:
        input_token_details['cache_read'] = cache_read
    if cache_creation:
        input_token_details['cache_creation'] = cache_creation
    if ephemeral_5m:
        input_token_details['ephemeral_5m_input_tokens'] = ephemeral_5m
    if ephemeral_1h:
        input_token_details['ephemeral_1h_input_tokens'] = ephemeral_1h

    metadata: dict = {
        'input_tokens': input_tokens,
        'output_tokens': output_tokens,
        'total_tokens': input_tokens + output_tokens,
    }
    if input_token_details:
        metadata['input_token_details'] = input_token_details

    return AIMessageChunk(content='', usage_metadata=metadata)


class TestAnthropicCacheTokensStreaming:
    """Verify cache_creation and cache_read extraction in the streaming path."""

    @patch('radicalbit_ai_gateway.invocation.model_invoker.emit_event', autospec=True)
    @pytest.mark.asyncio
    async def test_streaming_both_cache_types(self, mock_emit):
        """Streaming with cache_creation + cache_read tokens are correctly tracked."""
        chunks = [
            AIMessageChunk(content='Hello '),
            AIMessageChunk(content='world'),
            _make_usage_chunk(
                input_tokens=1000,
                output_tokens=50,
                cache_read=200,
                cache_creation=300,
            ),
        ]

        async def fake_astream(*args, **kwargs):
            for c in chunks:
                yield c

        mock_chat = MagicMock()
        mock_chat.astream = fake_astream

        invoker, cost_service = _make_invoker(mock_chat)

        async for _ in invoker.stream(**_COMMON_INVOKE_KWARGS):
            pass

        compute_calls = cost_service.compute_cost.call_args_list
        where_args = {c.kwargs['where'] for c in compute_calls}
        assert 'input' in where_args
        assert 'cached' in where_args
        assert 'cached_creation' in where_args
        assert 'output' in where_args

        input_call = next(c for c in compute_calls if c.kwargs['where'] == 'input')
        assert input_call.kwargs['token_processed'] == 500  # 1000 - 200 - 300

        cached_call = next(c for c in compute_calls if c.kwargs['where'] == 'cached')
        assert cached_call.kwargs['token_processed'] == 200

        creation_call = next(
            c for c in compute_calls if c.kwargs['where'] == 'cached_creation'
        )
        assert creation_call.kwargs['token_processed'] == 300

    @patch('radicalbit_ai_gateway.invocation.model_invoker.emit_event', autospec=True)
    @pytest.mark.asyncio
    async def test_streaming_1h_and_5m_cache_creation(self, mock_emit):
        """Streaming with ephemeral_5m and ephemeral_1h tokens tracked separately."""
        chunks = [
            AIMessageChunk(content='Hello '),
            AIMessageChunk(content='world'),
            _make_usage_chunk(
                input_tokens=1200,
                output_tokens=40,
                cache_read=100,
                ephemeral_5m=300,
                ephemeral_1h=200,
            ),
        ]

        async def fake_astream(*args, **kwargs):
            for c in chunks:
                yield c

        mock_chat = MagicMock()
        mock_chat.astream = fake_astream

        invoker, cost_service = _make_invoker(mock_chat)

        async for _ in invoker.stream(**_COMMON_INVOKE_KWARGS):
            pass

        compute_calls = cost_service.compute_cost.call_args_list
        where_args = {c.kwargs['where'] for c in compute_calls}
        assert 'input' in where_args
        assert 'cached' in where_args
        assert 'cached_creation' in where_args
        assert 'cached_creation_1h' in where_args

        input_call = next(c for c in compute_calls if c.kwargs['where'] == 'input')
        assert input_call.kwargs['token_processed'] == 600  # 1200 - 100 - 300 - 200

        creation_5m_call = next(
            c for c in compute_calls if c.kwargs['where'] == 'cached_creation'
        )
        assert creation_5m_call.kwargs['token_processed'] == 300

        creation_1h_call = next(
            c for c in compute_calls if c.kwargs['where'] == 'cached_creation_1h'
        )
        assert creation_1h_call.kwargs['token_processed'] == 200

    @patch('radicalbit_ai_gateway.invocation.model_invoker.emit_event', autospec=True)
    @pytest.mark.asyncio
    async def test_streaming_legacy_openai_format(self, mock_emit):
        """Legacy OpenAI response_metadata format is handled as fallback in streaming."""
        usage_chunk = AIMessageChunk(
            content='',
            usage_metadata={
                'input_tokens': 400,
                'output_tokens': 20,
                'total_tokens': 420,
            },
            response_metadata={
                'token_usage': {
                    'prompt_tokens_details': {'cached_tokens': 80},
                }
            },
        )

        async def fake_astream(*args, **kwargs):
            yield AIMessageChunk(content='Hi')
            yield usage_chunk

        mock_chat = MagicMock()
        mock_chat.astream = fake_astream

        invoker, cost_service = _make_invoker(mock_chat)

        async for _ in invoker.stream(**_COMMON_INVOKE_KWARGS):
            pass

        compute_calls = cost_service.compute_cost.call_args_list
        where_args = {c.kwargs['where'] for c in compute_calls}
        assert 'cached' in where_args
        assert 'cached_creation' not in where_args

        input_call = next(c for c in compute_calls if c.kwargs['where'] == 'input')
        assert input_call.kwargs['token_processed'] == 320  # 400 - 80
