"""The events of an upstream Messages API stream, as the gateway reads them.

``stream_usage`` reads the usage the events carry. ``MessageBuilder`` builds
the message object the stream carries: the one builder, for the answer the
gateway screens and caches and for the call's span.
"""

from __future__ import annotations

import json

# The event that opens a stream and carries the message's ``model``.
MESSAGE_START = 'message_start'
# The event that carries the stop reason and the final output token count.
MESSAGE_DELTA = 'message_delta'


def stream_usage(event: str, data: str, usage: dict) -> dict:
    """Return ``usage`` updated with what an upstream event says about it."""
    if event == MESSAGE_START:
        message = json.loads(data).get('message') or {}
        return {**usage, **(message.get('usage') or {})}
    if event == MESSAGE_DELTA:
        return {**usage, **(json.loads(data).get('usage') or {})}
    return usage


class MessageBuilder:
    """Builds the message object an upstream stream carries, event by event.

    A delta of a type it does not know is left out.
    """

    def __init__(self) -> None:
        self._message: dict | None = None
        self._blocks: dict[int, dict] = {}
        # The JSON text of each tool use's input, as it comes.
        self._inputs: dict[int, str] = {}
        #: The usage read so far, as ``stream_usage`` reads it.
        self.usage: dict = {}
        #: The data of the upstream's ``error`` event, if one came.
        self.error: str | None = None

    @property
    def complete(self) -> bool:
        """Whether the stream gave the reason the message stopped. It comes
        after every content block: the message is whole, whatever ends the
        stream after it.
        """
        return bool(self._message and self._message.get('stop_reason'))

    @property
    def has_cut_off_input(self) -> bool:
        """Whether the JSON text of a tool use's input stopped half way (a
        stream cut by ``max_tokens``).
        """
        return any(_parsed(text) is None for text in self._inputs.values() if text)

    def add(self, event: str, data: str) -> None:
        """Read one upstream event."""
        self.usage = stream_usage(event, data, self.usage)
        if event == 'error':
            self.error = data
        elif event == MESSAGE_START:
            self._message = dict(json.loads(data).get('message') or {})
        elif self._message is None:
            return
        elif event == MESSAGE_DELTA:
            self._message.update(json.loads(data).get('delta') or {})
        elif event == 'content_block_start':
            payload = json.loads(data)
            self._blocks[payload.get('index', 0)] = dict(
                payload.get('content_block') or {}
            )
        elif event == 'content_block_delta':
            payload = json.loads(data)
            self._add_delta(payload.get('index', 0), payload.get('delta') or {})

    def _add_delta(self, index: int, delta: dict) -> None:
        block = self._blocks.setdefault(index, {})
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
        elif delta_type == 'citations_delta' and 'citation' in delta:
            block['citations'] = [*(block.get('citations') or []), delta['citation']]

    def message(self) -> dict | None:
        """Return the message built so far, with its content blocks in their
        order and the usage read; nothing before ``message_start``.

        A tool use whose input stopped half way keeps the input it started
        with: half a JSON text is not an input.
        """
        if self._message is None:
            return None
        content = []
        for index in sorted(self._blocks):
            block = self._blocks[index]
            tool_input = _parsed(self._inputs.get(index) or '')
            if tool_input is not None:
                block = {**block, 'input': tool_input}
            content.append(block)
        return {**self._message, 'content': content, 'usage': self.usage}


def _parsed(text: str) -> object | None:
    """Return the value of a JSON text, nothing when it is not whole."""
    try:
        return json.loads(text)
    except ValueError:
        return None
