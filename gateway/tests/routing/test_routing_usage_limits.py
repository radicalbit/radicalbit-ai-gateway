"""A routing call is spend: it is costed and consumes the caller's limits (AG-1092)."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pook
import pytest

from tests.common.db_mock import API_KEY_UUID, GROUP_UUID, REQUEST_UUID
from tests.common.limits import (
    consumed,
    credential_limit,
    project_limit,
    request_limits,
)
from tests.common.mocked_build_openai_chat_completion import (
    to_mock_openai_chat_completion,
)
from tests.common.scope import scope_of

from radicalbit_ai_gateway.endpoints.chat_completions import pipeline as chat_pipeline
from radicalbit_ai_gateway.endpoints.chat_completions.pipeline import ChatRequest
from radicalbit_ai_gateway.gateway_route.factory import (
    build_gateway_routes_from_config,
    initialize_async_routers,
)
from radicalbit_ai_gateway.gateway_route.route import GatewayRoute
from radicalbit_ai_gateway.gateway_route.scope import RequestScope
from radicalbit_ai_gateway.guardrails.guardrails import Guardrails
from radicalbit_ai_gateway.guardrails.judges.judge_engine import JudgeEngine
from radicalbit_ai_gateway.guardrails.presidio import PresidioEngine
from radicalbit_ai_gateway.limiting.limits import RequestLimits
from radicalbit_ai_gateway.limiting.windows import (
    Category,
    credential_window,
    project_window,
)
from radicalbit_ai_gateway.llm.messages import HumanMessage
from radicalbit_ai_gateway.models.event_payload import InputTokenProcessedPayload
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.request_identity import RequestIdentity
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.exceptions import InputTokenLimitExceeded

PROJECT_UUID = '2f1c6d4e-0000-4000-8000-0000000000bb'
ROUTE = 'routed'
EMBEDDINGS_URL = 'https://api.openai.com/v1/embeddings'
CHAT_URL = 'https://api.openai.com/v1/chat/completions'
MODEL_INVOKER_EMIT = 'radicalbit_ai_gateway.invocation.recorder.emit_event'
LIMITS_EMIT = 'radicalbit_ai_gateway.limiting.limits.emit_event'

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


async def _route(config: GatewayConfig) -> GatewayRoute:
    """Build the route as the server does, then compute its centroids."""
    routes = build_gateway_routes_from_config(
        gateway_config=config,
        guardrails=Guardrails(
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
    await initialize_async_routers(routes)
    return route


def _scope(route: GatewayRoute, limits: RequestLimits | None = None) -> RequestScope:
    return scope_of(
        route,
        limits or request_limits(route),
        request_uuid=str(REQUEST_UUID),
        api_key_uuid=str(API_KEY_UUID),
        api_key_name='rb-key',
        group_uuid=str(GROUP_UUID),
        group_name='test-group',
    )


def _chat(**params) -> ChatRequest:
    return ChatRequest(
        messages=[HumanMessage(content=QUESTION)], tools=[], params=params
    )


async def _complete(route: GatewayRoute, limits: RequestLimits | None = None):
    return await chat_pipeline.complete(_scope(route, limits), _chat())


def _emitted(emit) -> list:
    return [c.args[0] for c in emit.call_args_list]


@pook.activate
@pytest.mark.asyncio
async def test_semantic_routing_embedding_emits_a_routing_cost_event():
    _mock_providers()
    with patch(MODEL_INVOKER_EMIT) as emit:
        route = await _route(_config())
        await _complete(route)

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


async def _no_chunks(**_):
    return
    yield


@pook.activate
@pytest.mark.asyncio
async def test_a_streamed_request_is_charged_for_routing_too():
    _mock_providers()
    with patch(MODEL_INVOKER_EMIT) as emit:
        route = await _route(_config())
        route.chat_invoker.stream = _no_chunks
        chunks = await chat_pipeline.stream(_scope(route), _chat(stream=True))
        assert [chunk async for chunk in chunks] == []

    assert [
        e.value
        for e in _emitted(emit)
        if isinstance(e, InputTokenProcessedPayload) and e.is_routing
    ] == [QUESTION_TOKENS]


# Limits well above what one request uses: they only count here.
ROUTE_LIMITS = {
    'token_limiting': {'input': {'window_size': '1 hour', 'max_tokens': 1000}},
    'budget_limiting': {'window_size': '1 hour', 'max_budget': 10},
}
CREDENTIAL_LIMITS = [
    credential_limit('token_input', 1000, '1 hour'),
    credential_limit('budget', 10, '1 hour'),
]
PROJECT_LIMITS = [project_limit(10, '1 hour')]
ROUTING_COST = int(QUESTION_TOKENS * EMBEDDING_INPUT_PRICE * 1_000_000_000)


def _limited(route: GatewayRoute) -> RequestLimits:
    return request_limits(route, CREDENTIAL_LIMITS, PROJECT_LIMITS)


async def _consumption(route: GatewayRoute) -> list[int]:
    """Return the route's, the credential's and the project's counters."""
    credential = str(API_KEY_UUID)
    return [
        await consumed(route.route_limits.window(Category.INPUT_TOKENS)),
        await consumed(route.route_limits.window(Category.COST)),
        await consumed(credential_window(credential, 'token_input', *HOUR)),
        await consumed(credential_window(credential, 'budget', *HOUR)),
        await consumed(project_window(PROJECT_UUID, *HOUR)),
    ]


HOUR = ('FIXED_WINDOW', '1 hour')


@pook.activate
@pytest.mark.asyncio
async def test_semantic_routing_embedding_consumes_route_credential_and_project_limits():
    _mock_providers()
    with patch(MODEL_INVOKER_EMIT):
        route = await _route(_config(**ROUTE_LIMITS))
        await _complete(route, _limited(route))

    assert await _consumption(route) == [
        QUESTION_TOKENS,
        ROUTING_COST,
        QUESTION_TOKENS,
        ROUTING_COST,
        ROUTING_COST,
    ]


@pook.activate
@pytest.mark.asyncio
async def test_centroids_at_startup_emit_no_cost_event_and_count_nothing():
    mock = _mock_providers()
    with patch(MODEL_INVOKER_EMIT) as emit:
        route = await _route(_config(**ROUTE_LIMITS))

    assert mock.calls == 2  # one centroid per output_mapping entry
    emit.assert_not_called()
    assert await _consumption(route) == [0, 0, 0, 0, 0]


# The limit check runs before routing, so routing spend is charged to the
# next request, not to the one it routes.

INPUT_LIMIT = {
    'input': {'window_size': '1 hour', 'max_tokens': 10}
}  # question + routing > 10


@pook.activate
@pytest.mark.asyncio
async def test_semantic_routing_spend_is_charged_to_the_next_request():
    _mock_providers()
    with patch(MODEL_INVOKER_EMIT), patch(LIMITS_EMIT):
        route = await _route(_config(token_limiting=INPUT_LIMIT))

        await _complete(route)
        with pytest.raises(InputTokenLimitExceeded):
            await _complete(route)


@pook.activate
@pytest.mark.asyncio
async def test_a_failing_routing_spend_count_does_not_fail_the_request():
    _mock_providers()
    with (
        patch(MODEL_INVOKER_EMIT),
        patch.object(
            RequestLimits, 'count', side_effect=RuntimeError('limits are down')
        ) as count,
    ):
        route = await _route(_config(**ROUTE_LIMITS))
        response = await _complete(route, _limited(route))

    # Routing never fails a request: it is still served.
    count.assert_awaited_once()
    assert response.choices[0].message.content == 'Paris'
