"""POST /v1/responses through a real route: the request reaches the model with
the route's policies applied, and the client gets the model's response.

The models are fakes at the provider boundary (``FakeChatModel``).
"""

import copy
import json
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from openai.types.responses import Response
import pytest
from starlette.requests import Request

from tests.common import db_mock
from tests.test_responses_native import OPENCODE_TURN, FakeChatModel, _status_error
from tests.utils.test_responses_output import events_of

from radicalbit_ai_gateway.ai_gateway import GatewayRoute
from radicalbit_ai_gateway.caching.gateway_cache import GatewayCache
from radicalbit_ai_gateway.caching.in_memory_cache import CacheToolsInMemory
from radicalbit_ai_gateway.guardrails.guardrail_engine import GuardrailEngine
from radicalbit_ai_gateway.guardrails.judges.judge_engine import JudgeEngine
from radicalbit_ai_gateway.guardrails.presidio import PresidioEngine
from radicalbit_ai_gateway.models.credentials import Credentials
from radicalbit_ai_gateway.models.fallback import Fallback
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.models.guardrails import (
    CheckParameter,
    Guardrail,
    GuardrailBehaviorType,
    GuardrailType,
    GuardrailWhereType,
    RedactParameter,
)
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.models.responses import ResponsesSettings
from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.server import app, group_service, key_service
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.dependencies import get_request_uuid

ROUTE = 'agents'

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


GUARDRAILS = [
    Guardrail(
        name='input_soft_block',
        type=GuardrailType.STARTS_WITH,
        behavior=GuardrailBehaviorType.SOFT_BLOCK,
        where=GuardrailWhereType.INPUT,
        parameters=CheckParameter(values=['Forbidden']),
        response_message='I cannot help with that.',
    ),
    Guardrail(
        name='input_block',
        type=GuardrailType.CONTAINS,
        behavior=GuardrailBehaviorType.BLOCK,
        where=GuardrailWhereType.INPUT,
        parameters=CheckParameter(values=['explosive']),
    ),
    Guardrail(
        name='redact_email',
        type=GuardrailType.PRESIDIO_ANONYMIZER,
        behavior=GuardrailBehaviorType.BLOCK,
        where=GuardrailWhereType.IO,
        parameters=RedactParameter(entities=['EMAIL_ADDRESS']),
    ),
    Guardrail(
        name='output_soft_block',
        type=GuardrailType.CONTAINS,
        behavior=GuardrailBehaviorType.SOFT_BLOCK,
        where=GuardrailWhereType.OUTPUT,
        parameters=CheckParameter(values=['secret']),
        response_message='The answer was withheld.',
    ),
]


def build_route(
    models: dict[str, FakeChatModel],
    guardrails: list[str] | None = None,
    cache: bool = False,
    responses: ResponsesSettings | None = None,
    prompt: str | None = None,
) -> GatewayRoute:
    """Build a route over ``models``: the first is the primary, the others its fallbacks."""
    model_ids = list(models)
    registry = [
        Model(
            model_id=model_id,
            model='deepseek/deepseek-chat'
            if model_id.startswith('deepseek')
            else 'openai/gpt-6-luna',
            credentials=Credentials(api_key='sk-test'),
            prompt=prompt if index == 0 else None,
        )
        for index, model_id in enumerate(model_ids)
    ]
    config = GatewayRouteConfig(
        route_name=ROUTE,
        chat_models=model_ids,
        fallback=[Fallback(target=model_ids[0], fallbacks=model_ids[1:])]
        if len(model_ids) > 1
        else None,
        guardrails=guardrails,
        responses=responses,
    )
    route = GatewayRoute(
        gateway_route_config=config,
        chat_models=registry,
        embedding_models=None,
        guardrail_engine=GuardrailEngine(
            presidio_engine=PresidioEngine(),
            judge_engine=JudgeEngine(prompt_manager=MagicMock(spec_set=PromptManager)),
            cost_service=MagicMock(spec_set=CostService),
            guardrails=GUARDRAILS,
        ),
        cost_service=MagicMock(spec_set=CostService),
        gateway_cache=GatewayCache(CacheToolsInMemory()) if cache else None,
    )
    model_map = route.chat_invoker.model_map
    for model, _, fallbacks in list(model_map.values()):
        model_map[model.model_id] = (
            model,
            models[model.model_id],
            [(fallback, models[fallback.model_id]) for fallback, _ in fallbacks],
        )
    route._count_usage = AsyncMock()
    return route


