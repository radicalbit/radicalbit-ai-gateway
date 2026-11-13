"""Limits and cost of POST /v1/messages.

The routes are built from a project config and served on the real app
(``open_gateway``); Anthropic is mocked over HTTP with pook. The tests check
what the client gets, what the upstreams received, and what the request
counted and recorded.
"""

from contextlib import ExitStack, contextmanager
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests.common import db_mock, provider_responses as canned
from tests.common.gateway_harness import open_gateway
from tests.common.limits import consumed, credential_limit, project_limit
from tests.common.messages_api import (
    BODY,
    CLAUDE,
    GPT,
    HAIKU,
    JEV,
    OVERLOADED,
    error_body,
    error_shape,
    limit_events,
    messages_routes,
    mock_anthropic,
    mock_anthropic_stream,
    mock_every_upstream,
    mock_openai,
    mock_typesafe,
    refuse,
    routing_events,
    send,
    serve,
    serve_with_fallback,
    spend_events,
)
from tests.common.provider_recorder import CannedResponse

from radicalbit_ai_gateway.limiting.windows import (
    Category,
    credential_window,
    project_window,
)
from radicalbit_ai_gateway.server import key_service

PROJECT_LIMITS = 'radicalbit_ai_gateway.endpoints.common.admission.load_project_limits'
MINUTE = ('FIXED_WINDOW', '1 minute')

# Limits well above what one request uses: they only count here.
ROOMY_ROUTE = {
    'rate_limiting': {'max_requests': 100},
    'token_limiting': {
        'input': {'max_tokens': 100_000},
        'output': {'max_tokens': 100_000},
    },
    'budget_limiting': {'max_budget': 10},
}
ROOMY_CREDENTIAL = (
    credential_limit('request_rate', 100),
    credential_limit('token_input', 100_000),
    credential_limit('token_output', 100_000),
    credential_limit('budget', 10),
)
ROOMY_PROJECT = (project_limit(10),)


@pytest.fixture
def gateway():
    with open_gateway(messages_routes(CLAUDE), use_pook=True) as gateway:
        yield gateway


@contextmanager
def _limited(credential=ROOMY_CREDENTIAL, project=ROOMY_PROJECT):
    """Give the caller's credential and the project these limits."""
    key = db_mock.get_sample_key_with_group(group_uuid=db_mock.GROUP_UUID)
    # A plain record: the ORM `limits` relationship only takes KeyLimit rows.
    record = SimpleNamespace(
        uuid=key.uuid,
        name=key.name,
        hashed_key=key.hashed_key,
        group=key.group,
        limits=list(credential),
        expires_on=None,
    )
    with ExitStack() as stack:
        stack.enter_context(
            patch.object(key_service, 'get_key_by_hashed_key', return_value=record)
        )
        stack.enter_context(patch(PROJECT_LIMITS, return_value=list(project)))
        yield


async def _counters(route) -> dict[str, int]:
    """Return what the route, the credential and the project have counted."""
    key = str(db_mock.RANDOM_UUID)
    windows = {
        'route requests': route.route_limits.window(Category.REQUESTS),
        'route input': route.route_limits.window(Category.INPUT_TOKENS),
        'route output': route.route_limits.window(Category.OUTPUT_TOKENS),
        'route cost': route.route_limits.window(Category.COST),
        'credential requests': credential_window(key, 'request_rate', *MINUTE),
        'credential input': credential_window(key, 'token_input', *MINUTE),
        'credential output': credential_window(key, 'token_output', *MINUTE),
        'credential cost': credential_window(key, 'budget', *MINUTE),
        'project cost': project_window(route.project_uuid, *MINUTE),
    }
    return {name: await consumed(window) for name, window in windows.items()}


def _counted(requests: int, input_tokens: int, output_tokens: int, cost: int) -> dict:
    """Return the counters after usage counted once at every scope."""
    return {
        'route requests': requests,
        'route input': input_tokens,
        'route output': output_tokens,
        'route cost': cost,
        'credential requests': requests,
        'credential input': input_tokens,
        'credential output': output_tokens,
        'credential cost': cost,
        'project cost': cost,
    }


