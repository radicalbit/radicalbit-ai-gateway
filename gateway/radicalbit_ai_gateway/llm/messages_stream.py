"""The events of an upstream Messages API stream, as the gateway reads them."""

from __future__ import annotations

import json

# The event that opens a stream and carries the message's ``model``.
MESSAGE_START = 'message_start'
# The event that carries the final output token count.
MESSAGE_DELTA = 'message_delta'


def stream_usage(event: str, data: str, usage: dict) -> dict:
    """Return ``usage`` updated with what an upstream event says about it."""
    if event == MESSAGE_START:
        message = json.loads(data).get('message') or {}
        return {**usage, **(message.get('usage') or {})}
    if event == MESSAGE_DELTA:
        return {**usage, **(json.loads(data).get('usage') or {})}
    return usage
