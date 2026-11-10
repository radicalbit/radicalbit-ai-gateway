"""The events of a Responses API stream.

``response_events`` builds the event sequence OpenAI streams for a response the
gateway builds or replays (a soft block, a cache hit, a reply changed by a
guardrail).
"""

from __future__ import annotations

import json
from typing import Any

from radicalbit_ai_gateway.llm.responses_stream import FINAL_EVENT_TYPES

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
    final_type = FINAL_EVENT_TYPES.get(response.get('status'), 'response.completed')
    events.add(final_type, response=response)
    return events.frames
