import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from freezegun import freeze_time
from langchain_core.messages import HumanMessage, SystemMessage
from openai.types import CreateEmbeddingResponse
from openai.types.chat.chat_completion import ChatCompletion
import pook
import pytest

from tests.common.db_mock import API_KEY_UUID, GROUP_UUID, REQUEST_UUID
from tests.common.mocked_build_openai_chat_completion import (
    to_mock_openai_chat_completion,
)
from tests.common.mocked_gateway_config_openai import (
    get_gateway_embedded_cached,
    get_gateway_embedded_limiting,
    get_gateway_openai_cached,
    get_gateway_openai_with_guardrails,
)
from tests.common.resolve_route_models import resolve_route_models

from radicalbit_ai_gateway.ai_gateway import GatewayRoute, InvokeResponse
from radicalbit_ai_gateway.caching.gateway_cache import GatewayCache
from radicalbit_ai_gateway.caching.in_memory_cache import CacheToolsInMemory
from radicalbit_ai_gateway.caching.redis_cache import RedisCache
from radicalbit_ai_gateway.guardrails.guardrail_engine import GuardrailEngine
from radicalbit_ai_gateway.guardrails.judges.judge_engine import JudgeEngine
from radicalbit_ai_gateway.guardrails.presidio import PresidioEngine
from radicalbit_ai_gateway.limiting.token_limiter import InputTokenLimitExceeded
from radicalbit_ai_gateway.models.credentials import Credentials
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.models.model import Model
import radicalbit_ai_gateway.preprocessing as preprocessing_module
from radicalbit_ai_gateway.preprocessing import (
    PreprocessingPlugin,
    register_preprocessing_plugin,
)
from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils import config_hooks
from radicalbit_ai_gateway.utils.exceptions import (
    BudgetLimitExceededError,
    GatewayBadRequest,
)


@patch('radicalbit_ai_gateway.invocation.model_invoker.emit_event', autospec=True)
@pook.activate
@pytest.mark.asyncio
async def test_gateway_invocation(mock_model_invoker_emit_event, fake_redis_client):
    pook.enable_network()
    gateway_config = get_gateway_openai_with_guardrails()
    cost_service: CostService = MagicMock(spec_set=CostService)
    prompt_manager: PromptManager = MagicMock(spec_set=PromptManager)
    redis_cache = RedisCache(fake_redis_client)
    guardrail_engine = GuardrailEngine(
        presidio_engine=PresidioEngine(),
        judge_engine=JudgeEngine(prompt_manager=prompt_manager),
        cost_service=cost_service,
        guardrails=gateway_config.guardrails or [],
    )
    gateway_cache = GatewayCache(redis_cache)

    route_cfg, chat_models, embedding_models = resolve_route_models(
        gateway_config, 'rb-gateway'
    )

    ai_gateway = GatewayRoute(
        gateway_route_config=route_cfg,
        chat_models=chat_models,
        embedding_models=embedding_models,
        guardrail_engine=guardrail_engine,
        gateway_cache=gateway_cache,
        cost_service=cost_service,
    )

    mocked_response = to_mock_openai_chat_completion(content='Paris')

    pook.post(
        url='https://api.openai.com/v1/chat/completions',
        reply=200,
        response_json=mocked_response.model_dump_json(),
    )
    invoke_response = await ai_gateway.invoke(
        request_uuid=str(REQUEST_UUID),
        api_key_uuid=str(API_KEY_UUID),
        api_key_name='rb-key',
        messages=[HumanMessage(content='What is the capital of France?')],
        route_name='rb-gateway',
        tools=[],
        tool_choice=None,
        group_uuid=str(GROUP_UUID),
        group_name='test-group',
    )

    assert isinstance(invoke_response, InvokeResponse)
    response = invoke_response.content
    assert isinstance(response, ChatCompletion)
    assert response.choices[0].message.content == 'Paris'

    pook.disable_network()


