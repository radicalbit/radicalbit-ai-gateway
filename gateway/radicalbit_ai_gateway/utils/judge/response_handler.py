"""Response handling utilities for the Judge engine.

This module provides functions for validating and extracting LLM responses
in the context of guardrail judges.
"""

import logging

from langchain_core.messages import AIMessage

from radicalbit_ai_gateway.models.judge_result import JudgeResult
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import (
    JudgeOutputTruncatedError,
    JudgeParsingError,
)

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)


def validate_response_completeness(response: AIMessage, model_id: str) -> None:
    """Check if the response was truncated due to token limits.

    This function inspects the response metadata to determine if the LLM
    stopped generating due to reaching the max_tokens limit (finish_reason='length').

    Args:
        response: The AIMessage response from the LLM.
        model_id: The identifier of the model that generated the response.

    Raises:
        JudgeOutputTruncatedError: If finish_reason indicates truncation ('length').

    """
    finish_reason = None
    if isinstance(response, AIMessage) and response.response_metadata:
        finish_reason = response.response_metadata.get('finish_reason')

        if not finish_reason:
            finish_reason = response.response_metadata.get('stop_reason')

    if finish_reason == 'length':
        logger.warning(
            'Judge output truncated: finish_reason=%s, model=%s',
            finish_reason,
            model_id,
        )
        raise JudgeOutputTruncatedError(finish_reason=finish_reason, model_id=model_id)


def extract_judge_result(structured_response: dict, model_id: str) -> JudgeResult:
    """Extract a JudgeResult from a with_structured_output(include_raw=True) response.

    Validates completeness, checks for parsing errors, and returns the parsed result.

    Args:
        structured_response: Dict with keys 'raw', 'parsed', 'parsing_error'
            as returned by LangChain's with_structured_output(include_raw=True).
        model_id: The identifier of the model that generated the response.

    Returns:
        JudgeResult: The validated and parsed judge result.

    Raises:
        JudgeOutputTruncatedError: If the raw response was truncated.
        JudgeParsingError: If parsing failed or produced no result.

    """
    raw_response: AIMessage | None = structured_response.get('raw')
    parsed: JudgeResult | None = structured_response.get('parsed')
    parsing_error: Exception | None = structured_response.get('parsing_error')

    if raw_response:
        validate_response_completeness(raw_response, model_id)

    if parsing_error:
        raw_content = getattr(raw_response, 'content', '') if raw_response else ''
        logger.warning(
            'Failed to parse structured judge response: model=%s, error=%s, content=%r',
            model_id,
            parsing_error,
            str(raw_content)[:200],
        )
        raise JudgeParsingError(
            raw_content=str(raw_content),
            original_error=parsing_error,
            model_id=model_id,
        )

    if not parsed:
        raw_content = getattr(raw_response, 'content', '') if raw_response else ''
        raise JudgeParsingError(
            raw_content=str(raw_content),
            original_error=ValueError('Empty parsed response from judge model'),
            model_id=model_id,
        )

    return parsed
