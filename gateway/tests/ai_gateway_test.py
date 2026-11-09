import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch

from freezegun import freeze_time
from openai.types import CreateEmbeddingResponse
from openai.types.audio.transcription import Transcription
from openai.types.audio.transcription_verbose import TranscriptionVerbose
from openai.types.chat.chat_completion import ChatCompletion
import pook
import pytest

from tests.common.cache_keys import chat_key, embedding_key
from tests.common.db_mock import (
    API_KEY_UUID,
    GROUP_UUID,
    REQUEST_UUID,
    TEST_PROJECT_UUID,
)
from tests.common.limits import credential_limit, project_limit, request_limits
from tests.common.mocked_build_openai_chat_completion import (
    to_mock_openai_chat_completion,
)
from tests.common.mocked_gateway_config_openai import (
    get_gateway_embedded_cached,
    get_gateway_embedded_limiting,
    get_gateway_openai_cached,
    get_gateway_openai_with_guardrails,
)
from tests.common.pipeline import (
    InvokeResponse,
    invoke,
    invoke_embeddings,
    invoke_transcription,
    invoke_transcription_stream,
)
from tests.common.request_identity import with_identity
from tests.common.resolve_route_models import resolve_route_models

from radicalbit_ai_gateway.ai_gateway import GatewayRoute
from radicalbit_ai_gateway.caching.gateway_cache import GatewayCache
from radicalbit_ai_gateway.caching.in_memory_cache import CacheToolsInMemory
from radicalbit_ai_gateway.caching.redis_cache import RedisCache
from radicalbit_ai_gateway.guardrails.guardrails import Guardrails
from radicalbit_ai_gateway.guardrails.judges.judge_engine import JudgeEngine
from radicalbit_ai_gateway.guardrails.presidio import PresidioEngine
from radicalbit_ai_gateway.limiting.limits import (
    Demand,
    RequestLimits,
    RouteLimits,
    Usage,
)
from radicalbit_ai_gateway.llm.messages import HumanMessage, SystemMessage
from radicalbit_ai_gateway.models.credentials import Credentials
from radicalbit_ai_gateway.models.fallback import Fallback, FallbackModelType
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.models.limiting import AudioDurationLimiting, BudgetLimiting
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
    AudioDurationLimitExceeded,
    BudgetLimitExceededError,
    GatewayBadRequest,
    InputTokenLimitExceeded,
)


