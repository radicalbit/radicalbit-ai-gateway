"""The response cache on POST /v1/messages, through a real route.

The routes are built from a project config and served on the real app
(``open_gateway``). Anthropic and the OpenAI embeddings are mocked over HTTP
with pook. The tests check what the client gets, what each upstream received,
and what the gateway records.
"""

import asyncio
from contextlib import contextmanager
import json
from unittest.mock import AsyncMock, patch

import pytest
import tiktoken

from tests.caching.test_semantic_caching import FakeSearchRedis
from tests.common import provider_responses as canned
from tests.common.db_mock import TEST_PROJECT_UUID
from tests.common.gateway_harness import open_gateway
from tests.common.messages_api import (
    BODY,
    CLAUDE,
    EMBEDDING,
    ROUTE_NAME,
    cut_off_tool_stream,
    messages_routes,
    mock_anthropic,
    mock_anthropic_stream,
    mock_embedding,
    refuse,
    send,
    send_stream,
    sent_body,
    serve,
    stream_frames,
)

from radicalbit_ai_gateway.caching.gateway_cache import GatewayCache
from radicalbit_ai_gateway.caching.route_cache import RouteCache
from radicalbit_ai_gateway.caching.semantic_caching import SemanticCache
from radicalbit_ai_gateway.gateway_route.route import GatewayRoute
from radicalbit_ai_gateway.limiting.limits import RequestLimits, Usage
from radicalbit_ai_gateway.models.event_type import EventType

CACHE_HIT = 'X-RB-AIGATEWAY-CACHE-HIT'
# No Redis client in these tests: an exact cache falls back to in-memory.
REDIS = {'cache': {'redis_host': 'localhost', 'redis_port': 6379}}
ANSWER = canned.anthropic_message().json_body
# The canned answer as the client gets it.
SERVED = {**ANSWER, 'model': ROUTE_NAME}
TOOL_USE = {'type': 'tool_use', **canned.ANTHROPIC_WEATHER_TOOL_USE}
CACHE_EVENTS = {
    EventType.CACHE_HIT,
    EventType.CACHE_INPUT_TOKENS,
    EventType.CACHE_OUTPUT_TOKENS,
}


@pytest.fixture
def gateway():
    with open_gateway(messages_routes(CLAUDE), use_pook=True) as gateway:
        yield gateway


OUTPUT_GUARDRAILS = [
    {
        'name': 'output_soft_block',
        'type': 'contains',
        'behavior': 'soft_block',
        'where': 'output',
        'parameters': {'values': ['secret']},
        'response_message': 'The answer was withheld.',
    },
    {
        'name': 'output_warn',
        'type': 'contains',
        'behavior': 'warn',
        'where': 'output',
        'parameters': {'values': ['secret']},
    },
]


def _serve_cached(*guardrails: str) -> GatewayRoute:
    """Serve the ``assistant`` route on Claude with an exact cache and the
    named output guardrails.
    """
    return serve(
        CLAUDE,
        caching={'type': 'exact'},
        guardrails=list(guardrails),
        config={**REDIS, 'guardrails': OUTPUT_GUARDRAILS},
    )


def _answer(text: str) -> dict:
    return canned.anthropic_message(text).json_body


def _ask(text: str, **fields: object) -> dict:
    """Return BODY with ``text`` as its one user message."""
    return {**BODY, 'messages': [{'role': 'user', 'content': text}], **fields}


def _cut_off(answer: dict) -> dict:
    return {**answer, 'stop_reason': 'max_tokens'}


def _cut_off_stream(*parts: str) -> str:
    """Return the canned stream, or one of ``parts``, ended by ``max_tokens``."""
    events = (
        canned.anthropic_stream(list(parts)) if parts else canned.anthropic_stream()
    ).sse_events
    for event in events:
        if event['type'] == 'message_delta':
            event['delta']['stop_reason'] = 'max_tokens'
    return ''.join(f'event: {e["type"]}\ndata: {json.dumps(e)}\n\n' for e in events)


