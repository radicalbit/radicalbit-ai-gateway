import unittest
from unittest.mock import MagicMock, patch

from langchain_core.messages import HumanMessage
import pytest

from tests.common.db_mock import API_KEY_UUID, GROUP_UUID, REQUEST_UUID

from radicalbit_ai_gateway.invocation.chat_model_invoker import ChatModelInvoker
from radicalbit_ai_gateway.invocation.embedding_model_invoker import (
    EmbeddingModelInvoker,
)
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.services.cost_service import CostService


class TestMockInvokers(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.emit_event_patcher = patch(
            'radicalbit_ai_gateway.invocation.model_invoker.emit_event', autospec=True
        )
        cls.emit_event_patcher.start()
        cls.cost_service: CostService = MagicMock(spec_set=CostService)

    @classmethod
    def tearDownClass(cls):
        cls.emit_event_patcher.stop()

    @pytest.mark.asyncio
    async def test_mock_chat_invoker_returns_configured_text(self):
        models = [
            Model(
                model_id='mock-chat',
                model='mock/gateway',
                params={'latency_ms': 1, 'response_text': 'risposta dal mock'},
            )
        ]
        invoker = ChatModelInvoker(
            models=models, fallbacks=None, cost_service=self.cost_service
        )

        result = await invoker.complete(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            group_uuid=str(GROUP_UUID),
            api_key_name='rb-key',
            group_name='test-group',
            route_name='mock-testing',
            messages=[HumanMessage(content='Ciao')],
            model_id='mock-chat',
            tools=None,
            tool_choice=None,
        )

        assert result.choices[0].message.content == 'risposta dal mock'

    async def test_mock_embeddings_invoker_returns_vectors(self):
        vector_size = 6
        models = [
            Model(
                model_id='mock-embed',
                model='mock/embeddings',
                params={'latency_ms': 1, 'vector_size': vector_size},
            )
        ]
        invoker = EmbeddingModelInvoker(
            models=models, fallbacks=None, cost_service=self.cost_service
        )

        resp = await invoker.embed(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            group_uuid=str(GROUP_UUID),
            api_key_name='rb-key',
            group_name='test-group',
            route_name='mock-testing',
            input_texts=['Hello world'],
            model_id='mock-embed',
        )

        assert len(resp.data) == 1
        assert len(resp.data[0].embedding) == vector_size


if __name__ == '__main__':
    unittest.main()