# 21 new input tokens, 4 read from the cache, 5 written to it for 5 minutes:
# 30 input tokens on the limits. 7 output tokens.
CACHED_REPLY = {'input_tokens': 21, 'cache_read': 4, 'cache_5m': 5}


def _mock_cached_reply(stream: bool):
    if stream:
        return mock_anthropic_stream(canned.anthropic_stream(**CACHED_REPLY).sse_text())
    return mock_anthropic(canned.anthropic_message(**CACHED_REPLY).json_body)


STREAMS = pytest.mark.parametrize('stream', [False, True], ids=['complete', 'stream'])
SCOPES = pytest.mark.parametrize('scope', ['route', 'credential', 'project'])
# The limit events of a refusal, by the scope of the limit.
RATE_EVENTS = {'route': 'RATE_LIMIT', 'credential': 'CREDENTIAL_RATE_LIMIT'}
BUDGET_EVENTS = {
    'route': 'BUDGET_LIMIT',
    'credential': 'CREDENTIAL_BUDGET_LIMIT',
    'project': 'PROJECT_BUDGET_LIMIT',
}


def _refused(response) -> str:
    """Check a 429 in the Messages error shape and return its message."""
    assert response.status_code == 429
    assert error_shape(response.json()) == error_shape(
        error_body('rate_limit_error', '')
    )
    return response.json()['error']['message']


# ── Request rate limits ─────────────────────────────────────────────────────


@pytest.mark.parametrize('scope', ['route', 'credential'])
@STREAMS
def test_a_request_over_a_request_limit_is_refused(gateway, scope, stream):
    """A project has budget limits only: no request limit to meet there."""
    by_scope = {
        'route': ({'rate_limiting': {'max_requests': 1}}, ()),
        'credential': ({}, (credential_limit('request_rate', 1),)),
    }
    route_limits, credential_limits = by_scope[scope]
    serve(CLAUDE, **route_limits)
    _mock_cached_reply(stream)
    upstreams = mock_every_upstream()

    with _limited(credential_limits, ()):
        first = send(gateway, {**BODY, 'stream': stream})
        second = send(gateway, {**BODY, 'stream': stream})

    assert first.status_code == 200
    assert 'ate limit exceeded: 1 requests per 1 minute' in _refused(second)
    assert not any(upstream.matched for upstream in upstreams)
    assert limit_events(gateway) == [(RATE_EVENTS[scope], scope, 'request_rate', None)]


# ── The input token limit, on the estimate ─────────────────────────────────

# 60 tokens for cl100k_base, the tokenizer of the estimate.
LONG = 'alpha ' * 60
TOOL_USE = {'type': 'tool_use', 'id': 'toolu_1', 'name': 'lookup', 'input': {}}


def _tool_result(content) -> dict:
    return {'type': 'tool_result', 'tool_use_id': 'toolu_1', 'content': content}


def _conversation(*messages: dict, system=BODY['system']) -> dict:
    return {**BODY, 'system': system, 'messages': list(messages)}


def _user(*blocks) -> dict:
    return {'role': 'user', 'content': list(blocks)}


HI = {'type': 'text', 'text': 'Hi'}
ASKS_A_TOOL = {'role': 'assistant', 'content': [TOOL_USE]}
# Where a request carries text: each of these holds the long text once.
LONG_REQUESTS = {
    'system_string': _conversation(_user(HI), system=LONG),
    'system_block': _conversation(_user(HI), system=[{'type': 'text', 'text': LONG}]),
    'second_text_block': _conversation(_user(HI, {'type': 'text', 'text': LONG})),
    'earlier_message': _conversation(
        {'role': 'user', 'content': LONG},
        {'role': 'assistant', 'content': 'Yes?'},
        _user(HI),
    ),
    'assistant_message': _conversation(
        _user(HI), {'role': 'assistant', 'content': LONG}, _user(HI)
    ),
    'tool_result_string': _conversation(
        _user(HI), ASKS_A_TOOL, _user(_tool_result(LONG))
    ),
    'tool_result_block': _conversation(
        _user(HI), ASKS_A_TOOL, _user(_tool_result([{'type': 'text', 'text': LONG}]))
    ),
}
# The long text alone is over this limit; a request without it is under.
ESTIMATE_LIMIT = {'input': {'max_tokens': 50}}


