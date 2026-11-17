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
from tests.common.messages_api import (
    ANTHROPIC_URL,
    BODY,
    CLAUDE,
    CONFIGURED_KEY,
    EMBEDDING,
    GPT,
    MISTRAL,
    OVERLOADED,
    ROUTE_KEY,
    ROUTE_NAME,
    SENT,
    X_API_KEY,
    error_body,
    error_shape,
    messages_routes,
    mock_anthropic,
    mock_anthropic_stream,
    mock_every_upstream,
    model_events,
    refuse,
    send,
    send_stream,
    sent_body,
    serve,
    serve_with_fallback,
    stream_frames,
)
from tests.common.provider_recorder import CannedResponse

from radicalbit_ai_gateway.limiting.limits import RequestLimits, Usage
from radicalbit_ai_gateway.models.request_event_type import RequestStatus, RequestType
from radicalbit_ai_gateway.models.request_identity import RequestIdentity
from radicalbit_ai_gateway.server import app, key_service
from radicalbit_ai_gateway.utils.exceptions import (
    KeyNotFoundError,
    ModelInvokerBadRequest,
    ModelInvokerInternalError,
)


@pytest.fixture
def gateway():
    with open_gateway(messages_routes(CLAUDE), use_pook=True) as gateway:
        yield gateway


# ── Round trip ──────────────────────────────────────────────────────────────


def test_the_body_goes_upstream_as_sent_and_comes_back_with_the_route_name(gateway):
    reply = {**canned.anthropic_message().json_body, 'future_field': {'kept': True}}
    upstream = mock_anthropic(reply)

    response = send(gateway)

    assert response.status_code == 200
    assert sent_body(upstream) == SENT
    assert response.json() == {**reply, 'model': ROUTE_NAME}


