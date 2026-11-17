"""Routing on POST /v1/messages: every router type picks the model of a
Messages request.

The routes are built from a project config and served on the real app
(``open_gateway``). Anthropic, OpenAI (the embedding model of semantic
routing, the router model of LLM routing) and Typesafe (decision routing)
are mocked over HTTP with pook. The tests check which model Anthropic was
asked for, what each router's upstream received, and what the gateway
records.
"""

import json

import pytest
import tiktoken

from tests.common.gateway_harness import open_gateway
from tests.common.messages_api import (
    BODY,
    CLAUDE,
    EMBEDDING,
    GPT,
    HAIKU,
    JEV,
    error_body,
    messages_routes,
    mock_anthropic,
    mock_anthropic_stream,
    mock_embedding,
    mock_every_upstream,
    mock_openai,
    mock_typesafe,
    routing_events,
    send,
    sent_body,
    serve,
    spend_events,
)

from radicalbit_ai_gateway.gateway_route.factory import initialize_async_routers
from radicalbit_ai_gateway.server import app

SONNET_NAME = 'claude-sonnet-4-5'
HAIKU_NAME = 'claude-haiku-4-5'
EMAIL = 'mario.rossi@example.com'
MASK = '<EMAIL_ADDRESS>'
REDACT_EMAIL = {
    'name': 'redact_email',
    'type': 'presidio_anonymizer',
    'behavior': 'block',
    'where': 'input',
    'parameters': {'entities': ['EMAIL_ADDRESS']},
}
STREAMS = pytest.mark.parametrize('stream', [False, True], ids=['complete', 'stream'])


@pytest.fixture
def gateway():
    with open_gateway(messages_routes(CLAUDE), use_pook=True) as gateway:
        yield gateway


def _serve(routing: dict, *more_models: dict, redact: bool = False, **config) -> None:
    """Serve the route on Claude and Haiku with ``routing``.

    ``more_models`` are chat models the route does not answer with: a
    router model, say. With ``redact``, emails are masked in the input.
    """
    serve(
        CLAUDE,
        HAIKU,
        *more_models,
        route_models=['claude', 'haiku'],
        routing=routing,
        guardrails=['redact_email'] if redact else [],
        config={'guardrails': [REDACT_EMAIL], **config},
    )


def _ask(gateway, text: str, stream: bool = False, system: str = BODY['system']):
    """Send ``text`` as the last user message, after an earlier turn."""
    messages = [
        {'role': 'user', 'content': 'Good morning'},
        {'role': 'assistant', 'content': 'Good morning to you'},
        {'role': 'user', 'content': [{'type': 'text', 'text': text}]},
    ]
    return send(
        gateway, {**BODY, 'system': system, 'messages': messages, 'stream': stream}
    )


def _mock_answer(stream: bool = False):
    return mock_anthropic_stream() if stream else mock_anthropic()


# ── Deterministic rules ─────────────────────────────────────────────────────


def _deterministic(rule: str, conditions) -> dict:
    """Return a rule that sends a match to Haiku, the rest to Claude."""
    return {
        'name': f'by_{rule}',
        'type': 'deterministic',
        'rule': rule,
        'default_model_id': 'claude',
        'output_mapping': [{'model_id': 'haiku', 'conditions': conditions}],
    }


EVERY_MINUTE = _deterministic('time', ['* * * * *'])
NEVER = _deterministic('time', ['0 0 30 2 *'])
BY_KEYWORD = _deterministic('keyword', ['code'])
BY_TOKEN_LENGTH = _deterministic('token_length', {'lte': 5})
BY_CONTEXT_LENGTH = _deterministic('context_length', {'gte': 60})
SHORT = 'Tell me a joke'
LONG = 'Tell me a long story about a cat that learns to sail around the world'
# Routing, the last user text, the system prompt, the model picked.
DETERMINISTIC = {
    'time_matches': (EVERY_MINUTE, SHORT, 'You are terse.', 'haiku'),
    'time_does_not_match': (NEVER, SHORT, 'You are terse.', 'claude'),
    'keyword_matches': (BY_KEYWORD, 'Review my CODE', 'You are terse.', 'haiku'),
    'keyword_does_not_match': (BY_KEYWORD, SHORT, 'You are terse.', 'claude'),
    # The keyword is read in the last user text only.
    'keyword_in_the_system_prompt': (BY_KEYWORD, SHORT, 'You write code.', 'claude'),
    'token_length_short': (BY_TOKEN_LENGTH, SHORT, 'You are terse.', 'haiku'),
    'token_length_long': (BY_TOKEN_LENGTH, LONG, 'You are terse.', 'claude'),
    'context_length_short': (BY_CONTEXT_LENGTH, SHORT, 'You are terse.', 'claude'),
    # The context is the whole conversation, the system prompt included.
    'context_length_long': (BY_CONTEXT_LENGTH, SHORT, 'alpha ' * 60, 'haiku'),
}
MODEL_NAMES = {'claude': SONNET_NAME, 'haiku': HAIKU_NAME}


