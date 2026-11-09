"""An Anthropic Messages API request as the gateway's policies see it.

The request goes upstream as the client sent it. The gateway's policies
(preprocessing plugins, routing, and later guardrails, limits and cache) read
chat messages, so ``MessagesRequest`` shows the request's texts as messages and
writes the texts they change back into the body. Blocks without text (images,
documents, tool use, thinking...) are never touched.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from typing_extensions import Required, TypedDict

from radicalbit_ai_gateway.llm.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from radicalbit_ai_gateway.utils.exceptions import GatewayInternalError

_MESSAGE_TYPES: dict[str, type[BaseMessage]] = {
    'user': HumanMessage,
    'assistant': AIMessage,
}


class MessageCreateParams(TypedDict, total=False):
    """The shape of a Messages request the gateway needs.

    It only validates the request: the body goes upstream with every field the
    client sent.
    """

    model: Required[str]
    """Gateway route name used to select the backend model."""

    messages: Required[list[dict[str, Any]]]
    """The conversation, as Anthropic's message objects."""

    max_tokens: Required[int]
    """The most tokens the model may generate."""

    system: str | list[dict[str, Any]] | None
    """The system prompt, a string or a list of text blocks."""

    stream: bool | None
    """Whether to stream the response."""


@dataclass
class _Text:
    """Where one text of the request lives: ``container[key]``."""

    container: dict
    key: str

    def get(self) -> str:
        return self.container[self.key]

    def set(self, text: str) -> None:
        self.container[self.key] = text


@dataclass
class _MessageTexts:
    """The texts of the system prompt or of one message, read as one message."""

    message_type: type[BaseMessage]
    texts: list[_Text]

    def message(self) -> BaseMessage:
        values = [text.get() for text in self.texts]
        content: str | list = (
            values[0]
            if len(values) == 1
            else [{'type': 'text', 'text': value} for value in values]
        )
        return self.message_type(content=content)


def _is_text_block(block: Any) -> bool:
    return (
        isinstance(block, dict)
        and block.get('type') == 'text'
        and isinstance(block.get('text'), str)
    )


def _content_texts(container: dict, key: str) -> list[_Text]:
    content = container.get(key)
    if isinstance(content, str):
        return [_Text(container, key)]
    if isinstance(content, list):
        return [_Text(block, 'text') for block in content if _is_text_block(block)]
    return []


def _texts_of(content: Any) -> list[str]:
    """Return the texts of a chat message's content."""
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        return [block['text'] for block in content if _is_text_block(block)]
    return []


def _all_message_texts(body: dict) -> list[_MessageTexts]:
    all_texts = []
    if system_texts := _content_texts(body, 'system'):
        all_texts.append(_MessageTexts(SystemMessage, system_texts))
    messages = body.get('messages')
    for message in messages if isinstance(messages, list) else []:
        if not isinstance(message, dict):
            continue
        message_type = _MESSAGE_TYPES.get(message.get('role'))
        texts = _content_texts(message, 'content')
        if message_type and texts:
            all_texts.append(_MessageTexts(message_type, texts))
    return all_texts


class MessagesRequest:
    """A copy of a Messages request body, with its texts read as chat messages."""

    def __init__(self, body: dict):
        self.body = copy.deepcopy(body)
        self._message_texts = _all_message_texts(self.body)

    def messages(self) -> list[BaseMessage]:
        """Read the system prompt, then each message that has text, as one message."""
        return [texts.message() for texts in self._message_texts]

    def write_back(self, messages: list[BaseMessage]) -> None:
        """Put the texts of ``messages``, as ``messages()`` returned them, in the body.

        Policies may change the texts, never the messages' structure.
        """
        if len(messages) != len(self._message_texts):
            raise GatewayInternalError(
                'The messages of a Messages request changed in number'
            )
        for message_texts, message in zip(self._message_texts, messages, strict=True):
            texts = _texts_of(message.content)
            if len(texts) != len(message_texts.texts):
                raise GatewayInternalError(
                    'The text parts of a Messages request changed in number'
                )
            for place, text in zip(message_texts.texts, texts, strict=True):
                place.set(text)

    def insert_system_prompt(self, prompt: BaseMessage) -> None:
        """Put the route's configured prompt first in the system prompt.

        A prompt sent as blocks (with ``cache_control``, say) keeps its blocks.
        """
        content = prompt.content
        blocks = (
            [{'type': 'text', 'text': content}]
            if isinstance(content, str)
            else [block for block in content if isinstance(block, dict)]
        )
        system = self.body.get('system')
        if not system:
            self.body['system'] = content if isinstance(content, str) else blocks
        elif isinstance(system, str):
            self.body['system'] = [*blocks, {'type': 'text', 'text': system}]
        else:
            self.body['system'] = [*blocks, *system]