def _answer_of(response) -> dict:
    """Return the answer a stream carries: its blocks and its stop reason."""
    frames = stream_frames(response.text)
    assert [event for event, _ in frames][0] == 'message_start'
    assert [event for event, _ in frames][-1] == 'message_stop'
    blocks: dict[int, dict] = {}
    inputs: dict[int, str] = {}
    answer: dict = {}
    for event, data in frames:
        if event == 'message_start':
            answer = dict(data['message'])
        elif event == 'content_block_start':
            blocks[data['index']] = dict(data['content_block'])
        elif event == 'content_block_delta' and data['delta']['type'] == 'text_delta':
            blocks[data['index']]['text'] += data['delta']['text']
        elif event == 'content_block_delta':
            inputs[data['index']] = (
                inputs.get(data['index'], '') + data['delta']['partial_json']
            )
        elif event == 'message_delta':
            answer.update(data['delta'])
    for index, raw in inputs.items():
        blocks[index]['input'] = json.loads(raw)
    return {
        'model': answer['model'],
        'content': [blocks[index] for index in sorted(blocks)],
        'stop_reason': answer['stop_reason'],
    }


def _cache_events(gateway) -> list[tuple]:
    """Return the cache events: type, value, cache type, model."""
    return [
        (e['EVENT_TYPE'].name, e['VALUE'], e['CACHE_TYPE'], e['MODEL_ID'])
        for e in gateway.event_rows
        if e['EVENT_TYPE'] in CACHE_EVENTS
    ]


# ── Exact cache ─────────────────────────────────────────────────────────────


def test_a_repeated_request_is_answered_from_the_cache(gateway):
    _serve_cached()
    upstream = mock_anthropic()

    first = send(gateway)
    second = send(gateway)

    assert first.status_code == second.status_code == 200
    assert len(upstream.matches) == 1
    assert CACHE_HIT not in first.headers
    assert second.headers[CACHE_HIT] == 'true'
    assert first.json() == second.json() == SERVED


def test_a_hit_on_a_streaming_request_is_a_valid_event_stream(gateway):
    _serve_cached()
    upstream = mock_anthropic()

    send(gateway)
    hit = send_stream(gateway)

    assert hit.status_code == 200
    assert len(upstream.matches) == 1
    assert hit.headers[CACHE_HIT] == 'true'
    assert hit.headers['content-type'].startswith('text/event-stream')
    assert [event for event, _ in stream_frames(hit.text)] == [
        'message_start',
        'content_block_start',
        'content_block_delta',
        'content_block_stop',
        'message_delta',
        'message_stop',
    ]
    assert _answer_of(hit) == {
        'model': ROUTE_NAME,
        'content': ANSWER['content'],
        'stop_reason': 'end_turn',
    }


def test_a_relayed_stream_that_ends_complete_is_cached(gateway):
    _serve_cached()
    upstream = mock_anthropic_stream()

    first = send_stream(gateway)
    as_json = send(gateway)
    as_stream = send_stream(gateway)

    assert first.status_code == as_json.status_code == as_stream.status_code == 200
    assert len(upstream.matches) == 1
    assert CACHE_HIT not in first.headers
    assert as_json.headers[CACHE_HIT] == as_stream.headers[CACHE_HIT] == 'true'
    assert as_json.json()['content'] == ANSWER['content']
    assert as_json.json()['model'] == ROUTE_NAME
    assert as_json.json()['stop_reason'] == 'end_turn'
    assert _answer_of(as_stream) == _answer_of(first)


def test_an_answer_that_calls_a_tool_is_cached_with_its_tool_use(gateway):
    _serve_cached()
    answer = canned.anthropic_message(
        'Let me check.', tool_use=[canned.ANTHROPIC_WEATHER_TOOL_USE]
    ).json_body
    upstream = mock_anthropic(answer)

    send(gateway)
    as_json = send(gateway)
    as_stream = send_stream(gateway)

    assert len(upstream.matches) == 1
    assert as_json.json() == {**answer, 'model': ROUTE_NAME}
    assert _answer_of(as_stream) == {
        'model': ROUTE_NAME,
        'content': [{'type': 'text', 'text': 'Let me check.'}, TOOL_USE],
        'stop_reason': 'tool_use',
    }