@patch('radicalbit_ai_gateway.invocation.model_invoker.emit_event', autospec=True)
@pook.activate
@pytest.mark.asyncio
async def test_wrong_model_id(mock_model_invoker_emit_event, fake_redis_client):
    pook.enable_network()
    gateway_config = get_gateway_openai_with_guardrails()
    cost_service: CostService = MagicMock(spec_set=CostService)
    prompt_manager: PromptManager = MagicMock(spec_set=PromptManager)
    guardrail_engine = GuardrailEngine(
        presidio_engine=PresidioEngine(),
        judge_engine=JudgeEngine(prompt_manager=prompt_manager),
        cost_service=cost_service,
        guardrails=gateway_config.guardrails or [],
    )
    redis_cache = RedisCache(fake_redis_client)
    gateway_cache = GatewayCache(redis_cache)

    route_cfg, chat_models, embedding_models = resolve_route_models(
        gateway_config, 'rb-gateway'
    )

    ai_gateway = GatewayRoute(
        gateway_route_config=route_cfg,
        chat_models=chat_models,
        embedding_models=embedding_models,
        guardrail_engine=guardrail_engine,
        gateway_cache=gateway_cache,
        cost_service=cost_service,
    )
    mocked_response = to_mock_openai_chat_completion(content='Paris')

    pook.post(
        url='https://api.openai.com/v1/chat/completions',
        reply=200,
        response_json=mocked_response.model_dump_json(),
    )
    with pytest.raises(
        GatewayBadRequest,
        match=r'openai must be the route name',
    ):
        invoke_response = await ai_gateway.invoke(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            api_key_name='rb-key',
            messages=[HumanMessage(content='What is the capital of France?')],
            route_name='openai',
            tools=[],
            tool_choice=None,
            group_uuid=str(GROUP_UUID),
            group_name='test-group',
        )
        _ = invoke_response.content
    pook.disable_network()


@patch('radicalbit_ai_gateway.ai_gateway.emit_event', autospec=True)
@patch('radicalbit_ai_gateway.invocation.model_invoker.emit_event', autospec=True)
@pook.activate
@pytest.mark.asyncio
async def test_model_invocation_with_redis_cache(
    mock_emit_event,
    model_invoker_emit_event,
    fake_redis_client,
):
    pook.enable_network()
    gateway_config = get_gateway_openai_cached()
    cost_service: CostService = MagicMock(spec_set=CostService)
    prompt_manager: PromptManager = MagicMock(spec_set=PromptManager)
    guardrail_engine = GuardrailEngine(
        presidio_engine=PresidioEngine(),
        judge_engine=JudgeEngine(prompt_manager=prompt_manager),
        cost_service=cost_service,
        guardrails=gateway_config.guardrails or [],
    )
    redis_cache = RedisCache(fake_redis_client)
    gateway_cache = GatewayCache(redis_cache)

    route_cfg, chat_models, embedding_models = resolve_route_models(
        gateway_config, 'rb-gateway'
    )

    ai_gateway = GatewayRoute(
        gateway_route_config=route_cfg,
        chat_models=chat_models,
        embedding_models=embedding_models,
        guardrail_engine=guardrail_engine,
        gateway_cache=gateway_cache,
        cost_service=cost_service,
    )
    mocked_response_1 = to_mock_openai_chat_completion(content='Paris')
    mocked_response_2 = to_mock_openai_chat_completion(
        content='The capital of France is Paris'
    )

    pook.post(
        url='https://api.openai.com/v1/chat/completions',
        times=1,
        reply=200,
        response_json=mocked_response_1.model_dump_json(),
    )
    pook.post(
        url='https://api.openai.com/v1/chat/completions',
        times=1,
        reply=200,
        response_json=mocked_response_2.model_dump_json(),
    )

    initial_datetime = datetime.datetime(
        year=2025, month=7, day=30, hour=10, minute=0, second=0
    )
    with freeze_time(initial_datetime) as frozen_datetime:
        assert frozen_datetime() == initial_datetime

        messages = [HumanMessage(content='What is the capital of France?')]
        tools = []
        tool_choice = 'auto'
        kwargs = {}
        cache_key = gateway_cache.generate_cache_key(
            route_name='rb-gateway',
            key_uuid=str(API_KEY_UUID),
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            **kwargs,
        )
        assert await gateway_cache.get(cache_key) is None

        invoke_response = await ai_gateway.invoke(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            api_key_name='rb-key',
            messages=[HumanMessage(content='What is the capital of France?')],
            route_name='rb-gateway',
            tools=tools,
            tool_choice=tool_choice,
            group_uuid=str(GROUP_UUID),
            group_name='test-group',
            **kwargs,
        )
        assert await gateway_cache.get(cache_key) is not None

        assert isinstance(invoke_response, InvokeResponse)
        response = invoke_response.content
        assert isinstance(response, ChatCompletion)
        assert response.choices[0].message.content == 'Paris'
        assert response.created == 1753869600
        # Cache miss: headers should be empty
        assert invoke_response.headers == {}

        assert len(pook.pending_mocks()) == 1

        frozen_datetime.tick(60)

        invoke_response_cached = await ai_gateway.invoke(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            api_key_name='rb-key',
            group_name='test-group',
            messages=messages,
            route_name='rb-gateway',
            tools=tools,
            tool_choice=tool_choice,
            group_uuid=str(GROUP_UUID),
            **kwargs,
        )

        # This response is from cache
        assert await gateway_cache.get(cache_key) is not None

        assert isinstance(invoke_response_cached, InvokeResponse)
        response_cached = invoke_response_cached.content
        assert isinstance(response_cached, ChatCompletion)
        assert response_cached.choices[0].message.content == 'Paris'
        # Cache hit: headers should contain cache hit flag
        assert invoke_response_cached.headers == {'X-RB-AIGATEWAY-CACHE-HIT': 'true'}

        # Created time is updated
        assert response_cached.created == 1753869660

        assert len(pook.pending_mocks()) == 1

        frozen_datetime.tick(61)

        # Cache is expired
        assert await gateway_cache.get(cache_key) is None
        invoke_response_new = await ai_gateway.invoke(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            api_key_name='rb-key',
            messages=messages,
            route_name='rb-gateway',
            tools=tools,
            tool_choice=tool_choice,
            group_uuid=str(GROUP_UUID),
            group_name='test-group',
            **kwargs,
        )

        assert isinstance(invoke_response_new, InvokeResponse)
        new_response = invoke_response_new.content
        assert isinstance(new_response, ChatCompletion)
        assert (
            new_response.choices[0].message.content == 'The capital of France is Paris'
        )

        assert len(pook.pending_mocks()) == 0
    pook.disable_network()


