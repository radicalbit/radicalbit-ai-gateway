"""The events of an upstream Responses API stream.

``NativeResponsesEvent`` is one event, relayed as it comes: the gateway only
rewrites the response's ``model`` to the route name and reads the final
response, for accounting, output guardrails and the cache.
"""

from __future__ import annotations

from dataclasses import dataclass
import json

# The event that ends a stream, by the final response's status.
FINAL_EVENT_TYPES = {
    'completed': 'response.completed',
    'incomplete': 'response.incomplete',
    'failed': 'response.failed',
}
_FINAL_EVENTS = frozenset(FINAL_EVENT_TYPES.values())
# Events whose payload carries the whole response object.
_RESPONSE_EVENTS = _FINAL_EVENTS | {
    'response.created',
    'response.queued',
    'response.in_progress',
}


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
