"""Middleware that emits REQUEST events for the gateway's proxy endpoints."""

from __future__ import annotations

import logging
import time
import uuid

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from radicalbit_ai_gateway.events.request_events_processor import emit_request_event
from radicalbit_ai_gateway.middleware.request_event_context import RequestEventContext
from radicalbit_ai_gateway.models.event_payload import RequestEventPayload
from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.models.request_event_type import RequestStatus, RequestType
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import (
    TagsHeaderError,
    gateway_exception_handler,
)
from radicalbit_ai_gateway.utils.request_context import set_current_request_tags
from radicalbit_ai_gateway.utils.request_tags import TAGS_HEADER, parse_tags_header

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)


class RequestEventMiddleware:
    """Stamps ``request_uuid`` and emits a REQUEST event per proxied request.

    Pure ASGI middleware that properly handles exceptions by emitting events
    after exception handlers have processed the error.

    ``request_uuid`` is generated here, and only here, so traces and events
    share one correlation id.
    """

    TRACKED_PATHS = {
        '/v1/chat/completions',
        '/v1/embeddings',
        '/v1/responses',
        '/v1/audio/transcriptions',
    }

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    @staticmethod
    def is_mcp_request(scope: Scope) -> bool:
        """Match ``POST /{project_name}/{route_name}/mcp``.

        The inbound MCP proxy is mounted at the root with a dynamic path, so it
        cannot be a literal in :attr:`TRACKED_PATHS`. Matching on an exact
        segment count and the POST method keeps the SPA catch-all and the
        ``/public/api/v1/...`` routes from colliding with it.
        """
        if scope.get('method') != 'POST':
            return False
        segments = [segment for segment in scope.get('path', '').split('/') if segment]
        return len(segments) == 3 and segments[2] == 'mcp'

    @classmethod
    def is_tracked(cls, scope: Scope) -> bool:
        return scope.get('path', '') in cls.TRACKED_PATHS or cls.is_mcp_request(scope)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        if not self.is_tracked(scope):
            await self.app(scope, receive, send)
            return

        # Create context early so exception handlers can populate it
        request = Request(scope, receive, send)
        ctx = RequestEventContext.get_or_create(request)

        # Generate request_uuid early so it's available even if auth fails
        request_uuid = str(uuid.uuid4())
        request.state.request_uuid = request_uuid

        start_time = time.time()
        status_code = 500  # Default to 500 if we can't capture the actual code
        event_emitted = False

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code, event_emitted
            if message['type'] == 'http.response.start':
                status_code = message['status']
            elif message['type'] == 'http.response.body' and not message.get(
                'more_body', True
            ):
                if not event_emitted:
                    event_emitted = True
                    self._emit_event(request, status_code, start_time)
            await send(message)

        # Validate X-RB-Tags here so every proxied endpoint shares one
        # implementation. This middleware sits outside Starlette's
        # ExceptionMiddleware, so a raised AppError would become a 500 --
        # call the registered handler and send its response instead. The
        # rejected request is still recorded, like any other handled error.
        # Reset before parsing: the reject path below returns early and skips
        # the ``finally`` cleanup, so a leaked value from an earlier request
        # in the same task must not tag this one.
        set_current_request_tags(())
        try:
            # getlist + join: a client may repeat X-RB-Tags; headers.get()
            # would silently drop every line but the first.
            tags = parse_tags_header(','.join(request.headers.getlist(TAGS_HEADER)))
        except TagsHeaderError as err:
            response = gateway_exception_handler(request, err)
            await response(scope, receive, send_wrapper)
            if not event_emitted:
                self._emit_event(request, status_code, start_time)
            return
        ctx.tags = tags
        set_current_request_tags(tags)

        # Event emission must happen at multiple ASGI lifecycle points:
        # - http.response.body (more_body=False): normal completion after exception handlers
        # - After app() returns: streaming responses that don't set more_body=False
        # - Exception propagation: capture context before outer handler loses it
        try:
            await self.app(scope, receive, send_wrapper)
            if not event_emitted:
                self._emit_event(request, status_code, start_time)
        except Exception as e:
            ctx = RequestEventContext.get(request)
            if ctx:
                error_str = str(e)
                ctx.error_type = type(e).__name__
                ctx.error_code = error_str[:500] if error_str else None
                ctx.is_unhandled_error = True
            if not event_emitted:
                event_emitted = True
                self._emit_event(request, status_code, start_time)
            raise
        finally:
            set_current_request_tags(())

    def _emit_event(
        self, request: Request, status_code: int, start_time: float
    ) -> None:
        try:
            ctx = RequestEventContext.get(request)
            if not ctx:
                logger.warning(
                    'RequestEventMiddleware: no context found, skipping event'
                )
                return

            if self.is_mcp_request(request.scope):
                request_type = RequestType.MCP
                if status_code == 202:
                    # 202 is only ever a JSON-RPC notification (no id, no
                    # response body). Emitting would fill request_event with
                    # no-op handshake traffic.
                    return
            elif '/audio/transcriptions' in request.url.path:
                request_type = RequestType.TRANSCRIPTIONS
            elif '/embeddings' in request.url.path:
                request_type = RequestType.EMBEDDINGS
            else:
                request_type = RequestType.CHAT_COMPLETIONS

            status = self._determine_status(status_code, ctx, request_type)

            emit_request_event(
                RequestEventPayload(
                    request_uuid=getattr(request.state, 'request_uuid', ''),
                    event_type=EventType.REQUEST,
                    route_name=ctx.route_name,
                    api_key_uuid=ctx.api_key_uuid,
                    api_key_name=ctx.api_key_name,
                    group_uuid=ctx.group_uuid,
                    group_name=ctx.group_name,
                    project_uuid=ctx.project_uuid,
                    project_name=ctx.project_name,
                    tags=list(ctx.tags),
                    request_type=request_type,
                    is_streaming=ctx.is_streaming,
                    status=status,
                    http_status_code=status_code,
                    error_type=ctx.error_type,
                    error_code=ctx.error_code,
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )
        except Exception:
            logger.exception('Failed to emit REQUEST event')

    @staticmethod
    def _determine_status(
        http_code: int,
        ctx: RequestEventContext,
        request_type: RequestType,
    ) -> RequestStatus:
        # MCP returns JSON-RPC failures as an `error` body over HTTP 200, so the
        # status code alone would report every failed tools/call as a success.
        # Scoped to MCP: on the /v1/* endpoints an error always carries a 4xx/5xx,
        # and widening this would reclassify anything that recovered to a 2xx.
        if request_type is RequestType.MCP and http_code < 400 and ctx.error_type:
            return RequestStatus.HANDLED_ERROR
        if http_code < 400:
            return RequestStatus.SUCCESS
        if ctx.is_unhandled_error:
            return RequestStatus.UNHANDLED_ERROR
        if ctx.error_type:
            return RequestStatus.HANDLED_ERROR
        return RequestStatus.UNHANDLED_ERROR
