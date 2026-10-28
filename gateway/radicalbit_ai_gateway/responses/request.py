"""A Responses API request as the gateway's policies see it.

The request goes upstream as the client sent it. The gateway's policies
(preprocessing plugins, routing, guardrails, limits, cache) read chat messages,
so ``ResponsesRequest`` shows the request's texts as messages and writes the
texts they change back into the body. Items without text (function calls,
reasoning, images...) are never touched.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
import re
from typing import Any

from radicalbit_ai_gateway.llm.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from radicalbit_ai_gateway.models.responses import ResponsesSettings
from radicalbit_ai_gateway.utils.content_utils import ContentUtils
from radicalbit_ai_gateway.utils.exceptions import (
    GatewayBadRequest,
    GatewayInternalError,
)

_MESSAGE_TYPES: dict[str, type[BaseMessage]] = {
    'user': HumanMessage,
    'assistant': AIMessage,
    'system': SystemMessage,
    'developer': SystemMessage,
}
_TEXT_PART_TYPES = frozenset({'input_text', 'output_text'})
# The outputs of the tools the client runs that carry text; a computer call's
# output is a screenshot.
_TOOL_OUTPUT_TYPES = frozenset(
    {
        'function_call_output',
        'custom_tool_call_output',
        'local_shell_call_output',
        'shell_call_output',
        'apply_patch_call_output',
    }
)
# Tools the client runs: any other tool type runs at the provider (hosted),
# except a shell in a local environment and a tool search the client executes.
_CLIENT_TOOL_TYPES = frozenset(
    {
        'function',
        'custom',
        'namespace',
        'local_shell',
        'apply_patch',
        'computer',
        'computer_use_preview',
    }
)
# A tool type's dated version (web_search_2025_08_26) is governed as the type.
_TOOL_TYPE_DATE = re.compile(r'_\d{4}_\d{2}_\d{2}$')
# Request fields that do not change the reply, left out of the cache key.
_UNCACHED_FIELDS = frozenset({'input', 'instructions', 'stream', 'stream_options'})


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
class _Slot:
    """The texts of the instructions or of one input item, read as one message."""

    message_type: type[BaseMessage]
    texts: list[_Text]
    tool_call_id: str = ''

    def message(self) -> BaseMessage:
        values = [text.get() for text in self.texts]
        content: str | list = (
            values[0]
            if len(values) == 1
            else [{'type': 'text', 'text': value} for value in values]
        )
        if self.message_type is ToolMessage:
            return ToolMessage(content=content, tool_call_id=self.tool_call_id)
        return self.message_type(content=content)


def _content_texts(item: dict, key: str) -> list[_Text]:
    content = item.get(key)
    if isinstance(content, str):
        return [_Text(item, key)]
    if isinstance(content, list):
        return [
            _Text(part, 'text')
            for part in content
            if isinstance(part, dict)
            and part.get('type') in _TEXT_PART_TYPES
            and isinstance(part.get('text'), str)
        ]
    return []


def _tool_output_texts(item: dict) -> list[_Text]:
    """Return the texts of a tool output item; a shell call's are its non-empty
    stdout and stderr.
    """
    if item.get('type') != 'shell_call_output':
        return _content_texts(item, 'output')
    return [
        _Text(chunk, stream)
        for chunk in item.get('output') or []
        if isinstance(chunk, dict)
        for stream in ('stdout', 'stderr')
        if isinstance(chunk.get(stream), str) and chunk[stream]
    ]


def _message_texts(content: Any) -> list[str]:
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        return [
            part['text']
            for part in content
            if isinstance(part, dict)
            and part.get('type') == 'text'
            and isinstance(part.get('text'), str)
        ]
    return []


def _input_items(body: dict) -> list:
    raw_input = body.get('input')
    return raw_input if isinstance(raw_input, list) else []


def _prompt_variable_texts(body: dict) -> list[_Text]:
    """Return the texts a reusable prompt's variables put in the prompt."""
    prompt = body.get('prompt')
    variables = prompt.get('variables') if isinstance(prompt, dict) else None
    if not isinstance(variables, dict):
        return []
    texts = []
    for name, value in variables.items():
        if isinstance(value, str):
            texts.append(_Text(variables, name))
        elif (
            isinstance(value, dict)
            and value.get('type') == 'input_text'
            and isinstance(value.get('text'), str)
        ):
            texts.append(_Text(value, 'text'))
    return texts


def _slots(body: dict) -> list[_Slot]:
    slots = []
    if isinstance(body.get('instructions'), str):
        slots.append(_Slot(SystemMessage, [_Text(body, 'instructions')]))
    if variable_texts := _prompt_variable_texts(body):
        slots.append(_Slot(HumanMessage, variable_texts))
    if isinstance(body.get('input'), str):
        slots.append(_Slot(HumanMessage, [_Text(body, 'input')]))
    for item in _input_items(body):
        if not isinstance(item, dict):
            continue
        item_type = item.get('type', 'message')
        if item_type == 'message':
            message_type = _MESSAGE_TYPES.get(item.get('role'))
            texts = _content_texts(item, 'content')
            if message_type and texts:
                slots.append(_Slot(message_type, texts))
        elif item_type in _TOOL_OUTPUT_TYPES:
            texts = _tool_output_texts(item)
            if texts:
                # A local shell call's output names its call by ``id``.
                call_id = item.get('call_id') or item.get('id') or ''
                slots.append(_Slot(ToolMessage, texts, call_id))
    return slots