@pytest.mark.parametrize(
    'fields',
    [
        {'stream': True},
        {'metadata': {'user_id': 'someone-else'}},
        {'stream': True, 'metadata': {'user_id': 'someone-else'}},
    ],
    ids=['stream', 'metadata', 'both'],
)
def test_stream_and_metadata_do_not_change_the_cached_answer(gateway, fields):
    _serve_cached()
    upstream = mock_anthropic()

    send(gateway, {**BODY, 'metadata': {'user_id': 'someone'}})
    second = send(gateway, {**BODY, **fields})

    assert second.status_code == 200
    assert len(upstream.matches) == 1
    assert second.headers[CACHE_HIT] == 'true'


@pytest.mark.parametrize(
    'other',
    [
        _ask('Hello'),
        {**BODY, 'max_tokens': 2048},
        {**BODY, 'system': 'You are chatty.'},
        {**BODY, 'tools': [{'name': 'get_weather', 'input_schema': {}}]},
    ],
    ids=['question', 'max_tokens', 'system', 'tools'],
)
def test_a_different_request_is_not_a_hit(gateway, other):
    _serve_cached()
    first = mock_anthropic()
    second = mock_anthropic()

    send(gateway)
    response = send(gateway, other)

    assert response.status_code == 200
    assert first.isdone() and second.isdone()
    assert CACHE_HIT not in response.headers


@pytest.mark.parametrize('stream', [False, True], ids=['json', 'stream'])
def test_an_answer_cut_off_by_max_tokens_is_not_cached(gateway, stream):
    _serve_cached()
    if stream:
        cut_off = mock_anthropic_stream(_cut_off_stream())
    else:
        cut_off = mock_anthropic(_cut_off(ANSWER))
    complete = mock_anthropic()

    first = send(gateway, {**BODY, 'stream': stream})
    second = send(gateway)

    assert first.status_code == 200
    assert cut_off.isdone() and complete.isdone()
    assert CACHE_HIT not in second.headers
    assert second.json() == SERVED


@contextmanager
def _limit_counts():
    """Collect what the request counts on the limits."""
    counted = []
    count = RequestLimits.count

    async def spy(limits, usage):
        counted.append(usage)
        await count(limits, usage)

    with patch.object(RequestLimits, 'count', spy):
        yield counted


# The canned usage at Sonnet 4.5's prices: $3 and $15 per million tokens.
COUNTED = Usage(input_tokens=21, output_tokens=7, costs=(63000, 105000))
# The half of the tool's input that came before the cut.
PARTIAL_INPUT = '{"city": "Paris'


def test_a_relayed_stream_cut_inside_a_tool_use_is_relayed_and_counted(gateway):
    _serve_cached()
    mock_anthropic_stream(cut_off_tool_stream())
    complete = mock_anthropic()

    with _limit_counts() as counted:
        first = send_stream(gateway)
    second = send(gateway)

    assert first.status_code == 200
    frames = stream_frames(first.text)
    assert frames[-1][0] == 'message_stop'
    assert frames[-2][1]['delta']['stop_reason'] == 'max_tokens'
    assert [
        data['delta']['partial_json']
        for event, data in frames
        if event == 'content_block_delta'
        and data['delta']['type'] == 'input_json_delta'
    ] == [PARTIAL_INPUT]
    assert counted == [COUNTED]
    assert complete.isdone()
    assert CACHE_HIT not in second.headers


def test_a_buffered_stream_cut_inside_a_tool_use_is_a_valid_answer(gateway):
    """The tool use keeps no input: half a JSON text is not an input."""
    _serve_cached('output_warn')
    mock_anthropic_stream(cut_off_tool_stream())
    complete = mock_anthropic()

    with _limit_counts() as counted:
        first = send_stream(gateway)
    second = send(gateway)

    assert first.status_code == 200
    assert _answer_of(first) == {
        'model': ROUTE_NAME,
        'content': [
            {'type': 'text', 'text': 'Let me check.'},
            {**TOOL_USE, 'input': {}},
        ],
        'stop_reason': 'max_tokens',
    }
    assert counted == [COUNTED]
    assert complete.isdone()
    assert CACHE_HIT not in second.headers


