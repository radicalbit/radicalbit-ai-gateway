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

from radicalbit_ai_gateway.endpoints.responses.reasoning import (
    Reasoning,
    assistant_message,
    text_parts,
)
from radicalbit_ai_gateway.llm.messages import AIMessage

# ── Output text ──────────────────────────────────────────────────────────


@dataclass
class _Slot:
    """One assistant message of the output, and the reasoning before it.

    Reasoning with no message after it (a turn that ends in a tool call) is a
    slot of its own, with no text parts.
    """

    parts: list[dict] = field(default_factory=list)
    reasoning: Reasoning = field(default_factory=Reasoning)

    def message(self) -> AIMessage:
        return assistant_message(
            ''.join(part['text'] for part in self.parts),
            self.reasoning,
            has_text=bool(self.parts),
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
            parts = text_parts(item.get('content'), 'output_text')
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
            slot.reasoning.write_from(message)
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