@patch('radicalbit_ai_gateway.ai_gateway.emit_event', autospec=True)
@patch('radicalbit_ai_gateway.invocation.model_invoker.emit_event', autospec=True)
@pook.activate
@pytest.mark.asyncio
async def test_model_invocation_with_cachetools_cache(
    mock_emit_event,
    model_invoker_emit_event,
):
    pook.enable_network()
    gateway_config = get_gateway_openai_cached()
    cost_service = MagicMock(spec_set=CostService)
    prompt_manager: PromptManager = MagicMock(spec_set=PromptManager)
    guardrail_engine = GuardrailEngine(
        presidio_engine=PresidioEngine(),
        judge_engine=JudgeEngine(prompt_manager=prompt_manager),
        cost_service=cost_service,
        guardrails=gateway_config.guardrails or [],
    )
    in_memory_cache = CacheToolsInMemory()
    gateway_cache = GatewayCache(in_memory_cache)

    route_cfg, chat_models, embedding_models = resolve_route_models(
        gateway_config, 'rb-gateway'
    )

    ai_gateway = GatewayRoute(
        gateway_route_config=route_cfg,
        chat_models=chat_models,
        embedding_models=embedding_models,
        guardrail_engine=guardrail_engine,
        gateway_cache=gateway_cache,
        cost_service=cost_service,
    )
    mocked_response_1 = to_mock_openai_chat_completion(content='Paris')
    mocked_response_2 = to_mock_openai_chat_completion(
        content='The capital of France is Paris'
    )

    pook.post(
        url='https://api.openai.com/v1/chat/completions',
        times=1,
        reply=200,
        response_json=mocked_response_1.model_dump_json(),
    )
    pook.post(
        url='https://api.openai.com/v1/chat/completions',
        times=1,
        reply=200,
        response_json=mocked_response_2.model_dump_json(),
    )

    initial_datetime = datetime.datetime(
        year=2025, month=7, day=30, hour=10, minute=0, second=0
    )
    with freeze_time(initial_datetime) as frozen_datetime:
        assert frozen_datetime() == initial_datetime

        messages = [HumanMessage(content='What is the capital of France?')]

        tools = []
        tool_choice = 'auto'
        kwargs = {}
        cache_key = gateway_cache.generate_cache_key(
            route_name='rb-gateway',
            key_uuid=str(API_KEY_UUID),
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            **kwargs,
        )
        assert await gateway_cache.get(cache_key) is None

        invoke_response = await ai_gateway.invoke(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            api_key_name='rb-key',
            messages=[HumanMessage(content='What is the capital of France?')],
            route_name='rb-gateway',
            tools=tools,
            tool_choice=tool_choice,
            group_uuid=str(GROUP_UUID),
            group_name='test-group',
            **kwargs,
        )
        assert await gateway_cache.get(cache_key) is not None

        assert isinstance(invoke_response, InvokeResponse)
        response = invoke_response.content
        assert isinstance(response, ChatCompletion)
        assert response.choices[0].message.content == 'Paris'
        assert response.created == 1753869600

        assert len(pook.pending_mocks()) == 1

        frozen_datetime.tick(60)

        invoke_response_cached = await ai_gateway.invoke(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            api_key_name='rb-key',
            messages=[HumanMessage(content='What is the capital of France?')],
            route_name='rb-gateway',
            tools=tools,
            tool_choice=tool_choice,
            group_uuid=str(GROUP_UUID),
            group_name='test-group',
            **kwargs,
        )

        # This response is from cache
        assert await gateway_cache.get(cache_key) is not None

        assert isinstance(invoke_response_cached, InvokeResponse)
        response_cached = invoke_response_cached.content
        assert isinstance(response_cached, ChatCompletion)
        assert response_cached.choices[0].message.content == 'Paris'

        # Created time is updated
        assert response_cached.created == 1753869660

        assert len(pook.pending_mocks()) == 1

        frozen_datetime.tick(61)

        # Cache is expired
        assert await gateway_cache.get(cache_key) is None

        invoke_response_new = await ai_gateway.invoke(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            api_key_name='rb-key',
            messages=[HumanMessage(content='What is the capital of France?')],
            route_name='rb-gateway',
            tools=tools,
            tool_choice=tool_choice,
            group_uuid=str(GROUP_UUID),
            group_name='test-group',
            **kwargs,
        )

        assert isinstance(invoke_response_new, InvokeResponse)
        new_response = invoke_response_new.content
        assert isinstance(new_response, ChatCompletion)
        assert (
            new_response.choices[0].message.content == 'The capital of France is Paris'
        )

        assert len(pook.pending_mocks()) == 0
    pook.disable_network()