@pytest.mark.parametrize('stream', [False, True], ids=['json', 'stream'])
def test_a_cut_off_answer_is_not_cached_when_a_soft_block_replaces_it(gateway, stream):
    _serve_cached('output_soft_block')
    if stream:
        cut_off = mock_anthropic_stream(_cut_off_stream('The secret is'))
    else:
        cut_off = mock_anthropic(_cut_off(_answer('The secret is')))
    complete = mock_anthropic()

    first = send(gateway, {**BODY, 'stream': stream})
    second = send(gateway)

    assert first.status_code == 200
    assert 'The answer was withheld.' in first.text
    assert cut_off.isdone() and complete.isdone()
    assert CACHE_HIT not in second.headers
    assert second.json() == SERVED


# ── Cache and output guardrails ─────────────────────────────────────────────


def test_a_hit_is_screened_by_the_output_guardrails(gateway):
    _serve_cached('output_warn')
    upstream = mock_anthropic(_answer('The secret is 42'))

    first = send(gateway)
    hit = send(gateway)

    assert len(upstream.matches) == 1
    assert hit.headers[CACHE_HIT] == 'true'
    assert hit.headers['X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-WARN'] == 'true'
    assert first.json() == hit.json()
    assert hit.json()['content'] == [{'type': 'text', 'text': 'The secret is 42'}]


def test_a_stream_the_output_guardrails_read_is_cached(gateway):
    _serve_cached('output_warn')
    upstream = mock_anthropic_stream()

    first = send_stream(gateway)
    as_json = send(gateway)
    as_stream = send_stream(gateway)

    assert first.status_code == as_json.status_code == as_stream.status_code == 200
    assert len(upstream.matches) == 1
    assert CACHE_HIT not in first.headers
    assert as_json.headers[CACHE_HIT] == as_stream.headers[CACHE_HIT] == 'true'
    assert as_json.json()['content'] == ANSWER['content']
    assert _answer_of(as_stream) == _answer_of(first)


def test_an_error_is_not_cached(gateway):
    _serve_cached()
    refused = refuse(400, {'type': 'error', 'error': {'type': 'x', 'message': 'no'}})
    answered = mock_anthropic()

    first = send(gateway)
    second = send(gateway)

    assert (first.status_code, second.status_code) == (400, 200)
    assert refused.isdone() and answered.isdone()
    assert CACHE_HIT not in second.headers


@pytest.mark.parametrize(
    'entry',
    [
        json.dumps({'object': 'chat.completion', 'choices': []}),
        json.dumps({'object': 'response', 'status': 'completed', 'output': []}),
        json.dumps(['message']),
        'not json',
    ],
    ids=['chat', 'responses', 'not_an_object', 'not_json'],
)
def test_an_entry_that_is_not_a_message_is_a_miss(gateway, entry):
    route = _serve_cached()
    upstream = mock_anthropic()

    with patch.object(route.gateway_cache, 'get', AsyncMock(return_value=entry)):
        response = send(gateway)

    assert response.status_code == 200
    assert upstream.isdone()
    assert CACHE_HIT not in response.headers
    assert response.json() == SERVED


# ── What the gateway records ────────────────────────────────────────────────


def test_a_hit_records_the_cache_events_and_no_model_event(gateway):
    _serve_cached()
    mock_anthropic(canned.anthropic_message(input_tokens=21, cache_read=4).json_body)

    send(gateway)
    assert _cache_events(gateway) == []
    send(gateway)

    # The saved input tokens count the answer's prompt cache reads too.
    assert _cache_events(gateway) == [
        ('CACHE_HIT', 1.0, 'in-memory', 'claude'),
        ('CACHE_INPUT_TOKENS', 25.0, 'in-memory', 'claude'),
        ('CACHE_OUTPUT_TOKENS', 7.0, 'in-memory', 'claude'),
    ]
    model_events = {
        EventType.MODEL_INVOCATION,
        EventType.INPUT_TOKEN_PROCESSED,
        EventType.OUTPUT_TOKEN_PROCESSED,
    }
    assert not [e for e in gateway.event_rows if e['EVENT_TYPE'] in model_events]


