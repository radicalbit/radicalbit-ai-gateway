"""POST /v1/messages through a real route: the Anthropic Messages API, passed
through.

The routes are built from a project config and served on the real app
(``open_gateway``). The Anthropic provider and its SDK are real; Anthropic is
mocked over HTTP with pook. The tests check what the client and the provider
see, and what the request counts and records.
"""

import asyncio
import datetime
import json
from unittest.mock import patch

import pook
import pytest

from tests.common import db_mock, provider_responses as canned
from tests.common.gateway_harness import build_routes, open_gateway

from radicalbit_ai_gateway.limiting.limits import RequestLimits, Usage
from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.models.request_event_type import RequestStatus, RequestType
from radicalbit_ai_gateway.models.request_identity import RequestIdentity
from radicalbit_ai_gateway.server import app, key_service
from radicalbit_ai_gateway.utils.exceptions import (
    KeyNotFoundError,
    ModelInvokerBadRequest,
)

ROUTE_KEY = 'proj/assistant'
# What the answer's ``model`` shows, as on the Responses API.
ROUTE_NAME = 'assistant'
ANTHROPIC_URL = 'https://api.anthropic.com/v1/messages'
CONFIGURED_KEY = 'sk-ant-configured'
X_API_KEY = {'x-api-key': db_mock.PLAIN_KEY}

MISTRAL = {
    'model_id': 'mistral',
    'model': 'mistralai/mistral-large-latest',
    'credentials': {'api_key': 'mistral-key'},
}
CLAUDE = {
    'model_id': 'claude',
    'model': 'anthropic/claude-sonnet-4-5',
    'credentials': {'api_key': CONFIGURED_KEY},
}
HAIKU = {
    'model_id': 'haiku',
    'model': 'anthropic/claude-haiku-4-5',
    'credentials': {'api_key': CONFIGURED_KEY},
}
GPT = {
    'model_id': 'gpt',
    'model': 'openai/gpt-4o-mini',
    'credentials': {'api_key': 'sk-openai'},
}
EMBEDDING = {
    'model_id': 'emb',
    'model': 'openai/text-embedding-3-small',
    'credentials': {'api_key': 'sk-openai'},
}

# Every upstream a test route could call.
UPSTREAM_URLS = (
    ANTHROPIC_URL,
    'https://api.openai.com/v1/chat/completions',
    'https://api.openai.com/v1/responses',
    'https://api.mistral.ai/v1/chat/completions',
)

# What a Messages client sends, with a field no SDK knows yet.
BODY = {
    'model': ROUTE_KEY,
    'max_tokens': 1024,
    'system': 'You are terse.',
    'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': 'Hi'}]}],
    'future_field': {'kept': True},
}
# BODY as it goes upstream: only ``model`` swapped.
SENT = {**BODY, 'model': 'claude-sonnet-4-5'}

MODEL_EVENTS = {
    EventType.MODEL_INVOCATION,
    EventType.FALLBACK,
    EventType.INPUT_TOKEN_PROCESSED,
    EventType.OUTPUT_TOKEN_PROCESSED,
}


def _error(error_type: str, message: str) -> dict:
    """Return a Messages API error body."""
    return {'type': 'error', 'error': {'type': error_type, 'message': message}}


OVERLOADED = _error('overloaded_error', 'busy')


def _routes(
    *models: dict,
    route_models: list[str] | None = None,
    fallbacks: list[str] | None = None,
    routing: dict | None = None,
    **route: object,
) -> dict:
    """Build the ``assistant`` route over ``models``: by default, on the first."""
    route_models = route_models or [models[0]['model_id']]
    config_route: dict = {'chat_models': route_models, **route}
    if fallbacks:
        config_route['fallback'] = [{'target': route_models[0], 'fallbacks': fallbacks}]
    if routing:
        config_route['routing'] = routing['name']
    return build_routes(
        {
            'chat_models': list(models),
            'routing': [routing] if routing else None,
            'routes': {'assistant': config_route},
        }
    )


@pytest.fixture
def gateway():
    with open_gateway(_routes(CLAUDE), use_pook=True) as gateway:
        yield gateway


def _serve(*models: dict, **route: object) -> None:
    """Serve the ``assistant`` route over ``models`` for the rest of the test
    (``open_gateway`` puts the routes back).
    """
    app.state.routes = _routes(*models, **route)