@patch('radicalbit_ai_gateway.invocation.model_invoker.emit_event', autospec=True)
@pook.activate
@pytest.mark.asyncio
async def test_invoke_embeddings_success(mock_emit_event):
    pook.enable_network()
    gateway_config = get_gateway_openai_with_guardrails()
    cost_service = MagicMock(spec_set=CostService)
    prompt_manager: PromptManager = MagicMock(spec_set=PromptManager)
    guardrail_engine = GuardrailEngine(
        presidio_engine=PresidioEngine(),
        judge_engine=JudgeEngine(prompt_manager=prompt_manager),
        cost_service=cost_service,
        guardrails=gateway_config.guardrails or [],
    )

    route_cfg, chat_models, embedding_models = resolve_route_models(
        gateway_config, 'rb-gateway'
    )

    ai_gateway = GatewayRoute(
        gateway_route_config=route_cfg,
        chat_models=chat_models,
        embedding_models=embedding_models,
        guardrail_engine=guardrail_engine,
        gateway_cache=None,
        cost_service=cost_service,
    )

    mocked_embedding_response = {
        'object': 'list',
        'data': [
            {
                'object': 'embedding',
                'embedding': [0.1, 0.2, 0.3],
                'index': 0,
            }
        ],
        'model': 'text-embedding-3-small',
        'usage': {'prompt_tokens': 2, 'total_tokens': 2},
    }

    pook.post(
        url='https://api.openai.com/v1/embeddings',
        reply=200,
        response_json=mocked_embedding_response,
    )

    response = await ai_gateway.invoke_embeddings(
        request_uuid=str(REQUEST_UUID),
        api_key_uuid=str(API_KEY_UUID),
        api_key_name='rb-key',
        route_name='rb-gateway',
        input_texts=['hello world'],
        group_uuid=str(GROUP_UUID),
        group_name='test-group',
    )

    assert isinstance(response, CreateEmbeddingResponse)
    assert response.data[0].embedding == [0.1, 0.2, 0.3]
    assert response.usage.total_tokens == 2
    assert response.model == 'text-embedding-3-small'

    pook.disable_network()


