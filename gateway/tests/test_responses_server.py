"""Integration tests for POST /v1/responses endpoint."""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage, SystemMessage
from openai.types.chat.chat_completion_chunk import (
    ChatCompletionChunk,
    Choice as ChunkChoice,
    ChoiceDelta,
)
from openai.types.completion_usage import CompletionUsage
from starlette.requests import Request

from tests.common import db_mock
from tests.common.mocked_build_openai_chat_completion import (
    to_mock_openai_chat_completion,
)

from radicalbit_ai_gateway.ai_gateway import GatewayRoute
from radicalbit_ai_gateway.server import (
    app,
    group_service,
    key_service,
    set_request_uuid,
)
from radicalbit_ai_gateway.utils.ai_gateway_types import (
    InvokeResponse,
    PrepareAndValidateResult,
)


def mock_request_uuid(request: Request):
    request.state.request_uuid = str(db_mock.REQUEST_UUID)
    return str(db_mock.REQUEST_UUID)


def _make_prepared_result() -> PrepareAndValidateResult:
    """Minimal PrepareAndValidateResult with no soft block or cache."""
    model = MagicMock()
    model.model_id = 'rb-gateway'
    return PrepareAndValidateResult(
        model_selected=model,
        redacted_messages=[],
        cache_key='',
        embeddings=None,
        cached_response=None,
        input_soft_block=None,
        guardrails_input_triggered=False,
        guardrails_block_triggered=False,
    )


def _make_mock_gateway() -> MagicMock:
    mock_gw = MagicMock(spec=GatewayRoute)
    limiter = MagicMock()
    limiter.check_and_count_request = AsyncMock()
    mock_gw.request_rate_limiter = limiter
    mock_gw.has_output_guardrails.return_value = False
    mock_gw.gateway_route_config = MagicMock()
    mock_gw.gateway_route_config.route_name = 'rb-gateway'
    mock_gw.project_uuid = ''
    mock_gw.project_name = ''
    return mock_gw


class TestResponsesEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gateways_mock = {'rb-gateway': _make_mock_gateway()}
        app.state.routes = cls.gateways_mock
        app.dependency_overrides[set_request_uuid] = mock_request_uuid
        cls.client = TestClient(app)
        cls.headers = {'Authorization': f'Bearer {db_mock.PLAIN_KEY}'}
        cls.emit_event_patcher = patch(
            'radicalbit_ai_gateway.limiting.rate_limiter.emit_event', autospec=True
        )
        cls.emit_event_patcher.start()

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides = {}
        cls.emit_event_patcher.stop()

    def setUp(self):
        # Reset mock between tests
        self.gateways_mock['rb-gateway'] = _make_mock_gateway()
        app.state.routes = self.gateways_mock

    # ── Non-streaming ─────────────────────────────────────────────────────────

    def test_basic_text_request(self):
        key_service.get_key_by_hashed_key = MagicMock(
            return_value=db_mock.get_sample_key_with_group(
                group_uuid=db_mock.GROUP_UUID
            )
        )
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)

        mock_completion = to_mock_openai_chat_completion(content='Hello from gateway!')
        self.gateways_mock['rb-gateway'].invoke = AsyncMock(
            return_value=InvokeResponse(content=mock_completion, headers={})
        )

        response = self.client.post(
            '/v1/responses',
            json={'model': 'rb-gateway', 'input': 'Hi there'},
            headers=self.headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data['object'] == 'response'
        assert data['model'] == 'rb-gateway'
        assert data['status'] == 'completed'
        assert len(data['output']) == 1
        assert data['output'][0]['type'] == 'message'
        assert data['output'][0]['content'][0]['text'] == 'Hello from gateway!'

    def test_invoke_called_with_translated_messages(self):
        key_service.get_key_by_hashed_key = MagicMock(
            return_value=db_mock.get_sample_key_with_group(
                group_uuid=db_mock.GROUP_UUID
            )
        )
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)

        mock_completion = to_mock_openai_chat_completion(content='Hi')
        self.gateways_mock['rb-gateway'].invoke = AsyncMock(
            return_value=InvokeResponse(content=mock_completion, headers={})
        )

        self.client.post(
            '/v1/responses',
            json={
                'model': 'rb-gateway',
                'instructions': 'Be concise.',
                'input': [
                    {'role': 'user', 'content': 'Hello!', 'type': 'message'},
                ],
            },
            headers=self.headers,
        )

        call_args = self.gateways_mock['rb-gateway'].invoke.call_args
        assert call_args is not None
        msgs = call_args.kwargs['messages']
        assert len(msgs) == 2
        assert isinstance(msgs[0], SystemMessage)
        assert msgs[0].content == 'Be concise.'
        assert isinstance(msgs[1], HumanMessage)
        assert msgs[1].content == 'Hello!'
        assert call_args.kwargs['route_name'] == 'rb-gateway'

    def test_unknown_route_returns_400(self):
        key_service.get_key_by_hashed_key = MagicMock(
            return_value=db_mock.get_sample_key_with_group(
                group_uuid=db_mock.GROUP_UUID
            )
        )
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)

        response = self.client.post(
            '/v1/responses',
            json={'model': 'non-existent-route', 'input': 'test'},
            headers=self.headers,
        )
        assert response.status_code == 400

    def test_previous_response_id_returns_400(self):
        key_service.get_key_by_hashed_key = MagicMock(
            return_value=db_mock.get_sample_key_with_group(
                group_uuid=db_mock.GROUP_UUID
            )
        )
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)

        response = self.client.post(
            '/v1/responses',
            json={
                'model': 'rb-gateway',
                'input': 'Hi',
                'previous_response_id': 'resp_abc123',
            },
            headers=self.headers,
        )
        assert response.status_code == 400
        # The gateway returns {"error": {..., "message": "..."}}
        error_msg = response.json().get('error', {}).get('message', '')
        assert 'previous_response_id' in error_msg.lower()

    def test_function_tools_translated(self):
        key_service.get_key_by_hashed_key = MagicMock(
            return_value=db_mock.get_sample_key_with_group(
                group_uuid=db_mock.GROUP_UUID
            )
        )
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)

        mock_completion = to_mock_openai_chat_completion(content='Done')
        self.gateways_mock['rb-gateway'].invoke = AsyncMock(
            return_value=InvokeResponse(content=mock_completion, headers={})
        )

        self.client.post(
            '/v1/responses',
            json={
                'model': 'rb-gateway',
                'input': 'Call my tool',
                'tools': [
                    {
                        'type': 'function',
                        'function': {
                            'name': 'my_tool',
                            'description': 'Does something',
                            'parameters': {'type': 'object', 'properties': {}},
                        },
                    },
                    {'type': 'file_search'},  # should be skipped
                ],
                'tool_choice': 'auto',
            },
            headers=self.headers,
        )

        call_args = self.gateways_mock['rb-gateway'].invoke.call_args
        tools = call_args.kwargs['tools']
        assert len(tools) == 1  # file_search was skipped
        assert tools[0]['type'] == 'function'
        assert tools[0]['function']['name'] == 'my_tool'

    def test_extra_params_passed_through(self):
        """Temperature / top_p / max_output_tokens are forwarded to invoke."""
        key_service.get_key_by_hashed_key = MagicMock(
            return_value=db_mock.get_sample_key_with_group(
                group_uuid=db_mock.GROUP_UUID
            )
        )
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)

        mock_completion = to_mock_openai_chat_completion(content='Done')
        self.gateways_mock['rb-gateway'].invoke = AsyncMock(
            return_value=InvokeResponse(content=mock_completion, headers={})
        )

        self.client.post(
            '/v1/responses',
            json={
                'model': 'rb-gateway',
                'input': 'Hi',
                'temperature': 0.7,
                'top_p': 0.9,
                'max_output_tokens': 100,
            },
            headers=self.headers,
        )

        call_args = self.gateways_mock['rb-gateway'].invoke.call_args
        assert call_args.kwargs.get('temperature') == 0.7
        assert call_args.kwargs.get('top_p') == 0.9
        assert call_args.kwargs.get('max_completion_tokens') == 100
        # max_output_tokens must be remapped; original key must not leak
        assert 'max_output_tokens' not in call_args.kwargs

    def test_guardrails_header_propagated(self):
        key_service.get_key_by_hashed_key = MagicMock(
            return_value=db_mock.get_sample_key_with_group(
                group_uuid=db_mock.GROUP_UUID
            )
        )
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)

        mock_completion = to_mock_openai_chat_completion(content='Hi')
        self.gateways_mock['rb-gateway'].invoke = AsyncMock(
            return_value=InvokeResponse(
                content=mock_completion,
                headers={'X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED': 'true'},
            )
        )

        response = self.client.post(
            '/v1/responses',
            json={'model': 'rb-gateway', 'input': 'sensitive input'},
            headers=self.headers,
        )

        assert response.status_code == 200
        assert response.headers.get('x-rb-aigateway-guardrails-triggered') == 'true'

    # ── Streaming ────────────────────────────────────────────────────────────

    def _make_text_chunk(
        self, content: str, finish: str | None = None
    ) -> ChatCompletionChunk:
        return ChatCompletionChunk(
            id='chunk-1',
            object='chat.completion.chunk',
            created=1700000000,
            model='test-model',
            choices=[
                ChunkChoice(
                    index=0,
                    delta=ChoiceDelta(role='assistant', content=content),
                    finish_reason=finish,
                )
            ],
        )

    def _make_usage_chunk(self) -> ChatCompletionChunk:
        return ChatCompletionChunk(
            id='chunk-usage',
            object='chat.completion.chunk',
            created=1700000000,
            model='test-model',
            choices=[],
            usage=CompletionUsage(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            ),
        )

    def test_streaming_returns_sse(self):
        key_service.get_key_by_hashed_key = MagicMock(
            return_value=db_mock.get_sample_key_with_group(
                group_uuid=db_mock.GROUP_UUID
            )
        )
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)

        chunks = [
            self._make_text_chunk('Hello '),
            self._make_text_chunk('world!', finish='stop'),
            self._make_usage_chunk(),
        ]
        prepared = _make_prepared_result()
        self.gateways_mock['rb-gateway'].prepare_stream = AsyncMock(
            return_value=prepared
        )
        self.gateways_mock['rb-gateway'].has_output_guardrails.return_value = False

        async def _fake_stream(*args, **kwargs):
            for chunk in chunks:
                yield chunk

        self.gateways_mock['rb-gateway'].invoke_stream = _fake_stream

        response = self.client.post(
            '/v1/responses',
            json={'model': 'rb-gateway', 'input': 'Hi', 'stream': True},
            headers=self.headers,
        )

        assert response.status_code == 200
        assert 'text/event-stream' in response.headers.get('content-type', '')

        body = response.text
        # Should contain the standard Responses API event types
        assert 'response.created' in body
        assert 'response.in_progress' in body
        assert 'response.output_text.delta' in body
        assert 'response.output_text.done' in body
        assert 'response.completed' in body
        assert '[DONE]' in body

    def test_streaming_contains_full_text_in_completed_event(self):
        key_service.get_key_by_hashed_key = MagicMock(
            return_value=db_mock.get_sample_key_with_group(
                group_uuid=db_mock.GROUP_UUID
            )
        )
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)

        chunks = [
            self._make_text_chunk('Foo'),
            self._make_text_chunk('Bar', finish='stop'),
        ]
        prepared = _make_prepared_result()
        self.gateways_mock['rb-gateway'].prepare_stream = AsyncMock(
            return_value=prepared
        )
        self.gateways_mock['rb-gateway'].has_output_guardrails.return_value = False

        async def _fake_stream(*args, **kwargs):
            for chunk in chunks:
                yield chunk

        self.gateways_mock['rb-gateway'].invoke_stream = _fake_stream

        response = self.client.post(
            '/v1/responses',
            json={'model': 'rb-gateway', 'input': 'Tell me something', 'stream': True},
            headers=self.headers,
        )

        body = response.text
        # Find the response.completed event and check it contains both text fragments
        completed_events = [
            line[len('data: ') :].strip()
            for line in body.splitlines()
            if line.startswith('data: {') and 'response.completed' in line
        ]
        assert len(completed_events) == 1
        completed_data = json.loads(completed_events[0])
        output = completed_data['response']['output']
        assert len(output) == 1
        assert output[0]['content'][0]['text'] == 'FooBar'

    def test_streaming_buffered_when_output_guardrails(self):
        """With output guardrails, the buffered path is used."""
        key_service.get_key_by_hashed_key = MagicMock(
            return_value=db_mock.get_sample_key_with_group(
                group_uuid=db_mock.GROUP_UUID
            )
        )
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)

        buffered_chunks = [
            self._make_text_chunk('Buffered response', finish='stop'),
        ]
        prepared = _make_prepared_result()
        self.gateways_mock['rb-gateway'].prepare_stream = AsyncMock(
            return_value=prepared
        )
        self.gateways_mock['rb-gateway'].has_output_guardrails.return_value = True
        self.gateways_mock['rb-gateway'].invoke_stream_buffered = AsyncMock(
            return_value=(buffered_chunks, {})
        )

        response = self.client.post(
            '/v1/responses',
            json={'model': 'rb-gateway', 'input': 'Hi', 'stream': True},
            headers=self.headers,
        )

        assert response.status_code == 200
        body = response.text
        assert 'response.created' in body
        assert 'response.completed' in body