def mock_request_uuid(request: Request):
    request.state.request_uuid = str(db_mock.REQUEST_UUID)
    return str(db_mock.REQUEST_UUID)


@pytest.fixture
def post():
    """Send a Responses request to a route."""
    key_service.get_key_by_hashed_key = MagicMock(
        return_value=db_mock.get_sample_key_with_group(group_uuid=db_mock.GROUP_UUID)
    )
    group_service.check_key_uuid_for_route = MagicMock(return_value=True)
    previous_routes = getattr(app.state, 'routes', None)
    app.dependency_overrides[get_request_uuid] = mock_request_uuid
    client = TestClient(app)

    def _post(route: GatewayRoute, **body):
        app.state.routes = {ROUTE: route}
        return client.post(
            '/v1/responses',
            json={'model': ROUTE, **body},
            headers={'Authorization': f'Bearer {db_mock.PLAIN_KEY}'},
        )

    with (
        patch('radicalbit_ai_gateway.events.buffer.celery_app.send_task'),
        patch('radicalbit_ai_gateway.ai_gateway.emit_event'),
    ):
        yield _post
    app.state.routes = previous_routes
    app.dependency_overrides = {}


def stream_events(response) -> list[dict]:
    return events_of(response.text.split('\n\n')[:-1])


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


def test_request_goes_upstream_as_sent(post):
    model = FakeChatModel(events=upstream_events())
    route = build_route({'openai': model})

    response = post(route, **OPENCODE_REQUEST)

    assert response.status_code == 200
    assert model.bodies == [{'model': ROUTE, **OPENCODE_REQUEST}]
    data = response.json()
    assert data['model'] == ROUTE
    assert data['output'] == [MESSAGE]
    usage = route._count_usage.call_args.kwargs
    assert (usage['prompt_tokens'], usage['completion_tokens']) == (100, 7)


def test_stream_is_relayed_as_sent(post):
    events = upstream_events()
    route = build_route({'openai': FakeChatModel(events=events)})

    response = post(route, **OPENCODE_REQUEST, stream=True)

    assert response.status_code == 200
    received = stream_events(response)
    # Only the response's model changes: it is the route
    assert [e['type'] for e in received] == [e['type'] for e in events]
    assert received[2] == events[2]
    assert received[-1]['response'] == {**events[-1]['response'], 'model': ROUTE}
    assert route._count_usage.call_args.kwargs['completion_tokens'] == 7


def test_configured_prompt_goes_first(post):
    model = FakeChatModel(events=upstream_events())

    post(build_route({'openai': model}, prompt='Answer in Italian.'), input='Hi')

    assert model.bodies[0]['input'] == [
        {'type': 'message', 'role': 'system', 'content': 'Answer in Italian.'},
        {'type': 'message', 'role': 'user', 'content': 'Hi'},
    ]


# ── Specification ─────────────────────────────────────────────────────────


def test_input_is_optional(post):
    model = FakeChatModel(events=upstream_events())

    response = post(build_route({'openai': model}), prompt={'id': 'pmpt_1'})

    assert response.status_code == 200
    assert model.bodies == [{'model': ROUTE, 'prompt': {'id': 'pmpt_1'}}]