@pytest.mark.parametrize(
    ('routing', 'text', 'system', 'model'),
    DETERMINISTIC.values(),
    ids=DETERMINISTIC.keys(),
)
@STREAMS
def test_a_deterministic_rule_picks_the_model(
    gateway, routing, text, system, model, stream
):
    _serve(routing)
    upstream = _mock_answer(stream)

    response = _ask(gateway, text, stream, system)

    assert response.status_code == 200
    assert sent_body(upstream)['model'] == MODEL_NAMES[model]
    assert routing_events(gateway) == [(routing['name'], model)]


# ── Semantic routing ────────────────────────────────────────────────────────

BY_MEANING = {
    'name': 'by_meaning',
    'type': 'semantic',
    'embedding_model_id': 'emb',
    'default_model_id': 'claude',
    'output_mapping': [
        {'model_id': 'claude', 'conditions': ['Prove this theorem']},
        {'model_id': 'haiku', 'conditions': ['How are you today?']},
    ],
}


async def _serve_semantic(redact: bool = False) -> list:
    """Serve the route with semantic routing: Claude's examples embed as
    (1, 0), Haiku's as (0, 1). Return the mocks of the two example calls.
    """
    examples = [mock_embedding(1.0, 0.0), mock_embedding(0.0, 1.0)]
    _serve(BY_MEANING, redact=redact, embedding_models=[EMBEDDING])
    await initialize_async_routers(app.state.routes)
    return examples


def _embedded(mock) -> list[str]:
    """Return the texts an embeddings call was sent: the client sends them
    as cl100k_base tokens.
    """
    encoding = tiktoken.get_encoding('cl100k_base')
    return [encoding.decode(tokens) for tokens in sent_body(mock)['input']]


@STREAMS
async def test_semantic_routing_embeds_the_last_user_text(gateway, stream):
    examples = await _serve_semantic()
    query = mock_embedding(0.1, 0.9)
    upstream = _mock_answer(stream)

    response = _ask(gateway, 'How is it going?', stream)

    assert response.status_code == 200
    assert [_embedded(example) for example in examples] == [
        ['Prove this theorem'],
        ['How are you today?'],
    ]
    assert sent_body(query)['model'] == 'text-embedding-3-small'
    assert _embedded(query) == ['How is it going?']
    assert sent_body(upstream)['model'] == HAIKU_NAME
    assert routing_events(gateway) == [('by_meaning', 'haiku')]
    # The query embedding is spend of the request: 5 tokens at $0.02 per
    # million.
    assert spend_events(gateway)[0] == (
        'routing',
        'INPUT_TOKEN_PROCESSED',
        'emb',
        None,
        5.0,
        0.0000001,
    )


async def test_semantic_routing_far_from_every_example_uses_the_default(gateway):
    await _serve_semantic()
    mock_embedding(-1.0, -1.0)
    upstream = mock_anthropic()

    response = _ask(gateway, 'zzz')

    assert response.status_code == 200
    assert sent_body(upstream)['model'] == SONNET_NAME
    assert routing_events(gateway) == [('by_meaning', 'claude')]


# ── LLM routing ─────────────────────────────────────────────────────────────

OPTIONS = [
    {'model_id': 'claude', 'description': 'Hard questions'},
    {'model_id': 'haiku', 'description': 'Small talk'},
]
BY_LLM = {
    'name': 'by_llm',
    'type': 'llm',
    'router_model_id': 'gpt',
    'default_model_id': 'claude',
    'output_mapping': OPTIONS,
}


def _mock_router_model(**scores: float):
    return mock_openai(json.dumps(scores), prompt_tokens=120, completion_tokens=12)


@STREAMS
def test_llm_routing_asks_the_router_model_about_the_last_user_text(gateway, stream):
    _serve(BY_LLM, GPT)
    router_model = _mock_router_model(option_1=0.1, option_2=0.9)
    upstream = _mock_answer(stream)

    response = _ask(gateway, 'How is it going?', stream)

    assert response.status_code == 200
    asked = sent_body(router_model)
    assert asked['model'] == 'gpt-4o-mini'
    assert asked['messages'][-1] == {'role': 'user', 'content': 'How is it going?'}
    assert sent_body(upstream)['model'] == HAIKU_NAME
    assert routing_events(gateway) == [('by_llm', 'haiku')]
    # GPT-4o mini's prices: $0.15 and $0.60 per million tokens.
    assert spend_events(gateway)[:2] == [
        ('routing', 'INPUT_TOKEN_PROCESSED', 'gpt', None, 120.0, 0.000018),
        ('routing', 'OUTPUT_TOKEN_PROCESSED', 'gpt', None, 12.0, 0.0000072),
    ]