def _serve_with_fallback(fallback: dict = HAIKU) -> None:
    _serve(
        CLAUDE,
        fallback,
        route_models=['claude', fallback['model_id']],
        fallbacks=[fallback['model_id']],
    )


def _send(gateway, body: dict | None = None, headers: dict | None = None):
    """Send a Messages request, with the credential as Anthropic clients send it."""
    return gateway.post(
        '/v1/messages',
        key=False,
        headers=X_API_KEY if headers is None else headers,
        json=body or BODY,
    )


def _stream(gateway, body: dict | None = None):
    return _send(gateway, {**(body or BODY), 'stream': True})


def _mock_anthropic(reply: dict | None = None, url: str = ANTHROPIC_URL):
    mock = pook.post(url).times(1)
    mock.reply(200).json(reply or canned.anthropic_message().json_body)
    return mock


def _mock_anthropic_stream(sse_text: str | None = None):
    mock = pook.post(ANTHROPIC_URL).times(1)
    mock.reply(200).header('Content-Type', 'text/event-stream').body(
        sse_text or canned.anthropic_stream().sse_text()
    )
    return mock


def _refuse(status: int, body: dict):
    mock = pook.post(ANTHROPIC_URL).times(1)
    mock.reply(status).json(body)
    return mock


def _mock_every_upstream() -> list:
    """Mock every upstream, to check later that none was called."""
    mocks = []
    for url in UPSTREAM_URLS:
        mock = pook.post(url).times(1)
        mock.reply(500).json({})
        mocks.append(mock)
    return mocks


def _sent(mock, index: int = 0) -> dict:
    """Return the JSON body of a request a pook mock matched."""
    return mock.matches[index].json


def _frames(text: str) -> list[tuple[str, dict]]:
    """Return the ``(event, data)`` pairs of an SSE body."""
    frames = []
    for block in text.strip().split('\n\n'):
        lines = dict(line.split(': ', 1) for line in block.splitlines())
        frames.append((lines['event'], json.loads(lines['data'])))
    return frames


def _shape(body: dict) -> dict:
    """Return a Messages API error body without its message."""
    return {'type': body['type'], 'error': {'type': body['error']['type']}}


def _model_events(gateway) -> list[tuple]:
    """Return the model events: type, model, target, fallback, value, cache type."""
    return [
        (
            e['EVENT_TYPE'].name,
            e.get('MODEL_ID') or None,
            e.get('TARGET') or None,
            e.get('FALLBACK') or None,
            e['VALUE'],
            e.get('CACHE_TYPE') or None,
        )
        for e in gateway.event_rows
        if e['EVENT_TYPE'] in MODEL_EVENTS
    ]


# ── Round trip ──────────────────────────────────────────────────────────────


def test_the_body_goes_upstream_as_sent_and_comes_back_with_the_route_name(gateway):
    reply = {**canned.anthropic_message().json_body, 'future_field': {'kept': True}}
    upstream = _mock_anthropic(reply)

    response = _send(gateway)

    assert response.status_code == 200
    assert _sent(upstream) == SENT
    assert response.json() == {**reply, 'model': ROUTE_NAME}


def test_anthropic_headers_go_upstream_with_the_configured_key(gateway):
    upstream = _mock_anthropic()

    response = _send(
        gateway,
        headers={
            **X_API_KEY,
            'anthropic-version': '2023-06-01',
            'anthropic-beta': 'interleaved-thinking-2025-05-14',
        },
    )

    assert response.status_code == 200
    sent = upstream.matches[0].headers
    assert sent['anthropic-version'] == '2023-06-01'
    assert sent['anthropic-beta'] == 'interleaved-thinking-2025-05-14'
    assert sent['x-api-key'] == CONFIGURED_KEY
    assert db_mock.PLAIN_KEY not in json.dumps(dict(sent))


def test_a_default_anthropic_version_is_sent_when_the_client_sets_none(gateway):
    upstream = _mock_anthropic()

    response = _send(gateway)

    assert response.status_code == 200
    assert upstream.matches[0].headers['anthropic-version'] == '2023-06-01'
    assert 'anthropic-beta' not in upstream.matches[0].headers


def test_a_model_with_a_custom_base_url_gets_the_request_there(gateway):
    _serve({**CLAUDE, 'params': {'base_url': 'https://claude.example.com'}})
    upstream = _mock_anthropic(url='https://claude.example.com/v1/messages')

    response = _send(gateway)

    assert response.status_code == 200
    assert upstream.isdone()


