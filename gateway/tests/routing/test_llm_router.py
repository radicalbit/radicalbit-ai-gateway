import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.common.decision_routing import ROUTER_SPAN
from tests.common.mocked_gateway_config_openai import get_gateway_routing_llm

from radicalbit_ai_gateway.llm.messages import AIMessage, HumanMessage, SystemMessage
from radicalbit_ai_gateway.routing.llm_router import (
    LLMRouter,
    RouterModel,
    build_response_schema,
    build_system_prompt,
)

RECORD_ROUTING_SPEND = 'radicalbit_ai_gateway.routing.llm_router.record_routing_spend'

# option_1 is code_model, option_2 general_model, in output_mapping order.
CODE = 'option_1'
GENERAL = 'option_2'


def _raw_message(input_tokens=120, output_tokens=15) -> AIMessage:
    return AIMessage(
        content='',
        usage_metadata={
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'total_tokens': input_tokens + output_tokens,
        },
    )


def _routing_config(**updates):
    routing_config = get_gateway_routing_llm().routing_by_name['llm_routing']
    return routing_config.model_copy(update=updates)


def _parsed(scores: dict | None):
    if scores is None:
        return None
    return build_response_schema(_routing_config()).model_validate(scores)


def _structured_model(scores=None, side_effect=None) -> AsyncMock:
    structured = AsyncMock()
    if side_effect is not None:
        structured.ainvoke = AsyncMock(side_effect=side_effect)
    else:
        structured.ainvoke = AsyncMock(
            return_value={
                'raw': _raw_message(),
                'parsed': _parsed(scores),
                'parsing_error': None,
            }
        )
    return structured


def _chat_model(structured) -> MagicMock:
    chat_model = MagicMock()
    chat_model.with_structured_output = MagicMock(return_value=structured)
    return chat_model


def _build_router(structured, fallback=None, **config_updates) -> LLMRouter:
    config = get_gateway_routing_llm()
    route = config.routes['smart_route']
    models_by_id = {mid: config.chat_models_by_id[mid] for mid in route.chat_models}
    router_models = {
        'router_model': RouterModel(
            config.chat_models_by_id['router_model'], _chat_model(structured)
        )
    }
    if fallback is not None:
        config_updates.setdefault('fallback_model_id', 'router_backup')
        router_models['router_backup'] = RouterModel(
            config.chat_models_by_id['router_backup'], _chat_model(fallback)
        )
    return LLMRouter(
        config=_routing_config(**config_updates),
        models_by_id=models_by_id,
        router_models=router_models,
    )


@pytest.fixture
def span():
    span = MagicMock()
    span.is_recording.return_value = True
    with patch(ROUTER_SPAN, return_value=span):
        yield span


def _attributes(span) -> dict:
    return {c.args[0]: c.args[1] for c in span.set_attribute.call_args_list}


