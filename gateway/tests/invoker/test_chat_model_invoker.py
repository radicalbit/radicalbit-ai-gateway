import unittest
from unittest.mock import MagicMock, patch

import pytest

from tests.common.db_mock import API_KEY_UUID, GROUP_UUID, REQUEST_UUID
from tests.common.mocked_gateway_config_openai import get_default_gateway_openai
from tests.common.mocked_runnables import (
    FailingChatModel,
    RateLimitedChatModel,
    UnauthorizedChatModel,
    WorkingChatModel,
)

from radicalbit_ai_gateway.invocation.chat_model_invoker import ChatModelInvoker
from radicalbit_ai_gateway.llm.messages import AIMessageChunk, HumanMessage
from radicalbit_ai_gateway.models.fallback import FallbackModelType
from radicalbit_ai_gateway.models.gateway_config import get_model_from_model_id
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.exceptions import ModelInvokerUpstreamError


class TestChatModelInvoker(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.gateway_config = get_default_gateway_openai()
        cls.route_config = cls.gateway_config.routes['rb-gateway']

        cls.models_by_id = {m.model_id: m for m in cls.gateway_config.chat_models}

        cls.route_chat_models = [
            get_model_from_model_id(
                models_by_id=cls.models_by_id,
                route_name=cls.route_config.route_name,
                model_id=mid,
            )
            for mid in (cls.route_config.chat_models or [])
        ]

        cls.chat_fallbacks = [
            fb
            for fb in (cls.route_config.fallback or [])
            if fb.type == FallbackModelType.CHAT
        ]
        cls.cost_service: CostService = MagicMock(spec_set=CostService)
        cls.chat_model_invoker = ChatModelInvoker(
            models=cls.route_chat_models,
            fallbacks=cls.chat_fallbacks,
            cost_service=cls.cost_service,
        )
        cls.emit_event_patcher = patch(
            'radicalbit_ai_gateway.invocation.recorder.emit_event', autospec=True
        )
        cls.emit_event_patcher.start()

    @classmethod
    def tearDownClass(cls):
        cls.emit_event_patcher.stop()

    def reset_invoker(self):
        self.chat_model_invoker = ChatModelInvoker(
            models=self.route_chat_models,
            fallbacks=self.chat_fallbacks,
            cost_service=self.cost_service,
        )

    def _get_model(self, model_id: str):
        return get_model_from_model_id(
            models_by_id=self.models_by_id,
            route_name=self.route_config.route_name,
            model_id=model_id,
        )

    async def _stream_with_fallback(self, primary_astream, fallback_astream):
        self.reset_invoker()
        primary, fallback = MagicMock(), MagicMock()
        primary.astream = primary_astream
        fallback.astream = fallback_astream
        model = self._get_model('openai-o4-mini')
        self.chat_model_invoker.model_map['openai-o4-mini'] = (
            model,
            primary,
            [(model, fallback)],
        )
        chunks = []
        try:
            async for chunk in self.chat_model_invoker.stream(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='rb-key',
                group_name='test-group',
                route_name='test-route',
                messages=[HumanMessage(content='Hi')],
                model_id='openai-o4-mini',
                tools=None,
                tool_choice=None,
            ):
                chunks.append(chunk.content)  # noqa: PERF401 — keep the chunks before an error
        except Exception as error:
            return chunks, error
        return chunks, None

    @staticmethod
    async def _fallback_stream(**_):
        yield AIMessageChunk(content='fallback')

    @pytest.mark.asyncio
    async def test_stream_error_after_a_chunk_does_not_fall_back(self):
        async def primary_stream(**_):
            yield AIMessageChunk(content='partial')
            raise RuntimeError('connection reset')

        chunks, error = await self._stream_with_fallback(
            primary_stream, self._fallback_stream
        )

        assert chunks == ['partial']
        assert isinstance(error, RuntimeError)

    @pytest.mark.asyncio
    async def test_stream_error_before_any_chunk_falls_back(self):
        async def primary_stream(**_):
            raise RuntimeError('connection refused')
            yield  # noqa: RUF027 — makes this an async generator

        chunks, error = await self._stream_with_fallback(
            primary_stream, self._fallback_stream
        )

        assert chunks == ['fallback']
        assert error is None

    @pytest.mark.asyncio
    async def test_invoker_with_fallbacks(self):
        self.reset_invoker()
        failing_chat = FailingChatModel()
        working_chat = WorkingChatModel()

        primary = self._get_model('openai-o4-mini')

        self.chat_model_invoker.model_map['openai-o4-mini'] = (
            primary,
            failing_chat,
            [(primary, working_chat)],
        )

        m = HumanMessage(content='What is the capital of France?')
        res = await self.chat_model_invoker.complete(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            group_uuid=str(GROUP_UUID),
            api_key_name='rb-key',
            group_name='test-group',
            route_name='test-route',
            messages=[m],
            model_id='openai-o4-mini',
            tools=[],
            tool_choice='auto',
        )
        assert (
            res.choices[0].message.content
            == 'This is a successful response from the WorkingChatModel.'
        )

    @pytest.mark.asyncio
    async def test_invoker_with_fallbacks_rate_limit(self):
        self.reset_invoker()
        rate_limit_chat = RateLimitedChatModel()
        working_chat = WorkingChatModel()

        primary = self._get_model('openai-o4-mini')

        self.chat_model_invoker.model_map['openai-o4-mini'] = (
            primary,
            rate_limit_chat,
            [(primary, working_chat)],
        )
        m = HumanMessage(content='What is the capital of France?')
        res = await self.chat_model_invoker.complete(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            group_uuid=str(GROUP_UUID),
            api_key_name='rb-key',
            group_name='test-group',
            route_name='test-route',
            messages=[m],
            model_id='openai-o4-mini',
            tools=[],
            tool_choice='auto',
        )
        assert (
            res.choices[0].message.content
            == 'This is a successful response from the WorkingChatModel.'
        )

    @pytest.mark.asyncio
    async def test_invoker_with_fallbacks_no_fallbacks(self):
        self.reset_invoker()
        failing_chat = RateLimitedChatModel()

        primary = self._get_model('openai-o4-mini')

        self.chat_model_invoker.model_map['openai-o4-mini'] = (
            primary,
            failing_chat,
            [],
        )

        m = HumanMessage(content='What is the capital of France?')
        # The provider's 4xx reaches the client as the provider sent it.
        with (
            self.assertLogs('radicalbit-ai-gateway', level='ERROR'),
            pytest.raises(ModelInvokerUpstreamError) as raised,
        ):
            await self.chat_model_invoker.complete(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='rb-key',
                group_name='test-group',
                route_name='test-route',
                messages=[m],
                model_id='openai-o4-mini',
                tools=[],
                tool_choice='auto',
            )
        assert raised.value.status_code == 429
        assert raised.value.body == {
            'error': {
                'message': 'You exceeded your current quota, please check your plan and billing details.',
                'type': 'insufficient_quota',
                'code': 'rate_limit_exceeded',
            }
        }

    @pytest.mark.asyncio
    async def test_invoker_with_fallbacks_unauthorized(self):
        self.reset_invoker()
        failing_chat = UnauthorizedChatModel()
        working_chat = WorkingChatModel()

        primary = self._get_model('openai-o4-mini')

        self.chat_model_invoker.model_map['openai-o4-mini'] = (
            primary,
            failing_chat,
            [(primary, working_chat)],
        )

        m = HumanMessage(content='What is the capital of France?')
        res = await self.chat_model_invoker.complete(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            group_uuid=str(GROUP_UUID),
            api_key_name='rb-key',
            group_name='test-group',
            route_name='test-route',
            messages=[m],
            model_id='openai-o4-mini',
            tools=[],
            tool_choice='auto',
        )
        assert (
            res.choices[0].message.content
            == 'This is a successful response from the WorkingChatModel.'
        )

    def test_model_map(self):
        self.reset_invoker()
        assert 'openai-o3' in self.chat_model_invoker.model_map
        assert 'openai-o4-mini' in self.chat_model_invoker.model_map
        assert 'openai-o1-mini' in self.chat_model_invoker.model_map

        assert self.chat_model_invoker.model_map['openai-o3'][0].model_id == 'openai-o3'
        assert (
            self.chat_model_invoker.model_map['openai-o4-mini'][0].model_id
            == 'openai-o4-mini'
        )
        assert (
            self.chat_model_invoker.model_map['openai-o1-mini'][0].model_id
            == 'openai-o1-mini'
        )

        assert len(self.chat_model_invoker.model_map['openai-o3'][2]) == 2
        assert len(self.chat_model_invoker.model_map['openai-o4-mini'][2]) == 2

        o3_fallbacks = self.chat_model_invoker.model_map['openai-o3'][2]
        o3_fallback_names = {chat_model.model_name for _, chat_model in o3_fallbacks}
        expected_o3_fallbacks = {'gpt-o4-mini', 'gpt-o1-mini'}
        assert o3_fallback_names == expected_o3_fallbacks

        o4_mini_fallbacks = self.chat_model_invoker.model_map['openai-o4-mini'][2]
        o4_mini_fallback_names = {
            chat_model.model_name for _, chat_model in o4_mini_fallbacks
        }
        expected_o4_mini_fallbacks = {'gpt-o1-mini', 'gpt-o3'}
        assert o4_mini_fallback_names == expected_o4_mini_fallbacks
