import unittest
from unittest.mock import MagicMock, patch

from langchain_core.messages import HumanMessage
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
from radicalbit_ai_gateway.models.fallback import FallbackModelType
from radicalbit_ai_gateway.models.gateway_config import get_model_from_model_id
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.exceptions import ModelInvokerInternalError


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
            'radicalbit_ai_gateway.invocation.model_invoker.emit_event', autospec=True
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
        with pytest.raises(
            ModelInvokerInternalError,
            match=r'All chat models failed for model test-route: You exceeded your current quota, please check your plan and billing details.',
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
