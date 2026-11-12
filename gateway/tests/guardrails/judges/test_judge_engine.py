from unittest.mock import AsyncMock, MagicMock, Mock, call, patch

import pytest

from radicalbit_ai_gateway.guardrails.judges.decision_judge_engine import (
    DecisionJudgeEngine,
)
from radicalbit_ai_gateway.guardrails.judges.judge_engine import JudgeEngine
from radicalbit_ai_gateway.llm.chat_model import ChatModel
from radicalbit_ai_gateway.llm.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from radicalbit_ai_gateway.llm.prompts import PromptTemplate
from radicalbit_ai_gateway.models.guardrails import (
    DecisionJudgeParameter,
    GuardrailWhereType,
    JudgeParameter,
)
from radicalbit_ai_gateway.models.judge_result import JudgeResult
from radicalbit_ai_gateway.models.judge_runtime_config import JudgeRuntimeConfig
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.exceptions import (
    JudgeInternalError,
    JudgeOutputTruncatedError,
    JudgeParsingError,
)
from radicalbit_ai_gateway.utils.judge import (
    extract_content_for_judge,
    extract_media_blocks_for_judge,
)


def _build_structured_response(
    raw_response: AIMessage,
    parsed: JudgeResult | None = None,
    parsing_error: Exception | None = None,
) -> dict:
    """Build the dict returned by with_structured_output(include_raw=True)."""
    return {
        'raw': raw_response,
        'parsed': parsed,
        'parsing_error': parsing_error,
    }


@pytest.fixture(autouse=True)
def mock_all_external_llm_calls():
    """Prevent real network/API calls by mocking model initialization globally.
    Ensures tests run fully offline.
    """
    mock_base_model = Mock(spec=ChatModel)
    # with_structured_output returns a runnable; we just return the mock itself
    mock_base_model.with_structured_output.return_value = mock_base_model
    with (
        patch(
            'radicalbit_ai_gateway.guardrails.judges.judge_engine.build_chat_model',
            return_value=mock_base_model,
        ),
    ):
        yield


