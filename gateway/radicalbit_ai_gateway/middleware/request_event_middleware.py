"""Middleware that emits REQUEST events for chat completions and embeddings."""

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

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)


class RequestEventMiddleware:
    """Emits REQUEST event for chat completions and embeddings.

    Pure ASGI middleware that properly handles exceptions by emitting events
    after exception handlers have processed the error.
    """

    TRACKED_PATHS = {
        '/v1/chat/completions',
        '/v1/embeddings',
        '/v1/responses',
        '/v1/audio/transcriptions',
    }

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        path = scope.get('path', '')
        if path not in self.TRACKED_PATHS:
            await self.app(scope, receive, send)
            return

        # Create context early so exception handlers can populate it
        request = Request(scope, receive, send)
        RequestEventContext.get_or_create(request)

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

            status = self._determine_status(status_code, ctx)
            if '/audio/transcriptions' in request.url.path:
                request_type = RequestType.TRANSCRIPTIONS
            elif '/embeddings' in request.url.path:
                request_type = RequestType.EMBEDDINGS
            else:
                request_type = RequestType.CHAT_COMPLETIONS

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
    def _determine_status(http_code: int, ctx: RequestEventContext) -> RequestStatus:
        if http_code < 400:
            return RequestStatus.SUCCESS
        if ctx.is_unhandled_error:
            return RequestStatus.UNHANDLED_ERROR
        if ctx.error_type:
            return RequestStatus.HANDLED_ERROR
        return RequestStatus.UNHANDLED_ERROR
