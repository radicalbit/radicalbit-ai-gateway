"""A judge call consumes the same limit counters as the main call (AG-1022)."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda
import pook
import pytest

from tests.common.db_mock import API_KEY_UUID, GROUP_UUID, REQUEST_UUID
from tests.common.mocked_build_openai_chat_completion import (
    to_mock_openai_chat_completion,
)
from tests.common.resolve_route_models import resolve_route_models

from radicalbit_ai_gateway.ai_gateway import GatewayRoute
from radicalbit_ai_gateway.guardrails.guardrail_engine import GuardrailEngine
from radicalbit_ai_gateway.guardrails.judges.judge_engine import JudgeEngine
from radicalbit_ai_gateway.guardrails.presidio import PresidioEngine
from radicalbit_ai_gateway.limiting.token_limiter import InputTokenLimitExceeded
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.judge_result import JudgeResult
from radicalbit_ai_gateway.models.request_identity import RequestIdentity
from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.request_context import (
    set_current_credential_limiter,
    set_current_project_budget_limiter,
)

PROJECT_UUID = '2f1c6d4e-0000-4000-8000-0000000000aa'
ROUTE = 'judged'

# The judge model has its own price, far from the main model's.
JUDGE_IN, JUDGE_OUT = 40, 6
JUDGE_INPUT_PRICE = Decimal('0.00001')
JUDGE_OUTPUT_PRICE = Decimal('0.00002')

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


def _config(where: str, **route) -> GatewayConfig:
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
                }
            ],
            'guardrails': [
                {
                    'name': 'j',
                    'type': 'judge',
                    'where': where,
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


def _limiter() -> AsyncMock:
    # No *_config: the route checks are skipped, only counting is observed.
    return AsyncMock(input_config=None, output_config=None, config=None)


def _judge_llm() -> MagicMock:
    """Stands in for the judge chat model: answers 'not triggered' with usage."""
    answer = {
        'raw': AIMessage(
            content='{"triggered": false}',
            usage_metadata={
                'input_tokens': JUDGE_IN,
                'output_tokens': JUDGE_OUT,
                'total_tokens': JUDGE_IN + JUDGE_OUT,
            },
        ),
        'parsed': JudgeResult(triggered=False, reasoning=None, violation_type=None),
        'parsing_error': None,
    }
    llm = MagicMock()
    llm.with_structured_output.return_value = RunnableLambda(lambda _: answer)
    return llm


@pytest.fixture
def limiters():
    route_tokens, route_budget = _limiter(), _limiter()
    credential, project = _limiter(), _limiter()
    set_current_credential_limiter(credential)
    set_current_project_budget_limiter(project)
    with (
        patch(
            'radicalbit_ai_gateway.guardrails.judges.judge_engine.init_chat_model',
            return_value=_judge_llm(),
        ),
        patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.emit_event'),
        patch('radicalbit_ai_gateway.invocation.model_invoker.emit_event'),
    ):
        yield route_tokens, route_budget, credential, project
    set_current_credential_limiter(None)
    set_current_project_budget_limiter(None)


def _gateway(where: str, route_tokens, route_budget) -> GatewayRoute:
    config = _config(where)
    cost_service = MagicMock(spec_set=CostService)
    route_cfg, chat_models, embedding_models = resolve_route_models(config, ROUTE)
    return GatewayRoute(
        gateway_route_config=route_cfg,
        chat_models=chat_models,
        embedding_models=embedding_models,
        guardrail_engine=GuardrailEngine(
            presidio_engine=PresidioEngine(),
            judge_engine=JudgeEngine(prompt_manager=MagicMock(spec_set=PromptManager)),
            cost_service=cost_service,
            guardrails=config.guardrails,
            chat_models_by_id=config.chat_models_by_id,
        ),
        gateway_cache=None,
        cost_service=cost_service,
        token_limiter=route_tokens,
        budget_limiter=route_budget,
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
        'route_name': ROUTE,
    }


def _assert_judge_counted(route_tokens, route_budget, credential, project):
    route_tokens.count_input.assert_any_await(prompt_tokens=JUDGE_IN, identity=IDENTITY)
    route_tokens.count_output.assert_any_await(token_count=JUDGE_OUT, identity=IDENTITY)
    route_budget.count_input.assert_any_await(
        token_count=JUDGE_IN, input_cost_per_token=JUDGE_INPUT_PRICE, identity=IDENTITY
    )
    route_budget.count_output.assert_any_await(
        token_count=JUDGE_OUT,
        output_cost_per_token=JUDGE_OUTPUT_PRICE,
        identity=IDENTITY,
    )
    credential.count_input_tokens.assert_any_await(JUDGE_IN, IDENTITY)
    credential.count_output_tokens.assert_any_await(JUDGE_OUT, IDENTITY)
    credential.count_budget_input.assert_any_await(
        token_count=JUDGE_IN, input_cost_per_token=JUDGE_INPUT_PRICE, identity=IDENTITY
    )
    credential.count_budget_output.assert_any_await(
        token_count=JUDGE_OUT,
        output_cost_per_token=JUDGE_OUTPUT_PRICE,
        identity=IDENTITY,
    )
    project.count_input.assert_any_await(
        token_count=JUDGE_IN, input_cost_per_token=JUDGE_INPUT_PRICE, identity=IDENTITY
    )
    project.count_output.assert_any_await(
        token_count=JUDGE_OUT,
        output_cost_per_token=JUDGE_OUTPUT_PRICE,
        identity=IDENTITY,
    )


@pytest.mark.parametrize('where', ['input', 'output'])
@pook.activate
@pytest.mark.asyncio
async def test_chat_judge_call_consumes_route_credential_and_project_limits(
    where, limiters
):
    # The main reply carries no usage, so every count comes from the judge.
    pook.post(
        url='https://api.openai.com/v1/chat/completions',
        reply=200,
        response_json=to_mock_openai_chat_completion('Paris').model_dump_json(),
    )
    gateway = _gateway(where, *limiters[:2])

    await gateway.invoke(
        **_caller(),
        messages=[HumanMessage(content='What is the capital of France?')],
        tools=[],
        tool_choice=None,
    )

    _assert_judge_counted(*limiters)


@pook.activate
@pytest.mark.asyncio
async def test_embedding_input_judge_call_consumes_route_credential_and_project_limits(
    limiters,
):
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
    gateway = _gateway('input', *limiters[:2])

    await gateway.invoke_embeddings(**_caller(), input_texts=['hello world'])

    _assert_judge_counted(*limiters)


# The limit check runs before the input judge, so a judge's spend is charged
# to the next request, not to the one it checks.

INPUT_LIMIT = {'input': {'window_size': '1 hour', 'max_tokens': 30}}  # < JUDGE_IN


@pytest.fixture
def judge_calls():
    calls = []
    llm = _judge_llm()
    answer = llm.with_structured_output.return_value
    llm.with_structured_output.return_value = RunnableLambda(
        lambda prompt: calls.append(prompt) or answer.invoke(prompt)
    )
    with (
        patch(
            'radicalbit_ai_gateway.guardrails.judges.judge_engine.init_chat_model',
            return_value=llm,
        ),
        patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.emit_event'),
        patch('radicalbit_ai_gateway.invocation.model_invoker.emit_event'),
        patch('radicalbit_ai_gateway.limiting.token_limiter.emit_event'),
    ):
        yield calls


def _gateway_with_input_limit() -> GatewayRoute:
    config = _config('input', token_limiting=INPUT_LIMIT)
    route_cfg = config.routes[ROUTE]
    return _gateway('input', route_cfg.get_token_limiter(PROJECT_UUID), None)


@pook.activate
@pytest.mark.asyncio
async def test_chat_judge_spend_is_charged_to_the_next_request(judge_calls):
    pook.post(
        url='https://api.openai.com/v1/chat/completions',
        reply=200,
        response_json=to_mock_openai_chat_completion('Paris').model_dump_json(),
    )
    gateway = _gateway_with_input_limit()
    request = {
        **_caller(),
        'messages': [HumanMessage(content='Capital of France?')],
        'tools': [],
        'tool_choice': None,
    }

    await gateway.invoke(**request)
    with pytest.raises(InputTokenLimitExceeded):
        await gateway.invoke(**request)

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
    gateway = _gateway_with_input_limit()

    await gateway.invoke_embeddings(**_caller(), input_texts=['hello world'])
    with pytest.raises(InputTokenLimitExceeded):
        await gateway.invoke_embeddings(**_caller(), input_texts=['hello world'])

    assert len(judge_calls) == 1
