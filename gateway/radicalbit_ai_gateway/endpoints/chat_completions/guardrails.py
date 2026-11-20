"""A chat completion's reply as the output guardrails read it."""

from __future__ import annotations

from dataclasses import dataclass, replace

from radicalbit_ai_gateway.llm.messages import (
    REASONING_KEY,
    AIMessage,
    BaseMessage,
    message_reasoning,
)


@dataclass(frozen=True)
class Reply:
    """A chat model's reply: its text and its reasoning. An empty reply is
    checked, not redacted.

    The reasoning rides on the message; only the guardrails that read
    reasoning see it.
    """

    text: str | None
    reasoning: str | None = None
    usage: dict | None = None
    skip = 0
    windowed = True

    def messages(self) -> list[BaseMessage]:
        # A reply with no text (a tool call) is read as empty text.
        return [
            AIMessage(
                content=self.text or '',
                usage_metadata=self.usage,
                additional_kwargs=(
                    {REASONING_KEY: self.reasoning} if self.reasoning else {}
                ),
            )
        ]

    def with_messages(self, messages: list[BaseMessage]) -> Reply:
        [message] = messages
        text = self.text
        if text is not None and isinstance(message.content, str):
            text = message.content
        reasoning = message_reasoning(message) if self.reasoning else self.reasoning
        return replace(self, text=text, reasoning=reasoning)

    @property
    def redactable(self) -> bool:
        return bool(self.text or self.reasoning)
