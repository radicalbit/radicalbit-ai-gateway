import asyncio
import contextlib
from http.client import responses as http_reasons
from unittest import mock

try:
    import httpx2
except ImportError:
    httpx2 = None

import pook
from pook.interceptors.base import BaseInterceptor
from pook.request import Request


def register_httpx2_interceptor():
    if httpx2 is None:
        return

    class MockedTransport2(httpx2.BaseTransport):
        def __init__(self, interceptor, client, orig_transport):
            self._interceptor = interceptor
            self._client = client
            self._orig = orig_transport

        def _get_pook_request(self, req: httpx2.Request) -> Request:
            r = Request(req.method)
            r.url = str(req.url)
            r.headers = dict(req.headers)
            return r

        def _get_httpx2_response(
            self, req: httpx2.Request, mock_res
        ) -> httpx2.Response:
            res = httpx2.Response(
                status_code=mock_res._status,
                headers=dict(mock_res._headers),
                content=mock_res._body,
                extensions={
                    'http_version': b'HTTP/1.1',
                    'reason_phrase': http_reasons.get(mock_res._status, '').encode(
                        'ascii'
                    ),
                    'network_stream': None,
                },
                request=req,
            )
            res.is_stream_consumed = False
            res.is_closed = False
            if hasattr(res, '_content'):
                del res._content
            return res

    class AsyncTransport2(MockedTransport2):
        async def handle_async_request(self, req: httpx2.Request) -> httpx2.Response:
            pook_req = self._get_pook_request(req)
            pook_req.body = await req.aread()

            matched = self._interceptor.engine.match(pook_req)
            if not matched:
                orig = self._orig(self._client, req.url)
                return await orig.handle_async_request(req)

            if matched._delay:
                await asyncio.sleep(matched._delay / 1000)

            return self._get_httpx2_response(req, matched._response)

    class SyncTransport2(MockedTransport2):
        def handle_request(self, req: httpx2.Request) -> httpx2.Response:
            pook_req = self._get_pook_request(req)
            pook_req.body = req.read()

            matched = self._interceptor.engine.match(pook_req)
            if not matched:
                orig = self._orig(self._client, req.url)
                return orig.handle_request(req)

            return self._get_httpx2_response(req, matched._response)

    class Httpx2Interceptor(BaseInterceptor):
        def _patch(self, path: str):
            transport_cls = AsyncTransport2 if 'AsyncClient' in path else SyncTransport2

            def handler(client, *_):
                return transport_cls(self, client, _orig)

            try:
                patcher = mock.patch(path, handler)
                _orig = patcher.get_original()[0]
                patcher.start()
                self.patchers.append(patcher)
            except Exception:
                pass

        def activate(self):
            for path in (
                'httpx2.Client._transport_for_url',
                'httpx2.AsyncClient._transport_for_url',
            ):
                self._patch(path)

        def disable(self):
            for p in self.patchers:
                p.stop()

    pook.interceptors.add(Httpx2Interceptor)
    with contextlib.suppress(Exception):
        pook.engine().mock_engine.add_interceptor(Httpx2Interceptor)


register_httpx2_interceptor()
