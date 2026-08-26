import datetime
import json

from freezegun import freeze_time
from langchain_core.messages import HumanMessage
from openai.types import CompletionUsage
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from openai.types.chat.chat_completion import Choice
import pytest

from tests.common.db_mock import TEST_PROJECT_UUID

from radicalbit_ai_gateway.caching.gateway_cache import GatewayCache
from radicalbit_ai_gateway.caching.in_memory_cache import CacheToolsInMemory
from radicalbit_ai_gateway.caching.redis_cache import RedisCache

PROJECT_UUID = str(TEST_PROJECT_UUID)


def test_hash_name_redis(fake_redis_client):
    redis_cache = RedisCache(fake_redis_client)
    gateway_cache = GatewayCache(cache_client=redis_cache)

    messages = [HumanMessage(content='Hello')]
    tools = []
    tool_choice = 'auto'
    kwargs = {}
    cache_key = gateway_cache.generate_cache_key(
        project_uuid=PROJECT_UUID,
        route_name='rb-gateway',
        key_uuid='fake-uuid',
        messages=messages,
        tools=tools,
        tool_choice=tool_choice,
        **kwargs,
    )
    assert (
        cache_key
        == f'response:aigateway:cache:{PROJECT_UUID}:rb-gateway:fake-uuid:e7e0a0714addd9767787243b19d8204cb5b435258a641d93856932c2057766ec'
    )


@pytest.mark.asyncio
async def test_get_and_set_redis(fake_redis_client):
    redis_cache = RedisCache(fake_redis_client)
    gateway_cache = GatewayCache(cache_client=redis_cache)

    messages = [HumanMessage(content='Hello')]
    tools = []
    tool_choice = 'auto'
    kwargs = {}
    cache_key = gateway_cache.generate_cache_key(
        project_uuid=PROJECT_UUID,
        route_name='rb-gateway',
        key_uuid='fake-uuid',
        messages=messages,
        tools=tools,
        tool_choice=tool_choice,
        **kwargs,
    )
    assert await gateway_cache.get(cache_key) is None

    response = ChatCompletion(
        id='run--a62e3f0c-045a-4d35-9f24-698fd7ef93c6-0',
        choices=[
            Choice(
                finish_reason='stop',
                index=0,
                logprobs=None,
                message=ChatCompletionMessage(
                    content='Hello there! How can I assist you today?',
                    refusal=None,
                    role='assistant',
                    annotations=None,
                    audio=None,
                    function_call=None,
                    tool_calls=None,
                ),
            )
        ],
        created=1753790056,
        model='qwen2.5:3b',
        object='chat.completion',
        service_tier=None,
        system_fingerprint=None,
        usage=CompletionUsage(
            completion_tokens=13,
            prompt_tokens=23,
            total_tokens=36,
            completion_tokens_details=None,
            prompt_tokens_details=None,
        ),
    )

    await gateway_cache.set(cache_key, response.model_dump_json(indent=None), None)
    cached_response = await gateway_cache.get(cache_key)
    assert ChatCompletion.model_validate(json.loads(cached_response)) == response


@pytest.mark.asyncio
async def test_get_and_set_with_ttl_redis(fake_redis_client):
    redis_cache = RedisCache(fake_redis_client)
    gateway_cache = GatewayCache(cache_client=redis_cache)

    messages = [HumanMessage(content='Hello')]
    tools = []
    tool_choice = 'auto'
    kwargs = {}
    cache_key = gateway_cache.generate_cache_key(
        project_uuid=PROJECT_UUID,
        route_name='rb-gateway',
        key_uuid='fake-uuid',
        messages=messages,
        tools=tools,
        tool_choice=tool_choice,
        **kwargs,
    )
    initial_datetime = datetime.datetime(
        year=2025, month=7, day=29, hour=15, minute=0, second=0
    )
    with freeze_time(initial_datetime) as frozen_datetime:
        assert frozen_datetime() == initial_datetime

        assert await gateway_cache.get(cache_key) is None

        response = ChatCompletion(
            id='run--a62e3f0c-045a-4d35-9f24-698fd7ef93c6-0',
            choices=[
                Choice(
                    finish_reason='stop',
                    index=0,
                    logprobs=None,
                    message=ChatCompletionMessage(
                        content='Hello there! How can I assist you today?',
                        refusal=None,
                        role='assistant',
                        annotations=None,
                        audio=None,
                        function_call=None,
                        tool_calls=None,
                    ),
                )
            ],
            created=1753790056,
            model='qwen2.5:3b',
            object='chat.completion',
            service_tier=None,
            system_fingerprint=None,
            usage=CompletionUsage(
                completion_tokens=13,
                prompt_tokens=23,
                total_tokens=36,
                completion_tokens_details=None,
                prompt_tokens_details=None,
            ),
        )

        await gateway_cache.set(cache_key, response.model_dump_json(indent=None), 100)

        assert (
            ChatCompletion.model_validate(
                json.loads(await gateway_cache.get(cache_key))
            )
            == response
        )

        # Increase time 50 seconds, cache should be populated
        frozen_datetime.tick(50)
        assert (
            ChatCompletion.model_validate(
                json.loads(await gateway_cache.get(cache_key))
            )
            == response
        )

        # Increase time additional 60 seconds, cache should miss (100 seconds ttl)
        frozen_datetime.tick(60)
        assert await gateway_cache.get(cache_key) is None