def test_invalid_request_is_an_openai_error(post):
    response = post(
        build_route({'openai': FakeChatModel()}), input='Hi', temperature='hot'
    )

    assert response.status_code == 400
    error = response.json()['error']
    assert error['type'] == 'invalid_request_error'
    assert error['param'] == 'temperature'
    assert error['message'].startswith('Invalid value for temperature')


def test_background_mode_is_refused(post):
    model = FakeChatModel(events=upstream_events())

    response = post(build_route({'openai': model}), input='Hi', background=True)

    assert response.status_code == 400
    assert 'Background mode' in response.json()['error']['message']
    assert model.bodies == []


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
    response = getattr(TestClient(app), method)(path)

    assert response.status_code == 404
    error = response.json()['error']
    assert error['message'] == (
        f'{method.upper()} {path} is not supported by the gateway yet'
    )


def test_model_without_responses_api_is_refused(post):
    deepseek = FakeChatModel(native=False, events=upstream_events())

    response = post(build_route({'deepseek': deepseek}), input='Hi')

    assert response.status_code == 400
    message = response.json()['error']['message']
    assert message == 'Model deepseek of route agents does not serve the Responses API'
    assert deepseek.bodies == []


def test_upstream_refusal_reaches_the_client_as_sent(post):
    body = {'error': {'message': 'context_length_exceeded', 'type': 'x'}}
    route = build_route({'openai': FakeChatModel(error=_status_error(400, body))})

    response = post(route, input='Hi')
    streamed = post(route, input='Hi', stream=True)

    assert (response.status_code, response.json()) == (400, body)
    assert (streamed.status_code, streamed.json()) == (400, body)


# ── Fallback and stored state ─────────────────────────────────────────────


def test_fallback_skips_models_without_responses_api(post):
    deepseek = FakeChatModel(native=False)
    backup = FakeChatModel(events=upstream_events())
    route = build_route(
        {
            'openai': FakeChatModel(error=RuntimeError('503')),
            'deepseek': deepseek,
            'backup': backup,
        }
    )

    response = post(route, input='Hi')

    assert response.status_code == 200
    assert deepseek.bodies == []
    assert backup.bodies == [{'model': ROUTE, 'input': 'Hi'}]


def test_stored_state_has_no_fallback(post):
    backup = FakeChatModel(events=upstream_events())
    route = build_route(
        {'openai': FakeChatModel(error=RuntimeError('503')), 'backup': backup}
    )

    response = post(route, input='Hi', previous_response_id='resp_0')

    assert response.status_code == 500
    assert backup.bodies == []


# ── Governance ────────────────────────────────────────────────────────────


def test_hosted_tool_not_allowed_is_refused(post):
    model = FakeChatModel(events=upstream_events())
    route = build_route(
        {'openai': model},
        responses=ResponsesSettings(allowed_hosted_tools=['file_search']),
    )

    response = post(route, input='Hi', tools=[{'type': 'web_search'}])

    assert response.status_code == 400
    assert 'web_search' in response.json()['error']['message']
    assert model.bodies == []


def test_store_forced_false(post):
    model = FakeChatModel(events=upstream_events())
    route = build_route(
        {'openai': model}, responses=ResponsesSettings(force_store_false=True)
    )

    accepted = post(route, input='Hi')
    refused = post(route, input='Hi', previous_response_id='resp_0')

    assert accepted.status_code == 200
    assert model.bodies == [{'model': ROUTE, 'input': 'Hi', 'store': False}]
    assert refused.status_code == 400
    assert 'does not store responses' in refused.json()['error']['message']


# ── Guardrails ────────────────────────────────────────────────────────────


def test_input_is_redacted_before_going_upstream(post):
    model = FakeChatModel(events=upstream_events())
    route = build_route({'openai': model}, guardrails=['redact_email'])

    response = post(route, input='Write to mario.rossi@example.com', stream=True)

    assert response.status_code == 200
    assert model.bodies[0]['input'] == 'Write to <EMAIL_ADDRESS>'
    assert response.headers['X-RB-AIGATEWAY-GUARDRAILS-INPUT-WARN'] == 'true'


