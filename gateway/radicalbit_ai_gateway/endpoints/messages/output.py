"""The output side of a Messages API request.

``MessagesOutput`` shows an answer's text to the output guardrails as one
message and writes their changes back.
``gateway_message`` builds the answer of a reply no model gave (a soft block);
``with_text`` puts the gateway's text in place of a model's reply.
"""

from __future__ import annotations

import copy

from radicalbit_ai_gateway.endpoints.messages.request import is_text_block
from radicalbit_ai_gateway.llm.messages import AIMessage, BaseMessage
from radicalbit_ai_gateway.utils.exceptions import GatewayInternalError

# ── Output text ──────────────────────────────────────────────────────────


class MessagesOutput:
    """A copy of a Messages answer, with its ``text`` blocks read as one message.

    Blocks without text (thinking, tool use...) are never touched.
    """

    def __init__(self, message: dict):
        self.message = copy.deepcopy(message)
        content = self.message.get('content')
        self._blocks = (
            [block for block in content if is_text_block(block)]
            if isinstance(content, list)
            else []
        )

    def messages(self) -> list[AIMessage]:
        """Return the answer's text as one message, or nothing when it has none.

        One text block reads as a string, many as text parts, as the request's
        messages do.
        """
        if not self._blocks:
            return []
        texts = [block['text'] for block in self._blocks]
        content: str | list = (
            texts[0]
            if len(texts) == 1
            else [{'type': 'text', 'text': text} for text in texts]
        )
        return [AIMessage(content=content)]

    def write_back(self, messages: list[BaseMessage]) -> None:
        """Put the texts of ``messages``, as ``messages()`` returned them, in the answer.

        Each text goes back in its own block. Block order, block types and
        every other field stay as they were.
        """
        if len(messages) != (1 if self._blocks else 0):
            raise GatewayInternalError(
                'The messages of a Messages answer changed in number'
            )
        if not messages:
            return
        content = messages[0].content
        texts = (
            [content]
            if isinstance(content, str)
            else [block['text'] for block in content if is_text_block(block)]
        )
        if len(texts) != len(self._blocks):
            raise GatewayInternalError(
                'The text parts of a Messages answer changed in number'
            )
        for block, text in zip(self._blocks, texts, strict=True):
            block['text'] = text


# ── Answers the gateway builds ───────────────────────────────────────────


def _gateway_message_id(request_id: str) -> str:
    return f'msg_{request_id.replace("-", "")}'


def _text_block(text: str) -> dict:
    return {'type': 'text', 'text': text}


def gateway_message(request_id: str, route_name: str, text: str) -> dict:
    """Build a complete answer with one text block. Nothing called a model,
    so its usage is zero.
    """
    return {
        'id': _gateway_message_id(request_id),
        'type': 'message',
        'role': 'assistant',
        'model': route_name,
        'content': [_text_block(text)],
        'stop_reason': 'end_turn',
        'stop_sequence': None,
        'usage': {
            'input_tokens': 0,
            'output_tokens': 0,
            'cache_creation_input_tokens': 0,
            'cache_read_input_tokens': 0,
        },
    }


def with_text(message: dict, text: str) -> dict:
    """Return ``message`` with ``text`` as its whole reply (an output soft
    block). The model was called, so its id and usage stay.
    """
    return {
        **message,
        'content': [_text_block(text)],
        'stop_reason': 'end_turn',
        'stop_sequence': None,
    }
