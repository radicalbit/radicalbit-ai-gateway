from unittest.mock import AsyncMock, MagicMock, Mock, patch

from langchain_core.language_models import BaseLanguageModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.prompts import PromptTemplate
import pytest

from radicalbit_ai_gateway.guardrails.judges.judge_engine import JudgeEngine
from radicalbit_ai_gateway.models.guardrails import GuardrailWhereType, JudgeParameter
from radicalbit_ai_gateway.models.judge_result import JudgeResult
from radicalbit_ai_gateway.models.judge_runtime_config import JudgeRuntimeConfig
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
    mock_base_model = Mock(spec=BaseLanguageModel)
    # with_structured_output returns a runnable; we just return the mock itself
    mock_base_model.with_structured_output.return_value = mock_base_model
    with (
        patch(
            'radicalbit_ai_gateway.guardrails.judges.judge_engine.init_chat_model',
            return_value=mock_base_model,
        ),
        patch(
            'radicalbit_ai_gateway.guardrails.judges.judge_engine.parse_provider_and_model',
            return_value=('openai', 'gpt-4o-mini'),
        ),
    ):
        yield


# -----------------------------------------------------
# Test Suite for JudgeEngine
# -----------------------------------------------------
class TestJudgeEngine:
    """Comprehensive test suite for the JudgeEngine implementation."""

    def setup_method(self):
        self.prompt_manager = Mock(spec=PromptManager)
        self.prompt_manager.get_judge_prompt.return_value = (
            'You are a business context judge.'
        )
        self.cost_service: CostService = MagicMock(spec_set=CostService)
        self.engine = JudgeEngine(prompt_manager=self.prompt_manager)

    # -----------------------------------------------------
    # extract_content_for_judge tests (INPUT vs OUTPUT)
    # -----------------------------------------------------
    def test_extract_content_input_default(self):
        """Default behavior (no where) -> INPUT: extracts all messages."""
        messages = [
            HumanMessage(content='Hello'),
            HumanMessage(content='How are you?'),
        ]
        result = extract_content_for_judge(messages)
        assert result == 'Hello\nHow are you?'

    def test_extract_content_input_includes_all_message_types(self):
        """INPUT includes all message types — role filtering is done upstream."""
        messages = [
            HumanMessage(content='Hello'),
            AIMessage(content='Assistant output'),
            HumanMessage(content='How are you?'),
        ]
        result = extract_content_for_judge(messages, where=GuardrailWhereType.INPUT)
        assert result == 'Hello\nAssistant output\nHow are you?'

    def test_extract_content_input_includes_tool_messages(self):
        """INPUT includes ToolMessage content — typical for tool-role guardrail checks."""
        messages = [
            HumanMessage(content='User request'),
            ToolMessage(content='Tool result with Zeiss data', tool_call_id='c1'),
        ]
        result = extract_content_for_judge(messages, where=GuardrailWhereType.INPUT)
        assert result == 'User request\nTool result with Zeiss data'

    def test_extract_content_input_includes_system_messages(self):
        """INPUT includes SystemMessage content when passed."""
        messages = [
            SystemMessage(content='System context'),
            HumanMessage(content='User request'),
        ]
        result = extract_content_for_judge(messages, where=GuardrailWhereType.INPUT)
        assert result == 'System context\nUser request'

    def test_extract_content_output_picks_ai(self):
        """OUTPUT must pick AI messages (assistant output)."""
        messages = [
            HumanMessage(content='User asks something'),
            AIMessage(content='This is the model output'),
        ]
        result = extract_content_for_judge(messages, where=GuardrailWhereType.OUTPUT)
        assert result == 'This is the model output'

    def test_extract_content_output_empty_when_no_ai(self):
        """OUTPUT with no AI messages -> empty string (your current policy)."""
        messages = [HumanMessage(content='Only user text')]
        result = extract_content_for_judge(messages, where=GuardrailWhereType.OUTPUT)
        assert result == ''

    def test_extract_content_with_structured_list_content(self):
        """INPUT with structured list content (OpenAI multimodal format) is extracted."""
        structured_content = [
            {'type': 'text', 'text': 'Hello, this is a test message'},
            {'type': 'image', 'source_type': 'base64', 'data': 'base64data'},
        ]
        messages = [HumanMessage(content=structured_content)]
        result = extract_content_for_judge(messages, where=GuardrailWhereType.INPUT)
        assert result == 'Hello, this is a test message'

    def test_extract_content_with_multiple_text_parts(self):
        """INPUT with multiple text parts in structured content."""
        structured_content = [
            {'type': 'text', 'text': 'First part'},
            {'type': 'text', 'text': 'Second part'},
        ]
        messages = [HumanMessage(content=structured_content)]
        result = extract_content_for_judge(messages, where=GuardrailWhereType.INPUT)
        assert result == 'First part Second part'

    # -----------------------------------------------------
    # Prompt template
    # -----------------------------------------------------
    def test_build_prompt_template_structure(self):
        config = JudgeRuntimeConfig(
            model_id='gpt-4o',
            prompt_ref='business_context_check.md',
            temperature=0.0,
            max_tokens=100,
            include_reasoning=False,
        )

        prompt_template = self.engine._build_prompt_template(config)

        assert isinstance(prompt_template, PromptTemplate)
        template_text = prompt_template.template
        assert 'Text Under Review' in template_text
        self.prompt_manager.get_judge_prompt.assert_called_once_with(
            'business_context_check.md'
        )

    def test_build_prompt_template_reasoning_enabled(self):
        config = JudgeRuntimeConfig(
            model_id='gpt-4o',
            prompt_ref='business_context_check.md',
            temperature=0.0,
            max_tokens=100,
            include_reasoning=True,
        )

        prompt_template = self.engine._build_prompt_template(config)
        template_text = prompt_template.template

        assert 'include a short reasoning' in template_text

    def test_build_prompt_template_reasoning_disabled(self):
        config = JudgeRuntimeConfig(
            model_id='gpt-4o',
            prompt_ref='business_context_check.md',
            temperature=0.0,
            max_tokens=100,
            include_reasoning=False,
        )

        prompt_template = self.engine._build_prompt_template(config)
        template_text = prompt_template.template

        assert (
            "Do NOT include any reasoning. The 'reasoning' field MUST be null or omitted."
            in template_text
        )

    # -----------------------------------------------------
    # Model caching (with_structured_output applied)
    # -----------------------------------------------------
    def test_get_or_create_model_uses_cache(self):
        mock_model = Mock(spec=BaseLanguageModel)

        model_cfg = Mock()
        model_cfg.model_id = 'gpt-4o-mini'
        model_cfg.model = 'openai:gpt-4o-mini'
        model_cfg.credentials = None

        config = JudgeRuntimeConfig(
            model_id='gpt-4o-mini',
            temperature=0.1,
            max_tokens=50,
            prompt_ref='prompt_ref.md',
        )

        # Prime the cache manually
        self.engine._model_cache.clear()
        self.engine._model_cache['gpt-4o-mini:0.1:50'] = mock_model

        result = self.engine._get_or_create_model(config, model_cfg)
        assert result is mock_model

    @patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.init_chat_model')
    def test_get_or_create_model_applies_structured_output(self, mock_init_chat_model):
        """Verify that with_structured_output(JudgeResult, include_raw=True) is applied."""
        mock_base = MagicMock()
        mock_structured = MagicMock()
        mock_base.with_structured_output.return_value = mock_structured
        mock_init_chat_model.return_value = mock_base

        model_cfg = Mock()
        model_cfg.model_id = 'gpt-4o'
        model_cfg.model = 'openai/gpt-4o'
        model_cfg.credentials = None

        config = JudgeRuntimeConfig(
            model_id='gpt-4o',
            temperature=0.5,
            max_tokens=100,
            prompt_ref='test.md',
        )

        self.engine._model_cache.clear()
        result = self.engine._get_or_create_model(config, model_cfg)

        mock_base.with_structured_output.assert_called_once_with(
            schema=JudgeResult, include_raw=True
        )
        assert result is mock_structured

    # -----------------------------------------------------
    # Execution flows
    # -----------------------------------------------------
    @patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.init_chat_model')
    @patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.emit_event')
    @patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.PromptTemplate')
    @pytest.mark.asyncio
    async def test_primary_model_succeeds(
        self, mock_prompt_template, mock_emit_event, mock_init_chat_model
    ):
        """Primary model executes successfully and returns JudgeResult."""
        mock_prompt = MagicMock(spec=PromptTemplate)
        expected_result = JudgeResult(
            triggered=True,
            reasoning='Detected off-topic message',
            violation_type='business_context',
        )

        mock_raw_response = AIMessage(
            content='{"triggered": true}',
            usage_metadata={'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15},
        )

        mock_chain = AsyncMock()
        mock_chain.ainvoke.return_value = _build_structured_response(
            raw_response=mock_raw_response,
            parsed=expected_result,
        )

        mock_prompt.__or__.return_value = mock_chain
        mock_prompt_template.return_value = mock_prompt

        mock_model_cfg = Mock(
            model_id='gpt-4o', model='openai:gpt-4o', credentials=None
        )
        judge_parameter = JudgeParameter(
            model_id='gpt-4o', prompt_ref='business_context_check.md'
        )

        result = await self.engine.execute_judge(
            messages=[HumanMessage(content="What's your favorite pizza?")],
            judge_parameter=judge_parameter,
            primary_model=mock_model_cfg,
            cost_service=self.cost_service,
        )

        assert isinstance(result, JudgeResult)
        assert result.triggered
        assert result.violation_type == 'business_context'

    @patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.init_chat_model')
    @patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.emit_event')
    @patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.PromptTemplate')
    @pytest.mark.asyncio
    async def test_primary_fails_fallback_succeeds(
        self, mock_prompt_template, mock_emit_event, mock_init_chat_model
    ):
        """Primary model fails, fallback model succeeds."""
        mock_prompt = MagicMock(spec=PromptTemplate)

        # Chain 1: Primary (Fails)
        mock_chain_primary = AsyncMock()
        mock_chain_primary.ainvoke.side_effect = Exception('Primary crashed')

        # Chain 2: Fallback (Succeeds)
        fallback_result = JudgeResult(
            triggered=False, reasoning='OK', violation_type=None
        )
        mock_raw_response = AIMessage(
            content='{"triggered": false}',
            usage_metadata={'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15},
        )
        mock_chain_fallback = AsyncMock()
        mock_chain_fallback.ainvoke.return_value = _build_structured_response(
            raw_response=mock_raw_response,
            parsed=fallback_result,
        )

        mock_prompt.__or__.side_effect = [mock_chain_primary, mock_chain_fallback]
        mock_prompt_template.return_value = mock_prompt

        mock_model_cfg = Mock(
            model_id='gpt-4o', model='openai:gpt-4o', credentials=None
        )
        judge_parameter = JudgeParameter(
            model_id='gpt-4o', prompt_ref='toxicity_check.md'
        )

        result = await self.engine.execute_judge(
            messages=[HumanMessage(content='Hello world')],
            judge_parameter=judge_parameter,
            primary_model=mock_model_cfg,
            cost_service=self.cost_service,
            fallback_model=mock_model_cfg,
        )

        assert isinstance(result, JudgeResult)
        assert not result.triggered
        assert result.reasoning == 'OK'

    @patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.PromptTemplate')
    @pytest.mark.asyncio
    async def test_both_primary_and_fallback_fail(self, mock_prompt_template):
        """Both models fail -> raises JudgeInternalError instead of returning silent default."""
        mock_prompt = MagicMock(spec=PromptTemplate)
        mock_model_primary = MagicMock()
        mock_model_fallback = MagicMock()

        mock_chain_primary = AsyncMock()
        mock_chain_primary.ainvoke.side_effect = Exception('Primary fail')

        mock_chain_fallback = AsyncMock()
        mock_chain_fallback.ainvoke.side_effect = Exception('Fallback fail')

        mock_prompt.__or__.side_effect = [mock_model_primary, mock_model_fallback]
        mock_model_primary.__or__.return_value = mock_chain_primary
        mock_model_fallback.__or__.return_value = mock_chain_fallback
        mock_prompt_template.return_value = mock_prompt

        mock_model_cfg = Mock(
            model_id='gpt-4o', model='openai:gpt-4o', credentials=None
        )
        judge_parameter = JudgeParameter(
            model_id='gpt-4o', prompt_ref='business_context_check.md'
        )

        with pytest.raises(JudgeInternalError) as exc_info:
            await self.engine.execute_judge(
                messages=[HumanMessage(content='Irrelevant text')],
                judge_parameter=judge_parameter,
                primary_model=mock_model_cfg,
                cost_service=self.cost_service,
                fallback_model=mock_model_cfg,
            )

        assert 'Both primary and fallback' in str(exc_info.value)

    @patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.init_chat_model')
    @patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.emit_event')
    @patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.PromptTemplate')
    @pytest.mark.asyncio
    async def test_execute_judge_without_reasoning(
        self, mock_prompt_template, mock_emit_event, mock_init_chat_model
    ):
        """Judge runs with include_reasoning=False -> reasoning=None."""
        mock_prompt = MagicMock(spec=PromptTemplate)

        expected_result = JudgeResult(
            triggered=True,
            reasoning=None,
            violation_type='toxicity',
        )

        mock_raw_response = AIMessage(
            content='{"triggered": true}',
            usage_metadata={'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15},
        )

        mock_chain = AsyncMock()
        mock_chain.ainvoke.return_value = _build_structured_response(
            raw_response=mock_raw_response,
            parsed=expected_result,
        )

        mock_prompt.__or__.return_value = mock_chain
        mock_prompt_template.return_value = mock_prompt

        mock_model_cfg = Mock(
            model_id='gpt-4o', model='openai:gpt-4o', credentials=None
        )
        self.prompt_manager.get_judge_prompt.return_value = 'Analyze toxicity.'

        judge_parameter = JudgeParameter(
            model_id='gpt-4o',
            prompt_ref='toxicity_check.md',
            include_reasoning=False,
        )

        result = await self.engine.execute_judge(
            messages=[HumanMessage(content='You are stupid')],
            judge_parameter=judge_parameter,
            primary_model=mock_model_cfg,
            cost_service=self.cost_service,
        )

        assert isinstance(result, JudgeResult)
        assert result.reasoning is None
        assert result.violation_type == 'toxicity'

    # -----------------------------------------------------
    # execute_judge with OUTPUT messages (AIMessage)
    # -----------------------------------------------------
    @patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.init_chat_model')
    @patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.emit_event')
    @patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.PromptTemplate')
    @pytest.mark.asyncio
    async def test_execute_judge_output_uses_ai_content(
        self, mock_prompt_template, mock_emit_event, mock_init_chat_model
    ):
        mock_prompt = MagicMock(spec=PromptTemplate)
        mock_prompt_template.return_value = mock_prompt

        expected = JudgeResult(
            triggered=True, reasoning='Off-topic output', violation_type='irrelevant'
        )
        mock_raw_response = AIMessage(
            content='{"triggered": true}',
            usage_metadata={'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15},
        )

        mock_chain = AsyncMock()
        mock_chain.ainvoke.return_value = _build_structured_response(
            raw_response=mock_raw_response,
            parsed=expected,
        )
        mock_prompt.__or__.return_value = mock_chain

        mock_model_cfg = Mock(
            model_id='gpt-4o', model='openai:gpt-4o', credentials=None
        )
        judge_parameter = JudgeParameter(
            model_id='gpt-4o', prompt_ref='business_context_check.md'
        )

        result = await self.engine.execute_judge(
            messages=[AIMessage(content='Carbonara is an Italian recipe...')],
            judge_parameter=judge_parameter,
            primary_model=mock_model_cfg,
            cost_service=self.cost_service,
            where=GuardrailWhereType.OUTPUT,
        )

        assert isinstance(result, JudgeResult)
        assert result.triggered is True
        assert result.violation_type == 'irrelevant'

    # -----------------------------------------------------
    # execute_judge with exception handling
    # -----------------------------------------------------
    @patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.init_chat_model')
    @patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.emit_event')
    @patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.PromptTemplate')
    @pytest.mark.asyncio
    async def test_raises_truncated_error_on_finish_reason_length(
        self, mock_prompt_template, mock_emit_event, mock_init_chat_model
    ):
        """Judge raises JudgeOutputTruncatedError when finish_reason is 'length'."""
        mock_prompt = MagicMock(spec=PromptTemplate)

        # Truncated response: finish_reason='length'
        truncated_response = AIMessage(
            content='{"triggered": true, "re',
            response_metadata={'finish_reason': 'length'},
            usage_metadata={
                'input_tokens': 10,
                'output_tokens': 200,
                'total_tokens': 210,
            },
        )

        mock_chain = AsyncMock()
        mock_chain.ainvoke.return_value = _build_structured_response(
            raw_response=truncated_response,
            parsed=None,
            parsing_error=ValueError('Truncated JSON'),
        )

        mock_prompt.__or__.return_value = mock_chain
        mock_prompt_template.return_value = mock_prompt

        mock_model_cfg = Mock(
            model_id='gpt-4o', model='openai:gpt-4o', credentials=None
        )
        judge_parameter = JudgeParameter(
            model_id='gpt-4o', prompt_ref='business_context_check.md', max_tokens=200
        )

        with pytest.raises(JudgeOutputTruncatedError) as exc_info:
            await self.engine.execute_judge(
                messages=[HumanMessage(content='Test content')],
                judge_parameter=judge_parameter,
                primary_model=mock_model_cfg,
                cost_service=self.cost_service,
            )

        assert exc_info.value.finish_reason == 'length'
        assert exc_info.value.model_id == 'gpt-4o'

    @patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.init_chat_model')
    @patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.emit_event')
    @patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.PromptTemplate')
    @pytest.mark.asyncio
    async def test_raises_parsing_error_on_empty_parsed(
        self, mock_prompt_template, mock_emit_event, mock_init_chat_model
    ):
        """Judge raises JudgeParsingError when structured output parsed is None."""
        mock_prompt = MagicMock(spec=PromptTemplate)

        empty_response = AIMessage(
            content='',
            response_metadata={'finish_reason': 'stop'},
            usage_metadata={'input_tokens': 10, 'output_tokens': 0, 'total_tokens': 10},
        )

        mock_chain = AsyncMock()
        mock_chain.ainvoke.return_value = _build_structured_response(
            raw_response=empty_response,
            parsed=None,
        )

        mock_prompt.__or__.return_value = mock_chain
        mock_prompt_template.return_value = mock_prompt

        mock_model_cfg = Mock(
            model_id='gpt-4o', model='openai:gpt-4o', credentials=None
        )
        judge_parameter = JudgeParameter(
            model_id='gpt-4o', prompt_ref='business_context_check.md'
        )

        with pytest.raises(JudgeParsingError) as exc_info:
            await self.engine.execute_judge(
                messages=[HumanMessage(content='Test content')],
                judge_parameter=judge_parameter,
                primary_model=mock_model_cfg,
                cost_service=self.cost_service,
            )

        assert 'Empty parsed response' in str(exc_info.value.original_error)

    @patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.init_chat_model')
    @patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.emit_event')
    @patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.PromptTemplate')
    @pytest.mark.asyncio
    async def test_raises_parsing_error_on_invalid_json(
        self, mock_prompt_template, mock_emit_event, mock_init_chat_model
    ):
        """Judge raises JudgeParsingError when structured output has parsing_error."""
        mock_prompt = MagicMock(spec=PromptTemplate)

        invalid_json_response = AIMessage(
            content='This is not valid JSON at all',
            response_metadata={'finish_reason': 'stop'},
            usage_metadata={
                'input_tokens': 10,
                'output_tokens': 50,
                'total_tokens': 60,
            },
        )

        mock_chain = AsyncMock()
        mock_chain.ainvoke.return_value = _build_structured_response(
            raw_response=invalid_json_response,
            parsed=None,
            parsing_error=ValueError('Invalid JSON'),
        )

        mock_prompt.__or__.return_value = mock_chain
        mock_prompt_template.return_value = mock_prompt

        mock_model_cfg = Mock(
            model_id='gpt-4o', model='openai:gpt-4o', credentials=None
        )
        judge_parameter = JudgeParameter(
            model_id='gpt-4o', prompt_ref='business_context_check.md'
        )

        with pytest.raises(JudgeParsingError) as exc_info:
            await self.engine.execute_judge(
                messages=[HumanMessage(content='Test content')],
                judge_parameter=judge_parameter,
                primary_model=mock_model_cfg,
                cost_service=self.cost_service,
            )

        assert 'This is not valid JSON at all' in exc_info.value.raw_content

    @patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.PromptTemplate')
    @pytest.mark.asyncio
    async def test_raises_error_when_no_fallback_and_primary_fails(
        self, mock_prompt_template
    ):
        """Judge raises JudgeInternalError when primary fails and no fallback is defined."""
        mock_prompt = MagicMock(spec=PromptTemplate)
        mock_model = MagicMock()

        mock_chain = AsyncMock()
        mock_chain.ainvoke.side_effect = Exception('Network error')

        mock_prompt.__or__.return_value = mock_model
        mock_model.__or__.return_value = mock_chain
        mock_prompt_template.return_value = mock_prompt

        mock_model_cfg = Mock(
            model_id='gpt-4o', model='openai:gpt-4o', credentials=None
        )
        judge_parameter = JudgeParameter(
            model_id='gpt-4o', prompt_ref='business_context_check.md'
        )

        with pytest.raises(JudgeInternalError) as exc_info:
            await self.engine.execute_judge(
                messages=[HumanMessage(content='Test content')],
                judge_parameter=judge_parameter,
                primary_model=mock_model_cfg,
                cost_service=self.cost_service,
                fallback_model=None,  # No fallback
            )

        assert 'Primary judge model failed' in str(exc_info.value)

    # -----------------------------------------------------
    # extract_media_blocks_for_judge
    # -----------------------------------------------------
    def test_extract_media_blocks_input_with_image_url(self):
        """image_url block is extracted from human message."""
        image_block = {
            'type': 'image_url',
            'image_url': {'url': 'data:image/png;base64,abc'},
        }
        messages = [
            HumanMessage(
                content=[{'type': 'text', 'text': 'Describe this.'}, image_block]
            )
        ]
        result = extract_media_blocks_for_judge(
            messages, where=GuardrailWhereType.INPUT
        )
        assert result == [image_block]

    def test_extract_media_blocks_input_with_file_block(self):
        """File block is extracted from human message."""
        file_block = {
            'type': 'file',
            'file': {
                'filename': 'doc.pdf',
                'file_data': 'data:application/pdf;base64,abc',
            },
        }
        messages = [
            HumanMessage(content=[{'type': 'text', 'text': 'Summarize.'}, file_block])
        ]
        result = extract_media_blocks_for_judge(messages)
        assert result == [file_block]

    def test_extract_media_blocks_input_text_only_returns_empty(self):
        """No media blocks when message is plain text."""
        messages = [HumanMessage(content='Just text')]
        result = extract_media_blocks_for_judge(messages)
        assert result == []

    def test_extract_media_blocks_input_structured_text_only_returns_empty(self):
        """No media blocks when structured content has only text blocks."""
        messages = [HumanMessage(content=[{'type': 'text', 'text': 'Hello'}])]
        result = extract_media_blocks_for_judge(messages)
        assert result == []

    def test_extract_media_blocks_includes_all_message_types_for_input(self):
        """Media blocks in all message types are included for INPUT phase.

        Role filtering is applied upstream; the extractor processes whatever
        messages it receives without further type discrimination.
        """
        image_block = {
            'type': 'image_url',
            'image_url': {'url': 'data:image/png;base64,abc'},
        }
        messages = [
            HumanMessage(content='User text'),
            AIMessage(content=[{'type': 'text', 'text': 'AI text'}, image_block]),
        ]
        result = extract_media_blocks_for_judge(
            messages, where=GuardrailWhereType.INPUT
        )
        assert result == [image_block]

    def test_extract_media_blocks_output_picks_last_ai_message(self):
        """Media blocks from the last AI message are returned for OUTPUT phase."""
        image_block = {
            'type': 'image_url',
            'image_url': {'url': 'data:image/png;base64,xyz'},
        }
        messages = [
            HumanMessage(content='User text'),
            AIMessage(content=[{'type': 'text', 'text': 'AI response'}, image_block]),
        ]
        result = extract_media_blocks_for_judge(
            messages, where=GuardrailWhereType.OUTPUT
        )
        assert result == [image_block]

    def test_extract_media_blocks_output_no_media_returns_empty(self):
        """Empty list when OUTPUT AI message has no media blocks."""
        messages = [AIMessage(content='Plain AI text')]
        result = extract_media_blocks_for_judge(
            messages, where=GuardrailWhereType.OUTPUT
        )
        assert result == []

    # -----------------------------------------------------
    # Multimodal execution path
    # -----------------------------------------------------
    @patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.emit_event')
    @pytest.mark.asyncio
    async def test_execute_judge_multimodal_invokes_with_human_message(
        self, mock_emit_event
    ):
        """With include_media=True and image blocks, structured model receives HumanMessage with mixed content."""
        image_block = {
            'type': 'image_url',
            'image_url': {'url': 'data:image/png;base64,abc123'},
        }
        messages = [
            HumanMessage(
                content=[
                    {'type': 'text', 'text': 'Analyze this for toxicity.'},
                    image_block,
                ]
            )
        ]

        expected_result = JudgeResult(
            triggered=False, reasoning=None, violation_type=None
        )
        mock_raw_response = AIMessage(
            content='{"triggered": false}',
            usage_metadata={'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15},
        )

        mock_structured_model = AsyncMock()
        mock_structured_model.ainvoke.return_value = _build_structured_response(
            raw_response=mock_raw_response,
            parsed=expected_result,
        )

        cache_key = 'gpt-4o-mini:0.7:100'
        self.engine._model_cache[cache_key] = mock_structured_model

        judge_parameter = JudgeParameter(
            model_id='gpt-4o-mini',
            prompt_ref='toxicity_check.md',
            temperature=0.7,
            max_tokens=100,
            include_media=True,
        )
        mock_model_cfg = Mock(
            model_id='gpt-4o-mini', model='openai:gpt-4o-mini', credentials=None
        )

        result = await self.engine.execute_judge(
            messages=messages,
            judge_parameter=judge_parameter,
            primary_model=mock_model_cfg,
            cost_service=self.cost_service,
        )

        mock_structured_model.ainvoke.assert_called_once()
        call_arg = mock_structured_model.ainvoke.call_args[0][0]
        assert isinstance(call_arg, list) and len(call_arg) == 1
        assert isinstance(call_arg[0], HumanMessage)
        human_content = call_arg[0].content
        assert isinstance(human_content, list)
        assert human_content[0]['type'] == 'text'
        assert 'Content Under Review' in human_content[0]['text']
        assert human_content[1] == image_block
        assert result.triggered is False

    @patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.emit_event')
    @patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.PromptTemplate')
    @pytest.mark.asyncio
    async def test_execute_judge_text_only_uses_chain(
        self, mock_prompt_template, mock_emit_event
    ):
        """With include_media=False (default), text-only path uses PromptTemplate chain."""
        mock_prompt = MagicMock(spec=PromptTemplate)
        expected_result = JudgeResult(
            triggered=False, reasoning=None, violation_type=None
        )
        mock_raw_response = AIMessage(
            content='{"triggered": false}',
            usage_metadata={'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15},
        )
        mock_chain = AsyncMock()
        mock_chain.ainvoke.return_value = _build_structured_response(
            raw_response=mock_raw_response,
            parsed=expected_result,
        )
        mock_prompt.__or__.return_value = mock_chain
        mock_prompt_template.return_value = mock_prompt

        judge_parameter = JudgeParameter(
            model_id='gpt-4o-mini',
            prompt_ref='toxicity_check.md',
            include_media=False,
        )
        mock_model_cfg = Mock(
            model_id='gpt-4o-mini', model='openai:gpt-4o-mini', credentials=None
        )

        result = await self.engine.execute_judge(
            messages=[HumanMessage(content='Hello world')],
            judge_parameter=judge_parameter,
            primary_model=mock_model_cfg,
            cost_service=self.cost_service,
        )

        mock_chain.ainvoke.assert_called_once_with({'content': 'Hello world'})
        assert result.triggered is False

    @patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.emit_event')
    @patch('radicalbit_ai_gateway.guardrails.judges.judge_engine.PromptTemplate')
    @pytest.mark.asyncio
    async def test_execute_judge_include_media_true_no_blocks_uses_chain(
        self, mock_prompt_template, mock_emit_event
    ):
        """With include_media=True but no media blocks in message, text-only chain is still used."""
        mock_prompt = MagicMock(spec=PromptTemplate)
        expected_result = JudgeResult(
            triggered=False, reasoning=None, violation_type=None
        )
        mock_raw_response = AIMessage(
            content='{"triggered": false}',
            usage_metadata={'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15},
        )
        mock_chain = AsyncMock()
        mock_chain.ainvoke.return_value = _build_structured_response(
            raw_response=mock_raw_response,
            parsed=expected_result,
        )
        mock_prompt.__or__.return_value = mock_chain
        mock_prompt_template.return_value = mock_prompt

        judge_parameter = JudgeParameter(
            model_id='gpt-4o-mini',
            prompt_ref='toxicity_check.md',
            include_media=True,
        )
        mock_model_cfg = Mock(
            model_id='gpt-4o-mini', model='openai:gpt-4o-mini', credentials=None
        )

        result = await self.engine.execute_judge(
            messages=[HumanMessage(content='Plain text, no images')],
            judge_parameter=judge_parameter,
            primary_model=mock_model_cfg,
            cost_service=self.cost_service,
        )

        mock_chain.ainvoke.assert_called_once()
        assert result.triggered is False
