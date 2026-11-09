import json
import unittest
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
from starlette.requests import Request

from tests.common import db_mock
from tests.common.routes import Prepared, answered_by_mocks, mock_route

from radicalbit_ai_gateway.caching.route_cache import RouteCache
from radicalbit_ai_gateway.guardrails.guardrails import GuardrailFlags, RouteGuardrails
from radicalbit_ai_gateway.limiting.limits import RouteLimits
from radicalbit_ai_gateway.llm.messages import HumanMessage
from radicalbit_ai_gateway.models.guardrails import GuardrailWhereType
from radicalbit_ai_gateway.server import app, group_service, key_service
from radicalbit_ai_gateway.utils.dependencies import get_request_uuid
from radicalbit_ai_gateway.utils.exceptions import GuardrailBadRequest

GROUP_NAME = 'group'


def mock_request_uuid(request: Request):
    request.state.request_uuid = str(db_mock.REQUEST_UUID)
    return str(db_mock.REQUEST_UUID)


class TestStreamingGuardrails(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls._answered = answered_by_mocks()
        cls._answered.__enter__()
        cls.mock_gateway = mock_route()
        cls.mock_gateway.route_limits = RouteLimits()
        cls.mock_gateway.project_uuid = ''
        cls.mock_gateway.project_name = ''
        cls.mock_gateway.cache = RouteCache()

        # Enable output guardrails in config
        mock_config = MagicMock()
        mock_config.guardrails.output = True
        mock_config.route_name = 'rb-gateway'
        cls.mock_gateway.gateway_route_config = mock_config

        app.state.routes = {'rb-gateway': cls.mock_gateway}
        app.dependency_overrides[get_request_uuid] = mock_request_uuid
        cls.client = TestClient(app)
        cls.headers = {'Authorization': f'Bearer {db_mock.PLAIN_KEY}'}

    @classmethod
    def tearDownClass(cls):
        cls._answered.__exit__(None, None, None)
        app.dependency_overrides = {}

    @staticmethod
    def _setup_mock_key_and_group():
        api_key = db_mock.get_sample_key_with_group(group_uuid=db_mock.GROUP_UUID)
        key_service.get_key_by_hashed_key = MagicMock(return_value=api_key)
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)
        return api_key

    @staticmethod
    def _create_prepared_result(
        messages: list | None = None,
        guardrails_input_triggered: bool = False,
        guardrails_block_triggered: bool = False,
    ) -> Prepared:
        return Prepared(
            GuardrailFlags(
                input_warned=guardrails_input_triggered,
                input_blocked=guardrails_block_triggered,
            ).headers()
        )

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
        self.mock_gateway.guardrails = RouteGuardrails()

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
        self.mock_gateway.guardrails = RouteGuardrails()

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
        self.mock_gateway.guardrails = RouteGuardrails()

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
    # Tests for Cache Integration
    # =========================================================================

    async def test_streaming_include_usage(self):
        # Create prepared result
        prepared = self._create_prepared_result()

        self.mock_gateway.prepare_stream = AsyncMock(return_value=prepared)
        self.mock_gateway.guardrails = RouteGuardrails()

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
