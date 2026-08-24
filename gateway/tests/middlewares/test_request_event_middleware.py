"""Path matching and REQUEST event classification in RequestEventMiddleware.

The MCP proxy is mounted at the root with a dynamic path, so it cannot be a
literal in ``TRACKED_PATHS`` — these tests pin the predicate that stands in for
one against the routes it must not swallow. They also pin the two ways MCP
differs from the ``/v1/*`` endpoints: a 202 notification is not an event, and a
JSON-RPC error arrives over HTTP 200 rather than a 4xx.
"""

from unittest.mock import patch
import uuid

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from radicalbit_ai_gateway.middleware.request_event_context import RequestEventContext
from radicalbit_ai_gateway.middleware.request_event_middleware import (
    RequestEventMiddleware,
)
from radicalbit_ai_gateway.models.request_event_type import RequestStatus, RequestType
from radicalbit_ai_gateway.utils.request_context import get_current_request_tags

EMIT = 'radicalbit_ai_gateway.middleware.request_event_middleware.emit_request_event'


def _scope(path: str, method: str = 'POST') -> dict:
    return {'type': 'http', 'path': path, 'method': method}


@pytest.mark.parametrize(
    'path',
    [
        '/proj/my-route/mcp',
        '/a/b/mcp',
        '/proj/route-with-dashes/mcp',
    ],
)
def test_is_mcp_request_matches_the_proxy_path(path):
    assert RequestEventMiddleware.is_mcp_request(_scope(path)) is True


@pytest.mark.parametrize(
    'path',
    [
        '/public/api/v1/projects/mcp',  # 5 segments: management API
        '/proj/my-route/mcp/extra',  # deeper than the route
        '/mcp',  # 1 segment
        '/proj/mcp',  # 2 segments
        '/proj/my-route/mcpx',  # near miss
        '/proj/my-route/tools',
        '/v1/chat/completions',  # 3 segments, but not mcp
        '',
    ],
)
def test_is_mcp_request_rejects_everything_else(path):
    assert RequestEventMiddleware.is_mcp_request(_scope(path)) is False


@pytest.mark.parametrize('method', ['GET', 'DELETE', 'PUT', 'OPTIONS'])
def test_is_mcp_request_is_post_only(method):
    """The SPA catch-all serves GET on arbitrary paths."""
    assert (
        RequestEventMiddleware.is_mcp_request(_scope('/proj/my-route/mcp', method))
        is False
    )


def _app(path: str, *, status_code: int = 200, error: str | None = None) -> TestClient:
    """Build a one-route app behind the middleware.

    ``error`` populates the request event context the way an exception handler
    or ``McpService._record_error_outcome`` would, without a 4xx response.
    """

    async def endpoint(request):
        if error is not None:
            ctx = RequestEventContext.get_or_create(request)
            ctx.error_type = error
            ctx.error_code = '-32602'
        # echo what the middleware stamped so the test can assert on it
        return JSONResponse(
            {'request_uuid': getattr(request.state, 'request_uuid', None)},
            status_code=status_code,
        )

    app = Starlette(routes=[Route(path, endpoint, methods=['POST'])])
    app.add_middleware(RequestEventMiddleware)
    return TestClient(app)


def test_mcp_requests_are_stamped_and_emit_an_mcp_event():
    with patch(EMIT) as emit:
        body = (
            _app('/{project_name}/{route_name}/mcp').post('/proj/my-route/mcp').json()
        )

    assert uuid.UUID(body['request_uuid']).version == 4
    payload = emit.call_args.args[0]
    assert payload.request_type is RequestType.MCP
    assert payload.request_uuid == body['request_uuid']


def test_tracked_paths_are_stamped_and_emit_an_event():
    with patch(EMIT) as emit:
        body = _app('/v1/chat/completions').post('/v1/chat/completions').json()

    assert uuid.UUID(body['request_uuid']).version == 4
    assert emit.call_args.args[0].request_type is RequestType.CHAT_COMPLETIONS