def test_config_params_are_not_merged_into_the_body(gateway):
    _serve({**CLAUDE, 'params': {'temperature': 0.1, 'max_tokens': 9}})
    upstream = _mock_anthropic()

    response = _send(gateway)

    assert response.status_code == 200
    assert _sent(upstream) == SENT


# Claude Code sends its system prompt as blocks, the last one cached.
CACHED_SYSTEM = [
    {'type': 'text', 'text': 'You are Claude Code.'},
    {'type': 'text', 'text': 'Project rules.', 'cache_control': {'type': 'ephemeral'}},
]


@pytest.mark.parametrize(
    ('system', 'sent_system'),
    [
        (
            'You are terse.',
            [
                {'type': 'text', 'text': 'Be kind.'},
                {'type': 'text', 'text': 'You are terse.'},
            ],
        ),
        (CACHED_SYSTEM, [{'type': 'text', 'text': 'Be kind.'}, *CACHED_SYSTEM]),
        (None, 'Be kind.'),
    ],
    ids=['first_in_the_system_prompt', 'before_a_cached_prompt', 'the_only_one'],
)
def test_the_configured_prompt_goes_first_in_the_system_prompt(
    gateway, system, sent_system
):
    _serve({**CLAUDE, 'prompt': 'Be kind.'})
    upstream = _mock_anthropic()
    body = {key: value for key, value in BODY.items() if key != 'system'}
    if system is not None:
        body['system'] = system

    response = _send(gateway, body)

    assert response.status_code == 200
    assert _sent(upstream) == {
        **body,
        'model': 'claude-sonnet-4-5',
        'system': sent_system,
    }


def test_blocks_without_text_pass_through_unchanged(gateway):
    body = {
        **BODY,
        'thinking': {'type': 'enabled', 'budget_tokens': 2048},
        'tools': [{'name': 'get_weather', 'input_schema': {'type': 'object'}}],
        'messages': [
            {
                'role': 'user',
                'content': [
                    {
                        'type': 'image',
                        'source': {
                            'type': 'base64',
                            'media_type': 'image/png',
                            'data': 'iVBORw0KGgo=',
                        },
                    },
                    {
                        'type': 'text',
                        'text': 'What is this?',
                        'cache_control': {'type': 'ephemeral'},
                    },
                ],
            },
            {
                'role': 'assistant',
                'content': [
                    {'type': 'thinking', 'thinking': 'Hm.', 'signature': 'sig'},
                    {
                        'type': 'tool_use',
                        'id': 'toolu_1',
                        'name': 'get_weather',
                        'input': {'city': 'Paris'},
                    },
                ],
            },
            {
                'role': 'user',
                'content': [
                    {
                        'type': 'tool_result',
                        'tool_use_id': 'toolu_1',
                        'content': 'Sunny',
                    }
                ],
            },
        ],
    }
    upstream = _mock_anthropic()

    response = _send(gateway, body)

    assert response.status_code == 200
    assert _sent(upstream) == {**body, 'model': 'claude-sonnet-4-5'}


# ── Auth ────────────────────────────────────────────────────────────────────


def test_a_bearer_credential_is_accepted(gateway):
    _mock_anthropic()

    response = _send(gateway, headers={'Authorization': f'Bearer {db_mock.PLAIN_KEY}'})

    assert response.status_code == 200


@pytest.mark.parametrize(
    ('headers', 'member', 'known', 'message'),
    [
        ({}, True, True, 'Missing API key'),
        ({'x-api-key': 'sk-rb-wrong'}, True, False, 'Incorrect API key provided.'),
        # Admission answers a non-member as it answers a wrong key.
        (X_API_KEY, False, True, 'Incorrect API key provided.'),
    ],
    ids=['missing', 'wrong', 'without_access_to_the_route'],
)
def test_a_refused_credential_is_an_authentication_error(
    gateway, headers, member, known, message
):
    gateway.member = member
    upstreams = _mock_every_upstream()

    with patch.object(
        key_service,
        'get_key_by_hashed_key',
        return_value=gateway.api_key,
        side_effect=None if known else KeyNotFoundError('no such key'),
    ):
        response = _send(gateway, headers=headers)

    assert response.status_code == 401
    assert response.json() == _error('authentication_error', message)
    assert not any(upstream.matched for upstream in upstreams)


