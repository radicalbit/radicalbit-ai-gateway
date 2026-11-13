"""The events of a Messages API stream.

``relay_frame`` relays an upstream event. ``MessageCollector`` builds the
answer an upstream stream carries. ``message_events`` builds the event
sequence Anthropic streams for an answer the gateway builds or replays (a soft
block, a cache hit, an answer the output guardrails read first).
"""

from __future__ import annotations

import json

from radicalbit_ai_gateway.llm.messages_stream import (
    MESSAGE_DELTA,
    MESSAGE_START,
    stream_usage,
)


def sse(event: str, data: str) -> str:
    return f'event: {event}\ndata: {data}\n\n'


def relay_frame(event: str, data: str, route_name: str) -> str:
    """Return an upstream event as the client gets it.

    Only ``message_start`` changes: its ``model`` shows the route name. Every
    other event goes out byte for byte.
    """
    if event != MESSAGE_START:
        return sse(event, data)
    payload = json.loads(data)
    message = payload.get('message')
    if isinstance(message, dict):
        payload = {**payload, 'message': {**message, 'model': route_name}}
    return sse(event, json.dumps(payload, ensure_ascii=False, separators=(',', ':')))


# ── The answer of an upstream stream ─────────────────────────────────────


class MessageCollector:
    """Builds the message object an upstream stream carries, event by event.

    It is the reverse of ``message_events``. A delta of a type it does not
    know is left out.
    """

    def __init__(self) -> None:
        self._message: dict | None = None
        self._blocks: dict[int, dict] = {}
        # The JSON text of each tool use's input, as it comes.
        self._inputs: dict[int, str] = {}
        self._complete = False
        #: The usage read so far, as ``stream_usage`` reads it.
        self.usage: dict = {}
        #: The data of the upstream's ``error`` event, if one came.
        self.error: str | None = None

    def add(self, event: str, data: str) -> None:
        """Read one upstream event."""
        self.usage = stream_usage(event, data, self.usage)
        if event == 'error':
            self.error = data
        elif event == 'message_stop':
            self._complete = True
        elif event == MESSAGE_START:
            self._message = dict(json.loads(data).get('message') or {})
        elif event == MESSAGE_DELTA and self._message is not None:
            self._message.update(json.loads(data).get('delta') or {})
        elif event == 'content_block_start':
            payload = json.loads(data)
            self._blocks[payload['index']] = dict(payload['content_block'])
        elif event == 'content_block_delta':
            payload = json.loads(data)
            self._add_delta(payload['index'], payload.get('delta') or {})
        elif event == 'content_block_stop':
            index = json.loads(data)['index']
            if self._inputs.get(index):
                self._blocks[index]['input'] = json.loads(self._inputs[index])

    def _add_delta(self, index: int, delta: dict) -> None:
        block = self._blocks.get(index)
        if block is None:
            return
        delta_type = delta.get('type')
        if delta_type == 'text_delta':
            block['text'] = (block.get('text') or '') + delta.get('text', '')
        elif delta_type == 'input_json_delta':
            self._inputs[index] = self._inputs.get(index, '') + delta.get(
                'partial_json', ''
            )
        elif delta_type == 'thinking_delta':
            block['thinking'] = (block.get('thinking') or '') + delta.get(
                'thinking', ''
            )
        elif delta_type == 'signature_delta':
            block['signature'] = delta.get('signature', '')
        elif delta_type == 'citations_delta':
            block['citations'] = [*(block.get('citations') or []), delta['citation']]

    def message(self) -> dict | None:
        """Return the answer, or nothing when the stream ended before
        ``message_stop``.
        """
        if not self._complete or self._message is None:
            return None
        content = [self._blocks[index] for index in sorted(self._blocks)]
        return {**self._message, 'content': content, 'usage': self.usage}


# ── Events the gateway builds ────────────────────────────────────────────

# The blocks whose ``input`` is streamed as JSON text.
_TOOL_USE_TYPES = ('tool_use', 'server_tool_use', 'mcp_tool_use')
# The usage fields ``message_delta`` carries.
_DELTA_USAGE_FIELDS = (
    'input_tokens',
    'output_tokens',
    'cache_creation_input_tokens',
    'cache_read_input_tokens',
    'server_tool_use',
)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def _block_start_and_deltas(block: dict) -> tuple[dict, list[dict]]:
    """Return a content block as ``content_block_start`` shows it, before
    its content, and the deltas that fill it.

    A block of a type with no deltas starts whole.
    """
    block_type = block.get('type')
    if block_type == 'text':
        start = {**block, 'text': ''}
        deltas = [{'type': 'text_delta', 'text': block.get('text') or ''}]
        if isinstance(block.get('citations'), list):
            start['citations'] = []
            deltas += [
                {'type': 'citations_delta', 'citation': citation}
                for citation in block['citations']
            ]
        return start, deltas
    if block_type in _TOOL_USE_TYPES:
        delta = {
            'type': 'input_json_delta',
            'partial_json': _json(block.get('input') or {}),
        }
        return {**block, 'input': {}}, [delta]
    if block_type == 'thinking':
        deltas = []
        # A thinking block has no text when the request asked to omit it.
        if block.get('thinking'):
            deltas.append({'type': 'thinking_delta', 'thinking': block['thinking']})
        deltas.append(
            {'type': 'signature_delta', 'signature': block.get('signature') or ''}
        )
        return {**block, 'thinking': '', 'signature': ''}, deltas
    return block, []


def message_events(message: dict) -> list[str]:
    """Return the SSE frames Anthropic streams for ``message``, a complete
    answer: each block in one delta, a tool use with its full input.

    The input usage goes in ``message_start`` and the final usage in
    ``message_delta``, as upstream.
    """
    usage = message.get('usage') or {}
    frames: list[str] = []

    def add(type_: str, **fields: object) -> None:
        frames.append(sse(type_, _json({'type': type_, **fields})))

    add(
        MESSAGE_START,
        message={
            **message,
            'content': [],
            'stop_reason': None,
            'stop_sequence': None,
            'usage': {'input_tokens': 0, **usage, 'output_tokens': 0},
        },
    )
    for index, block in enumerate(message.get('content') or []):
        start, deltas = _block_start_and_deltas(block)
        add('content_block_start', index=index, content_block=start)
        for delta in deltas:
            add('content_block_delta', index=index, delta=delta)
        add('content_block_stop', index=index)
    add(
        MESSAGE_DELTA,
        delta={
            'stop_reason': message.get('stop_reason'),
            'stop_sequence': message.get('stop_sequence'),
        },
        usage={
            'output_tokens': 0,
            **{key: usage[key] for key in _DELTA_USAGE_FIELDS if key in usage},
        },
    )
    add('message_stop')
    return frames
