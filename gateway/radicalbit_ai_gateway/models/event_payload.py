from enum import StrEnum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.models.request_event_type import RequestStatus, RequestType


class EventBase(BaseModel):
    request_uuid: str
    event_type: EventType
    route_name: str
    value: float
    api_key_uuid: str
    api_key_name: str
    group_uuid: str
    group_name: str
    cost: float = 0.0
    project_uuid: str = ''
    project_name: str = ''


class ModelInvocationPayload(EventBase):
    event_type: Literal[EventType.MODEL_INVOCATION]
    model_id: str
    model_type: str
    cache_type: str | None = None
    is_judge: bool = False
    # Set on the usage of a router's own model call: names the routing.
    routing_name: str | None = None


class InputTokenProcessedPayload(EventBase):
    event_type: Literal[EventType.INPUT_TOKEN_PROCESSED]
    model_id: str | None = None
    model_type: str | None = None
    cache_type: str | None = None
    is_cached_tokens: bool = False
    is_judge: bool = False
    # Set on the usage of a router's own model call: names the routing.
    routing_name: str | None = None


class OutputTokenProcessedPayload(EventBase):
    event_type: Literal[EventType.OUTPUT_TOKEN_PROCESSED]
    model_id: str | None = None
    model_type: str | None = None
    cache_type: str | None = None
    is_judge: bool = False
    # Set on the usage of a router's own model call: names the routing.
    routing_name: str | None = None


class FallbackEventPayload(EventBase):
    event_type: Literal[EventType.FALLBACK]
    target: str
    fallback: str
    is_judge: bool = False


class CacheEventPayload(EventBase):
    event_type: Literal[
        EventType.CACHE_HIT, EventType.CACHE_INPUT_TOKENS, EventType.CACHE_OUTPUT_TOKENS
    ]
    cache_type: str
    model_id: str


class GuardrailEventPayload(EventBase):
    event_type: Literal[EventType.GUARDRAIL]
    name: str
    type: str
    where: str
    parameters: str
    behavior: str
    is_judge: bool = False


class RoutingEventPayload(EventBase):
    event_type: Literal[EventType.ROUTING]
    routing_name: str
    selected_model_id: str


class McpInvocationEventPayload(EventBase):
    """One addressed MCP invocation, with the server and object it addressed.

    ``mcp_target`` is the tool for ``tools/call``, the prompt for
    ``prompts/get`` and the upstream uri for ``resources/read``. Both it and
    ``mcp_alias`` are empty when the route does not configure that server.
    """

    event_type: Literal[EventType.MCP_INVOCATION]
    mcp_method: str
    mcp_alias: str = ''
    mcp_target: str = ''


class LimitScope(StrEnum):
    """The entity that owns the limit counter.

    A StrEnum so the event row stores 'route', not 'LimitScope.ROUTE'.
    """

    ROUTE = 'route'
    PROJECT = 'project'
    CREDENTIAL = 'credential'


class LimitEventPayload(EventBase):
    """A limit blocked a request, or its consumption crossed a threshold.

    Names the exact limit and its window state. A ``LIMIT_THRESHOLD`` event
    carries the ``threshold_percentage`` it crossed; a block carries none.

    ``category`` is the limiter's scenario (``request_rate``, ``token_input``,
    ``token_output``, ``audio_duration``, ``budget``). ``maximum`` and
    ``consumption`` are in the limit's own unit, currency for a budget.
    ``consumption`` is the counter as it stands, so it can exceed ``maximum``.
    ``reset_time`` is a Unix timestamp in seconds. ``window_id`` is the
    limiter's id for the current window, None if no window was open.
    """

    event_type: Literal[
        EventType.RATE_LIMIT,
        EventType.TOKEN_INPUT_LIMIT,
        EventType.TOKEN_OUTPUT_LIMIT,
        EventType.AUDIO_DURATION_LIMIT,
        EventType.BUDGET_LIMIT,
        EventType.CREDENTIAL_RATE_LIMIT,
        EventType.CREDENTIAL_TOKEN_INPUT_LIMIT,
        EventType.CREDENTIAL_TOKEN_OUTPUT_LIMIT,
        EventType.CREDENTIAL_BUDGET_LIMIT,
        EventType.PROJECT_BUDGET_LIMIT,
        EventType.LIMIT_THRESHOLD,
    ]
    limit_scope: LimitScope
    category: str
    window_seconds: int
    maximum: float
    consumption: float
    reset_time: int
    window_id: str | None = None
    threshold_percentage: int | None = None


class RequestEventPayload(BaseModel):
    """REQUEST event payload."""

    request_uuid: str
    event_type: Literal[EventType.REQUEST]
    route_name: str
    api_key_uuid: str | None = None
    api_key_name: str = ''
    group_uuid: str | None = None
    group_name: str = ''
    project_uuid: str = ''
    project_name: str = ''
    tags: list[str] = []
    request_type: Literal[
        RequestType.CHAT_COMPLETIONS,
        RequestType.EMBEDDINGS,
        RequestType.TRANSCRIPTIONS,
        RequestType.DECISION_MODEL,
        RequestType.MCP,
    ]
    is_streaming: bool = False
    status: Literal[
        RequestStatus.SUCCESS,
        RequestStatus.HANDLED_ERROR,
        RequestStatus.UNHANDLED_ERROR,
    ]
    http_status_code: int
    error_type: str | None = None
    error_code: str | None = None
    duration_ms: float = 0.0


EventPayload = Annotated[
    Union[
        ModelInvocationPayload,
        InputTokenProcessedPayload,
        OutputTokenProcessedPayload,
        FallbackEventPayload,
        CacheEventPayload,
        GuardrailEventPayload,
        RoutingEventPayload,
        LimitEventPayload,
        McpInvocationEventPayload,
    ],
    Field(discriminator='event_type'),
]
