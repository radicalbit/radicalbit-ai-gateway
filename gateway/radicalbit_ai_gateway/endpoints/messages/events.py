"""The events of a Messages API stream, as the gateway relays them."""

from __future__ import annotations

import json

from radicalbit_ai_gateway.llm.messages_stream import MESSAGE_START


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
