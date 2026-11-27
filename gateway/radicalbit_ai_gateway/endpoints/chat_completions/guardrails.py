"""A chat completion's reply as the output guardrails read it."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Generic, TypeVar

from radicalbit_ai_gateway.llm.messages import AIMessage, BaseMessage, UsageMetadata

#: A reply's text: None for a reply with no text (a tool call). Screening
#: keeps it: a text stays a text.
T = TypeVar('T', str, str | None)


@dataclass(frozen=True)
class Reply(Generic[T]):
    """A chat model's reply text. An empty reply is checked, not redacted."""

    text: T
    usage: UsageMetadata | None = None
    skip = 0
    windowed = True

    def messages(self) -> list[BaseMessage]:
        # A reply with no text (a tool call) is read as empty text.
        return [AIMessage(content=self.text or '', usage_metadata=self.usage)]

    def with_messages(self, messages: list[BaseMessage]) -> Reply[T]:
        if self.text is None:
            return self
        return replace(self, text=messages[0].text)

    @property
    def redactable(self) -> bool:
        return bool(self.text)
