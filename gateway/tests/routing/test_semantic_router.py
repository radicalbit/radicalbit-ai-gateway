from unittest.mock import AsyncMock

from langchain_core.messages import HumanMessage, SystemMessage
import numpy as np
import pytest

from tests.common.mocked_gateway_config_openai import get_gateway_routing_semantic

from radicalbit_ai_gateway.routing.semantic_router import SemanticRouter


def _make_embeddings_mock(embed_fn):
    mock = AsyncMock()
    mock.aembed_documents = AsyncMock(side_effect=embed_fn)
    mock.aembed_query = AsyncMock(return_value=[0.0] * 5)
    return mock


def _build_router(embeddings_mock):
    config = get_gateway_routing_semantic()
    routing_config = config.routing_by_name['semantic_routing']
    route = config.routes['smart_route']
    models_by_id = {mid: config.chat_models_by_id[mid] for mid in route.chat_models}
    return SemanticRouter(
        config=routing_config,
        models_by_id=models_by_id,
        embeddings_model=embeddings_mock,
    )


# Centroid for code_model: mean of 3 vectors pointing in "code" direction
CODE_VECS = [
    [1.0, 0.0, 0.0, 0.0, 0.0],
    [0.9, 0.1, 0.0, 0.0, 0.0],
    [0.8, 0.2, 0.0, 0.0, 0.0],
]
# Centroid for general_model: mean of 3 vectors pointing in "general" direction
GENERAL_VECS = [
    [0.0, 0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 0.9, 0.1, 0.0],
    [0.0, 0.0, 0.8, 0.2, 0.0],
]


def _init_embed_fn(texts):
    if len(texts) == 3 and 'python' in texts[0]:
        return CODE_VECS
    if len(texts) == 3 and 'weather' in texts[0]:
        return GENERAL_VECS
    return [[0.0] * 5 for _ in texts]


class TestSemanticRouter:
    @pytest.fixture
    def embeddings_mock(self):
        return _make_embeddings_mock(_init_embed_fn)

    @pytest.fixture
    async def router(self, embeddings_mock):
        router = _build_router(embeddings_mock)
        await router.initialize()
        return router

    async def test_matches_code_model(self, router, embeddings_mock):
        embeddings_mock.aembed_query = AsyncMock(return_value=[1.0, 0.0, 0.0, 0.0, 0.0])
        result = await router.select_model([HumanMessage(content='write python code')])
        assert result.model_id == 'code_model'

    async def test_matches_general_model(self, router, embeddings_mock):
        embeddings_mock.aembed_query = AsyncMock(return_value=[0.0, 0.0, 1.0, 0.0, 0.0])
        result = await router.select_model(
            [HumanMessage(content='what is the weather today')]
        )
        assert result.model_id == 'general_model'

    async def test_below_threshold_returns_default(self, router, embeddings_mock):
        embeddings_mock.aembed_query = AsyncMock(return_value=[0.0, 0.0, 0.0, 0.0, 1.0])
        result = await router.select_model(
            [HumanMessage(content='something completely unrelated')]
        )
        assert result.model_id == 'default_model'

    async def test_no_human_message_returns_default(self, router):
        result = await router.select_model([SystemMessage(content='you are a bot')])
        assert result.model_id == 'default_model'

    async def test_empty_messages_returns_default(self, router):
        result = await router.select_model([])
        assert result.model_id == 'default_model'

    async def test_uses_last_human_message(self, router, embeddings_mock):
        embeddings_mock.aembed_query = AsyncMock(return_value=[1.0, 0.0, 0.0, 0.0, 0.0])
        result = await router.select_model(
            [
                HumanMessage(content='what is the weather'),
                HumanMessage(content='write python code'),
            ]
        )
        embeddings_mock.aembed_query.assert_called_once_with('write python code')
        assert result.model_id == 'code_model'

    async def test_not_initialized_returns_default(self, embeddings_mock):
        router = _build_router(embeddings_mock)
        result = await router.select_model([HumanMessage(content='hello')])
        assert result.model_id == 'default_model'

    async def test_initialize_computes_centroids(self, embeddings_mock):
        router = _build_router(embeddings_mock)
        await router.initialize()
        assert router._initialized is True
        assert len(router._centroids) == 2
        for model_id, centroid in router._centroids:
            assert model_id in ('code_model', 'general_model')
            norm = np.linalg.norm(centroid)
            assert abs(norm - 1.0) < 1e-6

    async def test_initialize_calls_aembed_for_each_entry(self, embeddings_mock):
        router = _build_router(embeddings_mock)
        await router.initialize()
        assert embeddings_mock.aembed_documents.call_count == 2
