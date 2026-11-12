"""A chat completion's reply as the output guardrails read it."""

from __future__ import annotations

from dataclasses import dataclass, replace

from radicalbit_ai_gateway.llm.messages import AIMessage, BaseMessage


@dataclass(frozen=True)
class Reply:
    """A chat model's reply text. An empty reply is checked, not redacted."""

    text: str | None
    usage: dict | None = None
    skip = 0
    windowed = True

    def messages(self) -> list[BaseMessage]:
        # A reply with no text (a tool call) is read as empty text.
        return [AIMessage(content=self.text or '', usage_metadata=self.usage)]

    def with_messages(self, messages: list[BaseMessage]) -> Reply:
        if self.text is None:
            return self
        return replace(self, text=messages[0].content)

    @property
    def redactable(self) -> bool:
        return bool(self.text)
