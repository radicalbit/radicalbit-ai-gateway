"""The events of a Responses API stream.

``NativeResponsesEvent`` is one event of an upstream stream, relayed as it
comes: the gateway only rewrites the response's ``model`` to the route name and
reads the final response, for accounting, output guardrails and the cache.
``response_events`` builds the event sequence OpenAI streams for a response the
gateway builds or replays (a soft block, a cache hit, a reply changed by a
guardrail).
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

# The event that ends a stream, by the final response's status.
_FINAL_EVENT_TYPES = {
    'completed': 'response.completed',
    'incomplete': 'response.incomplete',
    'failed': 'response.failed',
}
_FINAL_EVENTS = frozenset(_FINAL_EVENT_TYPES.values())
# Events whose payload carries the whole response object.
_RESPONSE_EVENTS = _FINAL_EVENTS | {
    'response.created',
    'response.queued',
    'response.in_progress',
}


# ── Upstream events ──────────────────────────────────────────────────────


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


# ── Events the gateway builds ───────────────────────────────────────────────────────────────


def sse(event: dict) -> str:
    data = json.dumps(event, ensure_ascii=False, separators=(',', ':'))
    return f'event: {event["type"]}\ndata: {data}\n\n'


class _Events:
    def __init__(self) -> None:
        self.frames: list[str] = []

    def add(self, type_: str, **fields: Any) -> None:
        self.frames.append(
            sse({'type': type_, **fields, 'sequence_number': len(self.frames)})
        )


def _added_item(item: dict) -> dict:
    """Show an output item as ``response.output_item.added`` does, before its content."""
    added = {**item, 'status': 'in_progress'} if 'status' in item else dict(item)
    if item.get('type') == 'message':
        added['content'] = []
    elif item.get('type') == 'reasoning':
        added['summary'] = []
    elif item.get('type') in _STREAMED_FIELDS:
        added[_STREAMED_FIELDS[item['type']]] = ''
    return added


# The field each item streams in deltas.
_STREAMED_FIELDS = {
    'function_call': 'arguments',
    'custom_tool_call': 'input',
    'mcp_call': 'arguments',
    'code_interpreter_call': 'code',
}
# The progress events a hosted tool call emits between its in_progress and
# completed events, besides its deltas.
_TOOL_PROGRESS = {
    'web_search_call': ['searching'],
    'file_search_call': ['searching'],
    'image_generation_call': ['generating'],
    'code_interpreter_call': ['interpreting'],
    'mcp_call': [],
    'mcp_list_tools': [],
}


def _tool_call_events(events: _Events, item: dict, where: dict) -> None:
    """Emit the events of a hosted tool call, as OpenAI streams them."""
    item_type = item['type']
    prefix = f'response.{item_type}'
    events.add(f'{prefix}.in_progress', **where)
    if item_type == 'mcp_call':
        arguments = item.get('arguments') or ''
        events.add('response.mcp_call_arguments.delta', **where, delta=arguments)
        events.add('response.mcp_call_arguments.done', **where, arguments=arguments)
    elif item_type == 'code_interpreter_call':
        code = item.get('code') or ''
        events.add('response.code_interpreter_call_code.delta', **where, delta=code)
        events.add('response.code_interpreter_call_code.done', **where, code=code)
    for progress in _TOOL_PROGRESS[item_type]:
        events.add(f'{prefix}.{progress}', **where)
    failed = item.get('status') == 'failed' and item_type.startswith('mcp_')
    events.add(f'{prefix}.{"failed" if failed else "completed"}', **where)


def _item_events(events: _Events, item: dict, output_index: int) -> None:
    item_id = item.get('id')
    item_type = item.get('type')
    events.add(
        'response.output_item.added', item=_added_item(item), output_index=output_index
    )
    if item_type == 'message':
        for content_index, part in enumerate(item.get('content') or []):
            where = {
                'content_index': content_index,
                'item_id': item_id,
                'output_index': output_index,
            }
            if part.get('type') == 'output_text':
                events.add(
                    'response.content_part.added', **where, part={**part, 'text': ''}
                )
                events.add(
                    'response.output_text.delta',
                    **where,
                    delta=part['text'],
                    logprobs=[],
                )
                events.add(
                    'response.output_text.done', **where, logprobs=[], text=part['text']
                )
            elif part.get('type') == 'refusal':
                events.add(
                    'response.content_part.added', **where, part={**part, 'refusal': ''}
                )
                events.add('response.refusal.delta', **where, delta=part['refusal'])
                events.add('response.refusal.done', **where, refusal=part['refusal'])
            else:
                events.add('response.content_part.added', **where, part=part)
            events.add('response.content_part.done', **where, part=part)
    elif item_type == 'function_call':
        where = {'item_id': item_id, 'output_index': output_index}
        events.add(
            'response.function_call_arguments.delta', **where, delta=item['arguments']
        )
        events.add(
            'response.function_call_arguments.done',
            **where,
            arguments=item['arguments'],
        )
    elif item_type == 'custom_tool_call':
        where = {'item_id': item_id, 'output_index': output_index}
        events.add(
            'response.custom_tool_call_input.delta', **where, delta=item['input']
        )
        events.add('response.custom_tool_call_input.done', **where, input=item['input'])
    elif item_type in _TOOL_PROGRESS:
        _tool_call_events(
            events, item, {'item_id': item_id, 'output_index': output_index}
        )
    elif item_type == 'reasoning':
        for summary_index, part in enumerate(item.get('summary') or []):
            where = {
                'item_id': item_id,
                'output_index': output_index,
                'summary_index': summary_index,
            }
            events.add(
                'response.reasoning_summary_part.added',
                **where,
                part={**part, 'text': ''},
            )
            events.add(
                'response.reasoning_summary_text.delta', **where, delta=part['text']
            )
            events.add(
                'response.reasoning_summary_text.done', **where, text=part['text']
            )
            events.add('response.reasoning_summary_part.done', **where, part=part)
    events.add('response.output_item.done', item=item, output_index=output_index)


def response_events(response: dict) -> list[str]:
    """Return the SSE frames OpenAI streams for ``response``, each text in one delta."""
    events = _Events()
    started = {
        **response,
        'status': 'in_progress',
        'completed_at': None,
        'output': [],
        'usage': None,
    }
    events.add('response.created', response=started)
    events.add('response.in_progress', response=started)
    for output_index, item in enumerate(response.get('output') or []):
        _item_events(events, item, output_index)
    final_type = _FINAL_EVENT_TYPES.get(response.get('status'), 'response.completed')
    events.add(final_type, response=response)
    return events.frames