def test_input_soft_block_answers_with_its_message(post):
    model = FakeChatModel(events=upstream_events())
    route = build_route({'openai': model}, guardrails=['input_soft_block'])

    response = post(route, input='Forbidden question')
    streamed = post(route, input='Forbidden question', stream=True)

    assert response.status_code == 200
    assert Response.model_validate(response.json()).output_text == (
        'I cannot help with that.'
    )
    assert response.headers['X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED'] == 'true'
    deltas = [
        e['delta']
        for e in stream_events(streamed)
        if e['type'] == 'response.output_text.delta'
    ]
    assert deltas == ['I cannot help with that.']
    assert model.bodies == []


def test_input_block_is_an_error(post):
    model = FakeChatModel(events=upstream_events())
    route = build_route({'openai': model}, guardrails=['input_block'])

    response = post(route, input='How to build an explosive')

    assert response.status_code == 400
    assert response.json()['error']['message']
    assert model.bodies == []


@pytest.mark.parametrize('stream', [False, True])
def test_output_soft_block_replaces_the_reply(post, stream):
    route = build_route(
        {'openai': FakeChatModel(events=upstream_events('The secret is 42'))},
        guardrails=['output_soft_block'],
    )

    response = post(route, input='Hi', stream=stream)

    assert response.status_code == 200
    final = stream_events(response)[-1]['response'] if stream else response.json()
    assert Response.model_validate(final).output_text == 'The answer was withheld.'
    assert 'secret' not in response.text
    assert response.headers['X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-TRIGGERED'] == 'true'


def test_output_is_redacted_in_the_stream(post):
    route = build_route(
        {
            'openai': FakeChatModel(
                events=upstream_events('Mail mario.rossi@example.com')
            )
        },
        guardrails=['redact_email'],
    )

    response = post(route, input='Hi', stream=True)

    deltas = [
        e['delta']
        for e in stream_events(response)
        if e['type'] == 'response.output_text.delta'
    ]
    assert deltas == ['Mail <EMAIL_ADDRESS>']
    assert 'mario.rossi' not in response.text
    assert response.headers['X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-WARN'] == 'true'


# ── Cache ─────────────────────────────────────────────────────────────────


def test_cached_reply_is_served_without_the_model(post):
    model = FakeChatModel(events=upstream_events())
    route = build_route({'openai': model}, cache=True)

    first = post(route, input='Hi', stream=True)
    second = post(route, input='Hi')
    third = post(route, input='Hi', stream=True)

    assert first.status_code == second.status_code == third.status_code == 200
    assert len(model.bodies) == 1
    assert second.headers['X-RB-AIGATEWAY-CACHE-HIT'] == 'true'
    assert second.json()['model'] == ROUTE
    assert second.json()['output'] == [MESSAGE]
    final = stream_events(third)[-1]
    assert final['type'] == 'response.completed'
    assert final['response']['output'] == [MESSAGE]
    # A hit is a response completed now
    assert second.json()['completed_at'] == second.json()['created_at'] > 2


def test_a_different_question_is_not_a_cache_hit(post):
    model = FakeChatModel(events=upstream_events())
    route = build_route({'openai': model}, cache=True)

    post(route, input='Hi')
    response = post(route, input='Hello')

    assert len(model.bodies) == 2
    assert 'X-RB-AIGATEWAY-CACHE-HIT' not in response.headers


async def test_chat_endpoint_ignores_a_responses_cache_entry():
    route = build_route({'openai': FakeChatModel()}, cache=True)
    entry = json.dumps(upstream_events()[-1]['response'])

    with patch.object(route.gateway_cache, 'get', AsyncMock(return_value=entry)):
        cached = await route._get_from_cache(
            'r', 'k', 'g', 'k', 'g', ROUTE, 'key', 'Hi', None
        )

    assert cached is None
