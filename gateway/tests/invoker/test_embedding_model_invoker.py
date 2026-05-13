import unittest
from unittest.mock import MagicMock, patch

import pytest

from tests.common.db_mock import API_KEY_UUID, GROUP_UUID, REQUEST_UUID
from tests.common.mocked_embeddings import (
    MockFailingEmbeddingModel,
    MockWorkingEmbeddingModel,
)
from tests.common.mocked_gateway_config_openai import get_default_gateway_openai

from radicalbit_ai_gateway.invocation.embedding_model_invoker import (
    EmbeddingModelInvoker,
)
from radicalbit_ai_gateway.models.fallback import FallbackModelType
from radicalbit_ai_gateway.models.gateway_config import get_model_from_model_id
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.exceptions import ModelInvokerInternalError


class TestEmbeddingModelInvoker(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.gateway_config = get_default_gateway_openai()
        cls.route_config = cls.gateway_config.routes['rb-gateway']

        cls.models_by_id = {
            m.model_id: m for m in (cls.gateway_config.embedding_models or [])
        }

        cls.route_embedding_models = [
            get_model_from_model_id(
                models_by_id=cls.models_by_id,
                route_name=cls.route_config.route_name,
                model_id=mid,
            )
            for mid in (cls.route_config.embedding_models or [])
        ]

        cls.embedding_fallbacks = [
            fb
            for fb in (cls.route_config.fallback or [])
            if fb.type == FallbackModelType.EMBEDDING
        ]

        cost_service: CostService = MagicMock(spec_set=CostService)

        cls.embedding_model_invoker = EmbeddingModelInvoker(
            models=cls.route_embedding_models,
            fallbacks=cls.embedding_fallbacks,
            cost_service=cost_service,
        )
        cls.emit_event_patcher = patch(
            'radicalbit_ai_gateway.invocation.model_invoker.emit_event', autospec=True
        )
        cls.emit_event_patcher.start()

    @classmethod
    def tearDownClass(cls):
        cls.emit_event_patcher.stop()

    def reset_invoker(self):
        cost_service: CostService = MagicMock(spec_set=CostService)
        self.embedding_model_invoker = EmbeddingModelInvoker(
            models=self.route_embedding_models,
            fallbacks=self.embedding_fallbacks,
            cost_service=cost_service,
        )

    def _get_model(self, model_id: str):
        return get_model_from_model_id(
            models_by_id=self.models_by_id,
            route_name=self.route_config.route_name,
            model_id=model_id,
        )

    async def test_embed_success(self):
        self.reset_invoker()

        primary = self._get_model('text-embedding-3-small')

        self.embedding_model_invoker.model_map['text-embedding-3-small'] = (
            primary,
            MockWorkingEmbeddingModel(),
            [],
        )

        input_texts = ['hello', 'world']
        res = await self.embedding_model_invoker.embed(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            group_uuid=str(GROUP_UUID),
            api_key_name='rb-key',
            group_name='test-group',
            route_name='test-route',
            input_texts=input_texts,
            model_id='text-embedding-3-small',
        )
        assert res.object == 'list'
        assert len(res.data) == len(input_texts)
        assert res.data[0].embedding == [0.0, 1.0, 2.0, 3.0, 4.0]

    async def test_embed_with_fallback(self):
        self.reset_invoker()

        primary = self._get_model('text-embedding-3-small')

        self.embedding_model_invoker.model_map['text-embedding-3-small'] = (
            primary,
            MockFailingEmbeddingModel(),
            [
                (
                    primary,
                    MockWorkingEmbeddingModel(),
                )
            ],
        )

        input_texts = ['fallback test']
        res = await self.embedding_model_invoker.embed(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            group_uuid=str(GROUP_UUID),
            api_key_name='rb-key',
            group_name='test-group',
            route_name='test-route',
            input_texts=input_texts,
            model_id='text-embedding-3-small',
        )
        assert len(res.data) == 1
        assert res.data[0].embedding == [0.0, 1.0, 2.0, 3.0, 4.0]

    async def test_embed_failing_model(self):
        self.reset_invoker()

        primary = self._get_model('text-embedding-3-small')

        self.embedding_model_invoker.model_map['text-embedding-3-small'] = (
            primary,
            MockFailingEmbeddingModel(),
            [],
        )

        with pytest.raises(ModelInvokerInternalError, match='Embedding model failure'):
            await self.embedding_model_invoker.embed(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='rb-key',
                group_name='test-group',
                route_name='test-route',
                input_texts=['text'],
                model_id='text-embedding-3-small',
            )

    def test_model_map_initialization(self):
        self.reset_invoker()
        for model in self.route_embedding_models:
            assert model.model_id in self.embedding_model_invoker.model_map
