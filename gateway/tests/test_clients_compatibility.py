import unittest
from unittest.mock import AsyncMock, MagicMock

from fastapi import Request
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from openai import AsyncOpenAI
from openai.types.chat.chat_completion_chunk import (
    ChatCompletionChunk,
    Choice,
    ChoiceDelta,
)

from tests.common import db_mock
from tests.common.mocked_build_openai_chat_completion import (
    to_mock_openai_chat_completion,
)

from radicalbit_ai_gateway.ai_gateway import GatewayRoute, InvokeResponse
from radicalbit_ai_gateway.server import app, group_service, key_service
from radicalbit_ai_gateway.utils.dependencies import get_request_uuid


def mock_request_uuid(request: Request):
    request.state.request_uuid = str(db_mock.REQUEST_UUID)
    return str(db_mock.REQUEST_UUID)


class TestClientCompatibility(unittest.IsolatedAsyncioTestCase):
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
        prepared = MagicMock(
            guardrails_block_triggered=False,
            guardrails_input_triggered=False,
            cached_response=None,
        )
        cls.mock_gateway.prepare_stream = AsyncMock(return_value=prepared)
        cls.mock_gateway.has_output_guardrails = MagicMock(return_value=False)

        app.state.routes = {'rb-gateway': cls.mock_gateway}
        app.dependency_overrides[get_request_uuid] = mock_request_uuid

        # Create a TestClient to act as the server
        cls.test_client = TestClient(app)
        cls.headers = {'Authorization': f'Bearer {db_mock.PLAIN_KEY}'}

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides = {}

    async def test_openai_sdk_streaming(self):
        # Prepare mock response generator
        async def mock_stream(*args, **kwargs):
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

        self.mock_gateway.invoke_stream = mock_stream

        # Check key and group for route
        api_key = db_mock.get_sample_key_with_group(group_uuid=db_mock.GROUP_UUID)
        key_service.get_key_by_hashed_key = MagicMock(return_value=api_key)
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)

        # Configure AsyncOpenAI to use TestClient transport
        transport = ASGITransport(app=app)
        client = AsyncOpenAI(
            api_key=db_mock.PLAIN_KEY,
            base_url='http://testkey/v1',
            http_client=AsyncClient(transport=transport, base_url='http://testkey'),
        )

        stream = await client.chat.completions.create(
            model='rb-gateway',
            messages=[{'role': 'user', 'content': 'Hi'}],
            stream=True,
        )

        chunks = [chunk async for chunk in stream]

        assert len(chunks) == 2
        assert chunks[0].choices[0].delta.content == 'Hello'
        assert chunks[1].choices[0].delta.content == ' World'

    async def test_openai_sdk_completion(self):
        self.mock_gateway.invoke = AsyncMock(
            return_value=InvokeResponse(
                content=to_mock_openai_chat_completion(content='Hello World'),
                headers={},
            )
        )

        # Check key and group for route
        api_key = db_mock.get_sample_key_with_group(group_uuid=db_mock.GROUP_UUID)
        key_service.get_key_by_hashed_key = MagicMock(return_value=api_key)
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)

        # Configure AsyncOpenAI to use TestClient transport
        transport = ASGITransport(app=app)
        client = AsyncOpenAI(
            api_key=db_mock.PLAIN_KEY,
            base_url='http://testkey/v1',
            http_client=AsyncClient(transport=transport, base_url='http://testkey'),
        )

        completion = await client.chat.completions.create(
            model='rb-gateway',
            messages=[{'role': 'user', 'content': 'Hi'}],
        )

        assert completion.choices[0].message.content == 'Hello World'