@pytest.mark.parametrize('stream', [False, True], ids=['json', 'stream'])
def test_a_hit_does_not_count_on_the_limits(gateway, stream):
    counted = []
    count = RequestLimits.count

    async def spy(limits, usage):
        counted.append(usage)
        await count(limits, usage)

    _serve_cached()
    mock_anthropic()

    with patch.object(RequestLimits, 'count', spy):
        send(gateway)
        hit = send(gateway, {**BODY, 'stream': stream})

    assert hit.headers[CACHE_HIT] == 'true'
    # Only the answer the model gave: Sonnet 4.5's prices are $3 and $15 per
    # million tokens.
    assert counted == [Usage(input_tokens=21, output_tokens=7, costs=(63000, 105000))]


# ── Semantic cache ──────────────────────────────────────────────────────────

DIM = 4


def _serve_semantic() -> GatewayRoute:
    """Serve the route on Claude with a semantic cache on a fake Redis search
    index, embedding with OpenAI.
    """
    route = serve(
        CLAUDE,
        embedding_models=['emb'],
        caching={'type': 'semantic', 'embedding_model_id': 'emb', 'dim': DIM},
        config={'embedding_models': [EMBEDDING], **REDIS},
        # The semantic index filters its entries by project.
        project_uuid=str(TEST_PROJECT_UUID),
    )

    async def build() -> SemanticCache:
        cache = SemanticCache(
            redis_client=FakeSearchRedis(),
            similarity_threshold=0.8,
            dim=DIM,
            distance_metric='cosine',
        )
        # The constructor creates the index in the background.
        await asyncio.gather(*list(cache._background_tasks))
        return cache

    route.gateway_cache = GatewayCache(asyncio.run(build()))
    route.cache = RouteCache.from_config(
        route.gateway_route_config,
        route.gateway_cache,
        route.cost_service,
        route.embedding_invoker,
        route.embedding_models,
    )
    return route


def _embedded(mock) -> list[str]:
    """Return the texts an embeddings mock was asked for. The OpenAI client
    sends each as its tokens.
    """
    encoding = tiktoken.get_encoding('cl100k_base')
    return [encoding.decode(tokens) for tokens in sent_body(mock)['input']]


def _stored(route: GatewayRoute) -> dict:
    """Return the entries of the route's semantic index."""
    return route.gateway_cache.cache_client.redis_client.hashes


def test_semantic_cache_hits_on_a_similar_request(gateway):
    route = _serve_semantic()
    upstream = mock_anthropic()
    first_embedding = mock_embedding(1, 0, 0, 0)
    second_embedding = mock_embedding(0.98, 0.2, 0, 0)
    history = [
        {'role': 'user', 'content': 'Earlier question'},
        {'role': 'assistant', 'content': 'Earlier answer'},
    ]

    first = send(
        gateway,
        {**BODY, 'messages': [*history, {'role': 'user', 'content': 'Hi there'}]},
    )
    second = send(gateway, _ask('Hello there'))

    assert first.status_code == second.status_code == 200
    assert len(upstream.matches) == 1
    assert CACHE_HIT not in first.headers
    assert second.headers[CACHE_HIT] == 'true'
    assert second.json() == SERVED
    # The last user text is embedded, by the route's OpenAI embedding model.
    assert _embedded(first_embedding) == ['Hi there']
    assert sent_body(first_embedding)['model'] == 'text-embedding-3-small'
    assert _embedded(second_embedding) == ['Hello there']
    assert _cache_events(gateway)[0] == ('CACHE_HIT', 1.0, 'semantic', 'claude')
    assert len(_stored(route)) == 1


