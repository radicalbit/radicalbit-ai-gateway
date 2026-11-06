"""The model's reasoning in a Responses API request or response.

A reasoning item rides on the assistant message after it, for the guardrails
that read reasoning. Encrypted reasoning is not readable and is never touched.
"""

from __future__ import annotations

from radicalbit_ai_gateway.llm.messages import (
    REASONING_KEY,
    AIMessage,
    BaseMessage,
    MessageContent,
    ReasoningOnlyMessage,
)


def text_parts(content: object, part_type: str) -> list[dict]:
    """Return the parts of ``content`` of type ``part_type`` that carry a text."""
    return [
        part
        for part in content or []
        if isinstance(part, dict)
        and part.get('type') == part_type
        and isinstance(part.get('text'), str)
    ]


def _reasoning_parts(item: dict) -> list[dict]:
    """Return the readable texts of a reasoning item: its summary and raw text."""
    return text_parts(item.get('summary'), 'summary_text') + text_parts(
        item.get('content'), 'reasoning_text'
    )


def _join(parts: list[dict]) -> str:
    return '\n'.join(part['text'] for part in parts if part['text'])


class Reasoning:
    """The readable reasoning of one or more reasoning items, read as one text.

    Some providers (Ollama) copy the readable text in ``encrypted_content``: a
    changed text replaces that copy too, so a redacted text does not come back
    there.
    """

    def __init__(self) -> None:
        self._parts: list[dict] = []
        # Each item, with the readable text it had when read.
        self._items: list[tuple[dict, str]] = []

    def add(self, item: dict) -> None:
        parts = _reasoning_parts(item)
        self._parts += parts
        self._items.append((item, _join(parts)))

    def text(self) -> str:
        return _join(self._parts)

    def __bool__(self) -> bool:
        """Return True when the items have readable text."""
        return bool(self.text())

    def write(self, text: str) -> None:
        """Put ``text`` in the first part and empty the others."""
        if not self._parts or text == self.text():
            return
        for index, part in enumerate(self._parts):
            part['text'] = text if index == 0 else ''
        for item, original in self._items:
            if original and item.get('encrypted_content') == original:
                item['encrypted_content'] = _join(_reasoning_parts(item))

    def write_from(self, message: BaseMessage) -> None:
        """Write back the reasoning of ``message``, as a guardrail left it.

        A policy that rebuilt the message without its reasoning leaves the
        reasoning as it is.
        """
        reasoning = message.additional_kwargs.get(REASONING_KEY)
        if isinstance(reasoning, str):
            self.write(reasoning)


def assistant_message(
    content: MessageContent, reasoning: Reasoning, has_text: bool
) -> AIMessage:
    """Build an assistant message that carries the reasoning before it.

    Without text, the message holds only reasoning.
    """
    text = reasoning.text()
    if not text:
        return AIMessage(content=content)
    message_type = AIMessage if has_text else ReasoningOnlyMessage
    return message_type(content=content, additional_kwargs={REASONING_KEY: text})
