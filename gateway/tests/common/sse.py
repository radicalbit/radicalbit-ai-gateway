"""Read the first events of a server-sent stream whose loop never ends."""

import asyncio
import json
from unittest.mock import patch

import anyio
from httpx import ASGITransport, AsyncClient


class _EndOfStream(Exception):
    """Ends a stream after the events a test reads."""


async def first_events(
    app, url: str, *, sleep: str, interval: float, params=None, wanted=1
) -> list:
    """Open ``url`` on ``app`` and return the JSON payloads of its first
    ``wanted`` events.

    ``sleep`` is the stream's ``asyncio.sleep``: its wait of ``interval``
    seconds between events ends the stream after them, and every other wait
    (the SSE response's own) runs as usual. The transport keeps the events
    sent before that error.
    """
    real_sleep = asyncio.sleep
    calls = 0

    async def end_after(delay, *args, **kwargs):
        nonlocal calls
        if delay != interval:
            return await real_sleep(delay, *args, **kwargs)
        calls += 1
        if calls >= wanted:
            # FastAPI's SSE response sends from another task: let it write
            # the events already produced before the error ends the stream.
            for _ in range(3):
                await real_sleep(0)
            raise _EndOfStream
        return None

    payloads = []
    with patch(sleep, new=end_after):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url='http://test') as client:
            with anyio.fail_after(5):
                async with client.stream('GET', url, params=params) as response:
                    assert response.status_code == 200
                    assert 'text/event-stream' in response.headers['content-type']
                    async for line in response.aiter_lines():
                        if line.startswith('data:'):
                            payloads.append(json.loads(line[len('data:') :]))
                            if len(payloads) == wanted:
                                break
    assert len(payloads) == wanted
    return payloads