@pytest.mark.parametrize('body', LONG_REQUESTS.values(), ids=LONG_REQUESTS.keys())
def test_the_estimate_counts_the_text_wherever_the_request_carries_it(gateway, body):
    serve(CLAUDE, token_limiting=ESTIMATE_LIMIT)
    upstreams = mock_every_upstream()

    response = send(gateway, body)

    assert _refused(response).startswith(
        'Input token limit exceeded: 50 tokens per 1 minute.'
    )
    assert not any(upstream.matched for upstream in upstreams)
    assert limit_events(gateway) == [
        ('TOKEN_INPUT_LIMIT', 'route', 'token_input', None)
    ]


def test_a_request_whose_estimate_fits_the_input_limit_is_served(gateway):
    """The control of the test above: the same requests without the long text."""
    serve(CLAUDE, token_limiting=ESTIMATE_LIMIT)
    upstream = mock_anthropic()

    response = send(
        gateway, _conversation(_user(HI), ASKS_A_TOOL, _user(_tool_result('Done')))
    )

    assert response.status_code == 200
    assert upstream.isdone()


def test_a_credential_input_limit_refuses_on_the_estimate(gateway):
    upstreams = mock_every_upstream()

    with _limited((credential_limit('token_input', 50),), ()):
        response = send(gateway, LONG_REQUESTS['tool_result_block'])

    assert 'nput token limit exceeded: 50 tokens per 1 minute' in _refused(response)
    assert not any(upstream.matched for upstream in upstreams)
    assert limit_events(gateway) == [
        ('CREDENTIAL_TOKEN_INPUT_LIMIT', 'credential', 'token_input', None)
    ]


# ── Real usage on the counters ──────────────────────────────────────────────


@STREAMS
async def test_a_reply_counts_its_usage_at_every_scope(gateway, stream):
    """The cache reads and writes count as input tokens, as on chat."""
    route = serve(CLAUDE, **ROOMY_ROUTE)
    _mock_cached_reply(stream)

    with _limited():
        response = send(gateway, {**BODY, 'stream': stream})

    assert response.status_code == 200
    # Sonnet 4.5's prices, $3 and $15 per million tokens, in billionths of a
    # dollar.
    assert await _counters(route) == _counted(1, 30, 7, 90_000 + 105_000)


@STREAMS
async def test_a_reply_over_an_output_limit_refuses_the_next_request(gateway, stream):
    serve(CLAUDE, token_limiting={'output': {'max_tokens': 7}})
    _mock_cached_reply(stream)
    upstreams = mock_every_upstream()

    first = send(gateway, {**BODY, 'stream': stream})
    second = send(gateway, {**BODY, 'stream': stream})

    assert first.status_code == 200
    assert _refused(second).startswith('Output token limit exceeded')
    assert not any(upstream.matched for upstream in upstreams)


# ── Budgets ─────────────────────────────────────────────────────────────────


def _serve_with_budget(scope: str, budget: float):
    """Serve the route with ``budget`` dollars a minute at ``scope``; return
    the route and the context that gives the credential and the project
    their limits.
    """
    route = serve(
        CLAUDE,
        **({'budget_limiting': {'max_budget': budget}} if scope == 'route' else {}),
    )
    return route, _limited(
        (credential_limit('budget', budget),) if scope == 'credential' else (),
        (project_limit(budget),) if scope == 'project' else (),
    )