def test_an_mcp_notification_emits_no_event():
    """202 means a JSON-RPC notification: no id, no body, nothing to bill."""
    with patch(EMIT) as emit:
        response = _app('/{project_name}/{route_name}/mcp', status_code=202).post(
            '/proj/my-route/mcp'
        )

    assert response.status_code == 202
    emit.assert_not_called()


def test_an_mcp_jsonrpc_error_over_200_is_a_handled_error():
    """The status code says success; only the error context says otherwise."""
    with patch(EMIT) as emit:
        _app('/{project_name}/{route_name}/mcp', error='mcp_jsonrpc_error').post(
            '/proj/my-route/mcp'
        )

    payload = emit.call_args.args[0]
    assert payload.http_status_code == 200
    assert payload.status is RequestStatus.HANDLED_ERROR
    assert payload.error_code == '-32602'


def test_a_successful_mcp_call_is_a_success():
    with patch(EMIT) as emit:
        _app('/{project_name}/{route_name}/mcp').post('/proj/my-route/mcp')

    assert emit.call_args.args[0].status is RequestStatus.SUCCESS


def test_an_error_context_on_a_2xx_llm_call_stays_a_success():
    """The MCP downgrade must not widen to the /v1/* endpoints."""
    with patch(EMIT) as emit:
        _app('/v1/chat/completions', error='SomeError').post('/v1/chat/completions')

    assert emit.call_args.args[0].status is RequestStatus.SUCCESS


def test_untracked_paths_are_left_alone():
    with patch(EMIT) as emit:
        body = _app('/public/api/v1/keys').post('/public/api/v1/keys').json()

    assert body['request_uuid'] is None
    emit.assert_not_called()


def test_each_mcp_request_gets_its_own_request_uuid():
    client = _app('/{project_name}/{route_name}/mcp')

    with patch(EMIT):
        first = client.post('/proj/my-route/mcp').json()['request_uuid']
        second = client.post('/proj/my-route/mcp').json()['request_uuid']

    assert first != second


def _tags_app(path: str) -> TestClient:
    """One-route app that echoes what the middleware resolved from X-RB-Tags.

    Reports both the request context and the ContextVar, since ``event`` rows
    reach the tags through the latter (``emit_event`` never sees the request).
    """

    async def endpoint(request):
        ctx = RequestEventContext.get_or_create(request)
        return JSONResponse(
            {
                'ctx_tags': list(ctx.tags),
                'contextvar_tags': list(get_current_request_tags()),
            }
        )

    app = Starlette(routes=[Route(path, endpoint, methods=['POST'])])
    app.add_middleware(RequestEventMiddleware)
    return TestClient(app)


# Imported from the middleware so this file cannot drift from it.
ALL_TAGGABLE_PATHS = sorted(RequestEventMiddleware.TRACKED_PATHS)


@pytest.mark.parametrize('path', ALL_TAGGABLE_PATHS)
def test_tags_are_parsed_on_every_tracked_path(path):
    """Validation lives in the middleware precisely so it is uniform."""
    with patch(EMIT) as emit:
        body = _tags_app(path).post(
            path, headers={'X-RB-Tags': 'cost_center=retail,env=prod'}
        )

    assert body.json()['ctx_tags'] == ['cost_center=retail', 'env=prod']
    assert emit.call_args.args[0].tags == ['cost_center=retail', 'env=prod']


def test_tags_are_parsed_on_the_mcp_path():
    with patch(EMIT) as emit:
        _tags_app('/{project_name}/{route_name}/mcp').post(
            '/proj/my-route/mcp', headers={'X-RB-Tags': 'env=prod'}
        )

    assert emit.call_args.args[0].tags == ['env=prod']


def test_tags_reach_the_contextvar_that_feeds_event_rows():
    body = (
        _tags_app('/v1/chat/completions')
        .post('/v1/chat/completions', headers={'X-RB-Tags': 'env=prod,app=x'})
        .json()
    )
    assert body['contextvar_tags'] == ['app=x', 'env=prod']


