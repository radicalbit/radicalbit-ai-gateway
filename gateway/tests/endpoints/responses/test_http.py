"""POST /v1/responses through a real route: the request reaches the model with
the route's policies applied, and the client gets the model's response.

The routes are built from a project config and served on the real app
(``open_gateway``). The OpenAI provider and its SDK are real; OpenAI is mocked
over HTTP with pook. Mistral stands for a provider without the Responses API.
"""

import copy
import json
from unittest.mock import AsyncMock, MagicMock, patch

from openai.types.create_embedding_response import CreateEmbeddingResponse, Usage
from openai.types.embedding import Embedding
from openai.types.responses import Response
import pook
import pytest

from tests.common.gateway_harness import build_routes, open_gateway
from tests.common.limits import project_limit
from tests.common.responses_api import OPENCODE_TURN, events_of
from tests.common.scope import scope_of

from radicalbit_ai_gateway.caching.gateway_cache import GatewayCache
from radicalbit_ai_gateway.caching.in_memory_cache import CacheToolsInMemory
from radicalbit_ai_gateway.caching.route_cache import RouteCache
from radicalbit_ai_gateway.endpoints.chat_completions.cache import ChatEntry
from radicalbit_ai_gateway.limiting.limits import Demand, RequestLimits
from radicalbit_ai_gateway.llm.messages import HumanMessage
from radicalbit_ai_gateway.models.caching import CacheType
from radicalbit_ai_gateway.models.guardrails import GuardrailType
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.server import app

PROJECT_LIMITS = 'radicalbit_ai_gateway.endpoints.common.admission.load_project_limits'
ROUTE = 'agents'
ROUTE_KEY = f'proj/{ROUTE}'
OPENAI_URL = 'https://api.openai.com/v1/responses'
MISTRAL_URL = 'https://api.mistral.ai/v1/chat/completions'

OPENAI = {
    'model_id': 'openai',
    'model': 'openai/gpt-6-luna',
    'credentials': {'api_key': 'sk-test'},
}
BACKUP = {
    'model_id': 'backup',
    'model': 'openai/gpt-6-sol',
    'credentials': {'api_key': 'sk-test'},
}
# A provider without the Responses API.
MISTRAL = {
    'model_id': 'mistral',
    'model': 'mistralai/mistral-large-latest',
    'credentials': {'api_key': 'mistral-key'},
}

MESSAGE = {
    'id': 'msg_1',
    'type': 'message',
    'status': 'completed',
    'role': 'assistant',
    'content': [
        {'type': 'output_text', 'annotations': [], 'logprobs': [], 'text': 'Hello'}
    ],
}


def upstream_events(text: str = 'Hello') -> list[dict]:
    """Return a reply as OpenAI streams it."""
    message = copy.deepcopy(MESSAGE)
    message['content'][0]['text'] = text
    started = {
        'id': 'resp_1',
        'object': 'response',
        'created_at': 1,
        'model': 'gpt-6-luna',
        'status': 'in_progress',
        'output': [],
        'tools': [],
        'tool_choice': 'auto',
        'parallel_tool_calls': True,
    }
    completed = {
        **started,
        'status': 'completed',
        'completed_at': 2,
        'output': [message],
        'usage': {
            'input_tokens': 100,
            'input_tokens_details': {'cached_tokens': 40, 'cache_write_tokens': 0},
            'output_tokens': 7,
            'output_tokens_details': {'reasoning_tokens': 0},
            'total_tokens': 107,
        },
    }
    where = {'item_id': 'msg_1', 'output_index': 0, 'content_index': 0}
    return [
        {'type': 'response.created', 'response': started, 'sequence_number': 0},
        {
            'type': 'response.output_item.added',
            'item': {**message, 'status': 'in_progress', 'content': []},
            'output_index': 0,
            'sequence_number': 1,
        },
        {
            'type': 'response.output_text.delta',
            **where,
            'delta': text,
            'logprobs': [],
            'obfuscation': 'xY',
            'sequence_number': 2,
        },
        {
            'type': 'response.output_item.done',
            'item': message,
            'output_index': 0,
            'sequence_number': 3,
        },
        {'type': 'response.completed', 'response': completed, 'sequence_number': 4},
    ]


def _guardrail(name, type_, behavior, where, parameters, message=None) -> dict:
    guardrail = {
        'name': name,
        'type': type_,
        'behavior': behavior,
        'where': where,
        'parameters': parameters,
    }
    if message:
        guardrail['response_message'] = message
    return guardrail