@patch('radicalbit_ai_gateway.invocation.model_invoker.emit_event', autospec=True)
@pook.activate
@pytest.mark.asyncio
async def test_invoke_embeddings_wrong_route(
    mock_emit_event,
):
    pook.enable_network()
    gateway_config = get_gateway_openai_with_guardrails()
    cost_service = MagicMock(spec_set=CostService)
    prompt_manager: PromptManager = MagicMock(spec_set=PromptManager)
    guardrail_engine = GuardrailEngine(
        presidio_engine=PresidioEngine(),
        judge_engine=JudgeEngine(prompt_manager=prompt_manager),
        cost_service=cost_service,
        guardrails=gateway_config.guardrails or [],
    )

    route_cfg, chat_models, embedding_models = resolve_route_models(
        gateway_config, 'rb-gateway'
    )

    ai_gateway = GatewayRoute(
        gateway_route_config=route_cfg,
        chat_models=chat_models,
        embedding_models=embedding_models,
        guardrail_engine=guardrail_engine,
        gateway_cache=None,
        cost_service=cost_service,
    )

    with pytest.raises(
        GatewayBadRequest,
        match=r'wrong-route must be the route name',
    ):
        await ai_gateway.invoke_embeddings(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            api_key_name='rb-key',
            route_name='wrong-route',
            input_texts=['hello'],
            group_uuid=str(GROUP_UUID),
            group_name='test-group',
        )

    pook.disable_network()


@patch('radicalbit_ai_gateway.invocation.model_invoker.emit_event', autospec=True)
@pook.activate
@pytest.mark.asyncio
async def test_invoke_embeddings_with_multiple_inputs(
    mock_model_invoker_emit_event,
):
    pook.enable_network()
    gateway_config = get_gateway_openai_with_guardrails()
    cost_service = MagicMock(spec_set=CostService)
    prompt_manager: PromptManager = MagicMock(spec_set=PromptManager)
    guardrail_engine = GuardrailEngine(
        presidio_engine=PresidioEngine(),
        judge_engine=JudgeEngine(prompt_manager=prompt_manager),
        cost_service=cost_service,
        guardrails=gateway_config.guardrails or [],
    )

    route_cfg, chat_models, embedding_models = resolve_route_models(
        gateway_config, 'rb-gateway'
    )

    ai_gateway = GatewayRoute(
        gateway_route_config=route_cfg,
        chat_models=chat_models,
        embedding_models=embedding_models,
        guardrail_engine=guardrail_engine,
        gateway_cache=None,
        cost_service=cost_service,
    )

    mocked_embedding_response = {
        'object': 'list',
        'data': [
            {'object': 'embedding', 'embedding': [0.1, 0.2], 'index': 0},
            {'object': 'embedding', 'embedding': [0.3, 0.4], 'index': 1},
        ],
        'model': 'text-embedding-3-small',
        'usage': {'prompt_tokens': 0, 'total_tokens': 0},
    }

    pook.post(
        url='https://api.openai.com/v1/embeddings',
        reply=200,
        response_json=mocked_embedding_response,
    )

    response = await ai_gateway.invoke_embeddings(
        request_uuid=str(REQUEST_UUID),
        api_key_uuid=str(API_KEY_UUID),
        api_key_name='rb-key',
        route_name='rb-gateway',
        input_texts=['hello', 'world'],
        group_uuid=str(GROUP_UUID),
        group_name='test-group',
    )

    assert isinstance(response, CreateEmbeddingResponse)
    assert len(response.data) == 2
    assert response.data[0].embedding == [0.1, 0.2]
    assert response.data[1].embedding == [0.3, 0.4]

    pook.disable_network()