JUDGE_PROMPT = 'You are a business context judge.'
WITH_REASONING = "You may include a short reasoning in the 'reasoning' field."
NO_REASONING = (
    "Do NOT include any reasoning. The 'reasoning' field MUST be null or omitted."
)
IMAGE_BLOCK = {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,abc'}}
FILE_BLOCK = {
    'type': 'file',
    'file': {'filename': 'doc.pdf', 'file_data': 'data:application/pdf;base64,abc'},
}
USAGE = {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15}
MODEL_CFG = Mock(model_id='gpt-4o', model='openai:gpt-4o', credentials=None)


def _template(base: str, note: str, label: str = 'Text Under Review') -> str:
    return f'{base}\n{note}\n---\n{label}:\n{{content}}\n'


def _answer(
    parsed: JudgeResult | None,
    content: str = '{"triggered": true}',
    parsing_error: Exception | None = None,
    **metadata,
) -> AsyncMock:
    """Build a structured judge model whose ainvoke answers once as given."""
    chain = AsyncMock()
    chain.ainvoke.return_value = _build_structured_response(
        raw_response=AIMessage(
            content=content, usage_metadata=metadata.pop('usage', USAGE), **metadata
        ),
        parsed=parsed,
        parsing_error=parsing_error,
    )
    return chain


def _failing(message: str) -> AsyncMock:
    chain = AsyncMock()
    chain.ainvoke.side_effect = Exception(message)
    return chain


# -----------------------------------------------------
# extract_content_for_judge / extract_media_blocks_for_judge
# -----------------------------------------------------
_IN = {'where': GuardrailWhereType.INPUT}
_OUT = {'where': GuardrailWhereType.OUTPUT}


@pytest.mark.parametrize(
    ('messages', 'kwargs', 'expected'),
    [
        # No where -> INPUT: every message is joined.
        pytest.param(
            [HumanMessage(content='Hello'), HumanMessage(content='How are you?')],
            {},
            'Hello\nHow are you?',
            id='input-default',
        ),
        # INPUT includes every message type: role filtering is done upstream.
        pytest.param(
            [
                HumanMessage(content='Hello'),
                AIMessage(content='Assistant output'),
                HumanMessage(content='How are you?'),
            ],
            {**_IN, 'message_roles': ['USER', 'ASSISTANT']},
            'Hello\nAssistant output\nHow are you?',
            id='input-ai',
        ),
        pytest.param(
            [
                HumanMessage(content='User request'),
                ToolMessage(content='Tool result with Zeiss data', tool_call_id='c1'),
            ],
            {**_IN, 'message_roles': ['USER', 'TOOL']},
            'User request\nTool result with Zeiss data',
            id='input-tool',
        ),
        pytest.param(
            [
                SystemMessage(content='System context'),
                HumanMessage(content='User request'),
            ],
            {**_IN, 'message_roles': ['USER', 'SYSTEM']},
            'System context\nUser request',
            id='input-system',
        ),
        pytest.param(
            [
                HumanMessage(content='User asks something'),
                AIMessage(content='This is the model output'),
            ],
            _OUT,
            'This is the model output',
            id='output-picks-ai',
        ),
        pytest.param(
            [HumanMessage(content='Only user text')], _OUT, '', id='output-without-ai'
        ),
        pytest.param(
            [
                HumanMessage(
                    content=[
                        {'type': 'text', 'text': 'Hello, this is a test message'},
                        {
                            'type': 'image',
                            'source_type': 'base64',
                            'data': 'base64data',
                        },
                    ]
                )
            ],
            _IN,
            'Hello, this is a test message',
            id='structured-text-and-image',
        ),
        pytest.param(
            [
                HumanMessage(
                    content=[
                        {'type': 'text', 'text': 'First part'},
                        {'type': 'text', 'text': 'Second part'},
                    ]
                )
            ],
            _IN,
            'First part Second part',
            id='structured-text-parts',
        ),
    ],
)
def test_extract_content_for_judge(messages, kwargs, expected):
    assert extract_content_for_judge(messages, **kwargs) == expected


@pytest.mark.parametrize(
    ('messages', 'kwargs', 'expected'),
    [
        pytest.param(
            [
                HumanMessage(
                    content=[{'type': 'text', 'text': 'Describe.'}, IMAGE_BLOCK]
                )
            ],
            _IN,
            [IMAGE_BLOCK],
            id='input-image-url',
        ),
        pytest.param(
            [
                HumanMessage(
                    content=[{'type': 'text', 'text': 'Summarize.'}, FILE_BLOCK]
                )
            ],
            {},
            [FILE_BLOCK],
            id='input-file',
        ),
        pytest.param([HumanMessage(content='Just text')], {}, [], id='plain-text'),
        pytest.param(
            [HumanMessage(content=[{'type': 'text', 'text': 'Hello'}])],
            {},
            [],
            id='structured-text-only',
        ),
        # Role filtering is upstream: INPUT reads media from any message type.
        pytest.param(
            [
                HumanMessage(content='User text'),
                AIMessage(content=[{'type': 'text', 'text': 'AI text'}, IMAGE_BLOCK]),
            ],
            {**_IN, 'message_roles': ['USER', 'ASSISTANT']},
            [IMAGE_BLOCK],
            id='input-ai-message',
        ),
        pytest.param(
            [
                HumanMessage(content='User text'),
                AIMessage(
                    content=[{'type': 'text', 'text': 'AI response'}, IMAGE_BLOCK]
                ),
            ],
            _OUT,
            [IMAGE_BLOCK],
            id='output-last-ai',
        ),
        pytest.param(
            [AIMessage(content='Plain AI text')], _OUT, [], id='output-no-media'
        ),
    ],
)
def test_extract_media_blocks_for_judge(messages, kwargs, expected):
    assert extract_media_blocks_for_judge(messages, **kwargs) == expected


# -----------------------------------------------------
# Test Suite for JudgeEngine
# -----------------------------------------------------
class TestJudgeEngine:
    def setup_method(self):
        self.prompt_manager = Mock(spec=PromptManager)
        self.prompt_manager.get_judge_prompt.return_value = JUDGE_PROMPT
        self.cost_service: CostService = MagicMock(spec_set=CostService)
        self.engine = JudgeEngine(prompt_manager=self.prompt_manager)

    async def _execute(self, *chains: AsyncMock, messages=None, **kwargs):
        """Run execute_judge with one chain per model call: primary, then fallback."""
        self.engine._get_or_create_model = MagicMock(side_effect=list(chains))
        kwargs.setdefault(
            'judge_parameter',
            JudgeParameter(model_id='gpt-4o', prompt_ref='business_context_check.md'),
        )
        with patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.emit_event'):
            return await self.engine.execute_judge(
                messages=messages or [HumanMessage(content='Test content')],
                primary_model=MODEL_CFG,
                cost_service=self.cost_service,
                **kwargs,
            )

    # -----------------------------------------------------
    # Prompt template
    # -----------------------------------------------------
    @pytest.mark.parametrize(
        ('config', 'expected', 'prompt_ref'),
        [
            pytest.param(
                {'prompt_ref': 'business_context_check.md', 'include_reasoning': False},
                _template(JUDGE_PROMPT, NO_REASONING),
                'business_context_check.md',
                id='prompt-ref-without-reasoning',
            ),
            pytest.param(
                {'prompt_ref': 'business_context_check.md', 'include_reasoning': True},
                _template(JUDGE_PROMPT, WITH_REASONING),
                'business_context_check.md',
                id='prompt-ref-with-reasoning',
            ),
            pytest.param(
                {'prompt': 'Flag any request for medical advice.'},
                _template('Flag any request for medical advice.', WITH_REASONING),
                None,
                id='inline-prompt',
            ),
        ],
    )
    def test_build_prompt_template(self, config, expected, prompt_ref):
        template = self.engine._build_prompt_template(
            JudgeRuntimeConfig(model_id='gpt-4o', max_tokens=100, **config)
        )

        assert isinstance(template, PromptTemplate)
        assert template.template == expected
        assert self.prompt_manager.get_judge_prompt.call_args_list == (
            [call(prompt_ref)] if prompt_ref else []
        )

    # -----------------------------------------------------
    # Model caching (with_structured_output applied)
    # -----------------------------------------------------
    def test_get_or_create_model_uses_cache(self):
        mock_model = Mock(spec=ChatModel)
        model_cfg = Mock(
            model_id='gpt-4o-mini', model='openai:gpt-4o-mini', credentials=None
        )
        config = JudgeRuntimeConfig(
            model_id='gpt-4o-mini', temperature=0.1, max_tokens=50, prompt_ref='p.md'
        )
        self.engine._model_cache.clear()
        self.engine._model_cache['gpt-4o-mini:0.1:50'] = mock_model

        assert self.engine._get_or_create_model(config, model_cfg) is mock_model

    @patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.build_chat_model')
    def test_get_or_create_model_applies_structured_output(self, mock_build_chat_model):
        """Verify that with_structured_output(JudgeResult, include_raw=True) is applied."""
        mock_base = MagicMock()
        mock_structured = MagicMock()
        mock_base.with_structured_output.return_value = mock_structured
        mock_build_chat_model.return_value = mock_base
        config = JudgeRuntimeConfig(
            model_id='gpt-4o', temperature=0.5, max_tokens=100, prompt_ref='test.md'
        )

        self.engine._model_cache.clear()
        result = self.engine._get_or_create_model(config, MODEL_CFG)

        mock_base.with_structured_output.assert_called_once_with(
            schema=JudgeResult, include_raw=True
        )
        assert result is mock_structured

    # -----------------------------------------------------
    # Execution flows
    # -----------------------------------------------------
    @pytest.mark.parametrize(
        ('parameter', 'messages', 'kwargs', 'note', 'text'),
        [
            pytest.param(
                {},
                [HumanMessage(content="What's your favorite pizza?")],
                {},
                WITH_REASONING,
                "What's your favorite pizza?",
                id='input',
            ),
            pytest.param(
                {'include_reasoning': False},
                [HumanMessage(content='You are stupid')],
                {},
                NO_REASONING,
                'You are stupid',
                id='without-reasoning',
            ),
            pytest.param(
                {},
                [
                    HumanMessage(content='Make me a recipe'),
                    AIMessage(content='Carbonara is an Italian recipe...'),
                ],
                {'where': GuardrailWhereType.OUTPUT},
                WITH_REASONING,
                'Carbonara is an Italian recipe...',
                id='output-reads-ai-content',
            ),
            # include_media with no media blocks still sends the text prompt.
            pytest.param(
                {'include_media': True},
                [HumanMessage(content='Plain text, no images')],
                {},
                WITH_REASONING,
                'Plain text, no images',
                id='include-media-without-blocks',
            ),
        ],
    )
    @pytest.mark.asyncio
    async def test_execute_judge_sends_the_text_prompt(
        self, parameter, messages, kwargs, note, text
    ):
        expected = JudgeResult(
            triggered=True, reasoning='Detected', violation_type='business_context'
        )
        chain = _answer(expected)

        result = await self._execute(
            chain,
            messages=messages,
            judge_parameter=JudgeParameter(
                model_id='gpt-4o', prompt_ref='business_context_check.md', **parameter
            ),
            **kwargs,
        )

        assert result == expected
        chain.ainvoke.assert_awaited_once_with(
            [HumanMessage(content=_template(JUDGE_PROMPT, note).format(content=text))]
        )

    @pytest.mark.asyncio
    async def test_primary_fails_fallback_succeeds(self):
        fallback_result = JudgeResult(
            triggered=False, reasoning='OK', violation_type=None
        )

        result = await self._execute(
            _failing('Primary crashed'),
            _answer(fallback_result, content='{"triggered": false}'),
            fallback_model=MODEL_CFG,
        )

        assert result == fallback_result

    @pytest.mark.parametrize(
        ('chains', 'fallback', 'message'),
        [
            pytest.param(
                [_failing('Primary fail'), _failing('Fallback fail')],
                MODEL_CFG,
                'Both primary and fallback',
                id='both-fail',
            ),
            pytest.param(
                [_failing('Network error')],
                None,
                'Primary judge model failed',
                id='primary-fails-without-fallback',
            ),
        ],
    )
    @pytest.mark.asyncio
    async def test_failure_raises_internal_error(self, chains, fallback, message):
        with pytest.raises(JudgeInternalError, match=message):
            await self._execute(*chains, fallback_model=fallback)

    @pytest.mark.asyncio
    async def test_raises_truncated_error_on_finish_reason_length(self):
        truncated = _answer(
            None,
            content='{"triggered": true, "re',
            parsing_error=ValueError('Truncated JSON'),
            response_metadata={'finish_reason': 'length'},
            usage={'input_tokens': 10, 'output_tokens': 200, 'total_tokens': 210},
        )

        with pytest.raises(JudgeOutputTruncatedError) as exc_info:
            await self._execute(
                truncated,
                judge_parameter=JudgeParameter(
                    model_id='gpt-4o',
                    prompt_ref='business_context_check.md',
                    max_tokens=200,
                ),
            )

        assert (exc_info.value.finish_reason, exc_info.value.model_id) == (
            'length',
            'gpt-4o',
        )

    @pytest.mark.asyncio
    async def test_raises_parsing_error_on_empty_parsed(self):
        empty = _answer(
            None,
            content='',
            response_metadata={'finish_reason': 'stop'},
            usage={'input_tokens': 10, 'output_tokens': 0, 'total_tokens': 10},
        )

        with pytest.raises(JudgeParsingError) as exc_info:
            await self._execute(empty)

        assert 'Empty parsed response' in str(exc_info.value.original_error)

    @pytest.mark.asyncio
    async def test_raises_parsing_error_on_invalid_json(self):
        invalid = _answer(
            None,
            content='This is not valid JSON at all',
            parsing_error=ValueError('Invalid JSON'),
            response_metadata={'finish_reason': 'stop'},
        )

        with pytest.raises(JudgeParsingError) as exc_info:
            await self._execute(invalid)

        assert 'This is not valid JSON at all' in exc_info.value.raw_content

    # -----------------------------------------------------
    # Multimodal execution path
    # -----------------------------------------------------
    @pytest.mark.asyncio
    async def test_execute_judge_multimodal_invokes_with_human_message(self):
        """With include_media and image blocks, the model gets text plus the image."""
        expected = JudgeResult(triggered=False, reasoning=None, violation_type=None)
        structured_model = _answer(expected, content='{"triggered": false}')
        self.engine._model_cache['gpt-4o-mini:0.7:100'] = structured_model
        judge_parameter = JudgeParameter(
            model_id='gpt-4o-mini',
            prompt_ref='toxicity_check.md',
            temperature=0.7,
            max_tokens=100,
            include_media=True,
        )
        model_cfg = Mock(
            model_id='gpt-4o-mini', model='openai:gpt-4o-mini', credentials=None
        )

        with patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.emit_event'):
            result = await self.engine.execute_judge(
                messages=[
                    HumanMessage(
                        content=[
                            {'type': 'text', 'text': 'Analyze this for toxicity.'},
                            IMAGE_BLOCK,
                        ]
                    )
                ],
                judge_parameter=judge_parameter,
                primary_model=model_cfg,
                cost_service=self.cost_service,
            )

        assert result == expected
        text = _template(JUDGE_PROMPT, WITH_REASONING, 'Content Under Review').format(
            content='Analyze this for toxicity.'
        )
        structured_model.ainvoke.assert_awaited_once_with(
            [HumanMessage(content=[{'type': 'text', 'text': text}, IMAGE_BLOCK])]
        )


# -----------------------------------------------------
# Usage reported to the limiters
# -----------------------------------------------------
def _judge_answer(input_tokens: int | None, output_tokens: int | None) -> dict:
    usage = (
        {
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'total_tokens': input_tokens + output_tokens,
        }
        if input_tokens is not None
        else None
    )
    return _build_structured_response(
        raw_response=AIMessage(content='{"triggered": false}', usage_metadata=usage),
        parsed=JudgeResult(triggered=False, reasoning='OK', violation_type=None),
    )


def _judge_model(**ainvoke_behaviour) -> AsyncMock:
    """Build a structured judge model whose ainvoke returns or raises as told."""
    model = AsyncMock()
    for name, value in ainvoke_behaviour.items():
        setattr(model.ainvoke, name, value)
    return model


class TestJudgeUsageCount:
    def setup_method(self):
        prompt_manager = Mock(spec=PromptManager)
        prompt_manager.get_judge_prompt.return_value = 'Judge this.'
        self.engine = JudgeEngine(prompt_manager=prompt_manager)
        self.primary = Mock(model_id='primary', model='openai:a', credentials=None)
        self.fallback = Mock(model_id='fallback', model='openai:b', credentials=None)
        self.count_usage = AsyncMock()

    async def _run(self, *models: AsyncMock, fallback: bool = False):
        # One model per call, in order: primary first, then the fallback.
        self.engine._get_or_create_model = MagicMock(side_effect=list(models))
        with patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.emit_event'):
            return await self.engine.execute_judge(
                messages=[HumanMessage(content='Hello')],
                judge_parameter=JudgeParameter(model_id='primary', prompt='Judge'),
                primary_model=self.primary,
                fallback_model=self.fallback if fallback else None,
                cost_service=MagicMock(spec_set=CostService),
                count_usage=self.count_usage,
            )

    @pytest.mark.asyncio
    async def test_fallback_answer_counts_its_tokens_on_the_fallback_model(self):
        await self._run(
            _judge_model(side_effect=Exception('Primary crashed')),
            _judge_model(return_value=_judge_answer(7, 3)),
            fallback=True,
        )

        self.count_usage.assert_awaited_once_with(self.fallback, 7, 3)

    @pytest.mark.asyncio
    async def test_answer_without_usage_counts_nothing(self):
        await self._run(_judge_model(return_value=_judge_answer(None, None)))

        self.count_usage.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_limiter_error_is_raised_and_does_not_call_the_fallback(self):
        self.count_usage.side_effect = ConnectionError('limiter storage down')
        fallback_model = _judge_model(return_value=_judge_answer(7, 3))

        with pytest.raises(ConnectionError, match='limiter storage down'):
            await self._run(
                _judge_model(return_value=_judge_answer(10, 5)),
                fallback_model,
                fallback=True,
            )

        fallback_model.ainvoke.assert_not_awaited()
        self.count_usage.assert_awaited_once_with(self.primary, 10, 5)

    @pytest.mark.asyncio
    async def test_unparsable_primary_and_fallback_answer_are_both_counted(self):
        unparsable = _judge_answer(10, 5)
        unparsable['parsed'] = None

        await self._run(
            _judge_model(return_value=unparsable),
            _judge_model(return_value=_judge_answer(7, 3)),
            fallback=True,
        )

        assert self.count_usage.await_args_list == [
            call(self.primary, 10, 5),
            call(self.fallback, 7, 3),
        ]


async def test_a_decision_judge_on_an_undefined_model_fails_without_a_recorded_call():
    jev = Model(model_id='jev', model='typesafe/jev-latest')
    engine = DecisionJudgeEngine(
        decision_models=[jev],
        cost_service=CostService(decision_models_by_id={'jev': jev}),
    )
    engine._invoker.recorder = MagicMock()

    with pytest.raises(JudgeInternalError):
        await engine.ask(
            [HumanMessage(content='hello')],
            DecisionJudgeParameter(model_id='nowhere', instructions='Is it rude?'),
        )
    engine._invoker.recorder.failure.assert_not_called()
