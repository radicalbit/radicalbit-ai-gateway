"""A Responses API response as the output guardrails read it."""

from __future__ import annotations

from dataclasses import dataclass, replace

from radicalbit_ai_gateway.endpoints.responses.output import ResponsesOutput
from radicalbit_ai_gateway.llm.messages import BaseMessage


@dataclass(frozen=True)
class ResponsesReply:
    """The output message texts of a Responses API response."""

    output: ResponsesOutput
    items: list[BaseMessage]
    skip = 0
    windowed = True
    redactable = True

    @classmethod
    def of(cls, response: dict) -> ResponsesReply:
        output = ResponsesOutput(response)
        return cls(output, output.messages())

    def messages(self) -> list[BaseMessage]:
        return self.items

    def with_messages(self, messages: list[BaseMessage]) -> ResponsesReply:
        return replace(self, items=messages)

    def response(self) -> dict:
        """Return the response with the texts of this reply written in."""
        self.output.write_back(self.items)
        return self.output.response