GUARDRAILS = [
    _guardrail(
        'input_soft_block',
        'starts_with',
        'soft_block',
        'input',
        {'values': ['Forbidden']},
        'I cannot help with that.',
    ),
    _guardrail('input_block', 'contains', 'block', 'input', {'values': ['explosive']}),
    _guardrail(
        'redact_email',
        'presidio_anonymizer',
        'block',
        'io',
        {'entities': ['EMAIL_ADDRESS']},
    ),
    _guardrail(
        'output_soft_block',
        'contains',
        'soft_block',
        'output',
        {'values': ['secret']},
        'The answer was withheld.',
    ),
    _guardrail('output_warn', 'contains', 'warn', 'output', {'values': ['secret']}),
]


def _routes(
    *models: dict,
    guardrails: list[str] | None = None,
    cache: bool = False,
    responses: dict | None = None,
    prompt: str | None = None,
) -> dict:
    """Build the ``agents`` route over ``models``: the first is the primary,
    the others its fallbacks. ``prompt`` is the primary's configured prompt.
    """
    model_ids = [model['model_id'] for model in models]
    chat_models = [
        {**model, 'prompt': prompt} if prompt and index == 0 else model
        for index, model in enumerate(models)
    ]
    route: dict = {'chat_models': model_ids}
    if len(model_ids) > 1:
        route['fallback'] = [{'target': model_ids[0], 'fallbacks': model_ids[1:]}]
    if guardrails:
        route['guardrails'] = guardrails
    if cache:
        route['caching'] = {'type': 'exact'}
    if responses:
        route['responses'] = responses
    config = {
        'chat_models': chat_models,
        'guardrails': GUARDRAILS,
        'routes': {ROUTE: route},
    }
    if cache:
        # No Redis client in these tests: an exact cache falls back to in-memory.
        config['cache'] = {'redis_host': 'localhost', 'redis_port': 6379}
    return build_routes(config)


@pytest.fixture
def gateway():
    with open_gateway(_routes(OPENAI), use_pook=True) as gateway:
        yield gateway


def _serve(*models: dict, **route: object):
    """Serve the ``agents`` route for the rest of the test (``open_gateway``
    puts the routes back); return it.
    """
    app.state.routes = _routes(*models, **route)
    return app.state.routes[ROUTE_KEY]


def _send(gateway, **body):
    """Send a Responses request to the ``agents`` route."""
    return gateway.post('/v1/responses', json={'model': ROUTE_KEY, **body})


def _sse(events: list[dict]) -> str:
    return ''.join(f'event: {e["type"]}\ndata: {json.dumps(e)}\n\n' for e in events)


def _mock_openai(text: str = 'Hello', times: int = 1):
    """Mock OpenAI answering ``text``, as a response object."""
    mock = pook.post(OPENAI_URL).times(times)
    mock.reply(200).json(upstream_events(text)[-1]['response'])
    return mock


def _mock_openai_stream(text: str = 'Hello'):
    """Mock OpenAI streaming ``text``."""
    mock = pook.post(OPENAI_URL).times(1)
    mock.reply(200).header('Content-Type', 'text/event-stream').body(
        _sse(upstream_events(text))
    )
    return mock


def _mock_reply(text: str, stream: bool):
    return _mock_openai_stream(text) if stream else _mock_openai(text)


def _refuse(status: int, body: dict):
    mock = pook.post(OPENAI_URL).times(1)
    mock.reply(status).json(body)
    return mock


def _mock_every_upstream() -> list:
    """Mock every upstream, to check later that none was called."""
    mocks = []
    for url in (OPENAI_URL, MISTRAL_URL):
        mock = pook.post(url).times(1)
        mock.reply(500).json({})
        mocks.append(mock)
    return mocks


def _sent(mock, index: int = 0) -> dict:
    """Return the JSON body of a request a pook mock matched."""
    return mock.matches[index].json


def stream_events(response) -> list[dict]:
    return events_of(response.text.split('\n\n')[:-1])


def _final(response, stream: bool) -> dict:
    """Return the response object a reply ends with, streamed or not."""
    return stream_events(response)[-1]['response'] if stream else response.json()


def _deltas(response) -> list[str]:
    return [
        e['delta']
        for e in stream_events(response)
        if e['type'] == 'response.output_text.delta'
    ]


