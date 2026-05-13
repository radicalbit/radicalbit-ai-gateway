"""Context for REQUEST events, stored in request.state."""

from __future__ import annotations

from dataclasses import dataclass

from starlette.requests import Request


@dataclass
class RequestEventContext:
    """Context for emitting REQUEST events. Stored in request.state."""

    request_type: str = ''  # "chat_completion" | "embedding"
    route_name: str = ''
    is_streaming: bool = False

    # Error info (set by exception handlers)
    error_type: str | None = None
    error_code: str | None = None
    is_unhandled_error: bool = False  # True if caught by catch-all handler

    # Auth context (set by dependencies)
    api_key_uuid: str = ''
    api_key_name: str = ''
    group_uuid: str = ''
    group_name: str = ''

    # Project context (set after route resolution)
    project_uuid: str = ''
    project_name: str = ''

    @classmethod
    def get(cls, request: Request) -> RequestEventContext | None:
        """Get context from request.scope, returns None if not set."""
        return request.scope.get('request_event_context')

    @classmethod
    def get_or_create(cls, request: Request) -> RequestEventContext:
        """Get or create context in request.scope.

        Uses scope directly instead of request.state to guarantee sharing
        between all Request objects created from the same ASGI scope.
        """
        if 'request_event_context' not in request.scope:
            request.scope['request_event_context'] = cls()
        return request.scope['request_event_context']