def test_an_expired_credential_is_told_it_expired():
    expired = db_mock.get_sample_key_with_group(group_uuid=db_mock.GROUP_UUID)
    expired.expires_on = datetime.date(2020, 1, 1)

    with open_gateway(_routes(CLAUDE), api_key=expired, use_pook=True) as gateway:
        response = _send(gateway)

    assert response.status_code == 401
    assert response.json() == _error('authentication_error', 'API key has expired.')


# ── Errors ──────────────────────────────────────────────────────────────────


def test_an_unknown_route_is_a_bad_request_naming_it(gateway):
    response = _send(gateway, {**BODY, 'model': 'proj/nowhere'})

    assert response.status_code == 400
    assert response.json() == _error(
        'invalid_request_error',
        'The route name [proj/nowhere] was not found in the config',
    )


def test_a_route_without_chat_models_is_a_bad_request_naming_it(gateway):
    app.state.routes = build_routes(
        {
            'embedding_models': [EMBEDDING],
            'routes': {'assistant': {'embedding_models': ['emb']}},
        }
    )
    upstreams = _mock_every_upstream()

    response = _send(gateway)

    assert response.status_code == 400
    assert response.json() == _error(
        'invalid_request_error', 'Route assistant has no chat models defined'
    )
    assert not any(upstream.matched for upstream in upstreams)


def test_a_malformed_body_is_a_bad_request_in_the_messages_shape(gateway):
    body = {key: value for key, value in BODY.items() if key != 'max_tokens'}

    response = _send(gateway, body)

    assert response.status_code == 400
    assert response.json() == _error(
        'invalid_request_error', 'max_tokens: Field required'
    )


def test_a_body_that_is_not_json_is_a_bad_request(gateway):
    response = gateway.client.post(
        '/v1/messages',
        content=b'{not json',
        headers={**X_API_KEY, 'content-type': 'application/json'},
    )

    assert response.status_code == 400
    assert _shape(response.json()) == _shape(_error('invalid_request_error', ''))


@pytest.mark.parametrize(
    ('method', 'path'),
    [('POST', 'count_tokens'), ('PUT', 'batches/msgbatch_1')],
)
def test_an_unknown_sub_path_is_not_found_whatever_the_method(gateway, method, path):
    response = gateway.client.request(
        method, f'/v1/messages/{path}', json={}, headers=X_API_KEY
    )

    assert response.status_code == 404
    assert response.json() == _error(
        'not_found_error',
        f'{method} /v1/messages/{path} is not supported by the gateway',
    )


def test_the_unsupported_messages_paths_stay_out_of_the_openapi_schema():
    """They only answer 404; their operationId would change between
    processes, which a generated client cannot use.
    """
    assert '/v1/messages/{path}' not in app.openapi()['paths']
    assert '/v1/messages' in app.openapi()['paths']


@pytest.mark.parametrize('model', [MISTRAL, GPT], ids=['mistral', 'openai'])
def test_a_model_without_messages_api_is_refused_before_any_upstream_call(
    gateway, model
):
    _serve(model)
    upstreams = _mock_every_upstream()

    response = _send(gateway)

    assert response.status_code == 400
    assert response.json() == _error(
        'invalid_request_error',
        f'Model {model["model_id"]} of route assistant does not serve the Messages API',
    )
    assert not any(upstream.matched for upstream in upstreams)


@pytest.mark.parametrize(
    ('status', 'error_type'),
    [(400, 'invalid_request_error'), (404, 'not_found_error')],
)
def test_an_upstream_refusal_reaches_the_client_as_sent(gateway, status, error_type):
    refusal = {**_error(error_type, 'upstream says no'), 'request_id': 'req_1'}
    _refuse(status, refusal)

    response = _send(gateway)

    assert response.status_code == status
    assert response.json() == refusal


def test_an_upstream_refusal_without_a_json_body_is_relayed_as_an_api_error(gateway):
    pook.post(ANTHROPIC_URL).times(1).reply(413).body('<html>Too large</html>')

    response = _send(gateway)

    assert response.status_code == 413
    assert response.json() == _error('api_error', '<html>Too large</html>')


def test_the_sdk_does_not_retry(gateway):
    upstream = pook.post(ANTHROPIC_URL).times(3)
    upstream.reply(529).json(OVERLOADED)

    response = _send(gateway)

    assert response.status_code == 500
    assert len(upstream.matches) == 1