class TestLLMRouter:
    async def test_selects_highest_score(self):
        router = _build_router(_structured_model({CODE: 0.9, GENERAL: 0.2}))
        result = await router.select_model([HumanMessage(content='fix this bug')])
        assert result.model_id == 'code_model'

    async def test_selects_other_highest_score(self):
        router = _build_router(_structured_model({CODE: 0.1, GENERAL: 0.8}))
        result = await router.select_model([HumanMessage(content='tell me a joke')])
        assert result.model_id == 'general_model'

    async def test_first_option_wins_a_tie(self):
        router = _build_router(_structured_model({CODE: 0.7, GENERAL: 0.7}))
        result = await router.select_model([HumanMessage(content='fix this bug')])
        assert result.model_id == 'code_model'

    async def test_below_threshold_returns_default(self, span):
        router = _build_router(_structured_model({CODE: 0.3, GENERAL: 0.2}))
        result = await router.select_model([HumanMessage(content='cook a pie')])
        assert result.model_id == 'default_model'
        attributes = _attributes(span)
        assert attributes['routing.llm.default_used'] is True
        assert attributes['routing.llm.default_reason'] == 'below_threshold'
        assert attributes['routing.llm.best_score'] == 0.3

    async def test_score_equal_to_threshold_selects_model(self):
        router = _build_router(_structured_model({CODE: 0.5, GENERAL: 0.2}))
        result = await router.select_model([HumanMessage(content='fix this bug')])
        assert result.model_id == 'code_model'

    async def test_unparsed_response_returns_default_without_fallback(self, span):
        fallback = _structured_model({CODE: 0.9, GENERAL: 0.1})
        router = _build_router(_structured_model(None), fallback=fallback)
        result = await router.select_model([HumanMessage(content='fix this bug')])
        assert result.model_id == 'default_model'
        assert _attributes(span)['routing.llm.default_reason'] == 'invalid_answer'
        fallback.ainvoke.assert_not_called()

    async def test_router_error_returns_default(self, span):
        router = _build_router(_structured_model(side_effect=RuntimeError('boom')))
        result = await router.select_model([HumanMessage(content='fix this bug')])
        assert result.model_id == 'default_model'
        assert _attributes(span)['routing.llm.default_reason'] == 'error'

    async def test_router_timeout_returns_default(self):
        async def _slow(*_args, **_kwargs):
            await asyncio.sleep(1)

        router = _build_router(_structured_model(side_effect=_slow), timeout=0.01)
        result = await router.select_model([HumanMessage(content='fix this bug')])
        assert result.model_id == 'default_model'

    async def test_router_error_goes_to_the_fallback(self, span):
        router = _build_router(
            _structured_model(side_effect=RuntimeError('boom')),
            fallback=_structured_model({CODE: 0.1, GENERAL: 0.8}),
        )
        result = await router.select_model([HumanMessage(content='tell me a joke')])
        assert result.model_id == 'general_model'
        attributes = _attributes(span)
        assert attributes['routing.llm.model_id'] == 'router_backup'
        assert attributes['routing.llm.fallback_used'] is True
        assert attributes['routing.llm.default_used'] is False

    async def test_failing_fallback_returns_default(self, span):
        router = _build_router(
            _structured_model(side_effect=RuntimeError('boom')),
            fallback=_structured_model(side_effect=RuntimeError('boom')),
        )
        result = await router.select_model([HumanMessage(content='fix this bug')])
        assert result.model_id == 'default_model'
        attributes = _attributes(span)
        assert attributes['routing.llm.fallback_used'] is True
        assert attributes['routing.llm.default_reason'] == 'error'

    async def test_no_human_message_returns_default(self, span):
        structured = _structured_model({CODE: 0.9, GENERAL: 0.1})
        router = _build_router(structured)
        result = await router.select_model([SystemMessage(content='you are a bot')])
        assert result.model_id == 'default_model'
        assert _attributes(span)['routing.llm.default_reason'] == 'no_text'
        structured.ainvoke.assert_not_called()

    async def test_sends_last_human_message(self):
        structured = _structured_model({CODE: 0.9, GENERAL: 0.1})
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

    async def test_history_all_sends_the_conversation(self):
        structured = _structured_model({CODE: 0.9, GENERAL: 0.1})
        router = _build_router(structured, history='all')
        await router.select_model(
            [
                SystemMessage(content='you are a bot'),
                HumanMessage(content='tell me a joke'),
                AIMessage(content='why did the chicken cross the road'),
                HumanMessage(content='fix this bug'),
            ]
        )
        sent = structured.ainvoke.await_args.args[0]
        assert sent[1].content == (
            'tell me a joke\nwhy did the chicken cross the road\nfix this bug'
        )

    async def test_the_span_records_options_scores_and_choice(self, span):
        router = _build_router(_structured_model({CODE: 0.9, GENERAL: 0.2}))
        await router.select_model([HumanMessage(content='fix this bug')])
        attributes = _attributes(span)
        assert json.loads(attributes['routing.llm.options']) == {
            CODE: {
                'model_id': 'code_model',
                'description': 'writing, debugging or reviewing code',
            },
            GENERAL: {
                'model_id': 'general_model',
                'description': 'general knowledge questions and small talk',
            },
        }
        assert attributes['routing.llm.state'] == 'fix this bug'
        assert json.loads(attributes['routing.llm.scores']) == {CODE: 0.9, GENERAL: 0.2}
        assert attributes['routing.llm.threshold'] == 0.5
        assert attributes['routing.llm.model_id'] == 'router_model'
        assert attributes['routing.llm.fallback_used'] is False
        assert attributes['routing.llm.chosen_model_id'] == 'code_model'
        assert attributes['routing.llm.default_used'] is False

    async def test_records_router_spend(self):
        router = _build_router(_structured_model({CODE: 0.9, GENERAL: 0.1}))
        with patch(RECORD_ROUTING_SPEND, new_callable=AsyncMock) as record:
            await router.select_model([HumanMessage(content='fix this bug')])
        record.assert_awaited_once()
        model, input_tokens, _latency_ms = record.await_args.args
        assert model.model_id == 'router_model'
        assert input_tokens == 120
        assert record.await_args.kwargs['model_type'] == 'chat-model'
        assert record.await_args.kwargs['output_tokens'] == 15

    async def test_records_fallback_spend_against_the_router_model(self):
        router = _build_router(
            _structured_model(side_effect=RuntimeError('boom')),
            fallback=_structured_model({CODE: 0.9, GENERAL: 0.1}),
        )
        with patch(RECORD_ROUTING_SPEND, new_callable=AsyncMock) as record:
            await router.select_model([HumanMessage(content='fix this bug')])
        record.assert_awaited_once()
        assert record.await_args.args[0].model_id == 'router_backup'
        assert record.await_args.kwargs['target_model_id'] == 'router_model'

    async def test_records_spend_even_below_threshold(self):
        router = _build_router(_structured_model({CODE: 0.1, GENERAL: 0.1}))
        with patch(RECORD_ROUTING_SPEND, new_callable=AsyncMock) as record:
            result = await router.select_model([HumanMessage(content='cook a pie')])
        assert result.model_id == 'default_model'
        record.assert_awaited_once()

    async def test_records_spend_for_an_unparsed_response(self):
        router = _build_router(_structured_model(None))
        with patch(RECORD_ROUTING_SPEND, new_callable=AsyncMock) as record:
            await router.select_model([HumanMessage(content='fix this bug')])
        record.assert_awaited_once()

    async def test_no_spend_without_token_usage(self):
        structured = _structured_model({CODE: 0.9, GENERAL: 0.1})
        structured.ainvoke.return_value['raw'] = AIMessage(content='')
        router = _build_router(structured)
        with patch(RECORD_ROUTING_SPEND, new_callable=AsyncMock) as record:
            result = await router.select_model([HumanMessage(content='fix this bug')])
        assert result.model_id == 'code_model'
        record.assert_not_awaited()

    async def test_a_failing_span_does_not_break_routing(self):
        router = _build_router(_structured_model({CODE: 0.9, GENERAL: 0.1}))
        with patch(ROUTER_SPAN, side_effect=RuntimeError('no tracer')):
            result = await router.select_model([HumanMessage(content='fix this bug')])
        assert result.model_id == 'code_model'

    async def test_no_spend_when_router_call_fails(self):
        router = _build_router(_structured_model(side_effect=RuntimeError('boom')))
        with patch(RECORD_ROUTING_SPEND, new_callable=AsyncMock) as record:
            await router.select_model([HumanMessage(content='fix this bug')])
        record.assert_not_awaited()

    async def test_model_without_structured_output_goes_to_the_fallback(self):
        config = get_gateway_routing_llm()
        unstructured = MagicMock()
        unstructured.with_structured_output = MagicMock(side_effect=NotImplementedError)
        fallback = _structured_model({CODE: 0.9, GENERAL: 0.1})
        router = LLMRouter(
            config=_routing_config(fallback_model_id='router_backup'),
            models_by_id=config.chat_models_by_id,
            router_models={
                'router_model': RouterModel(
                    config.chat_models_by_id['router_model'], unstructured
                ),
                'router_backup': RouterModel(
                    config.chat_models_by_id['router_backup'], _chat_model(fallback)
                ),
            },
        )
        result = await router.select_model([HumanMessage(content='fix this bug')])
        assert result.model_id == 'code_model'

    async def test_model_without_structured_output_returns_default(self):
        config = get_gateway_routing_llm()
        chat_model = MagicMock()
        chat_model.with_structured_output = MagicMock(side_effect=NotImplementedError)
        router = LLMRouter(
            config=_routing_config(),
            models_by_id=config.chat_models_by_id,
            router_models={
                'router_model': RouterModel(
                    config.chat_models_by_id['router_model'], chat_model
                )
            },
        )
        result = await router.select_model([HumanMessage(content='fix this bug')])
        assert result.model_id == 'default_model'


class TestPromptAndSchema:
    @pytest.fixture
    def routing_config(self):
        return _routing_config()

    def test_system_prompt_lists_every_option_with_its_description(
        self, routing_config
    ):
        prompt = build_system_prompt(routing_config)
        assert '- option_1: writing, debugging or reviewing code' in prompt
        assert '- option_2: general knowledge questions and small talk' in prompt
        # The reply's shape is the schema's job, not the prompt's.
        assert 'JSON' not in prompt

    def test_system_prompt_does_not_name_the_models(self, routing_config):
        prompt = build_system_prompt(routing_config)
        assert 'code_model' not in prompt
        assert 'general_model' not in prompt

    def test_schema_requires_one_score_per_option(self, routing_config):
        schema = build_response_schema(routing_config).model_json_schema()
        assert schema['required'] == [CODE, GENERAL]
        assert {name: prop['type'] for name, prop in schema['properties'].items()} == {
            CODE: 'number',
            GENERAL: 'number',
        }
        assert (
            schema['properties'][CODE]['description']
            == 'How pertinent the query is to option_1, from 0.0 to 1.0.'
        )
        assert schema['additionalProperties'] is False
        assert 'code_model' not in json.dumps(schema)