OPENCODE_REQUEST = {
    'instructions': 'You are opencode.',
    'input': OPENCODE_TURN,
    'store': False,
    'include': ['reasoning.encrypted_content'],
    'reasoning': {'effort': 'medium', 'summary': 'auto'},
    'text': {'verbosity': 'low'},
    'prompt_cache_key': 'ses_1',
    'tools': [{'type': 'function', 'name': 'read', 'parameters': {}}],
}


# ── Pass-through ──────────────────────────────────────────────────────────


def test_request_goes_upstream_as_sent(gateway):
    upstream = _mock_openai()

    with patch.object(RequestLimits, 'count', autospec=True) as count:
        response = _send(gateway, **OPENCODE_REQUEST)

    assert response.status_code == 200
    # An OpenAI upstream gets its own history back unchanged.
    assert _sent(upstream) == {**OPENCODE_REQUEST, 'model': 'gpt-6-luna'}
    data = response.json()
    assert data['model'] == ROUTE
    assert data['output'] == [MESSAGE]
    usage = count.call_args.args[1]
    assert (usage.input_tokens, usage.output_tokens) == (100, 7)


def test_stream_is_relayed_as_sent(gateway):
    events = upstream_events()
    upstream = _mock_openai_stream()

    with patch.object(RequestLimits, 'count', autospec=True) as count:
        response = _send(gateway, **OPENCODE_REQUEST, stream=True)

    assert response.status_code == 200
    assert _sent(upstream) == {
        **OPENCODE_REQUEST,
        'model': 'gpt-6-luna',
        'stream': True,
    }
    received = stream_events(response)
    # Only the response's model changes: it is the route
    assert [e['type'] for e in received] == [e['type'] for e in events]
    assert received[2] == events[2]
    assert received[-1]['response'] == {**events[-1]['response'], 'model': ROUTE}
    assert count.call_args.args[1].output_tokens == 7


def test_configured_prompt_goes_first(gateway):
    _serve(OPENAI, prompt='Answer in Italian.')
    upstream = _mock_openai()

    _send(gateway, input='Hi')

    assert _sent(upstream)['input'] == [
        {'type': 'message', 'role': 'system', 'content': 'Answer in Italian.'},
        {'type': 'message', 'role': 'user', 'content': 'Hi'},
    ]


# ── Specification ─────────────────────────────────────────────────────────


def test_input_is_optional(gateway):
    upstream = _mock_openai()

    response = _send(gateway, prompt={'id': 'pmpt_1'})

    assert response.status_code == 200
    assert _sent(upstream) == {'model': 'gpt-6-luna', 'prompt': {'id': 'pmpt_1'}}


def test_invalid_request_is_an_openai_error(gateway):
    response = _send(gateway, input='Hi', temperature='hot')

    assert response.status_code == 400
    error = response.json()['error']
    assert error['type'] == 'invalid_request_error'
    assert error['param'] == 'temperature'
    assert error['message'].startswith('Invalid value for temperature')


def test_background_mode_is_refused(gateway):
    upstreams = _mock_every_upstream()

    response = _send(gateway, input='Hi', background=True)

    assert response.status_code == 400
    assert 'Background mode' in response.json()['error']['message']
    assert not any(upstream.matched for upstream in upstreams)


@pytest.mark.parametrize(
    ('method', 'path'),
    [
        ('get', '/v1/responses/resp_1'),
        ('delete', '/v1/responses/resp_1'),
        ('post', '/v1/responses/resp_1/cancel'),
        ('get', '/v1/responses/resp_1/input_items'),
        ('post', '/v1/responses/compact'),
        ('post', '/v1/responses/input_tokens'),
    ],
)
def test_endpoints_not_served_say_so(method, path):
    with open_gateway() as gateway:
        response = getattr(gateway.client, method)(path)

    assert response.status_code == 404
    error = response.json()['error']
    assert error['message'] == (
        f'{method.upper()} {path} is not supported by the gateway yet'
    )


def test_model_without_responses_api_is_refused(gateway):
    _serve(MISTRAL)
    upstreams = _mock_every_upstream()

    response = _send(gateway, input='Hi')

    assert response.status_code == 400
    message = response.json()['error']['message']
    assert message == 'Model mistral of route agents does not serve the Responses API'
    assert not any(upstream.matched for upstream in upstreams)


