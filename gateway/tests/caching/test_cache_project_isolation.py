"""Two projects sharing one Redis must never read each other's cached responses.

Route names are unique only within a project, and an API key can be moved
between groups bound to different projects, so both the key format and the
route wiring have to carry the project.
"""

from unittest.mock import MagicMock, patch

from langchain_core.messages import HumanMessage
import pytest

from tests.common.db_mock import GROUP_UUID, SAMPLE_PROJECT_UUID, TEST_PROJECT_UUID
from tests.common.mocked_build_openai_chat_completion import (
    to_mock_openai_chat_completion,
)
from tests.common.resolve_route_models import resolve_route_models

from radicalbit_ai_gateway.ai_gateway import GatewayRoute
from radicalbit_ai_gateway.caching.gateway_cache import GatewayCache
from radicalbit_ai_gateway.caching.redis_cache import RedisCache
from radicalbit_ai_gateway.guardrails.guardrail_engine import GuardrailEngine
from radicalbit_ai_gateway.guardrails.judges.judge_engine import JudgeEngine
from radicalbit_ai_gateway.guardrails.presidio import PresidioEngine
from radicalbit_ai_gateway.models.caching import CacheConfig, Caching
from radicalbit_ai_gateway.models.credentials import Credentials
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.services.cost_service import CostService

API_KEY_UUID = 'f0f2f4f6-1111-4222-8333-444455556666'
ROUTE_NAME = 'default'


def _build_route(gateway_cache: GatewayCache, project_uuid: str) -> GatewayRoute:
    cost_service: CostService = MagicMock(spec_set=CostService)
    prompt_manager: PromptManager = MagicMock(spec_set=PromptManager)
    chat_registry = [
        Model(
            model_id='openai-o4-mini',
            model='openai/gpt-4o-mini',
            credentials=Credentials(api_key='sk-test'),
        )
    ]
    route_config = GatewayRouteConfig(
        route_name=ROUTE_NAME,
        chat_models=['openai-o4-mini'],
        caching=Caching(enabled=True, type='exact', ttl=None),
    )
    gateway_config = GatewayConfig(
        chat_models=chat_registry,
        routes={ROUTE_NAME: route_config},
        guardrails=[],
        cache=CacheConfig(redis_host='localhost', redis_port=6379),
    )
    resolved_route_cfg, chat_models, _ = resolve_route_models(
        gateway_config, ROUTE_NAME
    )
    guardrail_engine = GuardrailEngine(
        presidio_engine=PresidioEngine(),
        judge_engine=JudgeEngine(prompt_manager=prompt_manager),
        cost_service=cost_service,
    )
    return GatewayRoute(
        gateway_route_config=resolved_route_cfg,
        chat_models=chat_models,
        embedding_models=None,
        guardrail_engine=guardrail_engine,
        gateway_cache=gateway_cache,
        cost_service=cost_service,
        project_uuid=project_uuid,
    )


async def _invoke(route: GatewayRoute, request_uuid: str):
    return await route.invoke(
        request_uuid=request_uuid,
        api_key_uuid=API_KEY_UUID,
        api_key_name='rb-key',
        group_uuid=str(GROUP_UUID),
        group_name='test-group',
        messages=[HumanMessage(content='What is the capital of France?')],
        route_name=ROUTE_NAME,
        tools=[],
        tool_choice='auto',
    )


@patch('radicalbit_ai_gateway.invocation.chat_model_invoker.ChatModelInvoker.complete')
@patch('radicalbit_ai_gateway.ai_gateway.emit_event', autospec=True)
@patch('radicalbit_ai_gateway.invocation.model_invoker.emit_event', autospec=True)
@pytest.mark.asyncio
async def test_exact_cache_does_not_leak_across_projects(
    mock_model_invoker_emit_event,
    mock_emit_event,
    mock_complete,
    fake_redis_client,
    test_data_dir_fixture,
):
    """Same route name, same API key, same Redis, two projects: no cross-read.

    This is both leak paths from the report at once: a group bound to routes in
    two projects, and a key reassigned from one project's group to another's.
    """
    mock_complete.return_value = to_mock_openai_chat_completion(content='Paris')
    # One Redis, as when both projects point their cache config at the same host.
    shared_cache = GatewayCache(RedisCache(fake_redis_client))
    route_a = _build_route(shared_cache, str(TEST_PROJECT_UUID))
    route_b = _build_route(shared_cache, str(SAMPLE_PROJECT_UUID))

    response_a = await _invoke(route_a, 'req-1')
    assert response_a.headers == {}
    assert mock_complete.call_count == 1

    # Project B must not be served project A's completion.
    response_b = await _invoke(route_b, 'req-2')
    assert response_b.headers == {}
    assert mock_complete.call_count == 2

    # Project A still reads its own entry.
    response_a_again = await _invoke(route_a, 'req-3')
    assert response_a_again.headers == {'X-RB-AIGATEWAY-CACHE-HIT': 'true'}
    assert mock_complete.call_count == 2


def test_cache_key_is_scoped_by_project(fake_redis_client):
    gateway_cache = GatewayCache(RedisCache(fake_redis_client))
    keys = {
        gateway_cache.generate_cache_key(
            project_uuid=project_uuid,
            route_name=ROUTE_NAME,
            key_uuid=API_KEY_UUID,
            messages=[HumanMessage(content='Hello')],
            tools=[],
            tool_choice='auto',
        )
        for project_uuid in (str(TEST_PROJECT_UUID), str(SAMPLE_PROJECT_UUID))
    }
    assert len(keys) == 2


def test_embedding_cache_key_is_scoped_by_project(fake_redis_client):
    gateway_cache = GatewayCache(RedisCache(fake_redis_client))
    keys = {
        gateway_cache.generate_embedding_cache_key(
            project_uuid=project_uuid,
            route_name=ROUTE_NAME,
            key_uuid=API_KEY_UUID,
            input_texts=['hello world'],
        )
        for project_uuid in (str(TEST_PROJECT_UUID), str(SAMPLE_PROJECT_UUID))
    }
    assert len(keys) == 2
