import re

from radicalbit_ai_gateway.llm.messages import BaseMessage, HumanMessage
from radicalbit_ai_gateway.models.routing import (
    DeterministicRoutingConfig,
    RoutingConfig,
    RoutingRuleType,
)


class RoutingInputFilter:
    """Cleans the user messages a router reads. The model still gets the originals.

    Agent clients add their own text to a request: a context
    message after the user's one, or a text part of it (skip it), and envelope
    text around the user's words (strip it).
    """

    # The patterns run synchronously on every routed request: a pattern with
    # catastrophic backtracking blocks the event loop. Admins write them; a
    # linear-time engine (RE2) or a match timeout is a possible follow-up.
    def __init__(self, skip: list[str] | None, strip: list[str] | None):
        self._skip = [re.compile(p) for p in skip or []]
        self._strip = [re.compile(p) for p in strip or []]

    @classmethod
    def from_config(cls, config: RoutingConfig) -> 'RoutingInputFilter | None':
        """Build the filter of a routing config, or None when it has none to apply.

        The context_length rule never filters: it measures the conversation the
        model receives, and the model gets every message unchanged.
        """
        if (
            isinstance(config, DeterministicRoutingConfig)
            and config.rule == RoutingRuleType.CONTEXT_LENGTH
        ):
            return None
        skip = config.skip_user_messages_matching
        strip = config.strip_from_routing_text
        return cls(skip, strip) if skip or strip else None

    def apply(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        out = []
        for msg in messages:
            if not isinstance(msg, HumanMessage):
                out.append(msg)
                continue
            content = self._clean(msg.content)
            if content is None:
                continue
            if content != msg.content:
                msg = msg.model_copy(update={'content': content})
            out.append(msg)
        return out

    def _clean(self, content: str | list) -> str | list | None:
        """Return the content the router reads, or None to hide the message."""
        if isinstance(content, str):
            return None if self._skips(content) else self._strip_text(content)
        # Each text part is matched and stripped on its own. Images and other
        # non-text parts pass unchanged: they never become text.
        parts = []
        for part in content:
            text = _part_text(part)
            if text is None:
                parts.append(part)
                continue
            if self._skips(text):
                continue
            stripped = self._strip_text(text)
            if stripped:
                parts.append(
                    stripped if isinstance(part, str) else {**part, 'text': stripped}
                )
        # A message whose every part is skipped is hidden.
        if content and all(
            (text := _part_text(part)) is not None and self._skips(text)
            for part in content
        ):
            return None
        return parts

    def _skips(self, text: str) -> bool:
        return any(p.search(text) for p in self._skip)

    def _strip_text(self, text: str) -> str:
        if not self._strip:
            return text
        for p in self._strip:
            text = p.sub('', text)
        return text.strip()


def _part_text(part: object) -> str | None:
    """Return the text of a text part of a multi-part message, or None for other parts."""
    if isinstance(part, str):
        return part
    if isinstance(part, dict) and part.get('type') == 'text':
        text = part.get('text')
        return text if isinstance(text, str) else None
    return None