def test_repeated_tags_headers_are_combined():
    """headers.get() would silently drop all but the first X-RB-Tags line."""
    body = (
        _tags_app('/v1/chat/completions')
        .post(
            '/v1/chat/completions',
            headers=[('X-RB-Tags', 'env=prod'), ('X-RB-Tags', 'app=x')],
        )
        .json()
    )
    assert body['ctx_tags'] == ['app=x', 'env=prod']


def test_the_contextvar_does_not_leak_between_requests():
    client = _tags_app('/v1/chat/completions')
    client.post('/v1/chat/completions', headers={'X-RB-Tags': 'env=prod'})
    body = client.post('/v1/chat/completions').json()
    assert body['contextvar_tags'] == []


def test_no_header_means_no_tags_and_no_error():
    with patch(EMIT) as emit:
        response = _tags_app('/v1/chat/completions').post('/v1/chat/completions')

    assert response.status_code == 200
    assert response.json()['ctx_tags'] == []
    assert emit.call_args.args[0].tags == []


@pytest.mark.parametrize('path', ALL_TAGGABLE_PATHS)
def test_a_malformed_header_is_rejected_uniformly(path):
    with patch(EMIT):
        response = _tags_app(path).post(path, headers={'X-RB-Tags': 'broken'})

    assert response.status_code == 400
    error = response.json()['error']
    assert error['type'] == 'gateway_error'
    assert error['code'] == 'tags_header_invalid'
    assert 'broken' in error['message']


def test_an_oversized_header_is_rejected():
    with patch(EMIT):
        response = _tags_app('/v1/chat/completions').post(
            '/v1/chat/completions', headers={'X-RB-Tags': 'a=1,' * 2000}
        )

    assert response.status_code == 400
    assert response.json()['error']['code'] == 'tags_header_too_large'


def test_a_rejected_request_still_emits_a_request_event():
    """A 400 from the middleware must not become a hole in request_event."""
    with patch(EMIT) as emit:
        _tags_app('/v1/chat/completions').post(
            '/v1/chat/completions', headers={'X-RB-Tags': 'broken'}
        )

    payload = emit.call_args.args[0]
    assert payload.http_status_code == 400
    assert payload.status is RequestStatus.HANDLED_ERROR
    assert payload.error_code == 'tags_header_invalid'


def test_a_rejected_request_never_reaches_the_endpoint():
    reached = []

    async def endpoint(request):
        reached.append(True)
        return JSONResponse({})

    app = Starlette(
        routes=[Route('/v1/chat/completions', endpoint, methods=['POST'])],
    )
    app.add_middleware(RequestEventMiddleware)

    with patch(EMIT):
        response = TestClient(app).post(
            '/v1/chat/completions', headers={'X-RB-Tags': 'broken'}
        )

    assert response.status_code == 400
    assert reached == []


def test_untracked_paths_do_not_validate_tags():
    """The middleware only guards the proxied endpoints."""

    async def endpoint(request):
        return JSONResponse({'ok': True})

    app = Starlette(routes=[Route('/health', endpoint, methods=['POST'])])
    app.add_middleware(RequestEventMiddleware)

    response = TestClient(app).post('/health', headers={'X-RB-Tags': 'broken'})
    assert response.status_code == 200


def test_tags_stay_visible_while_a_streaming_response_is_produced():
    """Metric events are emitted mid-stream, so the ContextVar must outlive it."""
    seen = []

    async def endpoint(request):
        async def body():
            for _ in range(3):
                # Stands in for emit_event() being called during the stream.
                seen.append(get_current_request_tags())
                yield b'data: chunk\n\n'

        return StreamingResponse(body(), media_type='text/event-stream')

    app = Starlette(
        routes=[Route('/v1/chat/completions', endpoint, methods=['POST'])],
    )
    app.add_middleware(RequestEventMiddleware)

    with patch(EMIT) as emit:
        response = TestClient(app).post(
            '/v1/chat/completions', headers={'X-RB-Tags': 'env=prod,app=x'}
        )

    assert response.status_code == 200
    assert seen == [('app=x', 'env=prod')] * 3
    assert emit.call_args.args[0].tags == ['app=x', 'env=prod']