def test_llm_routing_below_its_threshold_uses_the_default(gateway):
    _serve(BY_LLM, GPT)
    _mock_router_model(option_1=0.1, option_2=0.2)
    upstream = mock_anthropic()

    response = _ask(gateway, 'zzz')

    assert response.status_code == 200
    assert sent_body(upstream)['model'] == SONNET_NAME
    assert routing_events(gateway) == [('by_llm', 'claude')]


# ── Decision routing ────────────────────────────────────────────────────────

INSTRUCTIONS = 'Choose the model best suited to answer this request.'
BY_DECISION = {
    'name': 'by_decision',
    'type': 'decision',
    'decision_model_id': 'jev',
    'instructions': INSTRUCTIONS,
    'default_model_id': 'claude',
    'output_mapping': OPTIONS,
}
# $1000 per million input tokens: a routing call of 280 tokens costs $0.28.
PRICEY_JEV = {**JEV, 'input_cost_per_million_tokens': 1000}


def _mock_decision_model(**probabilities: float):
    """Mock Typesafe choosing the most probable option."""
    top = max(probabilities, key=probabilities.get)
    return mock_typesafe(
        {
            'decision_routing': {
                'type': 'choice',
                'choice': top,
                'confidence': probabilities[top],
                'probabilities': probabilities,
            }
        }
    )


@STREAMS
def test_decision_routing_asks_typesafe_about_the_last_user_text(gateway, stream):
    _serve(BY_DECISION, decision_models=[PRICEY_JEV])
    typesafe = _mock_decision_model(option_1=0.1, option_2=0.9)
    upstream = _mock_answer(stream)

    response = _ask(gateway, 'How is it going?', stream)

    assert response.status_code == 200
    asked = sent_body(typesafe)
    assert asked['state'] == 'How is it going?'
    [question] = asked['questions'].values()
    assert question['instructions'] == INSTRUCTIONS
    assert sent_body(upstream)['model'] == HAIKU_NAME
    assert routing_events(gateway) == [('by_decision', 'haiku')]
    assert spend_events(gateway)[0] == (
        'routing',
        'INPUT_TOKEN_PROCESSED',
        'jev',
        None,
        280.0,
        0.28,
    )


# ── A router that picks a model without the Messages API ────────────────────

TO_OPENAI = {
    'name': 'to_openai',
    'type': 'deterministic',
    'rule': 'keyword',
    'default_model_id': 'claude',
    'output_mapping': [{'model_id': 'gpt', 'conditions': ['code']}],
}


@STREAMS
def test_a_router_that_picks_an_openai_model_is_a_bad_request(gateway, stream):
    serve(CLAUDE, GPT, route_models=['claude', 'gpt'], routing=TO_OPENAI)
    upstreams = mock_every_upstream()

    response = _ask(gateway, 'Review my code', stream)

    assert response.status_code == 400
    assert response.json() == error_body(
        'invalid_request_error',
        'Model gpt of route assistant does not serve the Messages API',
    )
    assert not any(upstream.matched for upstream in upstreams)
    assert routing_events(gateway) == [('to_openai', 'gpt')]


# ── Routers read the redacted text (ADR 0010) ───────────────────────────────

WRITE_TO = f'Write to {EMAIL}'
MASKED = f'Write to {MASK}'


def test_keyword_routing_reads_the_redacted_text(gateway):
    """The keyword is in the email a redact guardrail masks."""
    _serve(_deterministic('keyword', ['example.com']), redact=True)
    upstream = mock_anthropic()

    _ask(gateway, WRITE_TO)

    assert sent_body(upstream)['model'] == SONNET_NAME
    assert sent_body(upstream)['messages'][-1]['content'][0]['text'] == MASKED


async def test_semantic_routing_embeds_the_redacted_text(gateway):
    await _serve_semantic(redact=True)
    query = mock_embedding(0.1, 0.9)
    mock_anthropic()

    _ask(gateway, WRITE_TO)

    assert _embedded(query) == [MASKED]


def test_llm_routing_sends_the_redacted_text(gateway):
    _serve(BY_LLM, GPT, redact=True)
    router_model = _mock_router_model(option_1=0.1, option_2=0.9)
    mock_anthropic()

    _ask(gateway, WRITE_TO)

    assert EMAIL not in json.dumps(sent_body(router_model))
    assert sent_body(router_model)['messages'][-1]['content'] == MASKED


def test_decision_routing_sends_the_redacted_text(gateway):
    _serve(BY_DECISION, decision_models=[JEV], redact=True)
    typesafe = _mock_decision_model(option_1=0.1, option_2=0.9)
    mock_anthropic()

    _ask(gateway, WRITE_TO)

    assert sent_body(typesafe)['state'] == MASKED
