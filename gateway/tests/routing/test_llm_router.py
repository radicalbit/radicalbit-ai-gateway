import asyncio
from unittest.mock import AsyncMock, MagicMock

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
import pytest

from tests.common.mocked_gateway_config_openai import get_gateway_routing_llm

from radicalbit_ai_gateway.routing.llm_router import (
    LLMRouter,
    build_response_schema,
    build_system_prompt,
)


def _raw_message(input_tokens=120, output_tokens=15) -> AIMessage:
    return AIMessage(
        content='',
        usage_metadata={
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'total_tokens': input_tokens + output_tokens,
        },
    )


def _structured_model(scores=None, side_effect=None) -> AsyncMock:
    structured = AsyncMock()
    if side_effect is not None:
        structured.ainvoke = AsyncMock(side_effect=side_effect)
    else:
        structured.ainvoke = AsyncMock(
            return_value={
                'raw': _raw_message(),
                'parsed': scores,
                'parsing_error': None,
            }
        )
    return structured


def _build_router(structured) -> LLMRouter:
    config = get_gateway_routing_llm()
    routing_config = config.routing_by_name['llm_routing']
    route = config.routes['smart_route']
    models_by_id = {mid: config.chat_models_by_id[mid] for mid in route.chat_models}
    chat_model = MagicMock()
    chat_model.with_structured_output = MagicMock(return_value=structured)
    return LLMRouter(
        config=routing_config,
        models_by_id=models_by_id,
        router_model=config.chat_models_by_id['router_model'],
        chat_model=chat_model,
    )


class TestLLMRouter:
    async def test_selects_highest_score(self):
        router = _build_router(
            _structured_model({'code_model': 0.9, 'general_model': 0.2})
        )
        result = await router.select_model([HumanMessage(content='fix this bug')])
        assert result.model_id == 'code_model'

    async def test_selects_other_highest_score(self):
        router = _build_router(
            _structured_model({'code_model': 0.1, 'general_model': 0.8})
        )
        result = await router.select_model([HumanMessage(content='tell me a joke')])
        assert result.model_id == 'general_model'

    async def test_below_threshold_returns_default(self):
        router = _build_router(
            _structured_model({'code_model': 0.3, 'general_model': 0.2})
        )
        result = await router.select_model([HumanMessage(content='cook a pie')])
        assert result.model_id == 'default_model'

    async def test_score_equal_to_threshold_selects_model(self):
        router = _build_router(
            _structured_model({'code_model': 0.5, 'general_model': 0.2})
        )
        result = await router.select_model([HumanMessage(content='fix this bug')])
        assert result.model_id == 'code_model'

    async def test_unparsed_response_returns_default(self):
        router = _build_router(_structured_model(None))
        result = await router.select_model([HumanMessage(content='fix this bug')])
        assert result.model_id == 'default_model'

    async def test_router_error_returns_default(self):
        router = _build_router(_structured_model(side_effect=RuntimeError('boom')))
        result = await router.select_model([HumanMessage(content='fix this bug')])
        assert result.model_id == 'default_model'

    async def test_router_timeout_returns_default(self):
        async def _slow(*_args, **_kwargs):
            await asyncio.sleep(1)

        router = _build_router(_structured_model(side_effect=_slow))
        router._config = router._config.model_copy(update={'timeout': 0.01})
        result = await router.select_model([HumanMessage(content='fix this bug')])
        assert result.model_id == 'default_model'

    async def test_no_human_message_returns_default(self):
        structured = _structured_model({'code_model': 0.9, 'general_model': 0.1})
        router = _build_router(structured)
        result = await router.select_model([SystemMessage(content='you are a bot')])
        assert result.model_id == 'default_model'
        structured.ainvoke.assert_not_called()

    async def test_sends_last_human_message(self):
        structured = _structured_model({'code_model': 0.9, 'general_model': 0.1})
        router = _build_router(structured)
        await router.select_model(
            [
                HumanMessage(content='tell me a joke'),
                HumanMessage(content='fix this bug'),
            ]
        )
        sent = structured.ainvoke.await_args.args[0]
        assert isinstance(sent[0], SystemMessage)
        assert sent[1].content == 'fix this bug'

    async def test_reports_router_usage(self):
        router = _build_router(
            _structured_model({'code_model': 0.9, 'general_model': 0.1})
        )
        on_usage = AsyncMock()
        await router.select_model(
            [HumanMessage(content='fix this bug')], on_usage=on_usage
        )
        on_usage.assert_awaited_once()
        usage = on_usage.await_args.args[0]
        assert usage.model.model_id == 'router_model'
        assert usage.model_type == 'chat-model'
        assert usage.input_tokens == 120
        assert usage.output_tokens == 15

    async def test_reports_usage_even_below_threshold(self):
        router = _build_router(
            _structured_model({'code_model': 0.1, 'general_model': 0.1})
        )
        on_usage = AsyncMock()
        result = await router.select_model(
            [HumanMessage(content='cook a pie')], on_usage=on_usage
        )
        assert result.model_id == 'default_model'
        on_usage.assert_awaited_once()

    async def test_no_usage_when_router_call_fails(self):
        router = _build_router(_structured_model(side_effect=RuntimeError('boom')))
        on_usage = AsyncMock()
        await router.select_model(
            [HumanMessage(content='fix this bug')], on_usage=on_usage
        )
        on_usage.assert_not_awaited()

    async def test_model_without_structured_output_returns_default(self):
        config = get_gateway_routing_llm()
        chat_model = MagicMock()
        chat_model.with_structured_output = MagicMock(side_effect=NotImplementedError)
        router = LLMRouter(
            config=config.routing_by_name['llm_routing'],
            models_by_id=config.chat_models_by_id,
            router_model=config.chat_models_by_id['router_model'],
            chat_model=chat_model,
        )
        result = await router.select_model([HumanMessage(content='fix this bug')])
        assert result.model_id == 'default_model'


class TestPromptAndSchema:
    @pytest.fixture
    def routing_config(self):
        return get_gateway_routing_llm().routing_by_name['llm_routing']

    def test_system_prompt_lists_every_model_with_its_conditions(self, routing_config):
        prompt = build_system_prompt(routing_config)
        assert '- code_model: writing, debugging or reviewing code' in prompt
        assert '- general_model: general knowledge questions; small talk' in prompt
        assert 'keys are exactly: code_model, general_model' in prompt

    def test_schema_requires_one_score_per_model(self, routing_config):
        schema = build_response_schema(routing_config)
        assert schema['required'] == ['code_model', 'general_model']
        assert schema['properties'] == {
            'code_model': {'type': 'number'},
            'general_model': {'type': 'number'},
        }
        assert schema['additionalProperties'] is False
