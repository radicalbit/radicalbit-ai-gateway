"""Thinking blocks another provider signed.

A client may switch models in one conversation. A thinking block that DeepSeek
(say) signed then goes to Claude in the history, and Claude refuses the whole
request: the signature is not one of its own. The gateway sends the body as is
first. Only when the upstream refuses a signature does it retry once, without
the old thinking blocks (see ``without_old_thinking``).
"""

from __future__ import annotations

from typing import Any

from radicalbit_ai_gateway.llm.errors import provider_status

THINKING_BLOCK_TYPES = ('thinking', 'redacted_thinking')


def is_invalid_thinking_signature(error: BaseException) -> bool:
    """Whether the upstream refused the signature of a thinking block."""
    refusal = provider_status(error)
    if refusal is None or refusal[0] != 400:
        return False
    _, message, body = refusal
    detail = body.get('error') if isinstance(body, dict) else None
    if isinstance(detail, dict) and isinstance(detail.get('message'), str):
        message = detail['message']
    message = (message or '').lower()
    return 'signature' in message and 'thinking' in message


def _is_thinking(block: Any) -> bool:
    return isinstance(block, dict) and block.get('type') in THINKING_BLOCK_TYPES


def _is_tool_result(block: Any) -> bool:
    return isinstance(block, dict) and block.get('type') == 'tool_result'


def _last_index(messages: list, role: str) -> int | None:
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if isinstance(message, dict) and message.get('role') == role:
            return index
    return None


def _kept_index(messages: list) -> int | None:
    """Return the assistant message whose thinking must stay, if any.

    That is the last assistant message while a tool loop runs: the last user
    message carries a ``tool_result``. The model needs that thinking to go on.
    """
    last_user = _last_index(messages, 'user')
    if last_user is None:
        return None
    content = messages[last_user].get('content')
    if not isinstance(content, list) or not any(map(_is_tool_result, content)):
        return None
    return _last_index(messages, 'assistant')


def without_old_thinking(body: dict) -> tuple[dict, int]:
    """Return a copy of ``body`` without the old thinking blocks, and their number.

    Thinking and redacted thinking blocks leave the assistant messages, except
    the last one during a tool loop (see ``_kept_index``). A message they would
    leave empty is kept as it is. ``body`` itself is not changed: the copy
    shares only the messages it keeps as they are.
    """
    messages = body.get('messages')
    if not isinstance(messages, list):
        return body, 0
    kept = _kept_index(messages)
    stripped = 0
    new_messages = []
    for index, message in enumerate(messages):
        content = message.get('content') if isinstance(message, dict) else None
        if (
            index == kept
            or not isinstance(content, list)
            or message.get('role') != 'assistant'
        ):
            new_messages.append(message)
            continue
        rest = [block for block in content if not _is_thinking(block)]
        if not rest or len(rest) == len(content):
            new_messages.append(message)
            continue
        stripped += len(content) - len(rest)
        new_messages.append({**message, 'content': rest})
    if not stripped:
        return body, 0
    return {**body, 'messages': new_messages}, stripped
