"""How a Responses API request is cached: what keys it, and the response
as stored.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import time

from openai.types.completion_usage import CompletionUsage

from radicalbit_ai_gateway.caching.route_cache import Hit
from radicalbit_ai_gateway.endpoints.responses.request import (
    cache_signature,
    last_user_text,
)
from radicalbit_ai_gateway.llm.usage import responses_token_counts


@dataclass(frozen=True)
class ResponsesEntry:
    """A Responses API request, keyed on its ``cache_signature``."""

    body: dict

    lookup_spans = ('lookup_responses_cache',)
    get_spans = ()
    exact_only = False
    hit_log = None

    def signature(self) -> str | None:
        signature = cache_signature(self.body)
        if signature is None:
            return None
        return f'responses:{json.dumps(signature, ensure_ascii=False, sort_keys=True)}'

    def text(self) -> str:
        return last_user_text(self.body)

    def parse(self, raw: str) -> dict | None:
        """Return a cached response object; a chat completion is a miss.

        A semantic cache shares a route's entries between endpoints.
        """
        try:
            cached = json.loads(raw)
        except ValueError:
            return None
        if not isinstance(cached, dict) or cached.get('object') != 'response':
            return None
        return cached

    def dump(self, value: dict) -> str:
        return json.dumps(value)

    def hit(self, value: dict) -> Hit:
        input_tokens, _, output_tokens = responses_token_counts(value.get('usage'))
        return Hit(
            value.get('model', ''),
            CompletionUsage(
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
            ),
        )

    def refresh(self, value: dict) -> dict:
        now = int(time.time())
        return {
            **value,
            'created_at': now,
            'completed_at': now if value.get('completed_at') else None,
        }

    def store_spans(self, value) -> tuple[str, ...]:
        return ()
