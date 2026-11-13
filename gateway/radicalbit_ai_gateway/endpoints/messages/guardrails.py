"""A Messages API request and answer as the guardrails read them.

The input guardrails read the request as a ``Conversation`` of the messages
``MessagesRequest`` shows. The output guardrails read the answer as a
``MessagesReply``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from traceloop.sdk.decorators import workflow

from radicalbit_ai_gateway.endpoints.messages.output import MessagesOutput, with_text
from radicalbit_ai_gateway.gateway_route.scope import RequestScope
from radicalbit_ai_gateway.guardrails.guardrails import GuardrailFlags
from radicalbit_ai_gateway.llm.messages import BaseMessage


@dataclass(frozen=True)
class MessagesReply:
    """The text of a Messages API answer."""

    output: MessagesOutput
    items: list[BaseMessage]
    skip = 0
    windowed = True
    redactable = True

    @classmethod
    def of(cls, message: dict) -> MessagesReply:
        output = MessagesOutput(message)
        return cls(output, output.messages())

    def messages(self) -> list[BaseMessage]:
        return self.items

    def with_messages(self, messages: list[BaseMessage]) -> MessagesReply:
        return replace(self, items=messages)

    def message(self) -> dict:
        """Return the answer with the texts of this reply written in."""
        self.output.write_back(self.items)
        return self.output.message


@workflow(name='apply_messages_output_guardrails')
async def screen_output(scope: RequestScope, message: dict) -> dict:
    """Apply the output guardrails to the text of an answer and return the
    answer to send. A soft block replaces the reply. The flags go on the
    scope.
    """
    if not scope.route.guardrails.has_output:
        return message
    screened = await scope.guardrails.screen_output(MessagesReply.of(message))
    if screened.soft_block:
        scope.flags |= GuardrailFlags(output_warned=True, output_blocked=True)
        return with_text(message, screened.soft_block.get_soft_block_message())
    scope.flags |= GuardrailFlags(output_warned=screened.flags.output_warned)
    return screened.payload.message()
