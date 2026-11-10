import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from freezegun import freeze_time
from openai.types.create_embedding_response import CreateEmbeddingResponse, Usage
from openai.types.embedding import Embedding
import pytest

from tests.common.cache_keys import chat_key
from tests.common.db_mock import GROUP_UUID
from tests.common.limits import request_limits
from tests.common.mocked_build_openai_chat_completion import (
    to_mock_openai_chat_completion,
)
from tests.common.pipeline import invoke
from tests.common.resolve_route_models import resolve_route_models

from radicalbit_ai_gateway.caching.gateway_cache import GatewayCache
from radicalbit_ai_gateway.caching.in_memory_cache import CacheToolsInMemory
from radicalbit_ai_gateway.caching.route_cache import RouteCache
from radicalbit_ai_gateway.gateway_route.route import GatewayRoute
from radicalbit_ai_gateway.guardrails.guardrails import Guardrails
from radicalbit_ai_gateway.guardrails.judges.judge_engine import JudgeEngine
from radicalbit_ai_gateway.guardrails.presidio import PresidioEngine
from radicalbit_ai_gateway.llm.messages import AIMessage, HumanMessage, SystemMessage
from radicalbit_ai_gateway.models.caching import CacheConfig, CacheType, SemanticCaching
from radicalbit_ai_gateway.models.credentials import Credentials
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.services.cost_service import CostService


class FakeSemanticGatewayCache(GatewayCache):
    @property
    def cache_type(self) -> CacheType:
        return CacheType.SEMANTIC

    # Avoid touching real client storage in this semantic unit test
    async def get(self, cache_key: str, **kwargs) -> str | None:
        return None

    async def set(self, cache_key: str, response: str, ttl: int | None, **kwargs):
        return None


@patch('radicalbit_ai_gateway.invocation.chat_model_invoker.ChatModelInvoker.complete')
@patch(
    'radicalbit_ai_gateway.endpoints.chat_like.model_selection.emit_event',
    autospec=True,
)
@patch('radicalbit_ai_gateway.invocation.recorder.emit_event', autospec=True)
@pytest.mark.asyncio
async def test_exact_cache_hit_with_different_history(
    mock_model_invoker_emit_event, mock_emit_event, mock_complete, test_data_dir_fixture
):
    cost_service: CostService = MagicMock(spec_set=CostService)
    prompt_manager: PromptManager = MagicMock(spec_set=PromptManager)
    chat_registry = [
        Model(
            model_id='openai-o4-mini',
            model='openai/gpt-4o-mini',
            credentials=Credentials(api_key='sk-test'),
        )
    ]
    embedding_registry = [
        Model(
            model_id='text-embedding-3-small',
            model='openai/text-embedding-3-small',
            credentials=Credentials(api_key='sk-test'),
        )
    ]

    route_config = GatewayRouteConfig(
        route_name='rb-gateway',
        chat_models=['openai-o4-mini'],
        embedding_models=['text-embedding-3-small'],
    )

    gateway_config = GatewayConfig(
        chat_models=chat_registry,
        embedding_models=embedding_registry,
        routes={'rb-gateway': route_config},
        guardrails=[],
        cache=CacheConfig(redis_host='localhost', redis_port=6379),
    )

    resolved_route_cfg, chat_models, embedding_models = resolve_route_models(
        gateway_config, 'rb-gateway'
    )

    mock_complete.return_value = to_mock_openai_chat_completion(content='Paris')
    project_guardrails = Guardrails(
        presidio_engine=PresidioEngine(),
        judge_engine=JudgeEngine(prompt_manager=prompt_manager),
        cost_service=cost_service,
    )
    in_memory_cache = CacheToolsInMemory()
    gateway_cache = GatewayCache(in_memory_cache)
    ai_gateway = GatewayRoute(
        gateway_route_config=resolved_route_cfg,
        chat_models=chat_models,
        embedding_models=embedding_models,
        guardrails=project_guardrails.for_route(resolved_route_cfg),
        gateway_cache=gateway_cache,
        cost_service=cost_service,
    )

    initial_datetime = datetime.datetime(
        year=2025, month=7, day=30, hour=10, minute=0, second=0
    )
    with freeze_time(initial_datetime):
        # History A + same last user question
        messages_a = [
            SystemMessage(content='You are helpful.'),
            HumanMessage(content='Hi'),
            AIMessage(content='Hello!'),
            HumanMessage(content='What is the capital of France?'),
        ]
        # History B different, but same last user question
        messages_b = [
            SystemMessage(content='Assist the user.'),
            HumanMessage(content='Hello there'),
            AIMessage(content='Hi!'),
            HumanMessage(content='What is the capital of France?'),
        ]

        # First invocation => populate cache
        await invoke(
            ai_gateway,
            limits=request_limits(ai_gateway),
            request_uuid='req-1',
            api_key_uuid='key-1',
            api_key_name='rb-key',
            group_name='test-group',
            messages=messages_a,
            route_name='rb-gateway',
            tools=[],
            tool_choice='auto',
            group_uuid=str(GROUP_UUID),
        )

        # Second invocation with different history, same last user => should be a cache hit
        invoke_response_cached = await invoke(
            ai_gateway,
            limits=request_limits(ai_gateway),
            request_uuid='req-2',
            api_key_uuid='key-1',
            api_key_name='rb-key',
            messages=messages_b,
            route_name='rb-gateway',
            tools=[],
            tool_choice='auto',
            group_uuid=str(GROUP_UUID),
            group_name='test-group',
        )
        assert invoke_response_cached.headers == {'X-RB-AIGATEWAY-CACHE-HIT': 'true'}
        # Ensure the model was called only once (second call served from cache)
        assert mock_complete.call_count == 1


