"""How a Messages API request is cached: what keys it, and the answer as
stored.
"""

from __future__ import annotations

from dataclasses import dataclass
import json

from openai.types.completion_usage import CompletionUsage

from radicalbit_ai_gateway.caching.route_cache import Hit
from radicalbit_ai_gateway.llm.usage import messages_token_counts

# The fields that do not change the answer: how it is sent, and who asked.
_UNCACHED_FIELDS = ('stream', 'metadata')
# The stop reasons of a complete answer. A ``max_tokens`` answer is cut off,
# and a paused or refused turn is not the answer of the request.
_COMPLETE_STOP_REASONS = ('end_turn', 'stop_sequence', 'tool_use')


def is_complete(message: dict) -> bool:
    """Tell whether ``message`` is an answer the cache keeps."""
    return message.get('stop_reason') in _COMPLETE_STOP_REASONS


def last_user_text(body: dict) -> str:
    """Return the text of the request's last user message, empty when it has
    none (a turn of tool results only, say).
    """
    messages = body.get('messages')
    for message in reversed(messages if isinstance(messages, list) else []):
        if not isinstance(message, dict) or message.get('role') != 'user':
            continue
        content = message.get('content')
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return ''
        return ' '.join(
            block['text']
            for block in content
            if isinstance(block, dict)
            and block.get('type') == 'text'
            and isinstance(block.get('text'), str)
        )
    return ''


@dataclass(frozen=True)
class MessagesEntry:
    """A Messages API request, keyed on its whole body as it goes upstream."""

    body: dict

    lookup_spans = ('lookup_messages_cache',)
    get_spans = ()
    exact_only = False
    hit_log = None

    def signature(self) -> str:
        params = {
            key: value
            for key, value in self.body.items()
            if key not in _UNCACHED_FIELDS
        }
        return f'messages:{json.dumps(params, ensure_ascii=False, sort_keys=True)}'

    def text(self) -> str:
        return last_user_text(self.body)

    def parse(self, raw: str) -> dict | None:
        """Return a cached message object; a chat completion or a Responses
        API response is a miss.

        A semantic cache shares a route's entries between endpoints.
        """
        try:
            cached = json.loads(raw)
        except ValueError:
            return None
        if not isinstance(cached, dict) or cached.get('type') != 'message':
            return None
        return cached

    def dump(self, value: dict) -> str:
        return json.dumps(value)

    def hit(self, value: dict) -> Hit:
        input_tokens, output_tokens = messages_token_counts(value.get('usage'))
        return Hit(
            value.get('model', ''),
            CompletionUsage(
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
            ),
        )

    def refresh(self, value: dict) -> dict:
        return value

    def store_spans(self, value) -> tuple[str, ...]:
        return ()
