import json
import unittest
from unittest.mock import AsyncMock, MagicMock

from fastapi import Request
from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage
from openai.types.chat.chat_completion_chunk import (
    ChatCompletionChunk,
    Choice,
    ChoiceDelta,
)

from tests.common import db_mock

from radicalbit_ai_gateway.ai_gateway import GatewayRoute
from radicalbit_ai_gateway.server import app, group_service, key_service
from radicalbit_ai_gateway.utils.ai_gateway_types import PrepareAndValidateResult
from radicalbit_ai_gateway.utils.dependencies import get_request_uuid
from radicalbit_ai_gateway.utils.exceptions import ModelInvokerInternalError


def mock_request_uuid(request: Request):
    request.state.request_uuid = str(db_mock.REQUEST_UUID)
    return str(db_mock.REQUEST_UUID)


class TestStreaming(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mock_gateway = MagicMock(spec=GatewayRoute)
        mock_rate_limiter = MagicMock()
        mock_rate_limiter.check_and_count_request = AsyncMock()
        cls.mock_gateway.request_rate_limiter = mock_rate_limiter
        cls.mock_gateway.project_uuid = ''
        cls.mock_gateway.project_name = ''
        cls.mock_gateway.gateway_route_config = MagicMock()
        cls.mock_gateway.gateway_route_config.route_name = 'rb-gateway'

        app.state.routes = {'rb-gateway': cls.mock_gateway}
        app.dependency_overrides[get_request_uuid] = mock_request_uuid
        cls.client = TestClient(app)
        cls.headers = {'Authorization': f'Bearer {db_mock.PLAIN_KEY}'}

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides = {}

    @staticmethod
    def _create_prepared_result() -> PrepareAndValidateResult:
        mock_model = MagicMock()
        mock_model.model_id = 'test-model'
        mock_model.input_cost_per_token = None
        mock_model.output_cost_per_token = None

        return PrepareAndValidateResult(
            model_selected=mock_model,
            redacted_messages=[HumanMessage(content='Hi')],
            cache_key='',
            embeddings=None,
            cached_response=None,
            input_soft_block=None,
            guardrails_input_triggered=False,
            guardrails_block_triggered=False,
        )

    def test_chat_completions_streaming(self):
        api_key = db_mock.get_sample_key_with_group(group_uuid=db_mock.GROUP_UUID)
        key_service.get_key_by_hashed_key = MagicMock(return_value=api_key)
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)

        # Mock prepare_stream to return a valid PrepareAndValidateResult
        prepared = self._create_prepared_result()
        self.mock_gateway.prepare_stream = AsyncMock(return_value=prepared)
        self.mock_gateway.has_output_guardrails = MagicMock(return_value=False)

        # Mock invoke_stream to yield chunks
        async def mock_invoke_stream(*args, **kwargs):
            yield ChatCompletionChunk(
                id='1',
                choices=[
                    Choice(
                        index=0, delta=ChoiceDelta(content='Hello'), finish_reason=None
                    )
                ],
                created=123,
                model='rb-gateway',
                object='chat.completion.chunk',
            )
            yield ChatCompletionChunk(
                id='1',
                choices=[
                    Choice(
                        index=0,
                        delta=ChoiceDelta(content=' World'),
                        finish_reason='stop',
                    )
                ],
                created=124,
                model='rb-gateway',
                object='chat.completion.chunk',
            )

        self.mock_gateway.invoke_stream = mock_invoke_stream

        request_data = {
            'model': 'rb-gateway',
            'messages': [{'role': 'user', 'content': 'Hi'}],
            'stream': True,
        }

        response = self.client.post(
            '/v1/chat/completions', json=request_data, headers=self.headers
        )

        assert response.status_code == 200
        assert response.headers['content-type'] == 'text/event-stream; charset=utf-8'

        lines = response.text.strip().split('\n\n')
        assert len(lines) == 3
        assert lines[0].startswith('data: ')
        assert lines[1].startswith('data: ')
        assert lines[2] == 'data: [DONE]'

        chunk1 = json.loads(lines[0][6:])
        assert chunk1['choices'][0]['delta']['content'] == 'Hello'

        chunk2 = json.loads(lines[1][6:])
        assert chunk2['choices'][0]['delta']['content'] == ' World'
        assert chunk2['choices'][0]['finish_reason'] == 'stop'

    def test_chat_completions_streaming_with_guardrails_triggered_header(self):
        api_key = db_mock.get_sample_key_with_group(group_uuid=db_mock.GROUP_UUID)
        key_service.get_key_by_hashed_key = MagicMock(return_value=api_key)
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)

        # Mock prepare_stream with guardrails_block_triggered=True
        # (BLOCK/SOFT_BLOCK triggers header, not REDACT or WARN)
        prepared = self._create_prepared_result()
        prepared = PrepareAndValidateResult(
            model_selected=prepared.model_selected,
            redacted_messages=prepared.redacted_messages,
            cache_key='',
            embeddings=None,
            cached_response=None,
            input_soft_block=None,
            guardrails_input_triggered=True,
            guardrails_block_triggered=True,  # BLOCK/SOFT_BLOCK triggers the header
        )
        self.mock_gateway.prepare_stream = AsyncMock(return_value=prepared)
        self.mock_gateway.has_output_guardrails = MagicMock(return_value=False)

        # Mock invoke_stream
        async def mock_invoke_stream(*args, **kwargs):
            yield ChatCompletionChunk(
                id='1',
                choices=[
                    Choice(
                        index=0,
                        delta=ChoiceDelta(content='Redacted response'),
                        finish_reason='stop',
                    )
                ],
                created=123,
                model='rb-gateway',
                object='chat.completion.chunk',
            )

        self.mock_gateway.invoke_stream = mock_invoke_stream

        request_data = {
            'model': 'rb-gateway',
            'messages': [{'role': 'user', 'content': 'Hi'}],
            'stream': True,
        }

        response = self.client.post(
            '/v1/chat/completions', json=request_data, headers=self.headers
        )

        assert response.status_code == 200
        assert response.headers.get('X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED') == 'true'

    def test_chat_completions_streaming_error_returns_error_status(self):
        """When invoke_stream fails on the first chunk, the response should
        be a proper HTTP error (not 200) so clients see the failure.
        """

        api_key = db_mock.get_sample_key_with_group(group_uuid=db_mock.GROUP_UUID)
        key_service.get_key_by_hashed_key = MagicMock(return_value=api_key)
        group_service.check_key_for_route = MagicMock(return_value=True)

        prepared = self._create_prepared_result()
        self.mock_gateway.prepare_stream = AsyncMock(return_value=prepared)
        self.mock_gateway.has_output_guardrails = MagicMock(return_value=False)

        async def mock_invoke_stream_error(*args, **kwargs):
            raise ModelInvokerInternalError(
                'All chat models failed for model rb-gateway'
            )
            yield  # noqa: RUF027 — makes this an async generator

        self.mock_gateway.invoke_stream = mock_invoke_stream_error

        request_data = {
            'model': 'rb-gateway',
            'messages': [{'role': 'user', 'content': 'Hi'}],
            'stream': True,
        }

        response = self.client.post(
            '/v1/chat/completions', json=request_data, headers=self.headers
        )

        assert response.status_code == 500
        body = response.json()
        assert 'error' in body