@patch('radicalbit_ai_gateway.ai_gateway.emit_event', autospec=True)
@patch('radicalbit_ai_gateway.invocation.model_invoker.emit_event', autospec=True)
@pook.activate
@pytest.mark.asyncio
async def test_invoke_embeddings_with_cachetools_cache(
    mock_emit_event,
    mock_model_invoker_emit_event,
):
    pook.enable_network()
    gateway_config = get_gateway_embedded_cached()
    cost_service = MagicMock(spec_set=CostService)
    prompt_manager: PromptManager = MagicMock(spec_set=PromptManager)
    guardrail_engine = GuardrailEngine(
        presidio_engine=PresidioEngine(),
        judge_engine=JudgeEngine(prompt_manager=prompt_manager),
        cost_service=cost_service,
        guardrails=gateway_config.guardrails or [],
    )

    in_memory_cache = CacheToolsInMemory()
    gateway_cache = GatewayCache(in_memory_cache)

    route_cfg, chat_models, embedding_models = resolve_route_models(
        gateway_config, 'rb-gateway'
    )

    ai_gateway = GatewayRoute(
        gateway_route_config=route_cfg,
        chat_models=chat_models,
        embedding_models=embedding_models,
        guardrail_engine=guardrail_engine,
        gateway_cache=gateway_cache,
        cost_service=cost_service,
    )

    mocked_embedding_response = {
        'object': 'list',
        'data': [
            {
                'object': 'embedding',
                'embedding': [0.1, 0.2, 0.3],
                'index': 0,
            }
        ],
        'model': 'text-embedding-3-small',
        'usage': {'prompt_tokens': 2, 'total_tokens': 2},
    }

    pook.post(
        url='https://api.openai.com/v1/embeddings',
        times=1,
        reply=200,
        response_json=mocked_embedding_response,
    )

    input_texts = ['hello world']

    cache_key = gateway_cache.generate_embedding_cache_key(
        route_name='rb-gateway',
        key_uuid=str(API_KEY_UUID),
        input_texts=input_texts,
    )

    assert await gateway_cache.get(cache_key) is None

    response = await ai_gateway.invoke_embeddings(
        request_uuid=str(REQUEST_UUID),
        api_key_uuid=str(API_KEY_UUID),
        api_key_name='rb-key',
        route_name='rb-gateway',
        input_texts=input_texts,
        group_uuid=str(GROUP_UUID),
        group_name='test-group',
    )

    assert isinstance(response, CreateEmbeddingResponse)
    assert response.data[0].embedding == [0.1, 0.2, 0.3]
    assert await gateway_cache.get(cache_key) is not None

    response_cached = await ai_gateway.invoke_embeddings(
        request_uuid=str(REQUEST_UUID),
        api_key_uuid=str(API_KEY_UUID),
        api_key_name='rb-key',
        route_name='rb-gateway',
        input_texts=input_texts,
        group_uuid=str(GROUP_UUID),
        group_name='test-group',
    )

    assert isinstance(response_cached, CreateEmbeddingResponse)
    assert response_cached.data[0].embedding == [0.1, 0.2, 0.3]

    assert len(pook.pending_mocks()) == 0

    assert mock_emit_event.called

    pook.disable_network()


@patch('radicalbit_ai_gateway.limiting.token_limiter.emit_event', autospec=True)
@patch('radicalbit_ai_gateway.invocation.model_invoker.emit_event', autospec=True)
@pook.activate
@pytest.mark.asyncio
async def test_invoke_embeddings_token_limit_exceeded(
    mock_token_limiter_emit_event,
    mock_model_invoker_emit_event,
):
    pook.enable_network()
    gateway_config = get_gateway_embedded_limiting()
    cost_service = MagicMock(spec_set=CostService)
    prompt_manager: PromptManager = MagicMock(spec_set=PromptManager)
    guardrail_engine = GuardrailEngine(
        presidio_engine=PresidioEngine(),
        judge_engine=JudgeEngine(prompt_manager=prompt_manager),
        cost_service=cost_service,
        guardrails=gateway_config.guardrails or [],
    )

    route_cfg, chat_models, embedding_models = resolve_route_models(
        gateway_config, 'rb-gateway'
    )

    token_limiter = route_cfg.get_token_limiter()

    ai_gateway = GatewayRoute(
        gateway_route_config=route_cfg,
        chat_models=chat_models,
        embedding_models=embedding_models,
        guardrail_engine=guardrail_engine,
        gateway_cache=None,
        cost_service=cost_service,
        token_limiter=token_limiter,
    )

    long_text = 'hello world ' * 1000

    with pytest.raises(InputTokenLimitExceeded):
        await ai_gateway.invoke_embeddings(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            api_key_name='rb-key',
            route_name='rb-gateway',
            input_texts=[long_text],
            group_uuid=str(GROUP_UUID),
            group_name='test-group',
        )

    assert len(pook.pending_mocks()) == 0

    pook.disable_network()