def test_an_upstream_server_error_without_fallback_is_an_api_error(gateway):
    _refuse(500, _error('api_error', 'boom'))

    response = _send(gateway)

    assert response.status_code == 500
    assert _shape(response.json()) == _shape(_error('api_error', ''))


# ── Streaming ───────────────────────────────────────────────────────────────


def test_a_stream_is_relayed_in_order_with_the_route_name(gateway):
    upstream_events = canned.anthropic_stream().sse_events
    upstream = _mock_anthropic_stream()

    response = _stream(gateway)

    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/event-stream')
    assert _sent(upstream) == {**SENT, 'stream': True}
    start = upstream_events[0]
    expected = [
        {**start, 'message': {**start['message'], 'model': ROUTE_NAME}},
        *upstream_events[1:],
    ]
    assert _frames(response.text) == [(e['type'], e) for e in expected]


def test_an_upstream_refusal_before_streaming_is_an_http_error(gateway):
    refusal = _error('invalid_request_error', 'no')
    _refuse(400, refusal)

    response = _stream(gateway)

    assert response.status_code == 400
    assert response.json() == refusal


def test_a_failure_before_streaming_is_an_http_error_in_the_messages_shape(gateway):
    _refuse(500, _error('api_error', 'boom'))

    response = _stream(gateway)

    assert response.status_code == 500
    assert _shape(response.json()) == _shape(_error('api_error', ''))


def test_a_failure_after_the_first_event_ends_with_an_error_event(gateway):
    start = canned.anthropic_stream().sse_events[0]
    _mock_anthropic_stream(
        f'event: message_start\ndata: {json.dumps(start)}\n\ndata: {{broken\n\n'
    )

    response = _stream(gateway)

    assert response.status_code == 200
    frames = _frames(response.text)
    assert [event for event, _ in frames] == ['message_start', 'error']
    assert frames[-1][1] == _error('api_error', 'Internal server error')


def test_an_upstream_error_event_after_the_first_event_reaches_the_client(gateway):
    start = canned.anthropic_stream().sse_events[0]
    overloaded = _error('overloaded_error', 'Overloaded')
    _mock_anthropic_stream(
        f'event: message_start\ndata: {json.dumps(start)}\n\n'
        f'event: error\ndata: {json.dumps(overloaded)}\n\n'
    )

    response = _stream(gateway)

    assert response.status_code == 200
    assert _frames(response.text)[-1] == ('error', overloaded)


# ── Fallback ────────────────────────────────────────────────────────────────


def test_a_server_error_falls_back_to_the_next_model(gateway):
    _serve_with_fallback()
    _refuse(529, OVERLOADED)
    upstream = _mock_anthropic()

    response = _send(gateway)

    assert response.status_code == 200
    assert _sent(upstream)['model'] == 'claude-haiku-4-5'
    assert response.json()['model'] == ROUTE_NAME


def test_a_stream_falls_back_before_the_first_event(gateway):
    _serve_with_fallback()
    _refuse(529, OVERLOADED)
    upstream = _mock_anthropic_stream()

    response = _stream(gateway)

    assert response.status_code == 200
    assert _sent(upstream)['model'] == 'claude-haiku-4-5'
    assert [event for event, _ in _frames(response.text)][-1] == 'message_stop'


def test_a_client_error_does_not_fall_back(gateway):
    _serve_with_fallback()
    refusal = _error('invalid_request_error', 'bad')
    _refuse(400, refusal)
    unused = _mock_anthropic()

    response = _send(gateway)

    assert response.status_code == 400
    assert response.json() == refusal
    assert not unused.matched


def test_a_refusal_by_the_fallback_reaches_the_client_as_sent(gateway):
    _serve_with_fallback()
    _refuse(529, OVERLOADED)
    refusal = _error('invalid_request_error', 'haiku says no')
    _refuse(400, refusal)

    response = _send(gateway)

    assert response.status_code == 400
    assert response.json() == refusal


def test_an_upstream_access_refusal_falls_back_to_the_next_model(gateway):
    _serve_with_fallback()
    _refuse(401, _error('authentication_error', 'bad key'))
    upstream = _mock_anthropic()

    response = _send(gateway)

    assert response.status_code == 200
    assert _sent(upstream)['model'] == 'claude-haiku-4-5'


