import json
import unittest
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk, HumanMessage
import pytest
from starlette.requests import Request

from tests.common import db_mock

from radicalbit_ai_gateway.ai_gateway import GatewayRoute
from radicalbit_ai_gateway.models.guardrails import GuardrailWhereType
from radicalbit_ai_gateway.server import (
    app,
    group_service,
    key_service,
    set_request_uuid,
)
from radicalbit_ai_gateway.utils.ai_gateway_types import PrepareAndValidateResult
from radicalbit_ai_gateway.utils.exceptions import GuardrailBadRequest

GROUP_NAME = 'group'


def mock_request_uuid(request: Request):
    request.state.request_uuid = str(db_mock.REQUEST_UUID)
    return str(db_mock.REQUEST_UUID)


class TestStreamingGuardrails(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.mock_gateway = MagicMock(spec=GatewayRoute)
        mock_rate_limiter = MagicMock()
        mock_rate_limiter.check_and_count_request = AsyncMock()
        cls.mock_gateway.request_rate_limiter = mock_rate_limiter
        cls.mock_gateway.project_uuid = ''
        cls.mock_gateway.project_name = ''

        # Enable output guardrails in config
        mock_config = MagicMock()
        mock_config.guardrails.output = True
        mock_config.route_name = 'rb-gateway'
        cls.mock_gateway.gateway_route_config = mock_config

        app.state.routes = {'rb-gateway': cls.mock_gateway}
        app.dependency_overrides[set_request_uuid] = mock_request_uuid
        cls.client = TestClient(app)
        cls.headers = {'Authorization': f'Bearer {db_mock.PLAIN_KEY}'}

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides = {}

    @staticmethod
    def _setup_mock_key_and_group():
        api_key = db_mock.get_sample_key_with_group(group_uuid=db_mock.GROUP_UUID)
        key_service.get_key_by_hashed_key = MagicMock(return_value=api_key)
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)
        return api_key

    @staticmethod
    def _create_prepared_result(
        model_id: str = 'gpt-4',
        messages: list = None,
        input_soft_block=None,
        cached_response=None,
        guardrails_input_triggered: bool = False,
        guardrails_block_triggered: bool = False,
    ) -> PrepareAndValidateResult:
        mock_model = MagicMock()
        mock_model.model_id = model_id
        mock_model.input_cost_per_token = None
        mock_model.output_cost_per_token = None

        return PrepareAndValidateResult(
            model_selected=mock_model,
            redacted_messages=messages or [HumanMessage(content='Test message')],
            cache_key='',
            embeddings=None,
            cached_response=cached_response,
            input_soft_block=input_soft_block,
            guardrails_input_triggered=guardrails_input_triggered,
            guardrails_block_triggered=guardrails_block_triggered,
        )

    # =========================================================================
    # Tests for prepare_stream (Input Guardrail Validation)
    # =========================================================================

    async def test_prepare_stream_raises_guardrail_bad_request_on_block(self):
        api_key = self._setup_mock_key_and_group()

        # Mock _prepare_and_validate_request to raise GuardrailBadRequest
        mock_guardrail = MagicMock()
        mock_guardrail.name = 'input_blocker'
        mock_guardrail.type = MagicMock()
        mock_guardrail.type.name = 'JUDGE'
        mock_guardrail.where = GuardrailWhereType.INPUT

        mock_exception = GuardrailBadRequest(
            message='Input blocked by guardrail',
            guardrail=mock_guardrail,
            reason={'kind': 'judge', 'context': 'forbidden content'},
        )

        self.mock_gateway._prepare_and_validate_request = AsyncMock(
            side_effect=mock_exception
        )

        # Bind the real prepare_stream method
        self.mock_gateway.prepare_stream = GatewayRoute.prepare_stream.__get__(
            self.mock_gateway, GatewayRoute
        )

        # Verify exception is raised
        with pytest.raises(GuardrailBadRequest) as context:
            await self.mock_gateway.prepare_stream(
                request_uuid=str(db_mock.REQUEST_UUID),
                api_key_uuid=str(api_key.uuid),
                group_uuid=str(db_mock.GROUP_UUID),
                api_key_name=api_key.name,
                group_name=GROUP_NAME,
                messages=[HumanMessage(content='Forbidden input')],
                route_name='rb-gateway',
                tools=None,
                tool_choice=None,
                hashed_api_key=db_mock.HASHED_KEY,
            )

        assert context.value.client_message == 'Input blocked by guardrail'

    async def test_prepare_stream_returns_prepared_result_on_success(self):
        api_key = self._setup_mock_key_and_group()

        expected_result = self._create_prepared_result(
            messages=[HumanMessage(content='Valid input')]
        )

        self.mock_gateway._prepare_and_validate_request = AsyncMock(
            return_value=expected_result
        )

        self.mock_gateway.prepare_stream = GatewayRoute.prepare_stream.__get__(
            self.mock_gateway, GatewayRoute
        )

        result = await self.mock_gateway.prepare_stream(
            request_uuid=str(db_mock.REQUEST_UUID),
            api_key_uuid=str(api_key.uuid),
            group_uuid=str(db_mock.GROUP_UUID),
            api_key_name=api_key.name,
            group_name=GROUP_NAME,
            messages=[HumanMessage(content='Valid input')],
            route_name='rb-gateway',
            tools=None,
            tool_choice=None,
            hashed_api_key=db_mock.HASHED_KEY,
        )

        assert result == expected_result
        assert isinstance(result, PrepareAndValidateResult)

    async def test_prepare_stream_returns_soft_block_info(self):
        api_key = self._setup_mock_key_and_group()

        # Create a soft block response
        mock_soft_block = MagicMock()
        mock_soft_block.choices = [MagicMock()]
        mock_soft_block.choices[0].message.content = 'Soft blocked content'
        mock_soft_block.id = 'soft-block-id'

        expected_result = self._create_prepared_result(
            input_soft_block=mock_soft_block,
            guardrails_input_triggered=True,
        )

        self.mock_gateway._prepare_and_validate_request = AsyncMock(
            return_value=expected_result
        )

        self.mock_gateway.prepare_stream = GatewayRoute.prepare_stream.__get__(
            self.mock_gateway, GatewayRoute
        )

        result = await self.mock_gateway.prepare_stream(
            request_uuid=str(db_mock.REQUEST_UUID),
            api_key_uuid=str(api_key.uuid),
            group_uuid=str(db_mock.GROUP_UUID),
            api_key_name=api_key.name,
            group_name=GROUP_NAME,
            messages=[HumanMessage(content='Some input')],
            route_name='rb-gateway',
            tools=None,
            tool_choice=None,
            hashed_api_key=db_mock.HASHED_KEY,
        )

        assert result.input_soft_block is not None
        assert result.guardrails_input_triggered

    # =========================================================================
    # Tests for invoke_stream (Streaming Logic)
    # =========================================================================

    async def test_invoke_stream_yields_chunks_correctly(self):
        api_key = self._setup_mock_key_and_group()

        # Create prepared result
        prepared = self._create_prepared_result(
            messages=[HumanMessage(content='Hello')]
        )

        # Mock chat invoker stream
        async def mock_stream(*args, **kwargs):
            yield AIMessageChunk(content='Hello')
            yield AIMessageChunk(content=' World')

        mock_invoker = MagicMock()
        mock_invoker.stream = mock_stream
        self.mock_gateway.chat_invoker = mock_invoker
        self.mock_gateway.gateway_cache = None
        self.mock_gateway.token_limiter = MagicMock()
        self.mock_gateway.token_limiter.count_input = AsyncMock()
        self.mock_gateway.token_limiter.count_output = AsyncMock()
        self.mock_gateway.budget_limiter = MagicMock()
        self.mock_gateway.budget_limiter.count_input = AsyncMock()
        self.mock_gateway.budget_limiter.count_output = AsyncMock()

        # Bind real method
        self.mock_gateway.invoke_stream = GatewayRoute.invoke_stream.__get__(
            self.mock_gateway, GatewayRoute
        )

        # Collect chunks
        chunks = [
            chunk
            async for chunk in self.mock_gateway.invoke_stream(
                prepared=prepared,
                request_uuid=str(db_mock.REQUEST_UUID),
                api_key_uuid=str(api_key.uuid),
                group_uuid=str(db_mock.GROUP_UUID),
                api_key_name=api_key.name,
                group_name=GROUP_NAME,
                route_name='rb-gateway',
                tools=None,
                tool_choice=None,
                hashed_api_key=db_mock.HASHED_KEY,
            )
        ]

        assert len(chunks) == 2
        assert chunks[0].choices[0].delta.content == 'Hello'
        assert chunks[1].choices[0].delta.content == ' World'

    async def test_invoke_stream_yields_soft_block_chunk(self):
        api_key = self._setup_mock_key_and_group()

        mock_soft_block = MagicMock()
        mock_soft_block.choices = [MagicMock()]
        mock_soft_block.choices[0].message.content = 'Request blocked'
        mock_soft_block.id = 'soft-block-id'

        prepared = self._create_prepared_result(input_soft_block=mock_soft_block)

        # Bind real method
        self.mock_gateway.invoke_stream = GatewayRoute.invoke_stream.__get__(
            self.mock_gateway, GatewayRoute
        )

        # Collect chunks
        chunks = [
            chunk
            async for chunk in self.mock_gateway.invoke_stream(
                prepared=prepared,
                request_uuid=str(db_mock.REQUEST_UUID),
                api_key_uuid=str(api_key.uuid),
                group_uuid=str(db_mock.GROUP_UUID),
                api_key_name=api_key.name,
                group_name=GROUP_NAME,
                route_name='rb-gateway',
                tools=None,
                tool_choice=None,
                hashed_api_key=db_mock.HASHED_KEY,
            )
        ]

        # Should have exactly one soft block chunk
        assert len(chunks) == 1
        assert chunks[0].choices[0].delta.content == 'Request blocked'

    async def test_invoke_stream_yields_cached_response_chunk(self):
        api_key = self._setup_mock_key_and_group()

        # Create cached response mock
        mock_cached = MagicMock()
        mock_cached.choices = [MagicMock()]
        mock_cached.choices[0].message.content = 'Cached content'
        mock_cached.id = 'cached-id'

        prepared = self._create_prepared_result(cached_response=mock_cached)

        # Bind real method
        self.mock_gateway.invoke_stream = GatewayRoute.invoke_stream.__get__(
            self.mock_gateway, GatewayRoute
        )

        chunks = [
            chunk
            async for chunk in self.mock_gateway.invoke_stream(
                prepared=prepared,
                request_uuid=str(db_mock.REQUEST_UUID),
                api_key_uuid=str(api_key.uuid),
                group_uuid=str(db_mock.GROUP_UUID),
                api_key_name=api_key.name,
                group_name=GROUP_NAME,
                route_name='rb-gateway',
                tools=None,
                tool_choice=None,
                hashed_api_key=db_mock.HASHED_KEY,
            )
        ]

        # Should return cached content as a single chunk
        assert len(chunks) == 1
        assert chunks[0].choices[0].delta.content == 'Cached content'

    async def test_stream_from_prepared_includes_usage_when_requested(self):
        api_key = self._setup_mock_key_and_group()

        prepared = self._create_prepared_result(
            messages=[HumanMessage(content='Hello')]
        )

        # Mock chat invoker stream with usage metadata
        async def mock_stream(*args, **kwargs):
            yield AIMessageChunk(
                content='Test',
                usage_metadata={
                    'input_tokens': 10,
                    'output_tokens': 5,
                    'total_tokens': 15,
                },
            )

        mock_invoker = MagicMock()
        mock_invoker.stream = mock_stream
        self.mock_gateway.chat_invoker = mock_invoker
        self.mock_gateway.gateway_cache = None
        self.mock_gateway.token_limiter = MagicMock()
        self.mock_gateway.token_limiter.count_input = AsyncMock()
        self.mock_gateway.token_limiter.count_output = AsyncMock()
        self.mock_gateway.budget_limiter = MagicMock()
        self.mock_gateway.budget_limiter.count_input = AsyncMock()
        self.mock_gateway.budget_limiter.count_output = AsyncMock()
        self.mock_gateway._count_usage = AsyncMock()

        # Bind real method
        self.mock_gateway.invoke_stream = GatewayRoute.invoke_stream.__get__(
            self.mock_gateway, GatewayRoute
        )

        # Collect chunks with include_usage=True
        chunks = [
            chunk
            async for chunk in self.mock_gateway.invoke_stream(
                prepared=prepared,
                request_uuid=str(db_mock.REQUEST_UUID),
                api_key_uuid=str(api_key.uuid),
                group_uuid=str(db_mock.GROUP_UUID),
                api_key_name=api_key.name,
                group_name=GROUP_NAME,
                route_name='rb-gateway',
                tools=None,
                tool_choice=None,
                hashed_api_key=db_mock.HASHED_KEY,
                stream_options={'include_usage': True},
            )
        ]

        # Should have content chunk + usage chunk
        assert len(chunks) == 2

        # Second chunk should be usage
        usage_chunk = chunks[1]
        assert len(usage_chunk.choices) == 0
        assert usage_chunk.usage.total_tokens == 15

    # =========================================================================
    # Integration Tests (Full Flow via HTTP endpoint)
    # =========================================================================

    async def test_streaming_input_guardrail_exception_returns_http_400(self):
        # Mock prepare_stream to raise GuardrailBadRequest
        mock_guardrail = MagicMock()
        mock_guardrail.name = 'input_guardrail'
        mock_guardrail.type = MagicMock()
        mock_guardrail.type.name = 'REGEX'
        mock_guardrail.where = GuardrailWhereType.INPUT

        mock_exception = GuardrailBadRequest(
            message='Input Blocked',
            guardrail=mock_guardrail,
            reason={'context': 'forbidden'},
        )

        self.mock_gateway.prepare_stream = AsyncMock(side_effect=mock_exception)
        self.mock_gateway.has_output_guardrails = MagicMock(return_value=False)

        request_data = {
            'model': 'rb-gateway',
            'messages': [{'role': 'user', 'content': 'Forbidden input'}],
            'stream': True,
        }

        response = self.client.post(
            '/v1/chat/completions', json=request_data, headers=self.headers
        )

        # Verify HTTP 400 (not 200 with broken stream)
        assert response.status_code == 400

        # Verify guardrails header
        assert response.headers.get('X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED') == 'true'

        # Verify error body
        error_data = response.json()
        assert error_data['error']['message'] == 'Input Blocked'
        assert error_data['error']['type'] == 'guardrail_error'

    async def test_streaming_success_with_new_architecture(self):
        # Create successful prepared result
        prepared = self._create_prepared_result(
            messages=[HumanMessage(content='Hello')]
        )

        self.mock_gateway.prepare_stream = AsyncMock(return_value=prepared)
        self.mock_gateway.has_output_guardrails = MagicMock(return_value=False)

        # Mock invoke_stream to yield chunks
        async def mock_invoke_stream(*args, **kwargs):
            chunk1 = MagicMock()
            chunk1.model_dump_json = MagicMock(
                return_value='{"choices":[{"delta":{"content":"Hello"}}]}'
            )
            yield chunk1

            chunk2 = MagicMock()
            chunk2.model_dump_json = MagicMock(
                return_value='{"choices":[{"delta":{"content":" World"}}]}'
            )
            yield chunk2

        self.mock_gateway.invoke_stream = mock_invoke_stream

        request_data = {
            'model': 'rb-gateway',
            'messages': [{'role': 'user', 'content': 'Hello'}],
            'stream': True,
        }

        response = self.client.post(
            '/v1/chat/completions', json=request_data, headers=self.headers
        )

        assert response.status_code == 200
        lines = response.text.strip().split('\n\n')

        # Expect 2 data chunks + [DONE]
        assert len(lines) == 3

        chunk1 = json.loads(lines[0][6:])
        assert chunk1['choices'][0]['delta']['content'] == 'Hello'

        chunk2 = json.loads(lines[1][6:])
        assert chunk2['choices'][0]['delta']['content'] == ' World'

        assert lines[2] == 'data: [DONE]'

    async def test_streaming_guardrails_triggered_header_set(self):
        # Create prepared result with guardrails block triggered flag
        # (BLOCK/SOFT_BLOCK triggers header, not REDACT or WARN)
        prepared = self._create_prepared_result(
            messages=[HumanMessage(content='Hello')],
            guardrails_input_triggered=True,
            guardrails_block_triggered=True,
        )

        self.mock_gateway.prepare_stream = AsyncMock(return_value=prepared)
        self.mock_gateway.has_output_guardrails = MagicMock(return_value=False)

        async def mock_invoke_stream(*args, **kwargs):
            chunk = MagicMock()
            chunk.model_dump_json = MagicMock(
                return_value='{"choices":[{"delta":{"content":"Redacted"}}]}'
            )
            yield chunk

        self.mock_gateway.invoke_stream = mock_invoke_stream

        request_data = {
            'model': 'rb-gateway',
            'messages': [{'role': 'user', 'content': 'Hello'}],
            'stream': True,
        }

        response = self.client.post(
            '/v1/chat/completions', json=request_data, headers=self.headers
        )

        assert response.status_code == 200
        assert response.headers.get('X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED') == 'true'

    # =========================================================================
    # Tests for Output Guardrails (Buffered Streaming Path)
    # =========================================================================

    async def test_streaming_output_guardrail_blocked(self):
        # Mock stream to yield chunks
        async def mock_stream(*args, **kwargs):
            yield AIMessageChunk(content='Bad content')

        mock_invoker = MagicMock()
        mock_invoker.stream = mock_stream
        self.mock_gateway.chat_invoker = mock_invoker

        # Mock guardrail_engine.has_guardrails_for_route
        mock_guardrail_engine = MagicMock()
        mock_guardrail_engine.has_guardrails_for_route = MagicMock(return_value=True)
        self.mock_gateway.guardrail_engine = mock_guardrail_engine

        # Mock _apply_check_guardrails to return a block
        mock_block_response = MagicMock()
        mock_block_response.choices = [MagicMock()]
        mock_block_response.choices[0].message.content = 'I cannot say that.'
        mock_block_response.id = 'refusal-id'
        self.mock_gateway._apply_check_guardrails = AsyncMock(
            return_value=mock_block_response
        )

        # Mock prepare_stream to return a valid PrepareAndValidateResult
        self.mock_gateway.prepare_stream = AsyncMock(
            return_value=self._create_prepared_result()
        )

        # Use real invoke_stream_buffered logic
        self.mock_gateway.invoke_stream_buffered = (
            GatewayRoute.invoke_stream_buffered.__get__(self.mock_gateway, GatewayRoute)
        )
        self.mock_gateway._handle_buffered_stream = (
            GatewayRoute._handle_buffered_stream.__get__(
                self.mock_gateway, GatewayRoute
            )
        )
        self.mock_gateway.has_output_guardrails = MagicMock(return_value=True)

        request_data = {
            'model': 'rb-gateway',
            'messages': [{'role': 'user', 'content': 'Say something bad'}],
            'stream': True,
        }

        response = self.client.post(
            '/v1/chat/completions', json=request_data, headers=self.headers
        )

        # Verify HTTP 400 for blocked output
        assert response.status_code == 400

        # Verify Header
        assert response.headers.get('X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED') == 'true'

        # Verify Body
        error_data = response.json()
        assert error_data['error']['message'] == 'I cannot say that.'

    async def test_streaming_output_guardrail_passed(self):
        # Mock stream to yield chunks
        async def mock_stream(*args, **kwargs):
            yield AIMessageChunk(content='Good')
            yield AIMessageChunk(content=' content')

        mock_invoker = MagicMock()
        mock_invoker.stream = mock_stream
        self.mock_gateway.chat_invoker = mock_invoker

        # Mock guardrail_engine.has_guardrails_for_route
        mock_guardrail_engine = MagicMock()
        mock_guardrail_engine.has_guardrails_for_route = MagicMock(return_value=True)
        self.mock_gateway.guardrail_engine = mock_guardrail_engine

        # Mock _apply_check_guardrails to return None (check passed)
        self.mock_gateway._apply_check_guardrails = AsyncMock(return_value=None)

        # Mock prepare_stream to return a valid PrepareAndValidateResult
        self.mock_gateway.prepare_stream = AsyncMock(
            return_value=self._create_prepared_result()
        )

        # Use real buffered stream logic
        self.mock_gateway.invoke_stream_buffered = (
            GatewayRoute.invoke_stream_buffered.__get__(self.mock_gateway, GatewayRoute)
        )
        self.mock_gateway._handle_buffered_stream = (
            GatewayRoute._handle_buffered_stream.__get__(
                self.mock_gateway, GatewayRoute
            )
        )
        self.mock_gateway.has_output_guardrails = MagicMock(return_value=True)
        self.mock_gateway.gateway_cache = None

        request_data = {
            'model': 'rb-gateway',
            'messages': [{'role': 'user', 'content': 'Say something good'}],
            'stream': True,
        }

        response = self.client.post(
            '/v1/chat/completions', json=request_data, headers=self.headers
        )

        assert response.status_code == 200
        lines = response.text.strip().split('\n\n')

        # Expect 2 data chunks + [DONE]
        assert len(lines) == 3

        chunk1 = json.loads(lines[0][6:])
        assert chunk1['choices'][0]['delta']['content'] == 'Good'

        chunk2 = json.loads(lines[1][6:])
        assert chunk2['choices'][0]['delta']['content'] == ' content'

    async def test_streaming_output_guardrail_exception(self):
        # Mock stream to yield chunks
        async def mock_stream(*args, **kwargs):
            yield AIMessageChunk(content='Bad content')

        mock_invoker = MagicMock()
        mock_invoker.stream = mock_stream
        self.mock_gateway.chat_invoker = mock_invoker

        # Mock guardrail_engine.has_guardrails_for_route
        mock_guardrail_engine = MagicMock()
        mock_guardrail_engine.has_guardrails_for_route = MagicMock(return_value=True)
        self.mock_gateway.guardrail_engine = mock_guardrail_engine

        # Mock _apply_check_guardrails to raise GuardrailBadRequest
        mock_guardrail = MagicMock()
        mock_guardrail.name = 'test_guardrail'
        mock_guardrail.type = MagicMock()
        mock_guardrail.type.name = 'REGEX'
        mock_guardrail.where = GuardrailWhereType.OUTPUT

        mock_exception = GuardrailBadRequest(
            message='Guardrail Blocked',
            guardrail=mock_guardrail,
            reason={'foo': 'bar'},
        )
        self.mock_gateway._apply_check_guardrails = AsyncMock(
            side_effect=mock_exception
        )

        # Mock prepare_stream to return a valid PrepareAndValidateResult
        self.mock_gateway.prepare_stream = AsyncMock(
            return_value=self._create_prepared_result()
        )

        # Use real buffered stream logic
        self.mock_gateway.invoke_stream_buffered = (
            GatewayRoute.invoke_stream_buffered.__get__(self.mock_gateway, GatewayRoute)
        )
        self.mock_gateway._handle_buffered_stream = (
            GatewayRoute._handle_buffered_stream.__get__(
                self.mock_gateway, GatewayRoute
            )
        )
        self.mock_gateway.has_output_guardrails = MagicMock(return_value=True)

        request_data = {
            'model': 'rb-gateway',
            'messages': [{'role': 'user', 'content': 'Say something bad'}],
            'stream': True,
        }

        response = self.client.post(
            '/v1/chat/completions', json=request_data, headers=self.headers
        )

        # Verify HTTP 400
        assert response.status_code == 400

        # Verify Header
        assert response.headers.get('X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED') == 'true'

        # Verify Body
        error_data = response.json()
        assert error_data['error']['type'] == 'guardrail_error'
        assert error_data['error']['message'] == 'Guardrail Blocked'

    # =========================================================================
    # Tests for Error Handling During Streaming
    # =========================================================================

    async def test_streaming_error_propagation(self):
        api_key = self._setup_mock_key_and_group()

        prepared = self._create_prepared_result()

        # Mock chat invoker to raise an error
        async def mock_stream_error(*args, **kwargs):
            yield AIMessageChunk(content='Start')
            raise RuntimeError('Connection lost')

        mock_invoker = MagicMock()
        mock_invoker.stream = mock_stream_error
        self.mock_gateway.chat_invoker = mock_invoker
        self.mock_gateway.gateway_cache = None

        # Bind real method
        self.mock_gateway.invoke_stream = GatewayRoute.invoke_stream.__get__(
            self.mock_gateway, GatewayRoute
        )

        # Should raise RuntimeError
        with pytest.raises(RuntimeError) as context:
            [
                chunk
                async for chunk in self.mock_gateway.invoke_stream(
                    prepared=prepared,
                    request_uuid=str(db_mock.REQUEST_UUID),
                    api_key_uuid=str(api_key.uuid),
                    group_uuid=str(db_mock.GROUP_UUID),
                    api_key_name=api_key.name,
                    group_name=GROUP_NAME,
                    route_name='rb-gateway',
                    tools=None,
                    tool_choice=None,
                    hashed_api_key=db_mock.HASHED_KEY,
                )
            ]

        assert str(context.value) == 'Connection lost'

    # =========================================================================
    # Tests for Cache Integration
    # =========================================================================

    async def test_streaming_cache_hit(self):
        # Create cached response mock
        mock_cached_resp = MagicMock()
        mock_cached_resp.choices = [MagicMock()]
        mock_cached_resp.choices[0].message.content = 'Cached content'
        mock_cached_resp.usage = MagicMock()
        mock_cached_resp.usage.prompt_tokens = 10
        mock_cached_resp.usage.completion_tokens = 5
        mock_cached_resp.usage.total_tokens = 15
        mock_cached_resp.id = 'cached-id'

        # Create prepared result with cache hit
        prepared = self._create_prepared_result(cached_response=mock_cached_resp)

        self.mock_gateway.prepare_stream = AsyncMock(return_value=prepared)
        self.mock_gateway.has_output_guardrails = MagicMock(return_value=False)

        # Bind real invoke_stream
        self.mock_gateway.invoke_stream = GatewayRoute.invoke_stream.__get__(
            self.mock_gateway, GatewayRoute
        )

        request_data = {
            'model': 'rb-gateway',
            'messages': [{'role': 'user', 'content': 'Cacheable request'}],
            'stream': True,
        }

        response = self.client.post(
            '/v1/chat/completions', json=request_data, headers=self.headers
        )

        assert response.status_code == 200
        lines = response.text.strip().split('\n\n')

        # Should have cached content chunk + [DONE]
        assert len(lines) >= 2

        chunk1 = json.loads(lines[0][6:])
        assert chunk1['choices'][0]['delta']['content'] == 'Cached content'

    async def test_streaming_include_usage(self):
        # Create prepared result
        prepared = self._create_prepared_result()

        self.mock_gateway.prepare_stream = AsyncMock(return_value=prepared)
        self.mock_gateway.has_output_guardrails = MagicMock(return_value=False)

        # Mock stream with usage metadata
        async def mock_invoke_stream(prepared, *args, **kwargs):
            chunk1 = MagicMock()
            chunk1.model_dump_json = MagicMock(
                return_value='{"choices":[{"delta":{"content":"Test"}}]}'
            )
            yield chunk1

            # Usage chunk
            usage_chunk = MagicMock()
            usage_chunk.model_dump_json = MagicMock(
                return_value='{"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}}'
            )
            yield usage_chunk

        self.mock_gateway.invoke_stream = mock_invoke_stream

        request_data = {
            'model': 'rb-gateway',
            'messages': [{'role': 'user', 'content': 'Hello'}],
            'stream': True,
            'stream_options': {'include_usage': True},
        }

        response = self.client.post(
            '/v1/chat/completions', json=request_data, headers=self.headers
        )

        assert response.status_code == 200
        lines = response.text.strip().split('\n\n')

        # Expect Data chunk, Usage Chunk, [DONE]
        assert len(lines) >= 3

        # Last chunk before [DONE] should be usage
        usage_line = lines[-2]
        assert usage_line.startswith('data: ')
        usage_chunk = json.loads(usage_line[6:])

        assert len(usage_chunk['choices']) == 0
        assert usage_chunk['usage']['total_tokens'] == 15