@pytest.mark.parametrize('stream', [False, True], ids=['complete', 'stream'])
def test_upstream_refusal_reaches_the_client_as_sent(gateway, stream):
    body = {'error': {'message': 'context_length_exceeded', 'type': 'x'}}
    _refuse(400, body)

    response = _send(gateway, input='Hi', stream=stream)

    assert (response.status_code, response.json()) == (400, body)


@pytest.mark.parametrize('stream', [False, True], ids=['complete', 'stream'])
@pytest.mark.parametrize('status', [401, 403])
def test_upstream_access_refusal_is_a_bad_gateway_without_its_body(
    gateway, status, stream
):
    body = {'error': {'message': 'Incorrect API key provided: sk-1****', 'type': 'x'}}
    _refuse(status, body)

    response = _send(gateway, input='Hi', stream=stream)

    assert response.status_code == 502
    assert 'sk-1' not in response.text
    assert "refused the gateway's credentials" in response.text


# ── Fallback and stored state ─────────────────────────────────────────────

UNAVAILABLE = {'error': {'message': 'busy', 'type': 'server_error'}}


def test_fallback_skips_models_without_responses_api(gateway):
    _serve(OPENAI, MISTRAL, BACKUP)
    _refuse(503, UNAVAILABLE)
    mistral = pook.post(MISTRAL_URL).times(1)
    mistral.reply(500).json({})
    backup = _mock_openai()

    response = _send(gateway, input='Hi')

    assert response.status_code == 200
    assert not mistral.matched
    assert _sent(backup) == {'model': 'gpt-6-sol', 'input': 'Hi'}


def test_stored_state_has_no_fallback(gateway):
    _serve(OPENAI, BACKUP)
    _refuse(503, UNAVAILABLE)
    backup = _mock_openai()

    response = _send(gateway, input='Hi', previous_response_id='resp_0')

    assert response.status_code == 500
    assert not backup.matched


# ── Governance ────────────────────────────────────────────────────────────


def test_hosted_tool_not_allowed_is_refused(gateway):
    _serve(OPENAI, responses={'allowed_hosted_tools': ['file_search']})
    upstreams = _mock_every_upstream()

    response = _send(gateway, input='Hi', tools=[{'type': 'web_search'}])

    assert response.status_code == 400
    assert 'web_search' in response.json()['error']['message']
    assert not any(upstream.matched for upstream in upstreams)


def test_store_forced_false(gateway):
    _serve(OPENAI, responses={'force_store_false': True})
    upstream = _mock_openai(times=2)

    accepted = _send(gateway, input='Hi')
    refused = _send(gateway, input='Hi', previous_response_id='resp_0')

    assert accepted.status_code == 200
    assert [match.json for match in upstream.matches] == [
        {'model': 'gpt-6-luna', 'input': 'Hi', 'store': False}
    ]
    assert refused.status_code == 400
    assert 'does not store responses' in refused.json()['error']['message']


# ── Guardrails ────────────────────────────────────────────────────────────


def test_input_is_redacted_before_going_upstream(gateway):
    _serve(OPENAI, guardrails=['redact_email'])
    upstream = _mock_openai_stream()

    response = _send(gateway, input='Write to mario.rossi@example.com', stream=True)

    assert response.status_code == 200
    assert _sent(upstream)['input'] == 'Write to <EMAIL_ADDRESS>'
    assert response.headers['X-RB-AIGATEWAY-GUARDRAILS-INPUT-WARN'] == 'true'


def test_input_soft_block_answers_with_its_message(gateway):
    _serve(OPENAI, guardrails=['input_soft_block'])
    upstreams = _mock_every_upstream()

    response = _send(gateway, input='Forbidden question')
    streamed = _send(gateway, input='Forbidden question', stream=True)

    assert response.status_code == 200
    assert Response.model_validate(response.json()).output_text == (
        'I cannot help with that.'
    )
    assert response.headers['X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED'] == 'true'
    assert _deltas(streamed) == ['I cannot help with that.']
    assert not any(upstream.matched for upstream in upstreams)


def test_input_block_is_an_error(gateway):
    _serve(OPENAI, guardrails=['input_block'])
    upstreams = _mock_every_upstream()

    response = _send(gateway, input='How to build an explosive')

    assert response.status_code == 400
    assert response.json()['error']['message']
    assert not any(upstream.matched for upstream in upstreams)