def test_an_upstream_access_refusal_at_the_end_is_an_api_error(gateway):
    _serve_with_fallback()
    _refuse(529, OVERLOADED)
    _refuse(401, _error('authentication_error', 'bad key'))

    response = _send(gateway)

    assert response.status_code >= 500
    assert _shape(response.json()) == _shape(_error('api_error', ''))


def test_an_upstream_permission_refusal_without_fallback_is_an_api_error(gateway):
    _refuse(403, _error('permission_error', 'not allowed'))

    response = _send(gateway)

    assert response.status_code >= 500
    assert _shape(response.json()) == _shape(_error('api_error', ''))


@pytest.mark.parametrize('stream', [False, True], ids=['complete', 'stream'])
def test_a_fallback_to_a_model_without_messages_api_fails_naming_it(gateway, stream):
    _serve_with_fallback(MISTRAL)
    _refuse(529, OVERLOADED)

    response = _send(gateway, {**BODY, 'stream': stream})

    assert response.status_code == 400
    assert response.json() == _error(
        'invalid_request_error',
        'Model mistral of route assistant does not serve the Messages API',
    )


# ── Routing: it picks the model first, then the gateway checks it serves
# Messages ────────────────────────────────────────────────────────────────────

# Requests that mention code go to Claude, any other to Mistral.
BY_KEYWORD = {
    'name': 'by_keyword',
    'type': 'deterministic',
    'rule': 'keyword',
    'default_model_id': 'mistral',
    'output_mapping': [{'model_id': 'claude', 'conditions': ['code']}],
}


def _ask(gateway, text: str):
    _serve(MISTRAL, CLAUDE, route_models=['mistral', 'claude'], routing=BY_KEYWORD)
    return _send(gateway, {**BODY, 'messages': [{'role': 'user', 'content': text}]})


def test_a_request_routed_to_an_anthropic_model_is_served(gateway):
    upstream = _mock_anthropic()

    response = _ask(gateway, 'Review my code')

    assert response.status_code == 200
    assert upstream.isdone()


def test_a_request_routed_to_a_model_without_messages_api_is_refused(gateway):
    response = _ask(gateway, 'Tell me a joke')

    assert response.status_code == 400
    assert response.json() == _error(
        'invalid_request_error',
        'Model mistral of route assistant does not serve the Messages API',
    )


# ── A route whose models speak different APIs, without fallback ────────────


def test_a_messages_request_is_served_by_the_selected_anthropic_model(gateway):
    _serve(CLAUDE, MISTRAL, route_models=['claude', 'mistral'])
    upstream = _mock_anthropic()

    response = _send(gateway)

    assert response.status_code == 200
    assert upstream.isdone()


def test_chat_completions_to_the_anthropic_model_still_translate(gateway):
    _serve(CLAUDE, MISTRAL, route_models=['claude', 'mistral'])
    upstream = _mock_anthropic()

    response = gateway.chat(route='assistant', text='Hi')

    assert response.status_code == 200
    assert response.json()['choices'][0]['message']['content'] == (
        'Hello from the model'
    )
    assert _sent(upstream)['messages'] == [{'role': 'user', 'content': 'Hi'}]


# ── Request events ──────────────────────────────────────────────────────────


@pytest.mark.parametrize('stream', [False, True], ids=['complete', 'stream'])
def test_a_served_request_leaves_a_successful_chat_event(gateway, stream):
    if stream:
        _mock_anthropic_stream()
    else:
        _mock_anthropic()

    _send(gateway, {**BODY, 'stream': stream})

    [event] = gateway.request_events
    assert (
        event.route_name,
        event.request_type,
        event.status,
        event.http_status_code,
        event.is_streaming,
    ) == (ROUTE_NAME, RequestType.CHAT_COMPLETIONS, RequestStatus.SUCCESS, 200, stream)


def test_a_refused_request_leaves_a_failed_event(gateway):
    _send(gateway, headers={})

    [event] = gateway.request_events
    assert (event.status, event.http_status_code) == (RequestStatus.HANDLED_ERROR, 401)


# ── Limits and model events ─────────────────────────────────────────────────

INPUT_LIMIT = {'input': {'window_size': '1 minute', 'max_token': 3}}


def test_a_request_over_the_route_token_limit_is_refused_before_any_call(gateway):
    _serve(CLAUDE, token_limiting=INPUT_LIMIT)
    upstreams = _mock_every_upstream()

    response = _send(gateway)

    assert response.status_code == 429
    assert _shape(response.json()) == _shape(_error('rate_limit_error', ''))
    assert response.json()['error']['message'].startswith(
        'Input token limit exceeded: 3 tokens per 1 minute.'
    )
    assert not any(upstream.matched for upstream in upstreams)


