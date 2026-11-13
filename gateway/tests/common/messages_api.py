"""Messages API test helpers shared by the server tests of ``/v1/messages``.

A test serves the ``assistant`` route from a project config on the real app
(``open_gateway(messages_routes(CLAUDE), use_pook=True)``), mocks Anthropic
over HTTP with pook, and sends as an Anthropic client does.
"""

import json

import pook

from tests.common import db_mock, provider_responses as canned
from tests.common.gateway_harness import build_routes

from radicalbit_ai_gateway.gateway_route.route import GatewayRoute
from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.server import app

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


def error_body(error_type: str, message: str) -> dict:
    """Return a Messages API error body."""
    return {'type': 'error', 'error': {'type': error_type, 'message': message}}


def error_shape(body: dict) -> dict:
    """Return a Messages API error body without its message."""
    return {'type': body['type'], 'error': {'type': body['error']['type']}}


OVERLOADED = error_body('overloaded_error', 'busy')


# ── The published config ────────────────────────────────────────────────────


def messages_routes(
    *models: dict,
    route_models: list[str] | None = None,
    fallbacks: list[str] | None = None,
    routing: dict | None = None,
    config: dict | None = None,
    project_uuid: str = '',
    **route: object,
) -> dict:
    """Build the ``assistant`` route over ``models``: by default, on the first.

    ``route`` holds more keys of the route, ``config`` more top-level sections
    of the project config (guardrails, embedding models, cache).
    ``project_uuid`` is the project of the routes: the semantic cache needs one.
    """
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
            **(config or {}),
        },
        project_uuid=project_uuid,
    )


def serve(*models: dict, **route: object) -> GatewayRoute:
    """Serve the ``assistant`` route over ``models`` for the rest of the test
    (``open_gateway`` puts the routes back) and return it.
    """
    app.state.routes = messages_routes(*models, **route)
    return app.state.routes[ROUTE_KEY]


def serve_with_fallback(fallback: dict = HAIKU, **route: object) -> GatewayRoute:
    """Serve the route on Claude, with ``fallback`` as its fallback."""
    return serve(
        CLAUDE,
        fallback,
        route_models=['claude', fallback['model_id']],
        fallbacks=[fallback['model_id']],
        **route,
    )


# ── The client ──────────────────────────────────────────────────────────────


def send(gateway, body: dict | None = None, headers: dict | None = None):
    """Send a Messages request, with the credential as Anthropic clients send it."""
    return gateway.post(
        '/v1/messages',
        key=False,
        headers=X_API_KEY if headers is None else headers,
        json=body or BODY,
    )


def send_stream(gateway, body: dict | None = None):
    """Send a streaming Messages request."""
    return send(gateway, {**(body or BODY), 'stream': True})


def stream_frames(text: str) -> list[tuple[str, dict]]:
    """Return the ``(event, data)`` pairs of an SSE body."""
    frames = []
    for block in text.strip().split('\n\n'):
        lines = dict(line.split(': ', 1) for line in block.splitlines())
        frames.append((lines['event'], json.loads(lines['data'])))
    return frames


# ── The Anthropic mock ──────────────────────────────────────────────────────


def mock_anthropic(reply: dict | None = None, url: str = ANTHROPIC_URL):
    """Mock one Anthropic answer: ``reply``, or the canned message."""
    mock = pook.post(url).times(1)
    mock.reply(200).json(reply or canned.anthropic_message().json_body)
    return mock


def mock_anthropic_stream(sse_text: str | None = None):
    """Mock one Anthropic stream: ``sse_text``, or the canned stream."""
    mock = pook.post(ANTHROPIC_URL).times(1)
    mock.reply(200).header('Content-Type', 'text/event-stream').body(
        sse_text or canned.anthropic_stream().sse_text()
    )
    return mock


def refuse(status: int, body: dict):
    """Mock one Anthropic refusal."""
    mock = pook.post(ANTHROPIC_URL).times(1)
    mock.reply(status).json(body)
    return mock