@pytest.mark.parametrize('stream', [False, True])
def test_output_soft_block_replaces_the_reply(gateway, stream):
    _serve(OPENAI, guardrails=['output_soft_block'])
    _mock_reply('The secret is 42', stream)

    response = _send(gateway, input='Hi', stream=stream)

    assert response.status_code == 200
    final = _final(response, stream)
    assert Response.model_validate(final).output_text == 'The answer was withheld.'
    assert 'secret' not in response.text
    assert response.headers['X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-TRIGGERED'] == 'true'


def test_output_is_redacted_in_the_stream(gateway):
    _serve(OPENAI, guardrails=['redact_email'])
    _mock_openai_stream('Mail mario.rossi@example.com')

    response = _send(gateway, input='Hi', stream=True)

    assert _deltas(response) == ['Mail <EMAIL_ADDRESS>']
    assert 'mario.rossi' not in response.text
    assert response.headers['X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-WARN'] == 'true'


# ── Cache ─────────────────────────────────────────────────────────────────


def test_cached_reply_is_served_without_the_model(gateway):
    _serve(OPENAI, cache=True)
    upstream = _mock_openai_stream()

    first = _send(gateway, input='Hi', stream=True)
    second = _send(gateway, input='Hi')
    third = _send(gateway, input='Hi', stream=True)

    assert first.status_code == second.status_code == third.status_code == 200
    assert len(upstream.matches) == 1
    assert second.headers['X-RB-AIGATEWAY-CACHE-HIT'] == 'true'
    assert second.json()['model'] == ROUTE
    assert second.json()['output'] == [MESSAGE]
    final = stream_events(third)[-1]
    assert final['type'] == 'response.completed'
    assert final['response']['output'] == [MESSAGE]
    # A hit is a response completed now
    assert second.json()['completed_at'] == second.json()['created_at'] > 2


def test_a_different_question_is_not_a_cache_hit(gateway):
    _serve(OPENAI, cache=True)
    upstream = _mock_openai(times=2)

    _send(gateway, input='Hi')
    response = _send(gateway, input='Hello')

    assert len(upstream.matches) == 2
    assert 'X-RB-AIGATEWAY-CACHE-HIT' not in response.headers


async def test_chat_endpoint_ignores_a_responses_cache_entry():
    route = _routes(OPENAI, cache=True)[ROUTE_KEY]
    entry = json.dumps(upstream_events()[-1]['response'])

    with patch.object(route.gateway_cache, 'get', AsyncMock(return_value=entry)):
        cached = await scope_of(route).cache.lookup(
            ChatEntry([HumanMessage(content='Hi')])
        )

    assert not cached.hit


@pytest.mark.parametrize(
    'entry',
    [
        json.dumps({'object': 'chat.completion', 'choices': []}),
        'not json',
    ],
)
def test_an_entry_that_is_not_a_response_object_is_a_miss(gateway, entry):
    route = _serve(OPENAI, cache=True)
    upstream = _mock_openai()

    with patch.object(route.gateway_cache, 'get', AsyncMock(return_value=entry)):
        response = _send(gateway, input='Hi')

    assert response.status_code == 200
    assert len(upstream.matches) == 1
    assert 'X-RB-AIGATEWAY-CACHE-HIT' not in response.headers


class SemanticInMemoryCache(GatewayCache):
    """An in-memory cache that reads and writes as the semantic one does."""

    def __init__(self):
        super().__init__(CacheToolsInMemory())
        self.calls: list[tuple[str, dict]] = []

    @property
    def cache_type(self) -> CacheType:
        return CacheType.SEMANTIC

    async def get(self, cache_key: str, **kwargs) -> str | None:
        self.calls.append(('get', kwargs))
        return await super().get(cache_key, **kwargs)

    async def set(self, cache_key: str, response: str, ttl: int | None, **kwargs):
        self.calls.append(('set', kwargs))
        await super().set(cache_key, response, ttl, **kwargs)


def _serve_semantic(embedding_model: Model | None):
    """Serve the route with an in-memory semantic cache and a faked embedder."""
    route = _serve(OPENAI)
    route.gateway_cache = SemanticInMemoryCache()
    embedder = MagicMock()
    embedder.embed_answered = AsyncMock(
        return_value=(
            CreateEmbeddingResponse(
                object='list',
                data=[Embedding(index=0, embedding=[0.1, 0.2], object='embedding')],
                model='text-embedding-3-small',
                usage=Usage(prompt_tokens=1, total_tokens=1),
            ),
            embedding_model,
        )
    )
    route.cache = RouteCache(
        backend=route.gateway_cache,
        cost_service=route.cost_service,
        embedder=embedder,
        embedding_model=embedding_model,
    )
    return route