def test_hash_name_in_memory():
    in_memory_cache = CacheToolsInMemory()
    gateway_cache = GatewayCache(cache_client=in_memory_cache)

    messages = [HumanMessage(content='Hello')]
    tools = []
    tool_choice = 'auto'
    kwargs = {}
    cache_key = gateway_cache.generate_cache_key(
        project_uuid=PROJECT_UUID,
        route_name='rb-gateway',
        key_uuid='fake-uuid',
        messages=messages,
        tools=tools,
        tool_choice=tool_choice,
        **kwargs,
    )
    assert (
        cache_key
        == f'response:aigateway:cache:{PROJECT_UUID}:rb-gateway:fake-uuid:e7e0a0714addd9767787243b19d8204cb5b435258a641d93856932c2057766ec'
    )


@pytest.mark.asyncio
async def test_get_and_set_in_memory():
    in_memory_cache = CacheToolsInMemory()
    gateway_cache = GatewayCache(cache_client=in_memory_cache)

    messages = [HumanMessage(content='Hello')]
    tools = []
    tool_choice = 'auto'
    kwargs = {}
    cache_key = gateway_cache.generate_cache_key(
        project_uuid=PROJECT_UUID,
        route_name='rb-gateway',
        key_uuid='fake-uuid',
        messages=messages,
        tools=tools,
        tool_choice=tool_choice,
        **kwargs,
    )
    assert await gateway_cache.get(cache_key) is None

    response = ChatCompletion(
        id='run--a62e3f0c-045a-4d35-9f24-698fd7ef93c6-0',
        choices=[
            Choice(
                finish_reason='stop',
                index=0,
                logprobs=None,
                message=ChatCompletionMessage(
                    content='Hello there! How can I assist you today?',
                    refusal=None,
                    role='assistant',
                    annotations=None,
                    audio=None,
                    function_call=None,
                    tool_calls=None,
                ),
            )
        ],
        created=1753790056,
        model='qwen2.5:3b',
        object='chat.completion',
        service_tier=None,
        system_fingerprint=None,
        usage=CompletionUsage(
            completion_tokens=13,
            prompt_tokens=23,
            total_tokens=36,
            completion_tokens_details=None,
            prompt_tokens_details=None,
        ),
    )

    await gateway_cache.set(cache_key, response.model_dump_json(indent=None), None)

    assert (
        ChatCompletion.model_validate(json.loads(await gateway_cache.get(cache_key)))
        == response
    )


@pytest.mark.asyncio
async def test_get_and_set_with_ttl_in_memory(fake_redis_client):
    in_memory_cache = CacheToolsInMemory()
    gateway_cache = GatewayCache(cache_client=in_memory_cache)

    messages = [HumanMessage(content='Hello')]
    tools = []
    tool_choice = 'auto'
    kwargs = {}
    cache_key = gateway_cache.generate_cache_key(
        project_uuid=PROJECT_UUID,
        route_name='rb-gateway',
        key_uuid='fake-uuid',
        messages=messages,
        tools=tools,
        tool_choice=tool_choice,
        **kwargs,
    )
    initial_datetime = datetime.datetime(
        year=2025, month=7, day=29, hour=15, minute=0, second=0
    )
    with freeze_time(initial_datetime) as frozen_datetime:
        assert frozen_datetime() == initial_datetime

        assert await gateway_cache.get(cache_key) is None

        response = ChatCompletion(
            id='run--a62e3f0c-045a-4d35-9f24-698fd7ef93c6-0',
            choices=[
                Choice(
                    finish_reason='stop',
                    index=0,
                    logprobs=None,
                    message=ChatCompletionMessage(
                        content='Hello there! How can I assist you today?',
                        refusal=None,
                        role='assistant',
                        annotations=None,
                        audio=None,
                        function_call=None,
                        tool_calls=None,
                    ),
                )
            ],
            created=1753790056,
            model='qwen2.5:3b',
            object='chat.completion',
            service_tier=None,
            system_fingerprint=None,
            usage=CompletionUsage(
                completion_tokens=13,
                prompt_tokens=23,
                total_tokens=36,
                completion_tokens_details=None,
                prompt_tokens_details=None,
            ),
        )

        await gateway_cache.set(cache_key, response.model_dump_json(indent=None), 100)

        assert (
            ChatCompletion.model_validate(
                json.loads(await gateway_cache.get(cache_key))
            )
            == response
        )

        # Increase time 50 seconds, cache should be populated
        frozen_datetime.tick(50)
        assert (
            ChatCompletion.model_validate(
                json.loads(await gateway_cache.get(cache_key))
            )
            == response
        )

        # Increase time additional 60 seconds, cache should miss (100 seconds ttl)
        frozen_datetime.tick(60)
        assert await gateway_cache.get(cache_key) is None


