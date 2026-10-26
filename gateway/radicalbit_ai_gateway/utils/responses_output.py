"""The output side of a Responses API request.

``ResponsesOutput`` shows a response's text to the output guardrails as
messages and writes their changes back. A response the gateway builds or
replays (a soft block, a cache hit, a reply changed by a guardrail) is streamed
with ``response_events``, the event sequence OpenAI emits for it.
``serve_stream`` sends a stream to the client.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
import copy
import json
import logging
import re
import time
from typing import Any
import uuid

from radicalbit_ai_gateway.llm.messages import AIMessage
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import AppError, ModelInvokerUpstreamError

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)


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


# ── Events ───────────────────────────────────────────────────────────────


def sse(event: dict) -> str:
    data = json.dumps(event, ensure_ascii=False, separators=(',', ':'))
    return f'event: {event["type"]}\ndata: {data}\n\n'


_FINAL_EVENT_TYPES = {
    'completed': 'response.completed',
    'incomplete': 'response.incomplete',
    'failed': 'response.failed',
}


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


# ── Serving a stream ─────────────────────────────────────────────────────


def _error_body(exc: Exception) -> tuple[str, int]:
    """Return the HTTP error body and status of a request that failed before streaming."""
    if isinstance(exc, ModelInvokerUpstreamError):
        return json.dumps(exc.body), exc.status_code
    if isinstance(exc, AppError):
        error = {
            'message': exc.client_message,
            'type': 'model_invoker_error',
            'param': None,
            'code': exc.code or exc.status_code,
        }
        return json.dumps({'error': error}), exc.status_code
    logger.error('Unhandled error during streaming', exc_info=exc)
    error = {
        'message': 'Unhandled error during streaming',
        'type': 'internal_error',
        'param': None,
        'code': 500,
    }
    return json.dumps({'error': error}), 500


def _error_event(exc: Exception, sequence_number: int) -> str:
    body, status_code = _error_body(exc)
    error = json.loads(body).get('error') or {}
    return sse(
        {
            'type': 'error',
            'code': str(error.get('code') or status_code),
            'message': error.get('message') or 'Error during streaming',
            'param': error.get('param'),
            'sequence_number': sequence_number,
        }
    )


_SEQUENCE_NUMBER = re.compile(r'"sequence_number":\s*(\d+)')


def _next_sequence_number(frame: str, current: int) -> int:
    """Return the sequence number after ``frame``'s, read without parsing it."""
    numbers = _SEQUENCE_NUMBER.findall(frame)
    return int(numbers[-1]) + 1 if numbers else current


async def serve_stream(
    frames: AsyncIterator[str],
) -> AsyncIterator[str | tuple[str, int]]:
    """Send a Responses stream to the client.

    Nothing is sent before the first frame arrives, so a call that fails before
    streaming gets an HTTP error status (a ``(body, status)`` item, see
    ``StreamingResponseWithStatusCode``). After that, an error ends the stream
    with an ``error`` event.
    """
    try:
        first = await anext(frames)
    except StopAsyncIteration:
        return
    except Exception as exc:
        yield _error_body(exc)
        return

    sequence_number = _next_sequence_number(first, 0)
    try:
        yield first
        async for frame in frames:
            sequence_number = _next_sequence_number(frame, sequence_number)
            yield frame
    except Exception as exc:
        logger.warning('Responses stream failed after it started: %s', exc)
        yield _error_event(exc, sequence_number)