# 21 input tokens, 4 read from the cache, 5 written to it for 5 minutes.
CACHED_REPLY = {'input_tokens': 21, 'cache_read': 4, 'cache_5m': 5}


def _mock_cached_reply(stream: bool):
    if stream:
        return _mock_anthropic_stream(
            canned.anthropic_stream(**CACHED_REPLY).sse_text()
        )
    return _mock_anthropic(canned.anthropic_message(**CACHED_REPLY).json_body)


@pytest.mark.parametrize('stream', [False, True], ids=['complete', 'stream'])
def test_a_reply_counts_its_tokens_on_the_limits(gateway, stream):
    """The input counted includes the cache reads and writes, as on chat."""
    counted = []
    count = RequestLimits.count

    async def spy(limits, usage):
        counted.append(usage)
        await count(limits, usage)

    _mock_cached_reply(stream)

    with patch.object(RequestLimits, 'count', spy):
        response = _send(gateway, {**BODY, 'stream': stream})

    assert response.status_code == 200
    # Sonnet 4.5's prices: $3 and $15 per million tokens.
    assert counted == [Usage(input_tokens=30, output_tokens=7, costs=(90000, 105000))]


@pytest.mark.parametrize('stream', [False, True], ids=['complete', 'stream'])
def test_a_reply_records_its_tokens_on_the_model_that_answered(gateway, stream):
    _serve_with_fallback()
    _refuse(529, OVERLOADED)
    _mock_cached_reply(stream)

    response = _send(gateway, {**BODY, 'stream': stream})

    assert response.status_code == 200
    assert _model_events(gateway) == [
        ('MODEL_INVOCATION', 'haiku', None, None, 1.0, None),
        ('INPUT_TOKEN_PROCESSED', 'haiku', None, None, 21.0, None),
        ('INPUT_TOKEN_PROCESSED', 'haiku', None, None, 4.0, 'read'),
        ('INPUT_TOKEN_PROCESSED', 'haiku', None, None, 5.0, 'creation'),
        ('OUTPUT_TOKEN_PROCESSED', 'haiku', None, None, 7.0, None),
        ('FALLBACK', None, 'claude', 'haiku', 1.0, None),
    ]


@pytest.mark.parametrize('stream', [False, True], ids=['complete', 'stream'])
def test_a_call_no_model_answered_is_recorded(gateway, stream):
    """As on every endpoint: main recorded a failed stream, not a failed call."""
    _refuse(500, _error('api_error', 'boom'))

    response = _send(gateway, {**BODY, 'stream': stream})

    assert response.status_code == 500
    assert _model_events(gateway) == [
        ('MODEL_INVOCATION', 'claude', None, None, 1.0, None),
    ]


# ── Thinking another provider signed: retried once without it ──────────────

# What Anthropic says when a thinking block was signed by another provider.
SIGNATURE_REFUSAL = {
    **_error(
        'invalid_request_error',
        'messages.1.content.0: Invalid `signature` in `thinking` block',
    ),
    'request_id': 'req_1',
}
FOREIGN_THINKING = {'type': 'thinking', 'thinking': 'Hm.', 'signature': 'deepseek'}
ANSWER = {'type': 'text', 'text': 'Hello'}
# A conversation another provider answered with thinking.
FOREIGN_HISTORY = {
    **BODY,
    'messages': [
        {'role': 'user', 'content': 'Hi'},
        {'role': 'assistant', 'content': [FOREIGN_THINKING, ANSWER]},
        {'role': 'user', 'content': 'And now?'},
    ],
}
# FOREIGN_HISTORY's messages without the old thinking.
STRIPPED_HISTORY = [
    {'role': 'user', 'content': 'Hi'},
    {'role': 'assistant', 'content': [ANSWER]},
    {'role': 'user', 'content': 'And now?'},
]


def test_a_signature_refusal_is_retried_without_the_old_thinking(gateway):
    first = _refuse(400, SIGNATURE_REFUSAL)
    retry = _mock_anthropic()

    response = _send(gateway, FOREIGN_HISTORY)

    assert response.status_code == 200
    assert _sent(first)['messages'] == FOREIGN_HISTORY['messages']
    assert _sent(retry) == {
        **FOREIGN_HISTORY,
        'model': 'claude-sonnet-4-5',
        'messages': STRIPPED_HISTORY,
    }


