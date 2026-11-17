"""The route cache's interface: entries, lookups and stores.

What the endpoints do with it is pinned in ``test_cache_golden.py``.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from openai.types.audio.transcription import Transcription
from openai.types.audio.transcription_verbose import TranscriptionVerbose
from openai.types.chat.chat_completion_message_function_tool_call import (
    ChatCompletionMessageFunctionToolCall,
    Function,
)
from openai.types.create_embedding_response import CreateEmbeddingResponse, Usage
from openai.types.embedding import Embedding
import pytest

from tests.common.mocked_build_openai_chat_completion import (
    to_mock_openai_chat_completion,
)

from radicalbit_ai_gateway.caching.gateway_cache import GatewayCache
from radicalbit_ai_gateway.caching.in_memory_cache import CacheToolsInMemory
from radicalbit_ai_gateway.caching.route_cache import (
    CACHE_HIT_HEADER,
    Cached,
    RouteCache,
    cache_key,
)
from radicalbit_ai_gateway.caching.semantic_caching import SemanticCache
from radicalbit_ai_gateway.endpoints.chat_completions.cache import ChatEntry
from radicalbit_ai_gateway.endpoints.decision.cache import DecisionEntry
from radicalbit_ai_gateway.endpoints.embeddings.cache import EmbeddingEntry
from radicalbit_ai_gateway.endpoints.responses.cache import ResponsesEntry
from radicalbit_ai_gateway.endpoints.transcriptions.cache import TranscriptionEntry
from radicalbit_ai_gateway.llm.messages import AIMessage, HumanMessage, SystemMessage
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.models.request_identity import RequestIdentity

PROJECT = '11111111-1111-1111-1111-111111111111'
IDENTITY = RequestIdentity(
    request_uuid='req-1',
    route_name='rb-gateway',
    api_key_uuid='key-1',
    api_key_name='rb-key',
    group_uuid='group-1',
    group_name='group',
    project_uuid=PROJECT,
    project_name='proj',
)
EMIT = 'radicalbit_ai_gateway.caching.route_cache.emit_event'


def _key(signature_hash: str, route: str = 'rb-gateway') -> str:
    return f'response:aigateway:cache:{PROJECT}:{route}:key-1:{signature_hash}'


# ---------------------------------------------------------------------------
# Keys: the entries' signatures
# ---------------------------------------------------------------------------

# The keys every gateway before this one wrote: same inputs, same keys.
GOLDEN_KEYS = {
    'chat': _key('e7e0a0714addd9767787243b19d8204cb5b435258a641d93856932c2057766ec'),
}


def test_a_chat_key_is_the_key_every_earlier_gateway_wrote():
    entry = ChatEntry([HumanMessage(content='Hello')], [], 'auto')

    assert cache_key(PROJECT, 'rb-gateway', 'key-1', entry) == GOLDEN_KEYS['chat']


def test_a_chat_key_reads_the_turn_from_the_last_user_message_on():
    history = [
        SystemMessage(content='Be brief.'),
        HumanMessage(content='Hi'),
        AIMessage(content='Hello!'),
        HumanMessage(content='Hello'),
    ]

    assert cache_key(
        PROJECT, 'rb-gateway', 'key-1', ChatEntry(history, [], 'auto')
    ) == cache_key(PROJECT, 'rb-gateway', 'key-1', ChatEntry(history[-1:], [], 'auto'))
    assert ChatEntry(history).text() == 'Hello'
    assert ChatEntry([SystemMessage(content='Be brief.')]).signature() is None


def test_a_chat_key_leaves_the_stream_flags_out():
    plain = ChatEntry([HumanMessage(content='Hello')], [], 'auto', {'n': 1})
    streamed = ChatEntry(
        [HumanMessage(content='Hello')],
        [],
        'auto',
        {'n': 1, 'stream': True, 'stream_options': {'include_usage': True}},
        stream=True,
    )

    assert plain.signature() == streamed.signature()


def test_the_other_signatures():
    assert ResponsesEntry({'input': 'Hi', 'model': 'm'}).signature() == (
        'responses:{"input": "Hi", "params": {"model": "m"}}'
    )
    assert ResponsesEntry({'input': []}).signature() is None
    assert EmbeddingEntry(['caffè']).signature() == ('inputs:["caffè"];extra_args:{}')
    assert TranscriptionEntry(b'a', 't1', 'json').signature() == (
        'audio_hash:ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb;'
        'extra_args:{"model_id": "t1", "response_format": "json", '
        '"language": null, "prompt": null, "temperature": null}'
    )
    assert DecisionEntry({'b': 1, 'a': 'è'}, None, 'd1').signature() == (
        '{"model_id":"d1","questions":null,"state":{"a":"è","b":1}}'
    )


# ---------------------------------------------------------------------------
# Lookups and stores
# ---------------------------------------------------------------------------


def _route(backend=None, **fields) -> RouteCache:
    cost_service = MagicMock()
    cost_service.compute_cost.return_value = 0
    return RouteCache(
        backend=backend or GatewayCache(CacheToolsInMemory()),
        ttl=60,
        cost_service=cost_service,
        **fields,
    )


def _request(route: RouteCache, limits=None):
    return route.for_request(IDENTITY, limits or MagicMock())


async def test_a_route_without_a_cache_serves_nothing_and_stores_nothing():
    cached = await _request(RouteCache()).lookup(
        ChatEntry([HumanMessage(content='Hi')])
    )

    assert not cached.hit
    assert cached.headers() == {}
    await cached.store(to_mock_openai_chat_completion(content='x'))


@patch(EMIT)
async def test_a_miss_stores_and_the_next_lookup_hits(emit):
    route = _route()
    entry = ChatEntry([HumanMessage(content='Hi')])

    miss = await _request(route).lookup(entry)
    await miss.store(to_mock_openai_chat_completion(content='Hello'))
    hit = await _request(route).lookup(entry)

    assert not miss.hit
    assert hit.hit
    assert hit.value.choices[0].message.content == 'Hello'
    assert hit.headers() == {CACHE_HIT_HEADER: 'true'}
    assert emit.call_args_list[0].args[0].event_type.name == 'CACHE_HIT'


async def test_a_hit_does_not_store_again():
    store = AsyncMock()
    cached = Cached('reply', store)

    await cached.store('another')

    store.assert_not_awaited()


@patch(EMIT)
async def test_an_entry_that_does_not_parse_is_a_miss(emit):
    route = _route()
    await _request(route).lookup(EmbeddingEntry(['a']))
    key = cache_key(
        PROJECT, 'rb-gateway', 'key-1', ChatEntry([HumanMessage(content='Hi')])
    )
    await route.backend.set(key, '{"object": "response"}', None)

    cached = await _request(route).lookup(ChatEntry([HumanMessage(content='Hi')]))

    assert not cached.hit
    emit.assert_not_called()


@patch(EMIT)
async def test_a_stream_misses_a_reply_with_tool_calls(emit):
    route = _route()
    reply = to_mock_openai_chat_completion(content=None)
    reply.choices[0].message.tool_calls = [
        ChatCompletionMessageFunctionToolCall(
            id='call_1', type='function', function=Function(name='f', arguments='{}')
        )
    ]
    turn = [HumanMessage(content='Hi')]
    await (await _request(route).lookup(ChatEntry(turn))).store(reply)

    assert (await _request(route).lookup(ChatEntry(turn))).hit
    assert not (await _request(route).lookup(ChatEntry(turn, stream=True))).hit


class _Semantic(SemanticCache):
    def __init__(self):
        self.get = AsyncMock(return_value=None)
        self.set = AsyncMock()


def _embedding(tokens: int = 3) -> CreateEmbeddingResponse:
    return CreateEmbeddingResponse(
        object='list',
        data=[Embedding(index=0, embedding=[0.1, 0.2], object='embedding')],
        model='text-embedding-3-small',
        usage=Usage(prompt_tokens=tokens, total_tokens=tokens),
    )


async def test_an_exact_only_entry_skips_a_semantic_cache():
    semantic = _Semantic()

    cached = await _request(_route(GatewayCache(semantic))).lookup(
        EmbeddingEntry(['a'])
    )

    assert not cached.hit
    semantic.get.assert_not_awaited()


async def test_a_semantic_lookup_without_an_embedding_is_skipped():
    semantic = _Semantic()
    embedder = MagicMock()
    embedder.embed_answered = AsyncMock(side_effect=RuntimeError('down'))
    route = _route(
        GatewayCache(semantic),
        embedder=embedder,
        embedding_model=Model(model_id='e1', model='openai/text-embedding-3-small'),
    )

    cached = await _request(route).lookup(ChatEntry([HumanMessage(content='Hi')]))
    await cached.store(to_mock_openai_chat_completion(content='x'))

    semantic.get.assert_not_awaited()
    semantic.set.assert_not_awaited()


async def test_the_semantic_embedding_is_charged_to_the_request():
    semantic = _Semantic()
    model = Model(model_id='e1', model='openai/text-embedding-3-small')
    # A fallback answers: the call is charged at its price.
    answered = Model(model_id='e2', model='openai/text-embedding-3-large')
    embedder = MagicMock()
    embedder.embed_answered = AsyncMock(return_value=(_embedding(tokens=3), answered))
    limits = MagicMock()
    limits.charge_call = AsyncMock()
    route = _route(GatewayCache(semantic), embedder=embedder, embedding_model=model)

    cached = await _request(route, limits).lookup(
        ChatEntry([HumanMessage(content='Hi')])
    )
    await cached.store(to_mock_openai_chat_completion(content='x'))

    limits.charge_call.assert_awaited_once_with(answered, 3)
    assert embedder.embed_answered.call_args.kwargs['model_id'] == 'e1'
    assert embedder.embed_answered.call_args.kwargs['input_texts'] == ['Hi']
    assert embedder.embed_answered.call_args.kwargs['is_semantic_search'] is True
    tags = semantic.set.call_args.kwargs
    assert (tags['project_uuid'], tags['route_name'], tags['key_uuid']) == (
        PROJECT,
        'rb-gateway',
        'key-1',
    )
    assert semantic.get.call_args.kwargs['user_content'] == 'Hi'


@pytest.mark.parametrize(
    ('response_format', 'reply'),
    [
        ('json', Transcription(text='hello')),
        (
            'verbose_json',
            TranscriptionVerbose(
                text='hello', language='english', duration=1.5, segments=[]
            ),
        ),
    ],
)
@patch(EMIT)
async def test_a_transcription_hit_is_parsed_in_its_response_format(
    emit, response_format, reply
):
    route = _route()
    entry = TranscriptionEntry(b'audio', 't1', response_format)
    await (await _request(route).lookup(entry)).store(reply)

    hit = await _request(route).lookup(entry)

    assert hit.value == reply
