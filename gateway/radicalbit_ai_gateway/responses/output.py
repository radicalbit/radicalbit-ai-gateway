"""The output side of a Responses API request.

``ResponsesOutput`` shows a response's text to the output guardrails as
messages and writes their changes back. ``gateway_response`` builds the
response of a reply no model gave (a soft block).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
import time
import uuid

from radicalbit_ai_gateway.llm.messages import (
    REASONING_KEY,
    REASONING_ONLY_KEY,
    AIMessage,
)

# ── Output text ──────────────────────────────────────────────────────────


def _text_parts(content: object, part_type: str) -> list[dict]:
    return [
        part
        for part in content or []
        if isinstance(part, dict)
        and part.get('type') == part_type
        and isinstance(part.get('text'), str)
    ]


def _reasoning_parts(item: dict) -> list[dict]:
    """Return the readable texts of a reasoning item: its summary and raw text."""
    return _text_parts(item.get('summary'), 'summary_text') + _text_parts(
        item.get('content'), 'reasoning_text'
    )


def _join(parts: list[dict]) -> str:
    return '\n'.join(part['text'] for part in parts if part['text'])


class Reasoning:
    """The readable reasoning of one or more reasoning items, read as one text.

    Encrypted reasoning is not readable and is never touched. Some providers
    (Ollama) copy the readable text in ``encrypted_content``: a changed text
    replaces that copy too, so a redacted text does not come back there.
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


@dataclass
class _Slot:
    """One assistant message of the output, and the reasoning before it.

    Reasoning with no message after it (a turn that ends in a tool call) is a
    slot of its own, with no text parts.
    """

    parts: list[dict] = field(default_factory=list)
    reasoning: Reasoning = field(default_factory=Reasoning)

    def message(self) -> AIMessage:
        additional_kwargs: dict = {}
        if reasoning := self.reasoning.text():
            additional_kwargs[REASONING_KEY] = reasoning
            if not self.parts:
                additional_kwargs[REASONING_ONLY_KEY] = True
        return AIMessage(
            content=''.join(part['text'] for part in self.parts),
            additional_kwargs=additional_kwargs,
        )


def _slots(response: dict) -> list[_Slot]:
    slots: list[_Slot] = []
    reasoning = Reasoning()
    for item in response.get('output') or []:
        if not isinstance(item, dict):
            continue
        if item.get('type') == 'reasoning':
            reasoning.add(item)
        elif item.get('type') == 'message':
            parts = _text_parts(item.get('content'), 'output_text')
            if parts:
                slots.append(_Slot(parts, reasoning))
                reasoning = Reasoning()
        elif reasoning:
            slots.append(_Slot([], reasoning))
            reasoning = Reasoning()
    if reasoning:
        slots.append(_Slot([], reasoning))
    return [slot for slot in slots if slot.parts or slot.reasoning]


class ResponsesOutput:
    """A copy of a response, with the text of each output message read as a message.

    The reasoning before a message rides on it, for the guardrails that read
    reasoning.
    """

    def __init__(self, response: dict):
        self.response = copy.deepcopy(response)
        self._slots = _slots(self.response)

    def messages(self) -> list[AIMessage]:
        return [slot.message() for slot in self._slots]

    def write_back(self, messages: list[AIMessage]) -> None:
        """Put the texts of ``messages``, as ``messages()`` returned them, in the response.

        A message's text goes in its first part; a guardrail changes a text as
        a whole. A changed part loses its annotations, whose offsets point in
        the old text, and its logprobs, which spell the old text out. Changed
        reasoning goes in the first reasoning part the same way.
        """
        for slot, message in zip(self._slots, messages, strict=True):
            reasoning = message.additional_kwargs.get(REASONING_KEY)
            if isinstance(reasoning, str):
                slot.reasoning.write(reasoning)
            parts = slot.parts
            if not parts:
                continue
            text = message.content if isinstance(message.content, str) else ''
            if text == ''.join(part['text'] for part in parts):
                continue
            for index, part in enumerate(parts):
                part['text'] = text if index == 0 else ''
                part['annotations'] = []
                if 'logprobs' in part:
                    part['logprobs'] = []


# ── Responses the gateway builds ─────────────────────────────────────────


def gateway_response_id(request_id: str) -> str:
    return f'resp_{request_id.replace("-", "")}'


def message_item(text: str) -> dict:
    return {
        'id': f'msg_{uuid.uuid4().hex}',
        'type': 'message',
        'status': 'completed',
        'content': [
            {'type': 'output_text', 'annotations': [], 'logprobs': [], 'text': text}
        ],
        'role': 'assistant',
    }


def gateway_response(request_id: str, route_name: str, body: dict, text: str) -> dict:
    """Build a completed response with one assistant message, echoing the request as
    OpenAI does. Nothing called a model, so its usage is zero.
    """
    now = int(time.time())
    reasoning = body.get('reasoning') or {}
    return {
        'id': gateway_response_id(request_id),
        'object': 'response',
        'created_at': now,
        'status': 'completed',
        'background': False,
        'completed_at': now,
        'error': None,
        'incomplete_details': None,
        'instructions': body.get('instructions'),
        'max_output_tokens': body.get('max_output_tokens'),
        'max_tool_calls': body.get('max_tool_calls'),
        'model': route_name,
        'output': [message_item(text)],
        'parallel_tool_calls': body.get('parallel_tool_calls', True),
        'previous_response_id': body.get('previous_response_id'),
        'prompt_cache_key': body.get('prompt_cache_key'),
        'reasoning': {
            'effort': reasoning.get('effort'),
            'summary': reasoning.get('summary'),
        },
        'safety_identifier': body.get('safety_identifier'),
        'service_tier': body.get('service_tier', 'default'),
        'store': False,
        'temperature': body.get('temperature'),
        'text': {'format': {'type': 'text'}, **(body.get('text') or {})},
        'tool_choice': body.get('tool_choice') or 'auto',
        'tools': body.get('tools') or [],
        'top_logprobs': body.get('top_logprobs'),
        'top_p': body.get('top_p'),
        'truncation': body.get('truncation', 'disabled'),
        'usage': {
            'input_tokens': 0,
            'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0},
            'output_tokens': 0,
            'output_tokens_details': {'reasoning_tokens': 0},
            'total_tokens': 0,
        },
        'user': body.get('user'),
        'metadata': body.get('metadata') or {},
    }


# ── Usage ────────────────────────────────────────────────────────────────


def usage_token_counts(usage: dict | None) -> tuple[int, int, int]:
    """Return ``(input, cached input, output)`` tokens of a Responses usage."""
    if not usage:
        return 0, 0, 0
    cached = (usage.get('input_tokens_details') or {}).get('cached_tokens') or 0
    return usage.get('input_tokens') or 0, cached, usage.get('output_tokens') or 0
