"""The upstream side of a Responses API request.

The request body is forwarded as the gateway's policies left it and the
upstream events are relayed as they come. The gateway only rewrites the
response's ``model`` to the route name and reads the final response, for
accounting, output guardrails and the cache.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

# Events whose payload carries the whole response object.
_RESPONSE_EVENTS = frozenset(
    {
        'response.created',
        'response.queued',
        'response.in_progress',
        'response.completed',
        'response.incomplete',
        'response.failed',
    }
)
_FINAL_EVENTS = frozenset(
    {'response.completed', 'response.incomplete', 'response.failed'}
)


@dataclass
class NativeResponsesEvent:
    """One upstream stream event; ``payload`` is parsed only for response events."""

    event: str
    data: str
    payload: dict | None = None

    @classmethod
    def parse(cls, event: str, data: str) -> NativeResponsesEvent:
        payload = json.loads(data) if event in _RESPONSE_EVENTS else None
        return cls(event=event, data=data, payload=payload)

    @property
    def is_final(self) -> bool:
        return self.event in _FINAL_EVENTS

    @property
    def response(self) -> dict | None:
        if self.payload is None:
            return None
        return self.payload.get('response')

    @property
    def usage(self) -> dict | None:
        return (self.response or {}).get('usage')

    def to_sse(self, route_name: str) -> str:
        data = self.data
        if isinstance(self.response, dict):
            payload = {
                **self.payload,
                'response': {**self.response, 'model': route_name},
            }
            data = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
        return f'event: {self.event}\ndata: {data}\n\n'


def usage_token_counts(usage: dict | None) -> tuple[int, int, int]:
    """Return ``(input, cached input, output)`` tokens of a Responses usage."""
    if not usage:
        return 0, 0, 0
    cached = (usage.get('input_tokens_details') or {}).get('cached_tokens') or 0
    return usage.get('input_tokens') or 0, cached, usage.get('output_tokens') or 0


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