def test_anthropic_headers_go_upstream_with_the_configured_key(gateway):
    upstream = mock_anthropic()

    response = send(
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
    upstream = mock_anthropic()

    response = send(gateway)

    assert response.status_code == 200
    assert upstream.matches[0].headers['anthropic-version'] == '2023-06-01'
    assert 'anthropic-beta' not in upstream.matches[0].headers


def test_a_model_with_a_custom_base_url_gets_the_request_there(gateway):
    serve({**CLAUDE, 'params': {'base_url': 'https://claude.example.com'}})
    upstream = mock_anthropic(url='https://claude.example.com/v1/messages')

    response = send(gateway)

    assert response.status_code == 200
    assert upstream.isdone()


def test_config_params_are_not_merged_into_the_body(gateway):
    serve({**CLAUDE, 'params': {'temperature': 0.1, 'max_tokens': 9}})
    upstream = mock_anthropic()

    response = send(gateway)

    assert response.status_code == 200
    assert sent_body(upstream) == SENT


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
    serve({**CLAUDE, 'prompt': 'Be kind.'})
    upstream = mock_anthropic()
    body = {key: value for key, value in BODY.items() if key != 'system'}
    if system is not None:
        body['system'] = system

    response = send(gateway, body)

    assert response.status_code == 200
    assert sent_body(upstream) == {
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
    upstream = mock_anthropic()

    response = send(gateway, body)

    assert response.status_code == 200
    assert sent_body(upstream) == {**body, 'model': 'claude-sonnet-4-5'}


# ── Auth ────────────────────────────────────────────────────────────────────


def test_a_bearer_credential_is_accepted(gateway):
    mock_anthropic()

    response = send(gateway, headers={'Authorization': f'Bearer {db_mock.PLAIN_KEY}'})

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
    upstreams = mock_every_upstream()

    with patch.object(
        key_service,
        'get_key_by_hashed_key',
        return_value=gateway.api_key,
        side_effect=None if known else KeyNotFoundError('no such key'),
    ):
        response = send(gateway, headers=headers)

    assert response.status_code == 401
    assert response.json() == error_body('authentication_error', message)
    assert not any(upstream.matched for upstream in upstreams)


def test_an_expired_credential_is_told_it_expired():
    expired = db_mock.get_sample_key_with_group(group_uuid=db_mock.GROUP_UUID)
    expired.expires_on = datetime.date(2020, 1, 1)

    with open_gateway(
        messages_routes(CLAUDE), api_key=expired, use_pook=True
    ) as gateway:
        response = send(gateway)

    assert response.status_code == 401
    assert response.json() == error_body('authentication_error', 'API key has expired.')


# ── Errors ──────────────────────────────────────────────────────────────────


def test_an_unknown_route_is_a_bad_request_naming_it(gateway):
    response = send(gateway, {**BODY, 'model': 'proj/nowhere'})

    assert response.status_code == 400
    assert response.json() == error_body(
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
    upstreams = mock_every_upstream()

    response = send(gateway)

    assert response.status_code == 400
    assert response.json() == error_body(
        'invalid_request_error', 'Route assistant has no chat models defined'
    )
    assert not any(upstream.matched for upstream in upstreams)


def test_a_malformed_body_is_a_bad_request_in_the_messages_shape(gateway):
    body = {key: value for key, value in BODY.items() if key != 'max_tokens'}

    response = send(gateway, body)

    assert response.status_code == 400
    assert response.json() == error_body(
        'invalid_request_error', 'max_tokens: Field required'
    )


def test_a_body_that_is_not_json_is_a_bad_request(gateway):
    response = gateway.client.post(
        '/v1/messages',
        content=b'{not json',
        headers={**X_API_KEY, 'content-type': 'application/json'},
    )

    assert response.status_code == 400
    assert error_shape(response.json()) == error_shape(
        error_body('invalid_request_error', '')
    )


@pytest.mark.parametrize(
    ('method', 'path'),
    [('POST', 'count_tokens'), ('PUT', 'batches/msgbatch_1')],
)
def test_an_unknown_sub_path_is_not_found_whatever_the_method(gateway, method, path):
    response = gateway.client.request(
        method, f'/v1/messages/{path}', json={}, headers=X_API_KEY
    )

    assert response.status_code == 404
    assert response.json() == error_body(
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
    serve(model)
    upstreams = mock_every_upstream()

    response = send(gateway)

    assert response.status_code == 400
    assert response.json() == error_body(
        'invalid_request_error',
        f'Model {model["model_id"]} of route assistant does not serve the Messages API',
    )
    assert not any(upstream.matched for upstream in upstreams)


@pytest.mark.parametrize(
    ('status', 'error_type'),
    [(400, 'invalid_request_error'), (404, 'not_found_error')],
)
def test_an_upstream_refusal_reaches_the_client_as_sent(gateway, status, error_type):
    refusal = {**error_body(error_type, 'upstream says no'), 'request_id': 'req_1'}
    refuse(status, refusal)

    response = send(gateway)

    assert response.status_code == status
    assert response.json() == refusal


def test_an_upstream_refusal_without_a_json_body_is_relayed_as_an_api_error(gateway):
    pook.post(ANTHROPIC_URL).times(1).reply(413).body('<html>Too large</html>')

    response = send(gateway)

    assert response.status_code == 413
    assert response.json() == error_body('api_error', '<html>Too large</html>')


def test_the_sdk_does_not_retry(gateway):
    upstream = pook.post(ANTHROPIC_URL).times(3)
    upstream.reply(529).json(OVERLOADED)

    response = send(gateway)

    assert response.status_code == 500
    assert len(upstream.matches) == 1


def test_an_upstream_server_error_without_fallback_is_an_api_error(gateway):
    refuse(500, error_body('api_error', 'boom'))

    response = send(gateway)

    assert response.status_code == 500
    assert error_shape(response.json()) == error_shape(error_body('api_error', ''))


# ── Streaming ───────────────────────────────────────────────────────────────


def test_a_stream_is_relayed_in_order_with_the_route_name(gateway):
    upstream_events = canned.anthropic_stream().sse_events
    upstream = mock_anthropic_stream()

    response = send_stream(gateway)

    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/event-stream')
    assert sent_body(upstream) == {**SENT, 'stream': True}
    start = upstream_events[0]
    expected = [
        {**start, 'message': {**start['message'], 'model': ROUTE_NAME}},
        *upstream_events[1:],
    ]
    assert stream_frames(response.text) == [(e['type'], e) for e in expected]


def test_an_upstream_refusal_before_streaming_is_an_http_error(gateway):
    refusal = error_body('invalid_request_error', 'no')
    refuse(400, refusal)

    response = send_stream(gateway)

    assert response.status_code == 400
    assert response.json() == refusal


def test_a_failure_before_streaming_is_an_http_error_in_the_messages_shape(gateway):
    refuse(500, error_body('api_error', 'boom'))

    response = send_stream(gateway)

    assert response.status_code == 500
    assert error_shape(response.json()) == error_shape(error_body('api_error', ''))


def test_a_failure_after_the_first_event_ends_with_an_error_event(gateway):
    start = canned.anthropic_stream().sse_events[0]
    mock_anthropic_stream(
        f'event: message_start\ndata: {json.dumps(start)}\n\ndata: {{broken\n\n'
    )

    response = send_stream(gateway)

    assert response.status_code == 200
    frames = stream_frames(response.text)
    assert [event for event, _ in frames] == ['message_start', 'error']
    assert frames[-1][1] == error_body('api_error', 'Internal server error')


def test_an_upstream_error_event_after_the_first_event_reaches_the_client(gateway):
    start = canned.anthropic_stream().sse_events[0]
    overloaded = error_body('overloaded_error', 'Overloaded')
    mock_anthropic_stream(
        f'event: message_start\ndata: {json.dumps(start)}\n\n'
        f'event: error\ndata: {json.dumps(overloaded)}\n\n'
    )

    response = send_stream(gateway)

    assert response.status_code == 200
    assert stream_frames(response.text)[-1] == ('error', overloaded)


# ── Fallback ────────────────────────────────────────────────────────────────


def test_a_server_error_falls_back_to_the_next_model(gateway):
    serve_with_fallback()
    refuse(529, OVERLOADED)
    upstream = mock_anthropic()

    response = send(gateway)

    assert response.status_code == 200
    assert sent_body(upstream)['model'] == 'claude-haiku-4-5'
    assert response.json()['model'] == ROUTE_NAME


def test_a_stream_falls_back_before_the_first_event(gateway):
    serve_with_fallback()
    refuse(529, OVERLOADED)
    upstream = mock_anthropic_stream()

    response = send_stream(gateway)

    assert response.status_code == 200
    assert sent_body(upstream)['model'] == 'claude-haiku-4-5'
    assert [event for event, _ in stream_frames(response.text)][-1] == 'message_stop'


def test_a_client_error_does_not_fall_back(gateway):
    serve_with_fallback()
    refusal = error_body('invalid_request_error', 'bad')
    refuse(400, refusal)
    unused = mock_anthropic()

    response = send(gateway)

    assert response.status_code == 400
    assert response.json() == refusal
    assert not unused.matched


def test_a_refusal_by_the_fallback_reaches_the_client_as_sent(gateway):
    serve_with_fallback()
    refuse(529, OVERLOADED)
    refusal = error_body('invalid_request_error', 'haiku says no')
    refuse(400, refusal)

    response = send(gateway)

    assert response.status_code == 400
    assert response.json() == refusal


def test_an_upstream_access_refusal_falls_back_to_the_next_model(gateway):
    serve_with_fallback()
    refuse(401, error_body('authentication_error', 'bad key'))
    upstream = mock_anthropic()

    response = send(gateway)

    assert response.status_code == 200
    assert sent_body(upstream)['model'] == 'claude-haiku-4-5'


def test_an_upstream_access_refusal_at_the_end_is_an_api_error(gateway):
    serve_with_fallback()
    refuse(529, OVERLOADED)
    refuse(401, error_body('authentication_error', 'bad key'))

    response = send(gateway)

    assert response.status_code >= 500
    assert error_shape(response.json()) == error_shape(error_body('api_error', ''))


@pytest.mark.parametrize('status', [401, 403])
def test_an_upstream_access_refusal_without_fallback_is_a_bad_gateway(gateway, status):
    refuse(status, error_body('permission_error', 'not allowed for sk-ant-1****'))

    response = send(gateway)

    assert response.status_code == 502
    assert error_shape(response.json()) == error_shape(error_body('api_error', ''))
    assert 'sk-ant-1' not in response.text
    assert "refused the gateway's credentials" in response.text


@pytest.mark.parametrize('stream', [False, True], ids=['complete', 'stream'])
def test_a_fallback_to_a_model_without_messages_api_fails_naming_it(gateway, stream):
    serve_with_fallback(MISTRAL)
    refuse(529, OVERLOADED)

    response = send(gateway, {**BODY, 'stream': stream})

    assert response.status_code == 400
    assert response.json() == error_body(
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
    serve(MISTRAL, CLAUDE, route_models=['mistral', 'claude'], routing=BY_KEYWORD)
    return send(gateway, {**BODY, 'messages': [{'role': 'user', 'content': text}]})


def test_a_request_routed_to_an_anthropic_model_is_served(gateway):
    upstream = mock_anthropic()

    response = _ask(gateway, 'Review my code')

    assert response.status_code == 200
    assert upstream.isdone()


def test_a_request_routed_to_a_model_without_messages_api_is_refused(gateway):
    response = _ask(gateway, 'Tell me a joke')

    assert response.status_code == 400
    assert response.json() == error_body(
        'invalid_request_error',
        'Model mistral of route assistant does not serve the Messages API',
    )


# ── A route whose models speak different APIs, without fallback ────────────


def test_a_messages_request_is_served_by_the_selected_anthropic_model(gateway):
    serve(CLAUDE, MISTRAL, route_models=['claude', 'mistral'])
    upstream = mock_anthropic()

    response = send(gateway)

    assert response.status_code == 200
    assert upstream.isdone()


def test_chat_completions_to_the_anthropic_model_still_translate(gateway):
    serve(CLAUDE, MISTRAL, route_models=['claude', 'mistral'])
    upstream = mock_anthropic()

    response = gateway.chat(route='assistant', text='Hi')

    assert response.status_code == 200
    assert response.json()['choices'][0]['message']['content'] == (
        'Hello from the model'
    )
    assert sent_body(upstream)['messages'] == [{'role': 'user', 'content': 'Hi'}]


# 21 new input tokens, 4 read from the cache, 8 written: 5 for 5 minutes and
# 3 for 1 hour.
USAGE_WITH_TTL = canned.anthropic_message(
    input_tokens=21, cache_read=4, cache_5m=5, cache_1h=3
).json_body['usage']

# 21 new input tokens, 4 read from the cache, 5 written to it, from an
# upstream that does not split the cache writes by TTL.
USAGE_WITHOUT_TTL = {
    'input_tokens': 21,
    'output_tokens': 7,
    'cache_read_input_tokens': 4,
    'cache_creation_input_tokens': 5,
}


@pytest.mark.parametrize(
    ('usage', 'prompt_tokens', 'cache_events'),
    [
        (
            USAGE_WITH_TTL,
            33,
            [
                ('INPUT_TOKEN_PROCESSED', 'claude', None, None, 4.0, 'read'),
                ('INPUT_TOKEN_PROCESSED', 'claude', None, None, 5.0, 'creation'),
                ('INPUT_TOKEN_PROCESSED', 'claude', None, None, 3.0, 'creation_1h'),
            ],
        ),
        (
            USAGE_WITHOUT_TTL,
            30,
            [
                ('INPUT_TOKEN_PROCESSED', 'claude', None, None, 4.0, 'read'),
                ('INPUT_TOKEN_PROCESSED', 'claude', None, None, 5.0, 'creation'),
            ],
        ),
    ],
    ids=['with_a_ttl_breakdown', 'without_a_ttl_breakdown'],
)
def test_chat_completions_to_the_anthropic_model_count_the_cache_as_before(
    gateway, usage, prompt_tokens, cache_events
):
    mock_anthropic({**canned.anthropic_message().json_body, 'usage': usage})

    response = gateway.chat(route='assistant', text='Hi')

    assert response.status_code == 200
    counted = response.json()['usage']
    assert (
        counted['prompt_tokens'],
        counted['completion_tokens'],
        counted['total_tokens'],
    ) == (prompt_tokens, 7, prompt_tokens + 7)
    assert model_events(gateway) == [
        ('MODEL_INVOCATION', 'claude', None, None, 1.0, None),
        ('INPUT_TOKEN_PROCESSED', 'claude', None, None, 21.0, None),
        *cache_events,
        ('OUTPUT_TOKEN_PROCESSED', 'claude', None, None, 7.0, None),
    ]


# ── Request events ──────────────────────────────────────────────────────────


@pytest.mark.parametrize('stream', [False, True], ids=['complete', 'stream'])
def test_a_served_request_leaves_a_successful_chat_event(gateway, stream):
    if stream:
        mock_anthropic_stream()
    else:
        mock_anthropic()

    send(gateway, {**BODY, 'stream': stream})

    [event] = gateway.request_events
    assert (
        event.route_name,
        event.request_type,
        event.status,
        event.http_status_code,
        event.is_streaming,
    ) == (ROUTE_NAME, RequestType.CHAT_COMPLETIONS, RequestStatus.SUCCESS, 200, stream)


def test_a_refused_request_leaves_a_failed_event(gateway):
    send(gateway, headers={})

    [event] = gateway.request_events
    assert (event.status, event.http_status_code) == (RequestStatus.HANDLED_ERROR, 401)


# ── Limits and model events ─────────────────────────────────────────────────

INPUT_LIMIT = {'input': {'window_size': '1 minute', 'max_token': 3}}


def test_a_request_over_the_route_token_limit_is_refused_before_any_call(gateway):
    serve(CLAUDE, token_limiting=INPUT_LIMIT)
    upstreams = mock_every_upstream()

    response = send(gateway)

    assert response.status_code == 429
    assert error_shape(response.json()) == error_shape(
        error_body('rate_limit_error', '')
    )
    assert response.json()['error']['message'].startswith(
        'Input token limit exceeded: 3 tokens per 1 minute.'
    )
    assert not any(upstream.matched for upstream in upstreams)


# 21 input tokens, 4 read from the cache, 5 written to it for 5 minutes.
CACHED_REPLY = {'input_tokens': 21, 'cache_read': 4, 'cache_5m': 5}


def _mock_cached_reply(stream: bool):
    if stream:
        return mock_anthropic_stream(canned.anthropic_stream(**CACHED_REPLY).sse_text())
    return mock_anthropic(canned.anthropic_message(**CACHED_REPLY).json_body)


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
        response = send(gateway, {**BODY, 'stream': stream})

    assert response.status_code == 200
    # Sonnet 4.5's prices: $3 and $15 per million tokens.
    assert counted == [Usage(input_tokens=30, output_tokens=7, costs=(90000, 105000))]


@pytest.mark.parametrize('stream', [False, True], ids=['complete', 'stream'])
def test_a_reply_records_its_tokens_on_the_model_that_answered(gateway, stream):
    serve_with_fallback()
    refuse(529, OVERLOADED)
    _mock_cached_reply(stream)

    response = send(gateway, {**BODY, 'stream': stream})

    assert response.status_code == 200
    assert model_events(gateway) == [
        ('MODEL_INVOCATION', 'haiku', None, None, 1.0, None),
        ('INPUT_TOKEN_PROCESSED', 'haiku', None, None, 21.0, None),
        ('INPUT_TOKEN_PROCESSED', 'haiku', None, None, 4.0, 'read'),
        ('INPUT_TOKEN_PROCESSED', 'haiku', None, None, 5.0, 'creation'),
        ('OUTPUT_TOKEN_PROCESSED', 'haiku', None, None, 7.0, None),
        ('FALLBACK', None, 'claude', 'haiku', 1.0, None),
    ]


def _mock_reply_without_ttl(stream: bool):
    if not stream:
        reply = {**canned.anthropic_message().json_body, 'usage': USAGE_WITHOUT_TTL}
        return mock_anthropic(reply)
    start, *events = canned.anthropic_stream().sse_events
    start = {
        **start,
        'message': {
            **start['message'],
            'usage': {**USAGE_WITHOUT_TTL, 'output_tokens': 1},
        },
    }
    return mock_anthropic_stream(
        CannedResponse(sse_events=[start, *events], sse_format='anthropic').sse_text()
    )


@pytest.mark.parametrize('stream', [False, True], ids=['complete', 'stream'])
def test_cache_writes_without_a_ttl_breakdown_are_recorded_as_5_minute_ones(
    gateway, stream
):
    _mock_reply_without_ttl(stream)

    response = send(gateway, {**BODY, 'stream': stream})

    assert response.status_code == 200
    assert model_events(gateway) == [
        ('MODEL_INVOCATION', 'claude', None, None, 1.0, None),
        ('INPUT_TOKEN_PROCESSED', 'claude', None, None, 21.0, None),
        ('INPUT_TOKEN_PROCESSED', 'claude', None, None, 4.0, 'read'),
        ('INPUT_TOKEN_PROCESSED', 'claude', None, None, 5.0, 'creation'),
        ('OUTPUT_TOKEN_PROCESSED', 'claude', None, None, 7.0, None),
    ]


@pytest.mark.parametrize('stream', [False, True], ids=['complete', 'stream'])
def test_a_call_no_model_answered_is_recorded(gateway, stream):
    """As on every endpoint: main recorded a failed stream, not a failed call."""
    refuse(500, error_body('api_error', 'boom'))

    response = send(gateway, {**BODY, 'stream': stream})

    assert response.status_code == 500
    assert model_events(gateway) == [
        ('MODEL_INVOCATION', 'claude', None, None, 1.0, None),
    ]


# ── Thinking another provider signed: retried once without it ──────────────

# What Anthropic says when a thinking block was signed by another provider.
SIGNATURE_REFUSAL = {
    **error_body(
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
    first = refuse(400, SIGNATURE_REFUSAL)
    retry = mock_anthropic()

    response = send(gateway, FOREIGN_HISTORY)

    assert response.status_code == 200
    assert sent_body(first)['messages'] == FOREIGN_HISTORY['messages']
    assert sent_body(retry) == {
        **FOREIGN_HISTORY,
        'model': 'claude-sonnet-4-5',
        'messages': STRIPPED_HISTORY,
    }


def test_a_signature_refusal_of_a_stream_is_retried_without_the_old_thinking(
    gateway,
):
    refuse(400, SIGNATURE_REFUSAL)
    retry = mock_anthropic_stream()

    response = send_stream(gateway, FOREIGN_HISTORY)

    assert response.status_code == 200
    assert sent_body(retry)['messages'][1] == {'role': 'assistant', 'content': [ANSWER]}
    assert [event for event, _ in stream_frames(response.text)][-1] == 'message_stop'


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
    refuse(400, SIGNATURE_REFUSAL)
    retry = mock_anthropic()

    response = send(gateway, body)

    assert response.status_code == 200
    assert sent_body(retry)['messages'] == [*STRIPPED_HISTORY, *tool_loop]


def test_another_refusal_is_relayed_without_retry(gateway):
    refusal = error_body('invalid_request_error', 'max_tokens: bad')
    refuse(400, refusal)
    unused = mock_anthropic()

    response = send(gateway, FOREIGN_HISTORY)

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
    refuse(400, SIGNATURE_REFUSAL)
    unused = mock_anthropic()

    response = send(gateway, only_thinking)

    assert response.status_code == 400
    assert response.json() == SIGNATURE_REFUSAL
    assert not unused.matched


def test_a_refused_retry_is_relayed_as_sent(gateway):
    refuse(400, SIGNATURE_REFUSAL)
    refusal = error_body('invalid_request_error', 'still no')
    retry = refuse(400, refusal)
    unused = mock_anthropic()

    response = send(gateway, FOREIGN_HISTORY)

    assert response.status_code == 400
    assert response.json() == refusal
    assert retry.matched
    assert not unused.matched


def test_a_refused_stream_retry_is_an_http_error_as_sent(gateway):
    refuse(400, SIGNATURE_REFUSAL)
    retry = refuse(400, SIGNATURE_REFUSAL)

    response = send_stream(gateway, FOREIGN_HISTORY)

    assert response.status_code == 400
    assert response.json() == SIGNATURE_REFUSAL
    assert retry.matched


# ── The invoker's own checks, behind the route's support check ─────────────


def test_a_model_the_route_does_not_hold_does_not_serve_messages():
    invoker = messages_routes(CLAUDE)[ROUTE_KEY].chat_invoker

    assert not invoker.supports_messages('nowhere')


IDENTITY = RequestIdentity(
    request_uuid='r',
    route_name=ROUTE_NAME,
    api_key_uuid='k',
    api_key_name='key',
    group_uuid='g',
    group_name='group',
)


async def _stream_from_claude(invoker, answered: list[str]) -> None:
    """Stream BODY from Claude; ``answered`` gets the model the invoker says
    answered.
    """
    async for _ in invoker.stream_messages(
        identity=IDENTITY,
        body=BODY,
        headers={},
        model_id='claude',
        on_answer=lambda model: answered.append(model.model_id),
    ):
        pass


def test_a_stream_tells_which_model_answered(gateway):
    mock_anthropic_stream()
    invoker = messages_routes(CLAUDE)[ROUTE_KEY].chat_invoker
    answered = []

    asyncio.run(_stream_from_claude(invoker, answered))

    assert answered == ['claude']


def test_a_stream_that_fell_back_tells_the_fallback_answered(gateway):
    serve_with_fallback()
    refuse(529, OVERLOADED)
    mock_anthropic_stream()
    answered = []

    asyncio.run(_stream_from_claude(app.state.routes[ROUTE_KEY].chat_invoker, answered))

    assert answered == ['haiku']


def test_a_stream_no_model_answered_tells_no_model(gateway):
    refuse(500, error_body('api_error', 'boom'))
    invoker = messages_routes(CLAUDE)[ROUTE_KEY].chat_invoker
    answered = []

    with pytest.raises(ModelInvokerInternalError):
        asyncio.run(_stream_from_claude(invoker, answered))

    assert answered == []


def test_the_invoker_refuses_a_model_without_messages_api():
    invoker = messages_routes(MISTRAL)[ROUTE_KEY].chat_invoker
    with pytest.raises(ModelInvokerBadRequest) as refused:
        asyncio.run(
            invoker.complete_messages(
                identity=IDENTITY, body=BODY, headers={}, model_id='mistral'
            )
        )

    assert refused.value.client_message == (
        'Chat model mistral does not serve the Messages API'
    )