def test_semantic_cache_embeds_the_last_user_text(gateway):
    embedding_model = Model(
        model_id='embed',
        model='openai/text-embedding-3-small',
        credentials={'api_key': 'sk-test'},
    )
    route = _serve_semantic(embedding_model)
    upstream = _mock_openai()
    turn = [
        {'role': 'user', 'content': 'First question'},
        {'role': 'assistant', 'content': 'An answer'},
        {'role': 'user', 'content': 'Hi'},
    ]

    first = _send(gateway, input=turn)
    second = _send(gateway, input=turn)

    assert first.status_code == second.status_code == 200
    assert len(upstream.matches) == 1
    assert second.headers['X-RB-AIGATEWAY-CACHE-HIT'] == 'true'
    embedded = route.cache.embedder.embed_answered.call_args.kwargs
    assert embedded['input_texts'] == ['Hi']
    assert embedded['model_id'] == 'embed'
    assert [name for name, _ in route.gateway_cache.calls] == ['get', 'set', 'get']
    for _, kwargs in route.gateway_cache.calls:
        assert kwargs['embeddings'].tolist() == pytest.approx([0.1, 0.2])


def test_semantic_cache_without_embeddings_is_skipped(gateway):
    route = _serve_semantic(embedding_model=None)
    upstream = _mock_openai(times=2)

    _send(gateway, input='Hi')
    response = _send(gateway, input='Hi')

    assert response.status_code == 200
    assert len(upstream.matches) == 2
    assert route.gateway_cache.calls == []
    assert 'X-RB-AIGATEWAY-CACHE-HIT' not in response.headers


# ── Warn guardrails ───────────────────────────────────────────────────────


@pytest.mark.parametrize('stream', [False, True])
def test_output_warn_is_reported_and_the_reply_kept(gateway, stream):
    _serve(OPENAI, guardrails=['output_warn'])
    _mock_reply('The secret is 42', stream)

    response = _send(gateway, input='Hi', stream=stream)

    assert response.status_code == 200
    final = _final(response, stream)
    assert Response.model_validate(final).output_text == 'The secret is 42'
    assert response.headers['X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-WARN'] == 'true'
    assert 'X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED' not in response.headers


@pytest.mark.parametrize('stream', [False, True])
def test_output_warn_is_evaluated_once(gateway, stream):
    route = _serve(OPENAI, guardrails=['output_warn'])
    _mock_reply('The secret is 42', stream)
    mapping = route.guardrails.check._guardrail_check_mapping
    check = AsyncMock(wraps=mapping[GuardrailType.CONTAINS])
    mapping[GuardrailType.CONTAINS] = check

    response = _send(gateway, input='Hi', stream=stream)

    assert response.headers['X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-WARN'] == 'true'
    assert check.await_count == 1


# ── Limits ────────────────────────────────────────────────────────────────


def test_budget_limit_blocks_before_the_model(gateway):
    upstreams = _mock_every_upstream()

    with (
        patch(PROJECT_LIMITS, return_value=[project_limit(0)]),
        patch('radicalbit_ai_gateway.limiting.limits.emit_event') as emit_event,
    ):
        response = _send(gateway, input='Hi')

    assert response.status_code == 429
    assert not any(upstream.matched for upstream in upstreams)
    assert emit_event.call_args.args[0].route_name == ROUTE


@pytest.mark.parametrize('stream', [False, True])
def test_usage_is_counted_with_the_request_limits(gateway, stream):
    """A streamed reply is counted after the handler returns: still on the
    request's own limits, the project's included.
    """
    _mock_reply('Hello', stream)

    with (
        patch(PROJECT_LIMITS, return_value=[project_limit(10)]),
        patch.object(RequestLimits, 'count', autospec=True) as count,
    ):
        response = _send(gateway, input='Hi', stream=stream)

    assert response.status_code == 200
    request_limits = count.call_args.args[0]
    assert request_limits.applies(Demand(cost_room=True))


def test_the_unsupported_responses_paths_stay_out_of_the_openapi_schema():
    """They only answer 404; their operationId would change between
    processes, which a generated client cannot use.
    """
    assert '/v1/responses/{path}' not in app.openapi()['paths']
    assert '/v1/responses' in app.openapi()['paths']
