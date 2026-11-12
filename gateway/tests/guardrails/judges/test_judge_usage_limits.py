"""A judge call consumes the same limit counters as the main call (AG-1022)."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

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
from tests.common.resolve_route_models import resolve_route_models
from tests.common.scope import scope_of

from radicalbit_ai_gateway.endpoints.chat_completions import pipeline as chat_pipeline
from radicalbit_ai_gateway.endpoints.chat_completions.pipeline import ChatRequest
from radicalbit_ai_gateway.endpoints.embeddings import pipeline as embeddings_pipeline
from radicalbit_ai_gateway.gateway_route.route import GatewayRoute
from radicalbit_ai_gateway.guardrails.guardrails import Guardrails
from radicalbit_ai_gateway.guardrails.judges.judge_engine import JudgeEngine
from radicalbit_ai_gateway.guardrails.presidio import PresidioEngine
from radicalbit_ai_gateway.limiting.limits import RequestLimits, RouteLimits
from radicalbit_ai_gateway.limiting.windows import (
    Category,
    credential_window,
    project_window,
)
from radicalbit_ai_gateway.llm.messages import AIMessage, HumanMessage
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.judge_result import JudgeResult
from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.exceptions import InputTokenLimitExceeded

PROJECT_UUID = '2f1c6d4e-0000-4000-8000-0000000000aa'
ROUTE = 'judged'

# The judge model has its own price, far from the main model's.
JUDGE_IN, JUDGE_OUT = 40, 6
JUDGE_INPUT_PRICE = Decimal('0.00001')
JUDGE_OUTPUT_PRICE = Decimal('0.00002')
EMBEDDING_TOKENS = 2
EMBEDDING_PRICE = Decimal('0.000003')


def _config(where: str, behavior: str = 'block', **route) -> GatewayConfig:
    credentials = {'api_key': 'sk-test'}
    return GatewayConfig.model_validate(
        {
            'chat_models': [
                {
                    'model_id': 'gpt',
                    'model': 'openai/gpt-4o-mini',
                    'credentials': credentials,
                    'input_cost_per_million_tokens': 1,
                    'output_cost_per_million_tokens': 2,
                },
                {
                    'model_id': 'judge',
                    'model': 'openai/gpt-4o',
                    'credentials': credentials,
                    'input_cost_per_million_tokens': 10,
                    'output_cost_per_million_tokens': 20,
                },
            ],
            'embedding_models': [
                {
                    'model_id': 'emb',
                    'model': 'openai/text-embedding-3-small',
                    'credentials': credentials,
                    'input_cost_per_million_tokens': 3,
                }
            ],
            'guardrails': [
                {
                    'name': 'j',
                    'type': 'judge',
                    'where': where,
                    'behavior': behavior,
                    'parameters': {'model_id': 'judge', 'prompt': 'Judge this.'},
                }
            ],
            'routes': {
                ROUTE: {
                    'chat_models': ['gpt'],
                    'embedding_models': ['emb'],
                    'guardrails': ['j'],
                    **route,
                }
            },
        }
    )


def _judge_llm(triggered: bool = False) -> MagicMock:
    """Stands in for the judge chat model: answers ``triggered`` with usage."""
    answer = {
        'raw': AIMessage(
            content=f'{{"triggered": {str(triggered).lower()}}}',
            usage_metadata={
                'input_tokens': JUDGE_IN,
                'output_tokens': JUDGE_OUT,
                'total_tokens': JUDGE_IN + JUDGE_OUT,
            },
        ),
        'parsed': JudgeResult(triggered=triggered, reasoning=None, violation_type=None),
        'parsing_error': None,
    }
    llm = MagicMock()
    llm.with_structured_output.return_value.ainvoke = AsyncMock(return_value=answer)
    return llm


def _gateway(where: str, behavior: str = 'block') -> GatewayRoute:
    config = _config(where, behavior)
    cost_service = MagicMock(spec_set=CostService)
    route_cfg, chat_models, embedding_models = resolve_route_models(config, ROUTE)
    return GatewayRoute(
        gateway_route_config=route_cfg,
        chat_models=chat_models,
        embedding_models=embedding_models,
        guardrails=Guardrails(
            presidio_engine=PresidioEngine(),
            judge_engine=JudgeEngine(prompt_manager=MagicMock(spec_set=PromptManager)),
            cost_service=cost_service,
            guardrails=config.guardrails,
            chat_models_by_id=config.chat_models_by_id,
        ).for_route(route_cfg),
        gateway_cache=None,
        cost_service=cost_service,
        project_uuid=PROJECT_UUID,
        project_name='test-project',
    )


def _caller() -> dict:
    return {
        'request_uuid': str(REQUEST_UUID),
        'api_key_uuid': str(API_KEY_UUID),
        'api_key_name': 'rb-key',
        'group_uuid': str(GROUP_UUID),
        'group_name': 'test-group',
    }


def _chat(question: str = 'What is the capital of France?') -> ChatRequest:
    return ChatRequest(messages=[HumanMessage(content=question)], tools=[])


# Limits well above what one request uses: they only count here.
ROUTE_LIMITS = {
    'token_limiting': {
        'input': {'window_size': '1 hour', 'max_tokens': 1000},
        'output': {'window_size': '1 hour', 'max_tokens': 1000},
    },
    'budget_limiting': {'window_size': '1 hour', 'max_budget': 10},
}
CREDENTIAL_LIMITS = [
    credential_limit('token_input', 1000, '1 hour'),
    credential_limit('token_output', 1000, '1 hour'),
    credential_limit('budget', 10, '1 hour'),
]
PROJECT_LIMITS = [project_limit(10, '1 hour')]
HOUR = ('FIXED_WINDOW', '1 hour')
JUDGE_COST = int(JUDGE_IN * JUDGE_INPUT_PRICE * 1_000_000_000) + int(
    JUDGE_OUT * JUDGE_OUTPUT_PRICE * 1_000_000_000
)


def _limited_gateway(where: str, behavior: str = 'block', **route) -> GatewayRoute:
    """Return a route with its own limits, as the route factory builds it."""
    gateway = _gateway(where, behavior)
    config = _config(where, behavior, **route).routes[ROUTE]
    gateway.route_limits = RouteLimits.from_config(config, PROJECT_UUID)
    return gateway


def _limits(gateway: GatewayRoute) -> RequestLimits:
    return request_limits(gateway, CREDENTIAL_LIMITS, PROJECT_LIMITS)


async def _consumption(gateway: GatewayRoute) -> dict[str, int]:
    credential = str(API_KEY_UUID)
    windows = {
        'route input': gateway.route_limits.window(Category.INPUT_TOKENS),
        'route output': gateway.route_limits.window(Category.OUTPUT_TOKENS),
        'route cost': gateway.route_limits.window(Category.COST),
        'credential input': credential_window(credential, 'token_input', *HOUR),
        'credential output': credential_window(credential, 'token_output', *HOUR),
        'credential cost': credential_window(credential, 'budget', *HOUR),
        'project cost': project_window(PROJECT_UUID, *HOUR),
    }
    return {name: await consumed(window) for name, window in windows.items()}


JUDGE_COUNTED = {
    'route input': JUDGE_IN,
    'route output': JUDGE_OUT,
    'route cost': JUDGE_COST,
    'credential input': JUDGE_IN,
    'credential output': JUDGE_OUT,
    'credential cost': JUDGE_COST,
    'project cost': JUDGE_COST,
}


@pytest.fixture
def judge():
    with (
        patch(
            'radicalbit_ai_gateway.guardrails.judges.judge_engine.build_chat_model',
            return_value=_judge_llm(),
        ),
        patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.emit_event'),
        patch('radicalbit_ai_gateway.invocation.recorder.emit_event'),
        patch('radicalbit_ai_gateway.limiting.limit_event.emit_event'),
    ):
        yield


@pytest.mark.parametrize('where', ['input', 'output'])
@pook.activate
@pytest.mark.asyncio
async def test_chat_judge_call_consumes_route_credential_and_project_limits(
    where, judge
):
    # The main reply carries no usage, so every count comes from the judge.
    pook.post(
        url='https://api.openai.com/v1/chat/completions',
        reply=200,
        response_json=to_mock_openai_chat_completion('Paris').model_dump_json(),
    )
    gateway = _limited_gateway(where, **ROUTE_LIMITS)

    await chat_pipeline.complete(
        scope_of(gateway, _limits(gateway), **_caller()), _chat()
    )

    assert await _consumption(gateway) == JUDGE_COUNTED


@pytest.mark.parametrize('where', ['input', 'output'])
@pook.activate
@pytest.mark.asyncio
async def test_warn_judge_is_called_and_charged_once(where, judge):
    pook.post(
        url='https://api.openai.com/v1/chat/completions',
        reply=200,
        response_json=to_mock_openai_chat_completion('Paris').model_dump_json(),
    )
    judge_llm = _judge_llm(triggered=True)
    gateway = _limited_gateway(where, behavior='warn', **ROUTE_LIMITS)

    with patch(
        'radicalbit_ai_gateway.guardrails.judges.judge_engine.build_chat_model',
        return_value=judge_llm,
    ):
        scope = scope_of(gateway, _limits(gateway), **_caller())
        await chat_pipeline.complete(scope, _chat())

    assert judge_llm.with_structured_output.return_value.ainvoke.await_count == 1
    # The main reply carries no usage: the one count is the judge's.
    assert (await _consumption(gateway))['credential input'] == JUDGE_IN
    assert scope.headers()['X-RB-AIGATEWAY-GUARDRAILS-WARN'] == 'true'
    assert scope.headers()[f'X-RB-AIGATEWAY-GUARDRAILS-{where.upper()}-WARN'] == 'true'


@pook.activate
@pytest.mark.asyncio
async def test_embedding_call_and_its_judge_consume_route_credential_and_project_limits(
    judge,
):
    pook.post(
        url='https://api.openai.com/v1/embeddings',
        reply=200,
        response_json={
            'object': 'list',
            'data': [{'object': 'embedding', 'embedding': [0.1], 'index': 0}],
            'model': 'text-embedding-3-small',
            'usage': {
                'prompt_tokens': EMBEDDING_TOKENS,
                'total_tokens': EMBEDDING_TOKENS,
            },
        },
    )
    gateway = _limited_gateway('input', **ROUTE_LIMITS)

    await embeddings_pipeline.embed(
        scope_of(gateway, _limits(gateway), **_caller()), ['hello world']
    )

    embedding_cost = int(EMBEDDING_TOKENS * EMBEDDING_PRICE * 1_000_000_000)
    # Embeddings have no output: only the judge's output is counted.
    assert await _consumption(gateway) == {
        'route input': JUDGE_IN + EMBEDDING_TOKENS,
        'route output': JUDGE_OUT,
        'route cost': JUDGE_COST + embedding_cost,
        'credential input': JUDGE_IN + EMBEDDING_TOKENS,
        'credential output': JUDGE_OUT,
        'credential cost': JUDGE_COST + embedding_cost,
        'project cost': JUDGE_COST + embedding_cost,
    }


# The limit check runs before the input judge, so a judge's spend is charged
# to the next request, not to the one it checks.

INPUT_LIMIT = {'input': {'window_size': '1 hour', 'max_tokens': 30}}  # < JUDGE_IN


@pytest.fixture
def judge_calls():
    llm = _judge_llm()
    with (
        patch(
            'radicalbit_ai_gateway.guardrails.judges.judge_engine.build_chat_model',
            return_value=llm,
        ),
        patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.emit_event'),
        patch('radicalbit_ai_gateway.invocation.recorder.emit_event'),
        patch('radicalbit_ai_gateway.limiting.limits.emit_event'),
    ):
        yield llm.with_structured_output.return_value.ainvoke.await_args_list


@pook.activate
@pytest.mark.asyncio
async def test_chat_judge_spend_is_charged_to_the_next_request(judge_calls):
    pook.post(
        url='https://api.openai.com/v1/chat/completions',
        reply=200,
        response_json=to_mock_openai_chat_completion('Paris').model_dump_json(),
    )
    gateway = _limited_gateway('input', token_limiting=INPUT_LIMIT)

    def scope():
        return scope_of(gateway, request_limits(gateway), **_caller())

    await chat_pipeline.complete(scope(), _chat('Capital of France?'))
    with pytest.raises(InputTokenLimitExceeded):
        await chat_pipeline.complete(scope(), _chat('Capital of France?'))

    assert len(judge_calls) == 1


@pook.activate
@pytest.mark.asyncio
async def test_embedding_judge_spend_is_charged_to_the_next_request(judge_calls):
    pook.post(
        url='https://api.openai.com/v1/embeddings',
        reply=200,
        response_json={
            'object': 'list',
            'data': [{'object': 'embedding', 'embedding': [0.1], 'index': 0}],
            'model': 'text-embedding-3-small',
            'usage': {'prompt_tokens': 2, 'total_tokens': 2},
        },
    )
    gateway = _limited_gateway('input', token_limiting=INPUT_LIMIT)

    def scope():
        return scope_of(gateway, request_limits(gateway), **_caller())

    await embeddings_pipeline.embed(scope(), ['hello world'])
    with pytest.raises(InputTokenLimitExceeded):
        await embeddings_pipeline.embed(scope(), ['hello world'])

    assert len(judge_calls) == 1