def test_semantic_cache_misses_on_a_request_that_is_not_similar(gateway):
    _serve_semantic()
    first = mock_anthropic()
    second = mock_anthropic()
    mock_embedding(1, 0, 0, 0)
    mock_embedding(0, 1, 0, 0)

    send(gateway, _ask('Hi there'))
    response = send(gateway, _ask('What is the capital of France?'))

    assert response.status_code == 200
    assert first.isdone() and second.isdone()
    assert CACHE_HIT not in response.headers


def test_semantic_cache_is_skipped_without_an_embedding_model(gateway):
    # The config refuses a semantic cache on a route with no embedding model:
    # the route loses its model after it is built.
    route = _serve_semantic()
    route.cache = RouteCache.from_config(
        route.gateway_route_config, route.gateway_cache, route.cost_service
    )
    first = mock_anthropic()
    second = mock_anthropic()
    embeddings = mock_embedding(1, 0, 0, 0)

    send(gateway)
    response = send(gateway)

    assert response.status_code == 200
    assert first.isdone() and second.isdone()
    assert not embeddings.matches
    assert _stored(route) == {}
    assert CACHE_HIT not in response.headers


def test_semantic_cache_is_skipped_when_the_last_user_turn_has_no_text(gateway):
    route = _serve_semantic()
    first = mock_anthropic()
    second = mock_anthropic()
    embeddings = mock_embedding(1, 0, 0, 0)
    body = {
        **BODY,
        'messages': [
            {'role': 'user', 'content': 'Weather in Paris?'},
            {'role': 'assistant', 'content': [TOOL_USE]},
            {
                'role': 'user',
                'content': [
                    {
                        'type': 'tool_result',
                        'tool_use_id': TOOL_USE['id'],
                        'content': '12 degrees',
                    }
                ],
            },
        ],
    }

    send(gateway, body)
    response = send(gateway, body)

    assert response.status_code == 200
    assert first.isdone() and second.isdone()
    assert not embeddings.matches
    assert _stored(route) == {}
    assert CACHE_HIT not in response.headers


def test_a_chat_entry_is_not_served_to_a_messages_client(gateway):
    """A semantic cache shares a route's entries between endpoints: the same
    text asked on Chat Completions first is a miss on Messages.
    """
    _serve_semantic()
    for_chat = mock_anthropic()
    for_messages = mock_anthropic()
    mock_embedding(1, 0, 0, 0)
    mock_embedding(1, 0, 0, 0)

    chat = gateway.chat(route='assistant', text='Hi')
    response = send(gateway, _ask('Hi'))

    assert chat.status_code == response.status_code == 200
    assert for_chat.isdone() and for_messages.isdone()
    assert CACHE_HIT not in response.headers
    assert response.json() == SERVED


def test_a_messages_entry_is_not_served_to_a_chat_client(gateway):
    _serve_semantic()
    for_messages = mock_anthropic()
    for_chat = mock_anthropic()
    mock_embedding(1, 0, 0, 0)
    mock_embedding(1, 0, 0, 0)

    response = send(gateway, _ask('Hi'))
    chat = gateway.chat(route='assistant', text='Hi')

    assert response.status_code == chat.status_code == 200
    assert for_messages.isdone() and for_chat.isdone()
    assert CACHE_HIT not in chat.headers
    assert chat.json()['object'] == 'chat.completion'
    assert chat.json()['choices'][0]['message']['content'] == 'Hello from the model'


def test_exact_chat_and_messages_entries_for_the_same_text_do_not_collide(gateway):
    _serve_cached()
    for_chat = mock_anthropic()
    for_messages = mock_anthropic()

    gateway.chat(route='assistant', text='Hi')
    response = send(gateway, _ask('Hi'))
    chat = gateway.chat(route='assistant', text='Hi')
    again = send(gateway, _ask('Hi'))

    assert for_chat.isdone() and for_messages.isdone()
    assert CACHE_HIT not in response.headers
    # Each endpoint then hits its own entry.
    assert chat.headers[CACHE_HIT] == again.headers[CACHE_HIT] == 'true'
    assert chat.json()['object'] == 'chat.completion'
    assert again.json() == SERVED
