"""Content extraction utilities for the Judge engine.

This module provides functions for extracting text content from LangChain
messages based on the guardrail phase (input vs output).
"""

from langchain_core.messages import BaseMessage

from radicalbit_ai_gateway.models.guardrails import GuardrailWhereType
from radicalbit_ai_gateway.utils.content_utils import ContentUtils

_MEDIA_TYPES = frozenset({'image_url', 'image', 'file'})


def extract_content_for_judge(messages: list[BaseMessage], **kwargs) -> str:
    """Extract text content from messages based on guardrail phase.

    For INPUT phase: extracts content from all messages provided (role
    filtering is handled upstream by ``_filter_messages_by_roles``).
    For OUTPUT phase: extracts content from the last AI (assistant) message.

    Args:
        messages: List of LangChain messages.
        **kwargs: Must include 'where' (GuardrailWhereType) to determine phase.

    Returns:
        Extracted text content as a string. Returns empty string if no
        relevant content is found.

    """
    if not messages:
        return ''

    where = kwargs.get('where')
    if isinstance(where, GuardrailWhereType):
        where_value = where.value
    else:
        where_value = str(where or '').upper()

    if where_value == GuardrailWhereType.OUTPUT.value:
        return _extract_output_content(messages)

    return _extract_input_content(messages)


def _extract_output_content(messages: list[BaseMessage]) -> str:
    """Extract content from the last AI message for OUTPUT phase."""
    for m in reversed(messages):
        if _get_message_type(m) == 'ai':
            text = _get_message_text(m)
            if text:
                return text
    return ''


def _extract_input_content(messages: list[BaseMessage]) -> str:
    """Extract content from all provided messages for INPUT phase.

    Role-based filtering (e.g. user-only, tool-only) is applied upstream
    by ``_filter_messages_by_roles`` before the messages reach this function.
    No additional type filtering is performed here.
    """
    parts: list[str] = []
    for m in messages:
        text = _get_message_text(m)
        if text:
            parts.append(text)

    return '\n'.join(parts) if parts else ''


def _get_message_text(msg: BaseMessage) -> str:
    """Extract text content from a message."""
    content = getattr(msg, 'content', '')
    return ContentUtils.extract_text_content(content, strip=True)


def _get_message_type(msg: BaseMessage) -> str:
    """Get the type of a message (human, ai, etc.)."""
    return getattr(msg, 'type', '')


def extract_media_blocks_for_judge(messages: list[BaseMessage], **kwargs) -> list[dict]:
    """Extract image and file content blocks from messages based on guardrail phase.

    For INPUT phase: collects media blocks from all human messages.
    For OUTPUT phase: collects media blocks from the last AI message.

    Args:
        messages: List of LangChain messages.
        **kwargs: Accepts 'where' (GuardrailWhereType) to determine phase.

    Returns:
        List of content block dicts with type in {image_url, image, file}.
        Returns an empty list when no media blocks are present or for text-only messages.

    """
    if not messages:
        return []

    where = kwargs.get('where')
    if isinstance(where, GuardrailWhereType):
        where_value = where.value
    else:
        where_value = str(where or '').upper()

    if where_value == GuardrailWhereType.OUTPUT.value:
        return _extract_output_media_blocks(messages)
    return _extract_input_media_blocks(messages)


def _extract_input_media_blocks(messages: list[BaseMessage]) -> list[dict]:
    """Extract media blocks from all provided messages for INPUT phase.

    Role-based filtering is applied upstream; no additional type filtering here.
    """
    blocks: list[dict] = []
    for m in messages:
        blocks.extend(_get_media_blocks(m))
    return blocks


def _extract_output_media_blocks(messages: list[BaseMessage]) -> list[dict]:
    for m in reversed(messages):
        if _get_message_type(m) == 'ai':
            blocks = _get_media_blocks(m)
            if blocks:
                return blocks
    return []


def _get_media_blocks(msg: BaseMessage) -> list[dict]:
    content = getattr(msg, 'content', '')
    if not isinstance(content, list):
        return []
    return [
        item
        for item in content
        if isinstance(item, dict) and item.get('type') in _MEDIA_TYPES
    ]