@SCOPES
@STREAMS
def test_a_request_is_refused_once_the_budget_is_spent(gateway, scope, stream):
    # The reply costs $0.000195: more than the budget.
    _, limited = _serve_with_budget(scope, 0.0001)
    _mock_cached_reply(stream)
    upstreams = mock_every_upstream()

    with limited:
        first = send(gateway, {**BODY, 'stream': stream})
        second = send(gateway, {**BODY, 'stream': stream})

    assert first.status_code == 200
    assert 'udget limit exceeded: $0.0001 per 1 minute' in _refused(second)
    assert not any(upstream.matched for upstream in upstreams)
    assert limit_events(gateway) == [(BUDGET_EVENTS[scope], scope, 'budget', None)]


@SCOPES
@STREAMS
def test_a_reply_that_crosses_a_threshold_raises_its_event(gateway, scope, stream):
    # The reply costs $0.000195: 97.5% of the budget, past the 75% threshold.
    _, limited = _serve_with_budget(scope, 0.0002)
    _mock_cached_reply(stream)

    with limited:
        response = send(gateway, {**BODY, 'stream': stream})
        # A stream counts when its last frame is read.
        assert response.text

    assert response.status_code == 200
    assert limit_events(gateway) == [('LIMIT_THRESHOLD', scope, 'budget', '75')]


# ── Cost ────────────────────────────────────────────────────────────────────

# The reply's tokens at Sonnet 4.5's prices, in dollars: $3 per million
# input tokens, $0.30 read from the cache, $3.75 written to it, $15 output.
SONNET_SPEND = [
    ('model', 'INPUT_TOKEN_PROCESSED', 'claude', None, 21.0, 0.000063),
    ('model', 'INPUT_TOKEN_PROCESSED', 'claude', 'read', 4.0, 0.0000012),
    ('model', 'INPUT_TOKEN_PROCESSED', 'claude', 'creation', 5.0, 0.00001875),
    ('model', 'OUTPUT_TOKEN_PROCESSED', 'claude', None, 7.0, 0.000105),
]
# The same at Haiku 4.5's: $1, $0.10, $1.25 and $5.
HAIKU_SPEND = [
    ('model', 'INPUT_TOKEN_PROCESSED', 'haiku', None, 21.0, 0.000021),
    ('model', 'INPUT_TOKEN_PROCESSED', 'haiku', 'read', 4.0, 0.0000004),
    ('model', 'INPUT_TOKEN_PROCESSED', 'haiku', 'creation', 5.0, 0.00000625),
    ('model', 'OUTPUT_TOKEN_PROCESSED', 'haiku', None, 7.0, 0.000035),
]


def _stream_with_whole_final_usage() -> str:
    """Return the cached reply's stream as Anthropic sends it: the last
    ``message_delta`` repeats the input counts. The translated chat path
    reads its usage there.
    """
    reply = canned.anthropic_stream(**CACHED_REPLY)
    start_usage = reply.sse_events[0]['message']['usage']
    events = [
        {**event, 'usage': {**start_usage, **event['usage']}}
        if event['type'] == 'message_delta'
        else event
        for event in reply.sse_events
    ]
    return CannedResponse(sse_events=events, sse_format='anthropic').sse_text()


@STREAMS
async def test_the_same_usage_costs_the_same_as_on_chat_completions(gateway, stream):
    """Also the regression test of Chat Completions on the same Anthropic
    route: its token events, their cost and its counters are as before.
    """
    route = serve(CLAUDE, **ROOMY_ROUTE)
    for _ in range(2):
        if stream:
            mock_anthropic_stream(_stream_with_whole_final_usage())
        else:
            _mock_cached_reply(stream)

    with _limited():
        send(gateway, {**BODY, 'stream': stream})
        on_messages = spend_events(gateway)
        counted_on_messages = await _counters(route)
        response = gateway.chat(
            route='assistant',
            text='Hi',
            stream=stream,
            **({'stream_options': {'include_usage': True}} if stream else {}),
        )
        on_chat = spend_events(gateway)

    assert response.status_code == 200
    assert on_messages == on_chat == SONNET_SPEND
    assert counted_on_messages == _counted(1, 30, 7, 195_000)
    assert await _counters(route) == _counted(2, 60, 14, 390_000)


