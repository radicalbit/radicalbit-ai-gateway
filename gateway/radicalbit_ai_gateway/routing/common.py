from collections.abc import Awaitable
import logging
from typing import Any, Literal, Protocol

from opentelemetry import trace

from radicalbit_ai_gateway.llm.messages import BaseMessage, HumanMessage
from radicalbit_ai_gateway.models.guardrails import GuardrailMessageRole
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.build_user_content import stringify_message_content
from radicalbit_ai_gateway.utils.content_utils import ContentUtils

logger = logging.getLogger(get_app_config().log_config.logger_name)


class RoutingSpendRecorder(Protocol):
    """Charge one routing call to the request it routes.

    It emits the cost event (flagged as routing) at the model's input price
    and counts the input tokens on the route, credential and project limits.
    ``model_type`` is ``'embeddings'``, ``'decision_model'`` or
    ``'chat-model'``. Pass ``target_model_id`` when a fallback model answered
    instead of it, and ``output_tokens`` for a chat model router: its output
    tokens are then costed and counted too.
    """

    def __call__(
        self,
        model: Any,
        input_tokens: int,
        latency_ms: float,
        *,
        model_type: str,
        target_model_id: str | None = None,
        output_tokens: int | None = None,
    ) -> Awaitable[None]: ...


async def record_routing_spend(
    record: RoutingSpendRecorder | None,
    model: Any,
    input_tokens: int,
    latency_ms: float,
    *,
    model_type: str,
    target_model_id: str | None = None,
    output_tokens: int | None = None,
) -> None:
    """Charge one routing call with ``record``, if the caller gave one.

    Routing never fails a request: a failure here is logged, not raised.
    """
    if record is None:
        return
    try:
        await record(
            model,
            input_tokens,
            latency_ms,
            model_type=model_type,
            target_model_id=target_model_id,
            output_tokens=output_tokens,
        )
    except Exception:
        logger.exception('Routing spend on model %s was not recorded', model.model_id)


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