def test_embedding_hash_name_redis(fake_redis_client):
    redis_cache = RedisCache(fake_redis_client)
    gateway_cache = GatewayCache(cache_client=redis_cache)

    input_texts = ['hello world']
    kwargs = {}
    cache_key = gateway_cache.generate_embedding_cache_key(
        project_uuid=PROJECT_UUID,
        route_name='rb-gateway',
        key_uuid='fake-uuid',
        input_texts=input_texts,
        **kwargs,
    )
    assert cache_key.startswith(
        f'response:aigateway:cache:{PROJECT_UUID}:rb-gateway:fake-uuid:'
    )


def test_embedding_hash_name_in_memory():
    in_memory_cache = CacheToolsInMemory()
    gateway_cache = GatewayCache(cache_client=in_memory_cache)

    input_texts = ['hello world']
    kwargs = {}
    cache_key = gateway_cache.generate_embedding_cache_key(
        project_uuid=PROJECT_UUID,
        route_name='rb-gateway',
        key_uuid='fake-uuid',
        input_texts=input_texts,
        **kwargs,
    )
    assert cache_key.startswith(
        f'response:aigateway:cache:{PROJECT_UUID}:rb-gateway:fake-uuid:'
    )


def test_transcription_hash_name_redis(fake_redis_client):
    redis_cache = RedisCache(fake_redis_client)
    gateway_cache = GatewayCache(cache_client=redis_cache)

    cache_key = gateway_cache.generate_transcription_cache_key(
        project_uuid=PROJECT_UUID,
        route_name='rb-gateway',
        key_uuid='fake-uuid',
        audio_bytes=b'fake-audio-bytes',
        model_id='whisper-1',
        response_format='json',
        language=None,
        prompt=None,
        temperature=None,
    )
    assert cache_key.startswith(
        f'response:aigateway:cache:{PROJECT_UUID}:rb-gateway:fake-uuid:'
    )


def test_transcription_hash_name_in_memory():
    in_memory_cache = CacheToolsInMemory()
    gateway_cache = GatewayCache(cache_client=in_memory_cache)

    cache_key = gateway_cache.generate_transcription_cache_key(
        project_uuid=PROJECT_UUID,
        route_name='rb-gateway',
        key_uuid='fake-uuid',
        audio_bytes=b'fake-audio-bytes',
        model_id='whisper-1',
        response_format='json',
        language=None,
        prompt=None,
        temperature=None,
    )
    assert cache_key.startswith(
        f'response:aigateway:cache:{PROJECT_UUID}:rb-gateway:fake-uuid:'
    )


def test_transcription_hash_name_is_deterministic():
    gateway_cache = GatewayCache(cache_client=CacheToolsInMemory())

    kwargs = {
        'project_uuid': PROJECT_UUID,
        'route_name': 'rb-gateway',
        'key_uuid': 'fake-uuid',
        'audio_bytes': b'fake-audio-bytes',
        'model_id': 'whisper-1',
        'response_format': 'json',
        'language': None,
        'prompt': None,
        'temperature': None,
    }
    assert gateway_cache.generate_transcription_cache_key(
        **kwargs
    ) == gateway_cache.generate_transcription_cache_key(**kwargs)


def test_transcription_hash_name_differs_by_audio_bytes():
    gateway_cache = GatewayCache(cache_client=CacheToolsInMemory())

    common_kwargs = {
        'project_uuid': PROJECT_UUID,
        'route_name': 'rb-gateway',
        'key_uuid': 'fake-uuid',
        'model_id': 'whisper-1',
        'response_format': 'json',
        'language': None,
        'prompt': None,
        'temperature': None,
    }
    key_1 = gateway_cache.generate_transcription_cache_key(
        audio_bytes=b'audio-one', **common_kwargs
    )
    key_2 = gateway_cache.generate_transcription_cache_key(
        audio_bytes=b'audio-two', **common_kwargs
    )
    assert key_1 != key_2


def test_transcription_hash_name_differs_by_params():
    gateway_cache = GatewayCache(cache_client=CacheToolsInMemory())

    common_kwargs = {
        'project_uuid': PROJECT_UUID,
        'route_name': 'rb-gateway',
        'key_uuid': 'fake-uuid',
        'audio_bytes': b'fake-audio-bytes',
        'model_id': 'whisper-1',
        'language': None,
        'prompt': None,
        'temperature': None,
    }
    key_json = gateway_cache.generate_transcription_cache_key(
        response_format='json', **common_kwargs
    )
    key_verbose = gateway_cache.generate_transcription_cache_key(
        response_format='verbose_json', **common_kwargs
    )
    assert key_json != key_verbose