def _is_user_message(item: Any) -> bool:
    return (
        isinstance(item, dict)
        and item.get('type', 'message') == 'message'
        and item.get('role') == 'user'
    )


class ResponsesRequest:
    """A copy of a Responses request body, with its texts read as chat messages."""

    def __init__(self, body: dict):
        self.body = copy.deepcopy(body)
        self._slots = _slots(self.body)

    def messages(self) -> list[BaseMessage]:
        """Read the instructions, then each input item that has text, as one message."""
        return [slot.message() for slot in self._slots]

    def write_back(self, messages: list[BaseMessage]) -> None:
        """Put the texts of ``messages``, as ``messages()`` returned them, in the body.

        Policies may change the texts, never the messages' structure.
        """
        if len(messages) != len(self._slots):
            raise GatewayInternalError(
                'The messages of a Responses request changed in number'
            )
        for slot, message in zip(self._slots, messages, strict=True):
            texts = _message_texts(message.content)
            if len(texts) != len(slot.texts):
                raise GatewayInternalError(
                    'The text parts of a Responses request changed in number'
                )
            for place, text in zip(slot.texts, texts, strict=True):
                place.set(text)

    def insert_prompt(self, prompt: BaseMessage, role: str) -> None:
        """Put the route's configured prompt first in the input."""
        if isinstance(self.body.get('input'), str):
            self.body['input'] = [
                {'type': 'message', 'role': 'user', 'content': self.body['input']}
            ]
        self.body['input'] = [
            {
                'type': 'message',
                'role': role,
                'content': ContentUtils.extract_text_content(prompt.content),
            },
            *_input_items(self.body),
        ]


def references_stored_state(body: dict) -> bool:
    """Whether the request continues state stored at the provider.

    Only the provider account that stored it can serve such a request.
    """
    if body.get('previous_response_id') or body.get('conversation'):
        return True
    return any(
        isinstance(item, dict) and item.get('type') == 'item_reference'
        for item in _input_items(body)
    )


def check_supported(body: dict) -> None:
    """Refuse the Responses API features the gateway does not serve yet."""
    if body.get('background'):
        # A background response is read later from GET /v1/responses/{id}.
        raise GatewayBadRequest(
            'Background mode is not supported by the gateway yet: '
            'send the request with background false'
        )


def hosted_tool_type(tool: Any) -> str | None:
    """Return the type of a tool the provider runs, ``None`` for one the client runs."""
    tool_type = tool.get('type') if isinstance(tool, dict) else None
    if tool_type in _CLIENT_TOOL_TYPES:
        return None
    if tool_type == 'shell' and (tool.get('environment') or {}).get('type') in (
        None,
        'local',
    ):
        return None
    if tool_type == 'tool_search' and tool.get('execution') == 'client':
        return None
    return _TOOL_TYPE_DATE.sub('', tool_type) if isinstance(tool_type, str) else None


def apply_governance(
    body: dict, settings: ResponsesSettings | None, route_name: str
) -> None:
    """Enforce the route's Responses API settings on ``body``, in place."""
    if settings is None:
        return

    if settings.allowed_hosted_tools is not None:
        for tool in body.get('tools') or []:
            tool_type = hosted_tool_type(tool)
            if tool_type is not None and tool_type not in settings.allowed_hosted_tools:
                raise GatewayBadRequest(
                    f'The hosted tool {tool_type} is not allowed on route {route_name}'
                )

    if settings.force_store_false:
        if references_stored_state(body):
            raise GatewayBadRequest(
                f'Route {route_name} does not store responses: send the '
                'conversation context in input instead of previous_response_id, '
                'conversation or item_reference items'
            )
        body['store'] = False
        if isinstance(body.get('input'), list):
            # Reasoning sent by id only is read from the provider's storage,
            # where nothing is kept on this route.
            body['input'] = [
                item
                for item in body['input']
                if not (
                    isinstance(item, dict)
                    and item.get('type') == 'reasoning'
                    and not item.get('encrypted_content')
                )
            ]


def last_user_text(body: dict) -> str:
    """Return the text of the request's last user message."""
    if isinstance(body.get('input'), str):
        return body['input']
    for item in reversed(_input_items(body)):
        if _is_user_message(item):
            return ' '.join(text.get() for text in _content_texts(item, 'content'))
    return ''


def cache_signature(body: dict) -> dict | None:
    """Return what identifies a request's reply in the cache, as for chat completions:
    the input from the last user message on, and the parameters.

    ``None`` when the request has no user message.
    """
    raw_input = body.get('input')
    if isinstance(raw_input, str):
        turn: Any = raw_input
    else:
        items = _input_items(body)
        last_user = next(
            (
                index
                for index in range(len(items) - 1, -1, -1)
                if _is_user_message(items[index])
            ),
            None,
        )
        if last_user is None:
            return None
        turn = items[last_user:]
    params = {key: value for key, value in body.items() if key not in _UNCACHED_FIELDS}
    return {'input': turn, 'params': params}


def without_reasoning(body: dict) -> dict:
    """Drop the reasoning items, which only the model that produced them can resume."""
    items: Any = body.get('input')
    if not isinstance(items, list):
        return body
    return {
        **body,
        'input': [
            item
            for item in items
            if not (isinstance(item, dict) and item.get('type') == 'reasoning')
        ],
    }
