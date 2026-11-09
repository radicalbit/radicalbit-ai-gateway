import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import Request
from fastapi.testclient import TestClient
from openai.types.chat.chat_completion_chunk import (
    ChatCompletionChunk,
    Choice,
    ChoiceDelta,
)

from tests.common import db_mock
from tests.common.limits import project_limit
from tests.common.routes import Prepared, answered_by_mocks, mock_route

from radicalbit_ai_gateway.guardrails.guardrails import GuardrailFlags, RouteGuardrails
from radicalbit_ai_gateway.limiting.limits import Demand, RouteLimits
from radicalbit_ai_gateway.server import app, group_service, key_service
from radicalbit_ai_gateway.utils.dependencies import get_request_uuid
from radicalbit_ai_gateway.utils.exceptions import ModelInvokerInternalError


def mock_request_uuid(request: Request):
    request.state.request_uuid = str(db_mock.REQUEST_UUID)
    return str(db_mock.REQUEST_UUID)


class TestStreaming(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._answered = answered_by_mocks()
        cls._answered.__enter__()
        cls.mock_gateway = mock_route()
        cls.mock_gateway.route_limits = RouteLimits()
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
        cls._answered.__exit__(None, None, None)
        app.dependency_overrides = {}

    @staticmethod
    def _create_prepared_result() -> Prepared:
        return Prepared()

    def test_chat_completions_streaming(self):
        api_key = db_mock.get_sample_key_with_group(group_uuid=db_mock.GROUP_UUID)
        key_service.get_key_by_hashed_key = MagicMock(return_value=api_key)
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)

        # Mock prepare_stream to return a valid PrepareAndValidateResult
        prepared = self._create_prepared_result()
        self.mock_gateway.prepare_stream = AsyncMock(return_value=prepared)
        self.mock_gateway.guardrails = RouteGuardrails()

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
        prepared = Prepared(
            GuardrailFlags(input_warned=True, input_blocked=True).headers()
        )
        self.mock_gateway.prepare_stream = AsyncMock(return_value=prepared)
        self.mock_gateway.guardrails = RouteGuardrails()

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
        self.mock_gateway.guardrails = RouteGuardrails()

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

    def test_live_stream_body_counts_on_the_request_limits(self):
        """The handler returns before the stream body runs: the body still
        counts its usage on the request's limits, the project's included.
        """
        api_key = db_mock.get_sample_key_with_group(group_uuid=db_mock.GROUP_UUID)
        key_service.get_key_by_hashed_key = MagicMock(return_value=api_key)
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)
        self.mock_gateway.prepare_stream = AsyncMock(
            return_value=self._create_prepared_result()
        )
        self.mock_gateway.guardrails = RouteGuardrails()
        seen = {}

        async def mock_invoke_stream(*args, limits, **kwargs):
            yield ChatCompletionChunk(
                id='1',
                choices=[
                    Choice(
                        index=0, delta=ChoiceDelta(content='Hi'), finish_reason='stop'
                    )
                ],
                created=123,
                model='rb-gateway',
                object='chat.completion.chunk',
            )
            # Where GatewayRoute.invoke_stream counts the usage.
            seen['project limits'] = limits.applies(Demand(cost_room=True))

        self.mock_gateway.invoke_stream = mock_invoke_stream

        with patch(
            'radicalbit_ai_gateway.pipeline.admission.load_project_limits',
            return_value=[project_limit(10)],
        ):
            response = self.client.post(
                '/v1/chat/completions',
                json={
                    'model': 'rb-gateway',
                    'messages': [{'role': 'user', 'content': 'Hi'}],
                    'stream': True,
                },
                headers=self.headers,
            )

        assert response.status_code == 200
        assert seen == {'project limits': True}