@STREAMS
async def test_a_reply_after_a_fallback_is_costed_at_the_answering_models_prices(
    gateway, stream
):
    route = serve_with_fallback(**ROOMY_ROUTE)
    refuse(529, OVERLOADED)
    _mock_cached_reply(stream)

    with _limited():
        response = send(gateway, {**BODY, 'stream': stream})

    assert response.status_code == 200
    # Haiku 4.5's prices, $1 and $5 per million tokens, in billionths of a
    # dollar: Sonnet 4.5, the model asked for, costs three times as much.
    assert await _counters(route) == _counted(1, 30, 7, 30_000 + 35_000)
    assert spend_events(gateway) == HAIKU_SPEND


OUTPUT_WARN = {
    'name': 'output_warn',
    'type': 'contains',
    'behavior': 'warn',
    'where': 'output',
    'parameters': {'values': ['secret']},
}


async def test_a_stream_the_output_guardrails_read_is_costed_after_a_fallback(gateway):
    """The answer is collected whole before it is streamed: it is still
    costed at the prices of the fallback that answered.
    """
    route = serve_with_fallback(
        guardrails=['output_warn'], config={'guardrails': [OUTPUT_WARN]}, **ROOMY_ROUTE
    )
    refuse(529, OVERLOADED)
    _mock_cached_reply(stream=True)

    with _limited():
        response = send(gateway, {**BODY, 'stream': True})

    assert response.status_code == 200
    assert await _counters(route) == _counted(1, 30, 7, 30_000 + 35_000)


REDIS = {'cache': {'redis_host': 'localhost', 'redis_port': 6379}}


@STREAMS
def test_a_cache_hit_is_recorded_on_the_model_that_answered(gateway, stream):
    """The saved tokens of a hit are priced on the fallback that answered."""
    serve_with_fallback(caching={'type': 'exact'}, config=REDIS)
    refuse(529, OVERLOADED)
    _mock_cached_reply(stream)

    send(gateway, {**BODY, 'stream': stream})
    hit = send(gateway, {**BODY, 'stream': stream})

    assert hit.headers['X-RB-AIGATEWAY-CACHE-HIT'] == 'true'
    assert {
        (e['EVENT_TYPE'].name, e['MODEL_ID'])
        for e in gateway.event_rows
        if e['EVENT_TYPE'].name.startswith('CACHE_')
    } == {
        ('CACHE_HIT', 'haiku'),
        ('CACHE_INPUT_TOKENS', 'haiku'),
        ('CACHE_OUTPUT_TOKENS', 'haiku'),
    }


# ── Calls on behalf of the request (ADR 0006) ───────────────────────────────

JUDGE_TOKENS = 312
# $1000 per million input tokens: a judge call of 312 tokens costs $0.312.
PRICEY_JEV = {**JEV, 'input_cost_per_million_tokens': 1000}
DECISION_JUDGE = {
    'name': 'on_topic',
    'type': 'decision_judge',
    'behavior': 'block',
    'where': 'input',
    'parameters': {'model_id': 'jev', 'instructions': 'Is this off topic?'},
}
LLM_JUDGE = {
    'name': 'polite',
    'type': 'judge',
    'behavior': 'block',
    'where': 'output',
    'parameters': {'model_id': 'gpt', 'prompt': 'Judge this.'},
}


def _mock_decision_judge():
    return mock_typesafe(
        {'decision_judge': {'type': 'noul', 'noul': 0.1}}, input_tokens=JUDGE_TOKENS
    )


def _mock_llm_judge():
    verdict = {'triggered': False, 'reasoning': None, 'violation_type': None}
    return mock_openai(json.dumps(verdict), JUDGE_TOKENS, 4)


