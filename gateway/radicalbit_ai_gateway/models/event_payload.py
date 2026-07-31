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


class InputTokenProcessedPayload(EventBase):
    event_type: Literal[EventType.INPUT_TOKEN_PROCESSED]
    model_id: str | None = None
    model_type: str | None = None
    cache_type: str | None = None
    is_cached_tokens: bool = False
    is_judge: bool = False


class OutputTokenProcessedPayload(EventBase):
    event_type: Literal[EventType.OUTPUT_TOKEN_PROCESSED]
    model_id: str | None = None
    model_type: str | None = None
    cache_type: str | None = None
    is_judge: bool = False


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


class LimitEventPayload(EventBase):
    event_type: Literal[
        EventType.RATE_LIMIT, EventType.TOKEN_INPUT_LIMIT, EventType.TOKEN_OUTPUT_LIMIT
    ]


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
    request_type: Literal[
        RequestType.CHAT_COMPLETIONS,
        RequestType.EMBEDDINGS,
        RequestType.TRANSCRIPTIONS,
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
    ],
    Field(discriminator='event_type'),
]
