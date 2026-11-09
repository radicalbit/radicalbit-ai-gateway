"""The events of a Messages API stream, as the gateway relays them."""

from __future__ import annotations

import json

# The event that opens a stream and carries the message's ``model``.
MESSAGE_START = 'message_start'
# The event that carries the final output token count.
MESSAGE_DELTA = 'message_delta'


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


def stream_usage(event: str, data: str, usage: dict) -> dict:
    """Return ``usage`` updated with what an upstream event says about it."""
    if event == MESSAGE_START:
        message = json.loads(data).get('message') or {}
        return {**usage, **(message.get('usage') or {})}
    if event == MESSAGE_DELTA:
        return {**usage, **(json.loads(data).get('usage') or {})}
    return usage