@pytest.mark.asyncio
async def test_semantic_cache_uses_only_last_user_for_key_and_embedding(
    test_data_dir_fixture,
):
    # Build a route with semantic caching without YAML/!secret
    chat_registry = [
        Model(
            model_id='openai-o4-mini',
            model='openai/gpt-4o-mini',
            credentials=Credentials(api_key='sk-test'),
        )
    ]
    embedding_registry = [
        Model(
            model_id='text-embedding-3-small',
            model='openai/text-embedding-3-small',
            credentials=Credentials(api_key='sk-test'),
        )
    ]

    route_config = GatewayRouteConfig(
        route_name='rb-gateway',
        chat_models=['openai-o4-mini'],
        embedding_models=['text-embedding-3-small'],
        caching=SemanticCaching(
            enabled=True,
            type='semantic',
            ttl=120,
            embedding_model_id='text-embedding-3-small',
            similarity_threshold=0.7,
            distance_metric='cosine',
            dim=1536,
        ),
    )
    cost_service: CostService = MagicMock(spec_set=CostService)
    prompt_manager: PromptManager = MagicMock(spec_set=PromptManager)
    project_guardrails = Guardrails(
        presidio_engine=PresidioEngine(),
        judge_engine=JudgeEngine(prompt_manager=prompt_manager),
        cost_service=cost_service,
    )

    gateway_config = GatewayConfig(
        chat_models=chat_registry,
        embedding_models=embedding_registry,
        routes={'rb-gateway': route_config},
        guardrails=[],
        cache=CacheConfig(redis_host='localhost', redis_port=6379),
    )

    resolved_route_cfg, chat_models, embedding_models = resolve_route_models(
        gateway_config, 'rb-gateway'
    )

    ai_gateway = GatewayRoute(
        gateway_route_config=resolved_route_cfg,
        chat_models=chat_models,
        embedding_models=embedding_models,
        guardrails=project_guardrails.for_route(resolved_route_cfg),
        gateway_cache=None,
        cost_service=cost_service,
    )
    # An in-memory client, read as a semantic cache through the subclass.
    backend = FakeSemanticGatewayCache(cache_client=CacheToolsInMemory())
    backend.set = AsyncMock()
    embedder = MagicMock()
    embedder.embed_answered = AsyncMock(
        return_value=(
            CreateEmbeddingResponse(
                object='list',
                data=[Embedding(index=0, embedding=[0.1, 0.2], object='embedding')],
                model='text-embedding-3-small',
                usage=Usage(prompt_tokens=4, total_tokens=4),
            ),
            embedding_models[0],
        )
    )
    ai_gateway.cache = RouteCache(
        backend=backend,
        cost_service=cost_service,
        embedder=embedder,
        embedding_model=embedding_models[0],
    )

    messages = [
        SystemMessage(content='Sys'),
        HumanMessage(content='Earlier question'),
        AIMessage(content='Earlier answer'),
        HumanMessage(content='Final question to cache'),
    ]
    with patch(
        'radicalbit_ai_gateway.invocation.chat_model_invoker.ChatModelInvoker.complete',
        AsyncMock(return_value=to_mock_openai_chat_completion(content='Paris')),
    ):
        await invoke(
            ai_gateway,
            limits=request_limits(ai_gateway),
            request_uuid='req-1',
            api_key_uuid='key-1',
            api_key_name='rb-key',
            group_name='test-group',
            route_name='rb-gateway',
            messages=messages,
            tools=[],
            tool_choice='auto',
            group_uuid=str(GROUP_UUID),
        )

    # Only the last human message keys the entry and is embedded.
    assert embedder.embed_answered.call_args.kwargs['input_texts'] == [
        'Final question to cache'
    ]
    assert backend.set.call_args.args[0] == chat_key(
        '',
        'rb-gateway',
        'key-1',
        [HumanMessage(content='Final question to cache')],
        [],
        'auto',
    )