@patch('radicalbit_ai_gateway.invocation.model_invoker.emit_event', autospec=True)
@pook.activate
@pytest.mark.asyncio
async def test_invoke_embeddings_budget_limit_exceeded(
    mock_model_invoker_emit_event,
):
    pook.enable_network()
    gateway_config = get_gateway_embedded_limiting()
    cost_service = MagicMock(spec_set=CostService)
    prompt_manager: PromptManager = MagicMock(spec_set=PromptManager)
    guardrail_engine = GuardrailEngine(
        presidio_engine=PresidioEngine(),
        judge_engine=JudgeEngine(prompt_manager=prompt_manager),
        cost_service=cost_service,
        guardrails=gateway_config.guardrails or [],
    )

    route_cfg, chat_models, embedding_models = resolve_route_models(
        gateway_config, 'rb-gateway'
    )
    budget_limiter = route_cfg.get_budget_limiter()
    ai_gateway = GatewayRoute(
        gateway_route_config=route_cfg,
        chat_models=chat_models,
        embedding_models=embedding_models,
        guardrail_engine=guardrail_engine,
        gateway_cache=None,
        cost_service=cost_service,
        budget_limiter=budget_limiter,
    )

    budget_limiter.check_budget = AsyncMock(
        side_effect=BudgetLimitExceededError('Budget limit excedeed')
    )

    with pytest.raises(BudgetLimitExceededError):
        await ai_gateway.invoke_embeddings(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            api_key_name='rb-key',
            route_name='rb-gateway',
            input_texts=['hello world'],
            group_uuid=str(GROUP_UUID),
            group_name='test-group',
        )

    assert len(pook.pending_mocks()) == 0

    pook.disable_network()


@patch('radicalbit_ai_gateway.ai_gateway.emit_event', autospec=True)
@patch('radicalbit_ai_gateway.invocation.model_invoker.emit_event', autospec=True)
@pook.activate
@pytest.mark.asyncio
async def test_cache_hit_flag_set_on_request_state(
    mock_emit_event,
    model_invoker_emit_event,
):
    """Test that cache_hit flag is set on request.state when cache hit occurs"""
    pook.enable_network()
    gateway_config = get_gateway_openai_cached()
    cost_service = MagicMock(spec_set=CostService)
    prompt_manager: PromptManager = MagicMock(spec_set=PromptManager)
    guardrail_engine = GuardrailEngine(
        presidio_engine=PresidioEngine(),
        judge_engine=JudgeEngine(prompt_manager=prompt_manager),
        cost_service=cost_service,
        guardrails=gateway_config.guardrails or [],
    )
    in_memory_cache = CacheToolsInMemory()
    gateway_cache = GatewayCache(in_memory_cache)

    route_cfg, chat_models, embedding_models = resolve_route_models(
        gateway_config, 'rb-gateway'
    )

    ai_gateway = GatewayRoute(
        gateway_route_config=route_cfg,
        chat_models=chat_models,
        embedding_models=embedding_models,
        guardrail_engine=guardrail_engine,
        gateway_cache=gateway_cache,
        cost_service=cost_service,
    )
    mocked_response = to_mock_openai_chat_completion(content='Paris')

    pook.post(
        url='https://api.openai.com/v1/chat/completions',
        times=1,
        reply=200,
        response_json=mocked_response.model_dump_json(),
    )

    initial_datetime = datetime.datetime(
        year=2025, month=7, day=30, hour=10, minute=0, second=0
    )
    with freeze_time(initial_datetime):
        messages = [HumanMessage(content='What is the capital of France?')]
        tools = []
        tool_choice = 'auto'
        kwargs = {}

        # First invocation - should populate cache
        invoke_response = await ai_gateway.invoke(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            api_key_name='rb-key',
            group_uuid=str(GROUP_UUID),
            messages=messages,
            route_name='rb-gateway',
            tools=tools,
            tool_choice=tool_choice,
            group_name='test-group',
            **kwargs,
        )
        assert isinstance(invoke_response, InvokeResponse)
        response = invoke_response.content
        assert isinstance(response, ChatCompletion)
        # Cache miss: headers should be empty
        assert invoke_response.headers == {}

        # Second invocation - should hit cache and return header
        invoke_response_cached = await ai_gateway.invoke(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            api_key_name='rb-key',
            messages=messages,
            route_name='rb-gateway',
            tools=tools,
            tool_choice=tool_choice,
            group_uuid=str(GROUP_UUID),
            group_name='test-group',
            **kwargs,
        )

        # Verify response is from cache
        assert isinstance(invoke_response_cached, InvokeResponse)
        response_cached = invoke_response_cached.content
        assert isinstance(response_cached, ChatCompletion)
        assert response_cached.choices[0].message.content == 'Paris'

        # Verify cache hit header is present
        assert invoke_response_cached.headers == {'X-RB-AIGATEWAY-CACHE-HIT': 'true'}

        # Verify only one HTTP request was made (first call consumed the mock)
        # Second call used cache, so no more pending mocks
        assert len(pook.pending_mocks()) == 0

    pook.disable_network()


