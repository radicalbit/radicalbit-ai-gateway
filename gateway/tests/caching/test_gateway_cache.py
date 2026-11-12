import datetime
import json

from freezegun import freeze_time
from openai.types import CompletionUsage
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from openai.types.chat.chat_completion import Choice
import pytest

from tests.common.cache_keys import chat_key, embedding_key, transcription_key
from tests.common.db_mock import TEST_PROJECT_UUID

from radicalbit_ai_gateway.caching.gateway_cache import GatewayCache
from radicalbit_ai_gateway.caching.in_memory_cache import CacheToolsInMemory
from radicalbit_ai_gateway.caching.redis_cache import RedisCache
from radicalbit_ai_gateway.llm.messages import HumanMessage

PROJECT_UUID = str(TEST_PROJECT_UUID)
KEY_PREFIX = f'response:aigateway:cache:{PROJECT_UUID}:rb-gateway:fake-uuid:'
TRANSCRIPTION = {
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
RESPONSE = ChatCompletion(
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


def _chat_key(route_name: str = 'rb-gateway') -> str:
    return chat_key(
        project_uuid=PROJECT_UUID,
        route_name=route_name,
        key_uuid='fake-uuid',
        messages=[HumanMessage(content='Hello')],
        tools=[],
        tool_choice='auto',
    )


@pytest.fixture(params=['redis', 'in_memory'])
def gateway_cache(request) -> GatewayCache:
    if request.param == 'redis':
        client = RedisCache(request.getfixturevalue('fake_redis_client'))
    else:
        client = CacheToolsInMemory()
    return GatewayCache(cache_client=client)


async def _cached(gateway_cache: GatewayCache, key: str) -> ChatCompletion | None:
    cached = await gateway_cache.get(key)
    return None if cached is None else ChatCompletion.model_validate(json.loads(cached))


def test_the_chat_key_hashes_the_request_under_project_route_and_credential():
    assert _chat_key() == (
        f'{KEY_PREFIX}e7e0a0714addd9767787243b19d8204cb5b435258a641d93856932c2057766ec'
    )


@pytest.mark.parametrize(
    'key',
    [
        pytest.param(
            embedding_key(
                project_uuid=PROJECT_UUID,
                route_name='rb-gateway',
                key_uuid='fake-uuid',
                input_texts=['hello world'],
            ),
            id='embedding',
        ),
        pytest.param(transcription_key(**TRANSCRIPTION), id='transcription'),
    ],
)
def test_embedding_and_transcription_keys_sit_under_project_route_and_credential(key):
    assert key.startswith(KEY_PREFIX)


@pytest.mark.parametrize(
    ('field', 'other'),
    [
        pytest.param('audio_bytes', b'other-audio-bytes', id='audio-bytes'),
        pytest.param('response_format', 'verbose_json', id='params'),
    ],
)
def test_the_transcription_key_is_deterministic_and_differs_by_audio_and_params(
    field, other
):
    assert transcription_key(**TRANSCRIPTION) == transcription_key(**TRANSCRIPTION)
    assert transcription_key(**TRANSCRIPTION) != transcription_key(
        **{**TRANSCRIPTION, field: other}
    )


async def test_a_response_is_cached_until_its_ttl_and_without_one_for_good(
    gateway_cache,
):
    forever, expiring = _chat_key('forever'), _chat_key()
    with freeze_time(datetime.datetime(2025, 7, 29, 15)) as frozen_datetime:
        assert await gateway_cache.get(forever) is None
        assert await gateway_cache.get(expiring) is None

        await gateway_cache.set(forever, RESPONSE.model_dump_json(indent=None), None)
        await gateway_cache.set(expiring, RESPONSE.model_dump_json(indent=None), 100)

        assert await _cached(gateway_cache, forever) == RESPONSE
        assert await _cached(gateway_cache, expiring) == RESPONSE

        frozen_datetime.tick(50)
        assert await _cached(gateway_cache, expiring) == RESPONSE

        frozen_datetime.tick(60)  # 110 seconds, past the 100-second TTL
        assert await gateway_cache.get(expiring) is None
        assert await _cached(gateway_cache, forever) == RESPONSE
