"""The output side of a Responses API request.

``ResponsesOutput`` shows a response's text to the output guardrails as
messages and writes their changes back. ``gateway_response`` builds the
response of a reply no model gave (a soft block).
"""

from __future__ import annotations

import copy
import time
import uuid

from radicalbit_ai_gateway.llm.messages import AIMessage

# ── Output text ──────────────────────────────────────────────────────────


def _output_text_parts(response: dict) -> list[list[dict]]:
    """Return the ``output_text`` parts of each message item of the output."""
    return [
        [
            part
            for part in item.get('content') or []
            if isinstance(part, dict)
            and part.get('type') == 'output_text'
            and isinstance(part.get('text'), str)
        ]
        for item in response.get('output') or []
        if isinstance(item, dict) and item.get('type') == 'message'
    ]


class ResponsesOutput:
    """A copy of a response, with the text of each output message read as a message."""

    def __init__(self, response: dict):
        self.response = copy.deepcopy(response)
        self._parts = [parts for parts in _output_text_parts(self.response) if parts]

    def messages(self) -> list[AIMessage]:
        return [
            AIMessage(content=''.join(part['text'] for part in parts))
            for parts in self._parts
        ]

    def write_back(self, messages: list[AIMessage]) -> None:
        """Put the texts of ``messages``, as ``messages()`` returned them, in the response.

        A message's text goes in its first part; a guardrail changes a text as
        a whole. A changed part loses its annotations, whose offsets point in
        the old text, and its logprobs, which spell the old text out.
        """
        for parts, message in zip(self._parts, messages, strict=True):
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