@pytest.mark.asyncio
async def test_preprocessing_runs_before_prompt_injection():
    """Preprocessing sees only the client messages, and the route's configured
    system prompt is injected afterwards (so plugins can never modify it).
    """
    seen = []

    class Spy(PreprocessingPlugin):
        async def preprocess(self, messages, config):
            # Snapshot exactly what the plugin receives, then transform client text.
            seen.extend((type(m).__name__, m.content) for m in messages)
            for m in messages:
                if isinstance(m.content, str):
                    m.content = m.content.upper()
            return messages

    chat_model = Model(
        model_id='m',
        model='openai/gpt-4o',
        credentials=Credentials(api_key='sk-123'),
        prompt='You are a helpful assistant.',
    )
    route_cfg = GatewayRouteConfig(
        route_name='r',
        chat_models=['m'],
        extension={'spy': {'enabled': True}},
    )
    ai_gateway = GatewayRoute(
        gateway_route_config=route_cfg,
        chat_models=[chat_model],
        embedding_models=None,
        guardrail_engine=MagicMock(spec_set=GuardrailEngine),
        cost_service=MagicMock(spec_set=CostService),
        gateway_cache=None,
    )

    try:
        register_preprocessing_plugin(Spy(), name='spy')
        result = await ai_gateway._prepare_and_validate_request(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            group_uuid=str(GROUP_UUID),
            api_key_name='rb-key',
            group_name='test-group',
            route_name='r',
            messages=[HumanMessage(content='hello')],
            tools=[],
            tool_choice=None,
        )
    finally:
        preprocessing_module._registered.clear()
        config_hooks._extension_validators.clear()

    # The plugin only ever saw the client message — no injected system prompt.
    assert seen == [('HumanMessage', 'hello')]

    # The final messages start with the untouched system prompt, followed by the
    # client message the plugin transformed.
    messages = result.redacted_messages
    assert isinstance(messages[0], SystemMessage)
    assert messages[0].content == 'You are a helpful assistant.'
    assert messages[1].content == 'HELLO'


@pytest.mark.asyncio
async def test_preprocessing_includes_client_sent_system_prompt():
    """A system message the *client* sends is part of the incoming messages, so
    preprocessing sees and may transform it; only the *route-configured* prompt
    (injected afterwards) is shielded from plugins.
    """
    seen = []

    class Spy(PreprocessingPlugin):
        async def preprocess(self, messages, config):
            seen.extend((type(m).__name__, m.content) for m in messages)
            for m in messages:
                if isinstance(m.content, str):
                    m.content = m.content.upper()
            return messages

    chat_model = Model(
        model_id='m',
        model='openai/gpt-4o',
        credentials=Credentials(api_key='sk-123'),
        prompt='Route prompt.',
    )
    route_cfg = GatewayRouteConfig(
        route_name='r',
        chat_models=['m'],
        extension={'spy': {'enabled': True}},
    )
    ai_gateway = GatewayRoute(
        gateway_route_config=route_cfg,
        chat_models=[chat_model],
        embedding_models=None,
        guardrail_engine=MagicMock(spec_set=GuardrailEngine),
        cost_service=MagicMock(spec_set=CostService),
        gateway_cache=None,
    )

    try:
        register_preprocessing_plugin(Spy(), name='spy')
        result = await ai_gateway._prepare_and_validate_request(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            group_uuid=str(GROUP_UUID),
            api_key_name='rb-key',
            group_name='test-group',
            route_name='r',
            messages=[
                SystemMessage(content='client system'),
                HumanMessage(content='hello'),
            ],
            tools=[],
            tool_choice=None,
        )
    finally:
        preprocessing_module._registered.clear()
        config_hooks._extension_validators.clear()

    # The plugin saw the client's own system message (and the human message);
    # the route-configured prompt was NOT yet present.
    assert seen == [
        ('SystemMessage', 'client system'),
        ('HumanMessage', 'hello'),
    ]

    # Final order: route prompt prepended (untouched), then the client's
    # system + human messages, both transformed by the plugin.
    messages = result.redacted_messages
    assert [(type(m).__name__, m.content) for m in messages] == [
        ('SystemMessage', 'Route prompt.'),
        ('SystemMessage', 'CLIENT SYSTEM'),
        ('HumanMessage', 'HELLO'),
    ]
