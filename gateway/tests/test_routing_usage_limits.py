"""A routing call is spend: it is costed and consumes the caller's limits (AG-1092)."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pook
import pytest

from tests.common.db_mock import API_KEY_UUID, GROUP_UUID, REQUEST_UUID
from tests.common.mocked_build_openai_chat_completion import (
    to_mock_openai_chat_completion,
)

from radicalbit_ai_gateway.ai_gateway import GatewayRoute
from radicalbit_ai_gateway.guardrails.guardrail_engine import GuardrailEngine
from radicalbit_ai_gateway.guardrails.judges.judge_engine import JudgeEngine
from radicalbit_ai_gateway.guardrails.presidio import PresidioEngine
from radicalbit_ai_gateway.limiting.token_limiter import InputTokenLimitExceeded
from radicalbit_ai_gateway.llm.messages import HumanMessage
from radicalbit_ai_gateway.models.event_payload import InputTokenProcessedPayload
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.request_identity import RequestIdentity
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.gateway_route_factory import (
    build_gateway_routes_from_config,
    initialize_async_routers,
)
from radicalbit_ai_gateway.utils.request_context import (
    set_current_credential_limiter,
    set_current_project_budget_limiter,
)

PROJECT_UUID = '2f1c6d4e-0000-4000-8000-0000000000bb'
ROUTE = 'routed'
EMBEDDINGS_URL = 'https://api.openai.com/v1/embeddings'
CHAT_URL = 'https://api.openai.com/v1/chat/completions'
MODEL_INVOKER_EMIT = 'radicalbit_ai_gateway.invocation.model_invoker.emit_event'
TOKEN_LIMITER_EMIT = 'radicalbit_ai_gateway.limiting.token_limiter.emit_event'

QUESTION = 'What is the capital of France?'
# cl100k_base, the text-embedding-3-small tokenizer: one token per word, plus '?'.
QUESTION_TOKENS = 7
EMBEDDING_INPUT_PRICE = Decimal('0.00002')  # 20 per million tokens

IDENTITY = RequestIdentity(
    request_uuid=str(REQUEST_UUID),
    route_name=ROUTE,
    api_key_uuid=str(API_KEY_UUID),
    api_key_name='rb-key',
    group_uuid=str(GROUP_UUID),
    group_name='test-group',
    project_uuid=PROJECT_UUID,
    project_name='test-project',
)


def _config(**route) -> GatewayConfig:
    credentials = {'api_key': 'sk-test'}
    return GatewayConfig.model_validate(
        {
            'chat_models': [
                {
                    'model_id': 'small',
                    'model': 'openai/gpt-4o-mini',
                    'credentials': credentials,
                    'input_cost_per_million_tokens': 1,
                    'output_cost_per_million_tokens': 2,
                },
                {
                    'model_id': 'big',
                    'model': 'openai/gpt-4o',
                    'credentials': credentials,
                    'input_cost_per_million_tokens': 5,
                    'output_cost_per_million_tokens': 10,
                },
            ],
            # Top-level only: the route does not list it.
            'embedding_models': [
                {
                    'model_id': 'emb',
                    'model': 'openai/text-embedding-3-small',
                    'credentials': credentials,
                    'input_cost_per_million_tokens': 20,
                }
            ],
            'routing': [
                {
                    'name': 'by-meaning',
                    'type': 'semantic',
                    'embedding_model_id': 'emb',
                    'default_model_id': 'small',
                    'similarity_threshold': 0.5,
                    'output_mapping': [
                        {'model_id': 'small', 'conditions': ['tell me a joke']},
                        {'model_id': 'big', 'conditions': ['write a python app']},
                    ],
                }
            ],
            'routes': {
                ROUTE: {
                    'chat_models': ['small', 'big'],
                    'routing': 'by-meaning',
                    **route,
                }
            },
        }
    )


def _mock_providers():
    """Mock both providers. Return the embeddings mock."""
    # One text per call (one utterance per centroid, one query), one vector back.
    embeddings = pook.post(
        url=EMBEDDINGS_URL,
        reply=200,
        response_json={
            'object': 'list',
            'data': [{'object': 'embedding', 'embedding': [0.1, 0.2], 'index': 0}],
            'model': 'text-embedding-3-small',
            'usage': {'prompt_tokens': 1, 'total_tokens': 1},
        },
    ).persist()
    # The main reply carries no usage, so every count comes from routing.
    pook.post(
        url=CHAT_URL,
        reply=200,
        response_json=to_mock_openai_chat_completion('Paris').model_dump_json(),
    ).persist()
    return embeddings


def _limiter() -> AsyncMock:
    # No *_config: the route checks are skipped, only counting is observed.
    return AsyncMock(input_config=None, output_config=None, config=None)


async def _route(config: GatewayConfig, **limiters) -> GatewayRoute:
    """Build the route as the server does, then compute its centroids.

    ``limiters`` (``token_limiter``, ``budget_limiter``) replace the route's
    own, before the centroids are computed.
    """
    routes = build_gateway_routes_from_config(
        gateway_config=config,
        guardrail_engine=GuardrailEngine(
            presidio_engine=PresidioEngine(),
            judge_engine=JudgeEngine(prompt_manager=MagicMock()),
            cost_service=MagicMock(spec_set=CostService),
            guardrails=[],
        ),
        redis_client=None,
        cost_service=CostService(
            chat_models_by_id=config.chat_models_by_id,
            embedding_models_by_id=config.embedding_models_by_id,
        ),
        httpx_client=None,
        project_uuid=PROJECT_UUID,
    )
    route = routes[ROUTE]
    route.project_uuid = PROJECT_UUID
    route.project_name = 'test-project'
    for name, limiter in limiters.items():
        setattr(route, name, limiter)
    await initialize_async_routers(routes)
    return route


def _request() -> dict:
    return {
        'request_uuid': str(REQUEST_UUID),
        'api_key_uuid': str(API_KEY_UUID),
        'api_key_name': 'rb-key',
        'group_uuid': str(GROUP_UUID),
        'group_name': 'test-group',
        'route_name': ROUTE,
        'messages': [HumanMessage(content=QUESTION)],
        'tools': [],
        'tool_choice': None,
    }


def _emitted(emit) -> list:
    return [c.args[0] for c in emit.call_args_list]


@pook.activate
@pytest.mark.asyncio
async def test_semantic_routing_embedding_emits_a_routing_cost_event():
    _mock_providers()
    with patch(MODEL_INVOKER_EMIT) as emit:
        route = await _route(_config())
        await route.invoke(**_request())

    routing_inputs = [
        e
        for e in _emitted(emit)
        if isinstance(e, InputTokenProcessedPayload) and e.model_id == 'emb'
    ]
    assert len(routing_inputs) == 1
    event = routing_inputs[0]
    assert event.is_routing is True
    assert event.is_judge is False
    assert event.model_type == 'embeddings'
    assert event.value == QUESTION_TOKENS
    assert event.cost == pytest.approx(0.00014)  # 7 tokens at 20 per million
    assert event.request_uuid == str(REQUEST_UUID)
    assert event.project_uuid == PROJECT_UUID


@pook.activate
@pytest.mark.asyncio
async def test_a_streamed_request_is_charged_for_routing_too():
    _mock_providers()
    with patch(MODEL_INVOKER_EMIT) as emit:
        route = await _route(_config())
        await route.prepare_stream(**_request())

    assert [
        e.value
        for e in _emitted(emit)
        if isinstance(e, InputTokenProcessedPayload) and e.is_routing
    ] == [QUESTION_TOKENS]


@pytest.fixture
def limiters():
    route_tokens, route_budget = _limiter(), _limiter()
    credential, project = _limiter(), _limiter()
    set_current_credential_limiter(credential)
    set_current_project_budget_limiter(project)
    yield route_tokens, route_budget, credential, project
    set_current_credential_limiter(None)
    set_current_project_budget_limiter(None)


async def _limited_route(limiters) -> GatewayRoute:
    route_tokens, route_budget, _, _ = limiters
    return await _route(
        _config(), token_limiter=route_tokens, budget_limiter=route_budget
    )


@pook.activate
@pytest.mark.asyncio
async def test_semantic_routing_embedding_consumes_route_credential_and_project_limits(
    limiters,
):
    route_tokens, route_budget, credential, project = limiters
    _mock_providers()
    with patch(MODEL_INVOKER_EMIT):
        route = await _limited_route(limiters)
        await route.invoke(**_request())

    route_tokens.count_input.assert_any_await(
        prompt_tokens=QUESTION_TOKENS, identity=IDENTITY
    )
    route_budget.count_input.assert_any_await(
        token_count=QUESTION_TOKENS,
        input_cost_per_token=EMBEDDING_INPUT_PRICE,
        identity=IDENTITY,
    )
    credential.count_input_tokens.assert_any_await(QUESTION_TOKENS, IDENTITY)
    credential.count_budget_input.assert_any_await(
        token_count=QUESTION_TOKENS,
        input_cost_per_token=EMBEDDING_INPUT_PRICE,
        identity=IDENTITY,
    )
    project.count_input.assert_any_await(
        token_count=QUESTION_TOKENS,
        input_cost_per_token=EMBEDDING_INPUT_PRICE,
        identity=IDENTITY,
    )


@pook.activate
@pytest.mark.asyncio
async def test_centroids_at_startup_emit_no_cost_event_and_count_nothing(limiters):
    mock = _mock_providers()
    with patch(MODEL_INVOKER_EMIT) as emit:
        await _limited_route(limiters)

    assert mock.calls == 2  # one centroid per output_mapping entry
    emit.assert_not_called()
    for limiter in limiters:
        assert not [c for c in limiter.mock_calls if c[0].startswith('count')]


# The limit check runs before routing, so routing spend is charged to the
# next request, not to the one it routes.

INPUT_LIMIT = {
    'input': {'window_size': '1 hour', 'max_tokens': 10}
}  # question + routing > 10


@pook.activate
@pytest.mark.asyncio
async def test_semantic_routing_spend_is_charged_to_the_next_request():
    _mock_providers()
    with patch(MODEL_INVOKER_EMIT), patch(TOKEN_LIMITER_EMIT):
        route = await _route(_config(token_limiting=INPUT_LIMIT))

        await route.invoke(**_request())
        with pytest.raises(InputTokenLimitExceeded):
            await route.invoke(**_request())


@pook.activate
@pytest.mark.asyncio
async def test_a_failing_routing_spend_count_does_not_fail_the_request(limiters):
    _, _, credential, _ = limiters
    credential.count_input_tokens.side_effect = RuntimeError('limiter is down')
    _mock_providers()
    with patch(MODEL_INVOKER_EMIT):
        route = await _limited_route(limiters)
        response = await route.invoke(**_request())

    # Routing never fails a request: it is still served.
    credential.count_input_tokens.assert_any_await(QUESTION_TOKENS, IDENTITY)
    assert response.content.choices[0].message.content == 'Paris'