def test_a_signature_refusal_of_a_stream_is_retried_without_the_old_thinking(
    gateway,
):
    _refuse(400, SIGNATURE_REFUSAL)
    retry = _mock_anthropic_stream()

    response = _stream(gateway, FOREIGN_HISTORY)

    assert response.status_code == 200
    assert _sent(retry)['messages'][1] == {'role': 'assistant', 'content': [ANSWER]}
    assert [event for event, _ in _frames(response.text)][-1] == 'message_stop'


def test_the_thinking_of_a_running_tool_loop_stays_on_retry(gateway):
    tool_use = {
        'type': 'tool_use',
        'id': 'toolu_1',
        'name': 'get_weather',
        'input': {'city': 'Paris'},
    }
    own_thinking = {'type': 'thinking', 'thinking': 'Tool.', 'signature': 'own'}
    tool_loop = [
        {'role': 'assistant', 'content': [own_thinking, tool_use]},
        {
            'role': 'user',
            'content': [
                {'type': 'tool_result', 'tool_use_id': 'toolu_1', 'content': 'Sun'}
            ],
        },
    ]
    body = {**FOREIGN_HISTORY, 'messages': FOREIGN_HISTORY['messages'] + tool_loop}
    _refuse(400, SIGNATURE_REFUSAL)
    retry = _mock_anthropic()

    response = _send(gateway, body)

    assert response.status_code == 200
    assert _sent(retry)['messages'] == [*STRIPPED_HISTORY, *tool_loop]


def test_another_refusal_is_relayed_without_retry(gateway):
    refusal = _error('invalid_request_error', 'max_tokens: bad')
    _refuse(400, refusal)
    unused = _mock_anthropic()

    response = _send(gateway, FOREIGN_HISTORY)

    assert response.status_code == 400
    assert response.json() == refusal
    assert not unused.matched


def test_a_signature_refusal_with_nothing_to_strip_is_relayed_without_retry(
    gateway,
):
    only_thinking = {
        **BODY,
        'messages': [
            {'role': 'user', 'content': 'Hi'},
            {'role': 'assistant', 'content': [FOREIGN_THINKING]},
            {'role': 'user', 'content': 'And now?'},
        ],
    }
    _refuse(400, SIGNATURE_REFUSAL)
    unused = _mock_anthropic()

    response = _send(gateway, only_thinking)

    assert response.status_code == 400
    assert response.json() == SIGNATURE_REFUSAL
    assert not unused.matched


def test_a_refused_retry_is_relayed_as_sent(gateway):
    _refuse(400, SIGNATURE_REFUSAL)
    refusal = _error('invalid_request_error', 'still no')
    retry = _refuse(400, refusal)
    unused = _mock_anthropic()

    response = _send(gateway, FOREIGN_HISTORY)

    assert response.status_code == 400
    assert response.json() == refusal
    assert retry.matched
    assert not unused.matched


def test_a_refused_stream_retry_is_an_http_error_as_sent(gateway):
    _refuse(400, SIGNATURE_REFUSAL)
    retry = _refuse(400, SIGNATURE_REFUSAL)

    response = _stream(gateway, FOREIGN_HISTORY)

    assert response.status_code == 400
    assert response.json() == SIGNATURE_REFUSAL
    assert retry.matched


# ── The invoker's own checks, behind the route's support check ─────────────


def test_a_model_the_route_does_not_hold_does_not_serve_messages():
    invoker = _routes(CLAUDE)[ROUTE_KEY].chat_invoker

    assert not invoker.supports_messages('nowhere')


def test_the_invoker_refuses_a_model_without_messages_api():
    invoker = _routes(MISTRAL)[ROUTE_KEY].chat_invoker
    identity = RequestIdentity(
        request_uuid='r',
        route_name=ROUTE_NAME,
        api_key_uuid='k',
        api_key_name='key',
        group_uuid='g',
        group_name='group',
    )

    with pytest.raises(ModelInvokerBadRequest) as refused:
        asyncio.run(
            invoker.complete_messages(
                identity=identity, body=BODY, headers={}, model_id='mistral'
            )
        )

    assert refused.value.client_message == (
        'Chat model mistral does not serve the Messages API'
    )
