import unittest
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI
from openai.types.chat.chat_completion_chunk import (
    ChatCompletionChunk,
    Choice,
    ChoiceDelta,
)

from tests.common import db_mock

from radicalbit_ai_gateway.ai_gateway import GatewayRoute
from radicalbit_ai_gateway.server import (
    app,
    group_service,
    key_service,
    set_request_uuid,
)


def mock_request_uuid(request):
    request.state.request_uuid = str(db_mock.REQUEST_UUID)
    return str(db_mock.REQUEST_UUID)


class TestClientCompatibility(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mock_gateway = MagicMock(spec=GatewayRoute)
        mock_rate_limiter = MagicMock()
        mock_rate_limiter.check_and_count_request = AsyncMock()
        cls.mock_gateway.request_rate_limiter = mock_rate_limiter
        cls.mock_gateway.project_uuid = ''
        cls.mock_gateway.project_name = ''

        app.state.routes = {'rb-gateway': cls.mock_gateway}
        app.dependency_overrides[set_request_uuid] = mock_request_uuid

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

    async def test_langchain_client_streaming(self):
        # Prepare mock response generator (same as above)
        async def mock_stream(*args, **kwargs):
            yield ChatCompletionChunk(
                id='1',
                choices=[
                    Choice(
                        index=0,
                        delta=ChoiceDelta(content='LangChain'),
                        finish_reason=None,
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
                        delta=ChoiceDelta(content=' Works'),
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

        # Configure LangChain to use OpenAI client which uses TestClient transport
        transport = ASGITransport(app=app)
        async_client = AsyncClient(transport=transport, base_url='http://testkey/v1')

        chat = ChatOpenAI(
            api_key=db_mock.PLAIN_KEY,
            base_url='http://testkey/v1',
            model='rb-gateway',
            streaming=True,
            # We need to inject the custom http_client if possible, or patch it
            # LangChain's ChatOpenAI allows passing 'http_client' in 'openai_api_key' param? No.
            # It allows 'http_client' in constructor in newer versions or via 'default_headers'.
            # A cleaner way is to mock the underlying OpenAI client that LangChain creates.
            http_async_client=async_client,
        )

        chunks = [chunk async for chunk in chat.astream('Hi')]

        assert len(chunks) == 2
        assert chunks[0].content == 'LangChain'
        assert chunks[1].content == ' Works'
