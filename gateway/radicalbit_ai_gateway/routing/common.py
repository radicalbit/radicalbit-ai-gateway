from typing import Literal

from opentelemetry import trace

from radicalbit_ai_gateway.llm.messages import BaseMessage, HumanMessage
from radicalbit_ai_gateway.models.guardrails import GuardrailMessageRole
from radicalbit_ai_gateway.utils.build_user_content import stringify_message_content
from radicalbit_ai_gateway.utils.content_utils import ContentUtils

_MESSAGE_TYPE_BY_ROLE = {
    GuardrailMessageRole.USER: 'human',
    GuardrailMessageRole.ASSISTANT: 'ai',
    GuardrailMessageRole.SYSTEM: 'system',
    GuardrailMessageRole.TOOL: 'tool',
}
# history: all with no message_roles sends human and AI messages only.
_DEFAULT_MESSAGE_TYPES = frozenset({'human', 'ai'})


def last_human_text(messages: list[BaseMessage]) -> str | None:
    """Return the text content of the last HumanMessage, or None."""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            text = stringify_message_content(msg.content)
            if text:
                return text
    return None


def routing_text(
    messages: list[BaseMessage],
    history: Literal['last', 'all'],
    message_roles: list[GuardrailMessageRole] | None,
) -> str:
    """Return the text a routing model reads.

    The last human message, or with history: all the conversation filtered by role.
    """
    if history == 'last':
        return last_human_text(messages) or ''
    types = (
        {_MESSAGE_TYPE_BY_ROLE[r] for r in message_roles}
        if message_roles is not None
        else _DEFAULT_MESSAGE_TYPES
    )
    parts = []
    for msg in messages:
        if getattr(msg, 'type', '') not in types:
            continue
        text = ContentUtils.extract_text_content(msg.content, strip=True)
        if text:
            parts.append(text)
    return '\n'.join(parts)


def set_span_attributes(prefix: str, **attributes) -> None:
    """Set `<prefix><key>` attributes on the routing span."""
    try:
        span = trace.get_current_span()
        if span.is_recording():
            for key, value in attributes.items():
                span.set_attribute(prefix + key, value)
    except Exception:
        pass