@patch('radicalbit_ai_gateway.invocation.recorder.emit_event', autospec=True)
@pook.activate
@pytest.mark.asyncio
async def test_gateway_invocation(mock_model_invoker_emit_event, fake_redis_client):
    pook.enable_network()
    gateway_config = get_gateway_openai_with_guardrails()
    cost_service: CostService = MagicMock(spec_set=CostService)
    prompt_manager: PromptManager = MagicMock(spec_set=PromptManager)
    redis_cache = RedisCache(fake_redis_client)
    project_guardrails = Guardrails(
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
        guardrails=project_guardrails.for_route(route_cfg),
        gateway_cache=gateway_cache,
        cost_service=cost_service,
        project_uuid=str(TEST_PROJECT_UUID),
    )

    mocked_response = to_mock_openai_chat_completion(content='Paris')

    pook.post(
        url='https://api.openai.com/v1/chat/completions',
        reply=200,
        response_json=mocked_response.model_dump_json(),
    )
    invoke_response = await invoke(
        ai_gateway,
        limits=request_limits(ai_gateway),
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


@patch('radicalbit_ai_gateway.pipeline.conversation.emit_event', autospec=True)
@patch('radicalbit_ai_gateway.invocation.recorder.emit_event', autospec=True)
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
    project_guardrails = Guardrails(
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
        guardrails=project_guardrails.for_route(route_cfg),
        gateway_cache=gateway_cache,
        cost_service=cost_service,
        project_uuid=str(TEST_PROJECT_UUID),
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
        cache_key = chat_key(
            project_uuid=str(TEST_PROJECT_UUID),
            route_name='rb-gateway',
            key_uuid=str(API_KEY_UUID),
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            **kwargs,
        )
        assert await gateway_cache.get(cache_key) is None

        invoke_response = await invoke(
            ai_gateway,
            limits=request_limits(ai_gateway),
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

        invoke_response_cached = await invoke(
            ai_gateway,
            limits=request_limits(ai_gateway),
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
        invoke_response_new = await invoke(
            ai_gateway,
            limits=request_limits(ai_gateway),
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


@patch('radicalbit_ai_gateway.pipeline.conversation.emit_event', autospec=True)
@patch('radicalbit_ai_gateway.invocation.recorder.emit_event', autospec=True)
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
    project_guardrails = Guardrails(
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
        guardrails=project_guardrails.for_route(route_cfg),
        gateway_cache=gateway_cache,
        cost_service=cost_service,
        project_uuid=str(TEST_PROJECT_UUID),
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
        cache_key = chat_key(
            project_uuid=str(TEST_PROJECT_UUID),
            route_name='rb-gateway',
            key_uuid=str(API_KEY_UUID),
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            **kwargs,
        )
        assert await gateway_cache.get(cache_key) is None

        invoke_response = await invoke(
            ai_gateway,
            limits=request_limits(ai_gateway),
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

        invoke_response_cached = await invoke(
            ai_gateway,
            limits=request_limits(ai_gateway),
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

        invoke_response_new = await invoke(
            ai_gateway,
            limits=request_limits(ai_gateway),
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


@patch('radicalbit_ai_gateway.invocation.recorder.emit_event', autospec=True)
@pook.activate
@pytest.mark.asyncio
async def test_invoke_embeddings_success(mock_emit_event):
    pook.enable_network()
    gateway_config = get_gateway_openai_with_guardrails()
    cost_service = MagicMock(spec_set=CostService)
    prompt_manager: PromptManager = MagicMock(spec_set=PromptManager)
    project_guardrails = Guardrails(
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
        guardrails=project_guardrails.for_route(route_cfg),
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

    response = await invoke_embeddings(
        ai_gateway,
        limits=request_limits(ai_gateway),
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


@patch('radicalbit_ai_gateway.invocation.recorder.emit_event', autospec=True)
@pook.activate
@pytest.mark.asyncio
async def test_invoke_embeddings_with_multiple_inputs(
    mock_model_invoker_emit_event,
):
    pook.enable_network()
    gateway_config = get_gateway_openai_with_guardrails()
    cost_service = MagicMock(spec_set=CostService)
    prompt_manager: PromptManager = MagicMock(spec_set=PromptManager)
    project_guardrails = Guardrails(
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
        guardrails=project_guardrails.for_route(route_cfg),
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

    response = await invoke_embeddings(
        ai_gateway,
        limits=request_limits(ai_gateway),
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


@patch('radicalbit_ai_gateway.pipeline.conversation.emit_event', autospec=True)
@patch('radicalbit_ai_gateway.invocation.recorder.emit_event', autospec=True)
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
    project_guardrails = Guardrails(
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
        guardrails=project_guardrails.for_route(route_cfg),
        gateway_cache=gateway_cache,
        cost_service=cost_service,
        project_uuid=str(TEST_PROJECT_UUID),
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

    cache_key = embedding_key(
        project_uuid=str(TEST_PROJECT_UUID),
        route_name='rb-gateway',
        key_uuid=str(API_KEY_UUID),
        input_texts=input_texts,
    )

    assert await gateway_cache.get(cache_key) is None

    response = await invoke_embeddings(
        ai_gateway,
        limits=request_limits(ai_gateway),
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

    response_cached = await invoke_embeddings(
        ai_gateway,
        limits=request_limits(ai_gateway),
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


@patch('radicalbit_ai_gateway.limiting.limits.emit_event', autospec=True)
@patch('radicalbit_ai_gateway.invocation.recorder.emit_event', autospec=True)
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
    project_guardrails = Guardrails(
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
        guardrails=project_guardrails.for_route(route_cfg),
        gateway_cache=None,
        cost_service=cost_service,
        route_limits=RouteLimits.from_config(route_cfg, str(TEST_PROJECT_UUID)),
    )

    long_text = 'hello world ' * 1000

    with pytest.raises(InputTokenLimitExceeded):
        await invoke_embeddings(
            ai_gateway,
            limits=request_limits(ai_gateway),
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


SPENT = 0  # A budget of 0 blocks every request.


@pytest.mark.parametrize(
    ('route', 'credential', 'project', 'reported'),
    [
        (SPENT, None, None, '[BUDGET LIMIT]'),
        # The credential's, then the project's, before the route's.
        (SPENT, SPENT, None, '[CREDENTIAL BUDGET LIMIT]'),
        (SPENT, None, SPENT, '[PROJECT BUDGET LIMIT]'),
        (None, SPENT, SPENT, '[CREDENTIAL BUDGET LIMIT]'),
        # A project budget blocks with no other limit configured.
        (None, None, SPENT, '[PROJECT BUDGET LIMIT]'),
    ],
)
@pytest.mark.asyncio
async def test_embedding_budget_limits(route, credential, project, reported):
    gateway_config = get_gateway_embedded_limiting()
    cost_service = MagicMock(spec_set=CostService)
    route_cfg, chat_models, embedding_models = resolve_route_models(
        gateway_config, 'rb-gateway'
    )
    route_cfg = route_cfg.model_copy(
        update={
            'token_limiting': None,
            'budget_limiting': None
            if route is None
            else BudgetLimiting(max_budget=route, window_size='1 minute'),
        }
    )
    ai_gateway = GatewayRoute(
        gateway_route_config=route_cfg,
        chat_models=chat_models,
        embedding_models=embedding_models,
        gateway_cache=None,
        cost_service=cost_service,
        route_limits=RouteLimits.from_config(route_cfg, str(TEST_PROJECT_UUID)),
        project_uuid=str(TEST_PROJECT_UUID),
    )
    limits = request_limits(
        ai_gateway,
        [] if credential is None else [credential_limit('budget', credential)],
        [] if project is None else [project_limit(project)],
    )
    ai_gateway.embedding_invoker.embed = AsyncMock()

    with (
        patch('radicalbit_ai_gateway.limiting.limits.emit_event'),
        pytest.raises(BudgetLimitExceededError) as error,
    ):
        await invoke_embeddings(
            ai_gateway,
            limits=limits,
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            api_key_name='rb-key',
            route_name='rb-gateway',
            input_texts=['hello world'],
            group_uuid=str(GROUP_UUID),
            group_name='test-group',
        )

    assert error.value.log_message.startswith(reported)
    ai_gateway.embedding_invoker.embed.assert_not_awaited()


@patch('radicalbit_ai_gateway.invocation.recorder.emit_event', autospec=True)
@pook.activate
@pytest.mark.asyncio
async def test_project_budget_limit_blocks_chat_with_no_other_limiters_configured(
    mock_model_invoker_emit_event, fake_redis_client
):
    """Regression: the limits were once checked only when a route or
    credential limit was configured — a project-only budget limit must still
    be checked.
    """
    pook.enable_network()
    gateway_config = get_gateway_openai_with_guardrails()
    cost_service: CostService = MagicMock(spec_set=CostService)
    prompt_manager: PromptManager = MagicMock(spec_set=PromptManager)
    redis_cache = RedisCache(fake_redis_client)
    project_guardrails = Guardrails(
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
        guardrails=project_guardrails.for_route(route_cfg),
        gateway_cache=gateway_cache,
        cost_service=cost_service,
        project_uuid=str(TEST_PROJECT_UUID),
    )
    assert ai_gateway.route_limits == RouteLimits()

    with (
        patch('radicalbit_ai_gateway.limiting.limits.emit_event') as emit_event,
        pytest.raises(BudgetLimitExceededError, match='PROJECT BUDGET LIMIT'),
    ):
        await invoke(
            ai_gateway,
            limits=request_limits(ai_gateway, project_limits=[project_limit(0)]),
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

    # The block event names the caller and the route actually called.
    [event] = [call.args[0] for call in emit_event.call_args_list]
    assert (event.request_uuid, event.api_key_uuid, event.route_name) == (
        str(REQUEST_UUID),
        str(API_KEY_UUID),
        'rb-gateway',
    )
    assert len(pook.pending_mocks()) == 0

    pook.disable_network()


def _spied_limits() -> RequestLimits:
    """Return request limits that record what they are asked and let all pass."""
    return create_autospec(RequestLimits, instance=True)


def _make_transcription_route_config(
    model_id: str = 'whisper-1', **budget_kwargs
) -> GatewayRouteConfig:
    budget_limiting = BudgetLimiting(**budget_kwargs) if budget_kwargs else None
    return GatewayRouteConfig(
        route_name='rb-gateway',
        chat_models=[],
        transcription_models=[model_id],
        budget_limiting=budget_limiting,
    )


def test_transcription_invoker_only_receives_transcription_fallbacks():
    """`GatewayRoute` must filter the route's `fallback` list down to
    `FallbackModelType.TRANSCRIPTION` entries before wiring it into
    `TranscriptionModelInvoker` — CHAT/EMBEDDING fallbacks aren't meaningful
    there and would otherwise leak in unfiltered.
    """
    cost_service = MagicMock(spec_set=CostService)
    gpt4o_model = Model(
        model_id='gpt4o-transcribe',
        model='openai/gpt-4o-transcribe',
        credentials=Credentials(api_key='sk-test'),
    )
    gpt4o_mini_model = Model(
        model_id='gpt4o-mini-transcribe',
        model='openai/gpt-4o-mini-transcribe',
        credentials=Credentials(api_key='sk-test'),
    )
    transcription_fallback = Fallback(
        type=FallbackModelType.TRANSCRIPTION,
        target='gpt4o-transcribe',
        fallbacks=['gpt4o-mini-transcribe'],
    )
    chat_fallback = Fallback(
        type=FallbackModelType.CHAT, target='some-chat-model', fallbacks=['other']
    )
    route_cfg = GatewayRouteConfig(
        route_name='rb-gateway',
        chat_models=[],
        transcription_models=['gpt4o-transcribe', 'gpt4o-mini-transcribe'],
        fallback=[transcription_fallback, chat_fallback],
    )

    ai_gateway = GatewayRoute(
        gateway_route_config=route_cfg,
        chat_models=[],
        embedding_models=None,
        transcription_models=[gpt4o_model, gpt4o_mini_model],
        gateway_cache=None,
        cost_service=cost_service,
    )

    assert ai_gateway.transcription_invoker.fallbacks == [transcription_fallback]
    fallback_model_ids = {
        m.model_id
        for m, _ in ai_gateway.transcription_invoker.model_map['gpt4o-transcribe'][2]
    }
    assert fallback_model_ids == {'gpt4o-mini-transcribe'}


@pytest.mark.asyncio
async def test_invoke_transcription_checks_its_cost_and_audio_seconds():
    cost_service = MagicMock(spec_set=CostService)
    whisper_model = Model(
        model_id='whisper-1',
        model='openai/whisper-1',
        credentials=Credentials(api_key='sk-test'),
    )
    route_cfg = GatewayRouteConfig(
        route_name='rb-gateway',
        chat_models=[],
        transcription_models=['whisper-1'],
        duration_limiting=AudioDurationLimiting(
            max_duration_seconds=300, window_size='1 minute'
        ),
    )
    limits = _spied_limits()

    ai_gateway = GatewayRoute(
        gateway_route_config=route_cfg,
        chat_models=[],
        embedding_models=None,
        transcription_models=[whisper_model],
        gateway_cache=None,
        cost_service=cost_service,
    )

    fake_result = MagicMock(usage=MagicMock(type='duration', seconds=3))
    ai_gateway.transcription_invoker.transcribe = AsyncMock(return_value=fake_result)

    await invoke_transcription(
        ai_gateway,
        limits=limits,
        request_uuid=str(REQUEST_UUID),
        api_key_uuid=str(API_KEY_UUID),
        group_uuid=str(GROUP_UUID),
        api_key_name='rb-key',
        group_name='test-group',
        route_name='rb-gateway',
        audio_bytes=b'fake-audio',
        filename='test.wav',
        content_type='audio/wav',
    )

    # Not a WAV file: its length can't be read. Checked before the cache,
    # counted once the model is called.
    demand = Demand(cost_room=True, audio_seconds='unknown')
    limits.check.assert_awaited_once_with(demand, count=False)
    limits.count_checked.assert_awaited_once_with(demand)


@pytest.mark.asyncio
async def test_invoke_transcription_duration_limit_exceeded_blocks_before_invocation():
    cost_service = MagicMock(spec_set=CostService)
    whisper_model = Model(
        model_id='whisper-1',
        model='openai/whisper-1',
        credentials=Credentials(api_key='sk-test'),
    )
    route_cfg = GatewayRouteConfig(
        route_name='rb-gateway',
        chat_models=[],
        transcription_models=['whisper-1'],
        duration_limiting=AudioDurationLimiting(
            max_duration_seconds=300, window_size='1 minute'
        ),
    )
    limits = _spied_limits()
    limits.check.side_effect = AudioDurationLimitExceeded('limit exceeded')

    ai_gateway = GatewayRoute(
        gateway_route_config=route_cfg,
        chat_models=[],
        embedding_models=None,
        transcription_models=[whisper_model],
        gateway_cache=None,
        cost_service=cost_service,
    )
    ai_gateway.transcription_invoker.transcribe = AsyncMock()

    with pytest.raises(AudioDurationLimitExceeded):
        await invoke_transcription(
            ai_gateway,
            limits=limits,
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            group_uuid=str(GROUP_UUID),
            api_key_name='rb-key',
            group_name='test-group',
            route_name='rb-gateway',
            audio_bytes=b'fake-audio',
            filename='test.wav',
            content_type='audio/wav',
        )

    ai_gateway.transcription_invoker.transcribe.assert_not_awaited()


@pytest.mark.asyncio
async def test_invoke_transcription_success():
    cost_service = MagicMock(spec_set=CostService)
    whisper_model = Model(
        model_id='whisper-1',
        model='openai/whisper-1',
        credentials=Credentials(api_key='sk-test'),
    )
    route_cfg = _make_transcription_route_config()

    ai_gateway = GatewayRoute(
        gateway_route_config=route_cfg,
        chat_models=[],
        embedding_models=None,
        transcription_models=[whisper_model],
        gateway_cache=None,
        cost_service=cost_service,
    )

    fake_result = MagicMock(usage=MagicMock(type='duration', seconds=9))
    ai_gateway.transcription_invoker.transcribe = AsyncMock(return_value=fake_result)

    result = await invoke_transcription(
        ai_gateway,
        limits=request_limits(ai_gateway),
        request_uuid=str(REQUEST_UUID),
        api_key_uuid=str(API_KEY_UUID),
        group_uuid=str(GROUP_UUID),
        api_key_name='rb-key',
        group_name='test-group',
        route_name='rb-gateway',
        audio_bytes=b'fake-audio',
        filename='test.wav',
        content_type='audio/wav',
    )

    assert result is fake_result
    # transcribe() now records its own metrics/cost internally (mirroring
    # ChatModelInvoker.complete()/EmbeddingModelInvoker.embed()), so
    # ai_gateway just has to wire the identity/project params through.
    ai_gateway.transcription_invoker.transcribe.assert_awaited_once_with(
        **with_identity(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            group_uuid=str(GROUP_UUID),
            api_key_name='rb-key',
            group_name='test-group',
            route_name='rb-gateway',
            audio_bytes=b'fake-audio',
            filename='test.wav',
            content_type='audio/wav',
            model_id='whisper-1',
            requested_response_format='json',
            language=None,
            prompt=None,
            temperature=None,
        )
    )


@patch('radicalbit_ai_gateway.pipeline.conversation.emit_event', autospec=True)
@pytest.mark.asyncio
async def test_invoke_transcription_cache_miss_then_hit_skips_reinvocation(
    mock_emit_event,
):
    cost_service = MagicMock(spec_set=CostService)
    whisper_model = Model(
        model_id='whisper-1',
        model='openai/whisper-1',
        credentials=Credentials(api_key='sk-test'),
    )
    route_cfg = _make_transcription_route_config()
    gateway_cache = GatewayCache(CacheToolsInMemory())

    ai_gateway = GatewayRoute(
        gateway_route_config=route_cfg,
        chat_models=[],
        embedding_models=None,
        transcription_models=[whisper_model],
        gateway_cache=gateway_cache,
        cost_service=cost_service,
    )
    limits = _spied_limits()

    fake_result = Transcription(
        text='Ciao, questo è un test.', usage={'type': 'duration', 'seconds': 9}
    )
    ai_gateway.transcription_invoker.transcribe = AsyncMock(return_value=fake_result)

    kwargs = {
        'limits': limits,
        'request_uuid': str(REQUEST_UUID),
        'api_key_uuid': str(API_KEY_UUID),
        'group_uuid': str(GROUP_UUID),
        'api_key_name': 'rb-key',
        'group_name': 'test-group',
        'route_name': 'rb-gateway',
        'audio_bytes': b'fake-audio',
        'filename': 'test.wav',
        'content_type': 'audio/wav',
    }

    first_result = await invoke_transcription(ai_gateway, **kwargs)
    assert first_result == fake_result
    ai_gateway.transcription_invoker.transcribe.assert_awaited_once()
    limits.check.assert_awaited_once()

    second_result = await invoke_transcription(ai_gateway, **kwargs)
    assert second_result == fake_result
    # The second call is served from cache, never reaching the invoker; the
    # limits are checked first, as on every request (D10).
    ai_gateway.transcription_invoker.transcribe.assert_awaited_once()
    assert limits.check.await_count == 2


@patch('radicalbit_ai_gateway.pipeline.conversation.emit_event', autospec=True)
@pytest.mark.asyncio
async def test_invoke_transcription_cache_hit_verbose_json_roundtrips(
    mock_emit_event,
):
    cost_service = MagicMock(spec_set=CostService)
    whisper_model = Model(
        model_id='whisper-1',
        model='openai/whisper-1',
        credentials=Credentials(api_key='sk-test'),
    )
    route_cfg = _make_transcription_route_config()
    gateway_cache = GatewayCache(CacheToolsInMemory())

    ai_gateway = GatewayRoute(
        gateway_route_config=route_cfg,
        chat_models=[],
        embedding_models=None,
        transcription_models=[whisper_model],
        gateway_cache=gateway_cache,
        cost_service=cost_service,
    )

    fake_result = TranscriptionVerbose(
        task='transcribe',
        language='italian',
        duration=8.25,
        text='Ciao, questo è un test.',
        segments=[],
        usage={'type': 'duration', 'seconds': 9},
    )
    ai_gateway.transcription_invoker.transcribe = AsyncMock(return_value=fake_result)

    kwargs = {
        'limits': request_limits(ai_gateway),
        'request_uuid': str(REQUEST_UUID),
        'api_key_uuid': str(API_KEY_UUID),
        'group_uuid': str(GROUP_UUID),
        'api_key_name': 'rb-key',
        'group_name': 'test-group',
        'route_name': 'rb-gateway',
        'audio_bytes': b'fake-audio',
        'filename': 'test.wav',
        'content_type': 'audio/wav',
        'requested_response_format': 'verbose_json',
    }

    await invoke_transcription(ai_gateway, **kwargs)
    second_result = await invoke_transcription(ai_gateway, **kwargs)

    ai_gateway.transcription_invoker.transcribe.assert_awaited_once()
    assert isinstance(second_result, TranscriptionVerbose)
    assert second_result.language == 'italian'
    assert second_result.segments == []


@patch('radicalbit_ai_gateway.pipeline.conversation.emit_event', autospec=True)
@pytest.mark.asyncio
async def test_invoke_transcription_cache_miss_when_audio_bytes_differ(
    mock_emit_event,
):
    cost_service = MagicMock(spec_set=CostService)
    whisper_model = Model(
        model_id='whisper-1',
        model='openai/whisper-1',
        credentials=Credentials(api_key='sk-test'),
    )
    route_cfg = _make_transcription_route_config()
    gateway_cache = GatewayCache(CacheToolsInMemory())

    ai_gateway = GatewayRoute(
        gateway_route_config=route_cfg,
        chat_models=[],
        embedding_models=None,
        transcription_models=[whisper_model],
        gateway_cache=gateway_cache,
        cost_service=cost_service,
    )

    fake_result = Transcription(
        text='Ciao, questo è un test.', usage={'type': 'duration', 'seconds': 9}
    )
    ai_gateway.transcription_invoker.transcribe = AsyncMock(return_value=fake_result)

    common_kwargs = {
        'limits': request_limits(ai_gateway),
        'request_uuid': str(REQUEST_UUID),
        'api_key_uuid': str(API_KEY_UUID),
        'group_uuid': str(GROUP_UUID),
        'api_key_name': 'rb-key',
        'group_name': 'test-group',
        'route_name': 'rb-gateway',
        'filename': 'test.wav',
        'content_type': 'audio/wav',
    }

    await invoke_transcription(ai_gateway, audio_bytes=b'audio-one', **common_kwargs)
    await invoke_transcription(ai_gateway, audio_bytes=b'audio-two', **common_kwargs)

    assert ai_gateway.transcription_invoker.transcribe.await_count == 2


@pytest.mark.asyncio
async def test_invoke_transcription_passes_through_requested_response_format():
    cost_service = MagicMock(spec_set=CostService)
    whisper_model = Model(
        model_id='whisper-1',
        model='openai/whisper-1',
        credentials=Credentials(api_key='sk-test'),
    )
    route_cfg = _make_transcription_route_config()

    ai_gateway = GatewayRoute(
        gateway_route_config=route_cfg,
        chat_models=[],
        embedding_models=None,
        transcription_models=[whisper_model],
        gateway_cache=None,
        cost_service=cost_service,
    )

    fake_result = MagicMock(usage=MagicMock(type='duration', seconds=9))
    ai_gateway.transcription_invoker.transcribe = AsyncMock(return_value=fake_result)

    await invoke_transcription(
        ai_gateway,
        limits=request_limits(ai_gateway),
        request_uuid=str(REQUEST_UUID),
        api_key_uuid=str(API_KEY_UUID),
        group_uuid=str(GROUP_UUID),
        api_key_name='rb-key',
        group_name='test-group',
        route_name='rb-gateway',
        audio_bytes=b'fake-audio',
        filename='test.wav',
        content_type='audio/wav',
        requested_response_format='verbose_json',
    )

    assert (
        ai_gateway.transcription_invoker.transcribe.call_args.kwargs[
            'requested_response_format'
        ]
        == 'verbose_json'
    )


@pytest.mark.asyncio
async def test_invoke_transcription_counts_budget_duration():
    """usage.type == 'duration' (whisper-1): the cost is the seconds at the
    per-second price, both floats.
    """
    cost_service = MagicMock(spec_set=CostService)
    whisper_model = Model(
        model_id='whisper-1',
        model='openai/whisper-1',
        credentials=Credentials(api_key='sk-test'),
        input_cost_per_second=Decimal('0.0001'),
    )
    route_cfg = _make_transcription_route_config(max_budget=10.0, window_size=3600)
    limits = _spied_limits()

    ai_gateway = GatewayRoute(
        gateway_route_config=route_cfg,
        chat_models=[],
        embedding_models=None,
        transcription_models=[whisper_model],
        gateway_cache=None,
        cost_service=cost_service,
    )

    fake_result = MagicMock(usage=MagicMock(type='duration', seconds=3))
    ai_gateway.transcription_invoker.transcribe = AsyncMock(return_value=fake_result)

    await invoke_transcription(
        ai_gateway,
        limits=limits,
        request_uuid=str(REQUEST_UUID),
        api_key_uuid=str(API_KEY_UUID),
        group_uuid=str(GROUP_UUID),
        api_key_name='rb-key',
        group_name='test-group',
        route_name='rb-gateway',
        audio_bytes=b'fake-audio',
        filename='test.wav',
        content_type='audio/wav',
    )

    limits.check.assert_awaited_once()
    # 3 seconds at 0.0001 a second, in billionths of a dollar.
    limits.count.assert_awaited_once_with(Usage(costs=(300_000,)))


@pytest.mark.asyncio
async def test_invoke_transcription_counts_budget_tokens():
    """usage.type == 'tokens' (gpt-4o-transcribe family): audio, text and
    output tokens each costed at their own price, a part counted only when
    its price is non-zero.
    """
    cost_service = MagicMock(spec_set=CostService)
    gpt4o_model = Model(
        model_id='gpt4o-transcribe',
        model='openai/gpt-4o-transcribe',
        credentials=Credentials(api_key='sk-test'),
        input_cost_per_million_tokens=Decimal('2.5'),
        output_cost_per_million_tokens=Decimal('10.0'),
        input_cost_per_audio_token=Decimal('0.000006'),
    )
    route_cfg = _make_transcription_route_config(
        model_id='gpt4o-transcribe', max_budget=10.0, window_size=3600
    )
    limits = _spied_limits()

    ai_gateway = GatewayRoute(
        gateway_route_config=route_cfg,
        chat_models=[],
        embedding_models=None,
        transcription_models=[gpt4o_model],
        gateway_cache=None,
        cost_service=cost_service,
    )

    fake_result = MagicMock(
        usage=MagicMock(
            type='tokens',
            input_tokens=87,
            output_tokens=38,
            input_token_details=MagicMock(audio_tokens=82, text_tokens=5),
        )
    )
    ai_gateway.transcription_invoker.transcribe = AsyncMock(return_value=fake_result)

    await invoke_transcription(
        ai_gateway,
        limits=limits,
        request_uuid=str(REQUEST_UUID),
        api_key_uuid=str(API_KEY_UUID),
        group_uuid=str(GROUP_UUID),
        api_key_name='rb-key',
        group_name='test-group',
        route_name='rb-gateway',
        audio_bytes=b'fake-audio',
        filename='test.wav',
        content_type='audio/wav',
    )

    limits.check.assert_awaited_once()
    # Audio, text and output tokens, each at its own price.
    limits.count.assert_awaited_once_with(Usage(costs=(492_000, 12_500, 380_000)))


@pytest.mark.asyncio
async def test_invoke_transcription_no_models_configured_raises():
    cost_service = MagicMock(spec_set=CostService)
    route_cfg = GatewayRouteConfig(route_name='rb-gateway', chat_models=[])

    ai_gateway = GatewayRoute(
        gateway_route_config=route_cfg,
        chat_models=[],
        embedding_models=None,
        transcription_models=None,
        gateway_cache=None,
        cost_service=cost_service,
    )

    with pytest.raises(GatewayBadRequest, match='no transcription models defined'):
        await invoke_transcription(
            ai_gateway,
            limits=request_limits(ai_gateway),
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            group_uuid=str(GROUP_UUID),
            api_key_name='rb-key',
            group_name='test-group',
            route_name='rb-gateway',
            audio_bytes=b'fake-audio',
            filename='test.wav',
            content_type='audio/wav',
        )


@pytest.mark.asyncio
async def test_invoke_transcription_stream_relays_events_and_counts_usage_once():
    cost_service = MagicMock(spec_set=CostService)
    gpt4o_model = Model(
        model_id='gpt4o-transcribe',
        model='openai/gpt-4o-transcribe',
        credentials=Credentials(api_key='sk-test'),
        input_cost_per_million_tokens=Decimal('2.5'),
        output_cost_per_million_tokens=Decimal('10.0'),
        input_cost_per_audio_token=Decimal('0.000006'),
    )
    route_cfg = _make_transcription_route_config(
        model_id='gpt4o-transcribe', max_budget=10.0, window_size=3600
    )
    limits = _spied_limits()

    ai_gateway = GatewayRoute(
        gateway_route_config=route_cfg,
        chat_models=[],
        embedding_models=None,
        transcription_models=[gpt4o_model],
        gateway_cache=None,
        cost_service=cost_service,
    )

    delta_event = MagicMock(usage=None)
    done_event = MagicMock(
        usage=MagicMock(
            type='tokens',
            input_tokens=87,
            output_tokens=38,
            input_token_details=MagicMock(audio_tokens=82, text_tokens=5),
        )
    )

    async def fake_stream(**kwargs):
        yield delta_event
        yield done_event

    ai_gateway.transcription_invoker.stream = fake_stream

    events = await invoke_transcription_stream(
        ai_gateway,
        limits=limits,
        request_uuid=str(REQUEST_UUID),
        api_key_uuid=str(API_KEY_UUID),
        group_uuid=str(GROUP_UUID),
        api_key_name='rb-key',
        group_name='test-group',
        route_name='rb-gateway',
        audio_bytes=b'fake-audio',
        filename='test.wav',
        content_type='audio/wav',
    )

    assert events == [delta_event, done_event]
    limits.check.assert_awaited_once()
    # Usage is only available on the final event — budget counting must use
    # that one, not the (usage=None) delta in between.
    limits.count.assert_awaited_once_with(Usage(costs=(492_000, 12_500, 380_000)))


@pytest.mark.asyncio
async def test_invoke_transcription_stream_no_models_configured_raises():
    cost_service = MagicMock(spec_set=CostService)
    route_cfg = GatewayRouteConfig(route_name='rb-gateway', chat_models=[])

    ai_gateway = GatewayRoute(
        gateway_route_config=route_cfg,
        chat_models=[],
        embedding_models=None,
        transcription_models=None,
        gateway_cache=None,
        cost_service=cost_service,
    )

    with pytest.raises(GatewayBadRequest, match='no transcription models defined'):
        await invoke_transcription_stream(
            ai_gateway,
            limits=request_limits(ai_gateway),
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            group_uuid=str(GROUP_UUID),
            api_key_name='rb-key',
            group_name='test-group',
            route_name='rb-gateway',
            audio_bytes=b'fake-audio',
            filename='test.wav',
            content_type='audio/wav',
        )


@patch('radicalbit_ai_gateway.pipeline.conversation.emit_event', autospec=True)
@patch('radicalbit_ai_gateway.invocation.recorder.emit_event', autospec=True)
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
    project_guardrails = Guardrails(
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
        guardrails=project_guardrails.for_route(route_cfg),
        gateway_cache=gateway_cache,
        cost_service=cost_service,
        project_uuid=str(TEST_PROJECT_UUID),
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
        invoke_response = await invoke(
            ai_gateway,
            limits=request_limits(ai_gateway),
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
        invoke_response_cached = await invoke(
            ai_gateway,
            limits=request_limits(ai_gateway),
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
        plugins={'spy': {'enabled': True}},
    )
    ai_gateway = GatewayRoute(
        gateway_route_config=route_cfg,
        chat_models=[chat_model],
        embedding_models=None,
        cost_service=MagicMock(spec_set=CostService),
        gateway_cache=None,
    )

    try:
        register_preprocessing_plugin(Spy(), name='spy')
        ai_gateway.chat_invoker.complete = AsyncMock(
            return_value=to_mock_openai_chat_completion(content='hi')
        )
        await invoke(
            ai_gateway,
            limits=request_limits(ai_gateway),
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
        config_hooks._plugins_validators.clear()
        config_hooks._known_plugin_keys.clear()

    # The plugin only ever saw the client message — no injected system prompt.
    assert seen == [('HumanMessage', 'hello')]

    # The final messages start with the untouched system prompt, followed by the
    # client message the plugin transformed.
    messages = ai_gateway.chat_invoker.complete.call_args.kwargs['messages']
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
        plugins={'spy': {'enabled': True}},
    )
    ai_gateway = GatewayRoute(
        gateway_route_config=route_cfg,
        chat_models=[chat_model],
        embedding_models=None,
        cost_service=MagicMock(spec_set=CostService),
        gateway_cache=None,
    )

    try:
        register_preprocessing_plugin(Spy(), name='spy')
        ai_gateway.chat_invoker.complete = AsyncMock(
            return_value=to_mock_openai_chat_completion(content='hi')
        )
        await invoke(
            ai_gateway,
            limits=request_limits(ai_gateway),
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
        config_hooks._plugins_validators.clear()
        config_hooks._known_plugin_keys.clear()

    # The plugin saw the client's own system message (and the human message);
    # the route-configured prompt was NOT yet present.
    assert seen == [
        ('SystemMessage', 'client system'),
        ('HumanMessage', 'hello'),
    ]

    # Final order: route prompt prepended (untouched), then the client's
    # system + human messages, both transformed by the plugin.
    messages = ai_gateway.chat_invoker.complete.call_args.kwargs['messages']
    assert [(type(m).__name__, m.content) for m in messages] == [
        ('SystemMessage', 'Route prompt.'),
        ('SystemMessage', 'CLIENT SYSTEM'),
        ('HumanMessage', 'HELLO'),
    ]