def mock_every_upstream() -> list:
    """Mock every upstream, to check later that none was called."""
    mocks = []
    for url in UPSTREAM_URLS:
        mock = pook.post(url).times(1)
        mock.reply(500).json({})
        mocks.append(mock)
    return mocks


EMBEDDINGS_URL = 'https://api.openai.com/v1/embeddings'
OPENAI_URL = 'https://api.openai.com/v1/chat/completions'
TYPESAFE_URL = 'https://api.typesafe.ai/v1/systemone'
# A decision model, for decision judges and decision routing.
JEV = {
    'model_id': 'jev',
    'model': 'typesafe/jev-latest',
    'credentials': {'api_key': 'ts-key'},
}


def mock_openai(content: str, prompt_tokens: int = 9, completion_tokens: int = 4):
    """Mock one OpenAI chat completion saying ``content``."""
    mock = pook.post(OPENAI_URL).times(1)
    mock.reply(200).json(
        canned.openai_completion(
            content, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
        ).json_body
    )
    return mock


def mock_typesafe(answers: dict, input_tokens: int = 280):
    """Mock one Typesafe answer: ``answers`` by question id."""
    mock = pook.post(TYPESAFE_URL).times(1)
    mock.reply(200).json(
        {
            'model': 'jev-1.13.0',
            'answers': answers,
            'usage': {'input_tokens': input_tokens, 'output_tokens': 0},
        }
    )
    return mock


def mock_embedding(*vector: float):
    """Mock one OpenAI embeddings answer: ``vector``, for 3 input tokens."""
    mock = pook.post(EMBEDDINGS_URL).times(1)
    mock.reply(200).json(
        {
            'object': 'list',
            'data': [{'object': 'embedding', 'index': 0, 'embedding': list(vector)}],
            'model': 'text-embedding-3-small',
            'usage': {'prompt_tokens': 3, 'total_tokens': 3},
        }
    )
    return mock


def sent_body(mock, index: int = 0) -> dict:
    """Return the JSON body of a request a pook mock matched."""
    return mock.matches[index].json


# ── What the gateway records ────────────────────────────────────────────────


def spend_events(gateway) -> list[tuple]:
    """Return the token events with their cost: who spent (the request's
    model, a judge or a router), the type, the model, the cache type, the
    tokens and the cost in dollars.
    """
    return [
        (
            'judge' if e['IS_JUDGE'] else 'routing' if e['IS_ROUTING'] else 'model',
            e['EVENT_TYPE'].name,
            e.get('MODEL_ID') or None,
            e.get('CACHE_TYPE') or None,
            e['VALUE'],
            round(e.get('COST') or 0, 9),
        )
        for e in gateway.event_rows
        if e['EVENT_TYPE']
        in (EventType.INPUT_TOKEN_PROCESSED, EventType.OUTPUT_TOKEN_PROCESSED)
    ]


def limit_events(gateway) -> list[tuple]:
    """Return the limit and threshold events: type, scope, category and,
    for a threshold, its percentage.
    """
    return [
        (
            e['EVENT_TYPE'].name,
            e['ATTRIBUTES']['limit_scope'],
            e['ATTRIBUTES']['category'],
            e['ATTRIBUTES'].get('threshold_percentage'),
        )
        for e in gateway.event_rows
        if e['EVENT_TYPE'].name.endswith('_LIMIT')
        or e['EVENT_TYPE'] is EventType.LIMIT_THRESHOLD
    ]


def routing_events(gateway) -> list[tuple]:
    """Return the routing events: the routing's name and the model selected."""
    return [
        (e['ROUTING_NAME'], e['ROUTING_SELECTED_MODEL_ID'])
        for e in gateway.event_rows
        if e['EVENT_TYPE'] is EventType.ROUTING
    ]


def model_events(gateway) -> list[tuple]:
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