# Per judge: its guardrail, its mock, what its call records and what it adds
# to the counters (input tokens, output tokens, cost).
JUDGES = {
    'decision': (
        DECISION_JUDGE,
        _mock_decision_judge,
        [
            ('judge', 'INPUT_TOKEN_PROCESSED', 'jev', None, 312.0, 0.312),
            ('judge', 'OUTPUT_TOKEN_PROCESSED', 'jev', None, 0.0, 0),
        ],
        (312, 0, 312_000_000),
    ),
    # GPT-4o mini's prices: $0.15 and $0.60 per million tokens.
    'llm': (
        LLM_JUDGE,
        _mock_llm_judge,
        [
            ('judge', 'INPUT_TOKEN_PROCESSED', 'gpt', None, 312.0, 0.0000468),
            ('judge', 'OUTPUT_TOKEN_PROCESSED', 'gpt', None, 4.0, 0.0000024),
        ],
        (312, 4, 46_800 + 2_400),
    ),
}


@pytest.mark.parametrize('judge', JUDGES)
@STREAMS
async def test_a_judge_call_consumes_the_callers_limits(gateway, judge, stream):
    guardrail, mock_judge, judge_spend, (input_tokens, output_tokens, cost) = JUDGES[
        judge
    ]
    route = serve(
        CLAUDE,
        GPT,
        route_models=['claude'],
        guardrails=[guardrail['name']],
        config={'guardrails': [guardrail], 'decision_models': [PRICEY_JEV]},
        **ROOMY_ROUTE,
    )
    judged = mock_judge()
    _mock_cached_reply(stream)

    with _limited():
        response = send(gateway, {**BODY, 'stream': stream})

    assert response.status_code == 200
    assert judged.isdone()
    assert sorted(spend_events(gateway), key=str) == sorted(
        SONNET_SPEND + judge_spend, key=str
    )
    assert await _counters(route) == _counted(
        1, 30 + input_tokens, 7 + output_tokens, 195_000 + cost
    )


BY_LLM = {
    'name': 'by_llm',
    'type': 'llm',
    'router_model_id': 'gpt',
    'default_model_id': 'claude',
    'output_mapping': [
        {'model_id': 'claude', 'description': 'Hard questions'},
        {'model_id': 'haiku', 'description': 'Small talk'},
    ],
}


@STREAMS
async def test_a_routing_call_consumes_the_callers_limits(gateway, stream):
    route = serve(
        CLAUDE,
        HAIKU,
        GPT,
        route_models=['claude', 'haiku'],
        routing=BY_LLM,
        **ROOMY_ROUTE,
    )
    routed = mock_openai(json.dumps({'option_1': 0.1, 'option_2': 0.9}), 120, 12)
    _mock_cached_reply(stream)

    with _limited():
        response = send(gateway, {**BODY, 'stream': stream})

    assert response.status_code == 200
    assert routed.isdone()
    assert routing_events(gateway) == [('by_llm', 'haiku')]
    # GPT-4o mini's prices: $0.15 and $0.60 per million tokens.
    assert spend_events(gateway) == [
        ('routing', 'INPUT_TOKEN_PROCESSED', 'gpt', None, 120.0, 0.000018),
        ('routing', 'OUTPUT_TOKEN_PROCESSED', 'gpt', None, 12.0, 0.0000072),
        *HAIKU_SPEND,
    ]
    assert await _counters(route) == _counted(
        1, 30 + 120, 7 + 12, 65_000 + 18_000 + 7_200
    )


# ── Chat Completions on the same route ──────────────────────────────────────


def test_chat_completions_are_refused_once_the_budget_is_spent_as_before(gateway):
    """The regression test of the limits on Chat Completions to the same
    Anthropic route: the refusal keeps the Chat Completions error shape.
    """
    serve(CLAUDE, budget_limiting={'max_budget': 0.0001})
    _mock_cached_reply(False)
    upstreams = mock_every_upstream()

    first = gateway.chat(route='assistant', text='Hi')
    second = gateway.chat(route='assistant', text='Hi')

    assert first.status_code == 200
    assert second.status_code == 429
    assert 'type' not in second.json()
    assert 'Budget limit exceeded: $0.0001 per 1 minute' in second.text
    assert not any(upstream.matched for upstream in upstreams)
    assert limit_events(gateway) == [('BUDGET_LIMIT', 'route', 'budget', None)]
