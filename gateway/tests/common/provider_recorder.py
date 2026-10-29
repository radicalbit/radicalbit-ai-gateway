"""Network recorder for provider tests.

Patches the network transports of ``httpx``, ``httpx2`` (used by the openai and
anthropic SDKs) and ``httpx-aiohttp`` so every request a provider SDK makes is
recorded and answered from a queue of canned responses. Patching the transport
rather than the client keeps the client's own header and auth handling in the
recorded request. Raw sockets are blocked so a missed hook fails loudly instead
of reaching a real provider.

Recorded requests are normalized so they compare equal across SDK versions:
transport and telemetry headers are dropped and JSON bodies are parsed.
"""

from collections import deque
from dataclasses import dataclass, field
import json
import socket
from typing import Any
from unittest.mock import patch
from urllib.parse import parse_qsl, urlsplit

import httpx
import httpx2
from httpx_aiohttp.transport import AiohttpTransport

# Headers that carry SDK/runtime telemetry or transport details, not payload.
_DROPPED_HEADERS = {
    'user-agent',
    'content-length',
    'accept-encoding',
    'connection',
    'host',
    'x-goog-api-client',
    'idempotency-key',
}
_DROPPED_HEADER_PREFIXES = ('x-stainless-',)


@dataclass
class CannedResponse:
    status: int = 200
    json_body: Any = None
    sse_events: list[Any] | None = None
    sse_format: str = 'data'  # 'data' or 'anthropic' (event: + data:)
    headers: dict[str, str] = field(default_factory=dict)

    def to_response(self, request):
        lib = httpx2 if isinstance(request, httpx2.Request) else httpx
        if self.sse_events is not None:
            lines = []
            for event in self.sse_events:
                if self.sse_format == 'anthropic':
                    lines.append(f'event: {event["type"]}\n')
                    lines.append(f'data: {json.dumps(event)}\n\n')
                elif event == '[DONE]':
                    lines.append('data: [DONE]\n\n')
                else:
                    lines.append(f'data: {json.dumps(event)}\n\n')
            return lib.Response(
                self.status,
                headers={'content-type': 'text/event-stream', **self.headers},
                content=''.join(lines).encode(),
                request=request,
            )
        return lib.Response(
            self.status,
            headers={'content-type': 'application/json', **self.headers},
            content=json.dumps(self.json_body).encode(),
            request=request,
        )


def normalize_request(request) -> dict[str, Any]:
    url = urlsplit(str(request.url))
    headers = {
        k.lower(): v
        for k, v in request.headers.items()
        if k.lower() not in _DROPPED_HEADERS
        and not k.lower().startswith(_DROPPED_HEADER_PREFIXES)
    }
    raw = request.content
    body: Any
    try:
        body = json.loads(raw) if raw else None
    except ValueError:
        body = raw.decode(errors='replace')
    return {
        'method': request.method,
        'url': f'{url.scheme}://{url.netloc}{url.path}',
        'query': sorted(parse_qsl(url.query)),
        'headers': dict(sorted(headers.items())),
        'body': body,
    }


class ProviderRecorder:
    def __init__(self, responses: list[CannedResponse]):
        self._responses = deque(responses)
        self.requests: list[dict[str, Any]] = []

    def _answer(self, request):
        self.requests.append(normalize_request(request))
        if not self._responses:
            raise AssertionError(
                f'Unexpected provider request: {request.method} {request.url}'
            )
        return self._responses.popleft().to_response(request)

    def __enter__(self):
        """Install the transport hooks and the socket block."""
        recorder = self

        async def handle_async(self, request):
            await request.aread()
            return recorder._answer(request)

        def handle_sync(self, request):
            return recorder._answer(request)

        def blocked(*args, **kwargs):
            raise AssertionError('Real network access attempted in golden test')

        self._patches = [
            patch.object(
                httpx.AsyncHTTPTransport, 'handle_async_request', handle_async
            ),
            patch.object(httpx.HTTPTransport, 'handle_request', handle_sync),
            patch.object(AiohttpTransport, 'handle_async_request', handle_async),
            patch.object(
                httpx2.AsyncHTTPTransport, 'handle_async_request', handle_async
            ),
            patch.object(httpx2.HTTPTransport, 'handle_request', handle_sync),
            patch.object(socket.socket, 'connect', blocked),
            patch.object(socket.socket, 'connect_ex', blocked),
            # google-genai prefers raw aiohttp when installed; force its httpx
            # path so the wire payload is captured by the same hook.
            patch('google.genai._api_client.has_aiohttp', False),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        """Remove every hook installed by ``__enter__``."""
        for p in reversed(self._patches):
            p.stop()
        return False

    @property
    def unused(self) -> int:
        return len(self._responses)
