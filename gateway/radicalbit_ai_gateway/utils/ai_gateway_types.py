from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import TypeAlias

from openai.types.chat.chat_completion import ChatCompletion
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk

from radicalbit_ai_gateway.caching.route_cache import Cached
from radicalbit_ai_gateway.guardrails.guardrails import GuardrailFlags
from radicalbit_ai_gateway.limiting.limits import RequestLimits
from radicalbit_ai_gateway.llm.messages import BaseMessage
from radicalbit_ai_gateway.models.model import Model

# Type aliases for streaming methods
StreamBufferedResult: TypeAlias = tuple[list[ChatCompletionChunk], dict[str, str]]
StreamGenerator: TypeAlias = AsyncGenerator[ChatCompletionChunk, None]


@dataclass
class InvokeResponse:
    """Response from gateway invocation.

    Attributes:
        content: The ChatCompletion response from the model.
        headers: HTTP headers to include in the response (e.g., cache hit flags).

    """

    content: ChatCompletion
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class PrepareAndValidateResult:
    """Result of request preparation and validation.

    Contains all the data needed after the pre-invocation validation phase,
    including selected model, redacted messages, cache results, and guardrail status.
    """

    model_selected: Model
    redacted_messages: list[BaseMessage]
    input_soft_block: ChatCompletion | None
    guardrails_input_triggered: bool
    guardrails_block_triggered: bool
    #: The request's cache lookup: the reply on a hit, where to store it on
    #: a miss.
    cached: Cached = field(default_factory=Cached)

    @property
    def guardrail_flags(self) -> GuardrailFlags:
        return GuardrailFlags(
            input_warned=self.guardrails_input_triggered,
            input_blocked=self.guardrails_block_triggered,
        )


@dataclass
class ResponsesPrepared:
    """A Responses API request after the gateway's policies, before the model call.

    Attributes:
        body: The request body to forward upstream.
        model_selected: The model routing selected.
        allow_fallback: False when the request continues state stored at the
            provider, which only the selected model's account can serve.
        identity: Who made the request, as the keyword arguments
            (``request_uuid``, ``api_key_uuid``, ``group_uuid``, ``api_key_name``,
            ``group_name``) the route's policies take.
        limits: The limits the request is subject to.
        cached: The request's cache lookup: the response object on a hit,
            where to store the response on a miss.
        soft_block: The response object of an input soft block.
        guardrails_input_triggered: Whether an input REDACT or WARN guardrail triggered.

    """

    body: dict
    model_selected: Model
    allow_fallback: bool
    identity: dict[str, str]
    limits: RequestLimits
    cached: Cached = field(default_factory=Cached)
    soft_block: dict | None = None
    guardrails_input_triggered: bool = False


@dataclass
class MessagesPrepared:
    """A Messages API request after the gateway's policies, before the model call.

    Attributes:
        body: The request body to forward upstream.
        headers: The client's ``anthropic-*`` headers to forward upstream.
        model_selected: The model routing selected.
        identity: Who made the request, as the keyword arguments
            (``request_uuid``, ``api_key_uuid``, ``group_uuid``, ``api_key_name``,
            ``group_name``) the route's policies take.

    """

    body: dict
    headers: dict[str, str]
    model_selected: Model
    identity: dict[str, str]


@dataclass
class OutputProcessResult:
    """A chat completion after the output guardrails, and what they did."""

    response: ChatCompletion
    guardrail_flags: GuardrailFlags = field(default_factory=GuardrailFlags)


@dataclass
class ChunkAccumulationResult:
    """Result of chunk content accumulation during streaming.

    Attributes:
        text: The accumulated text content.
        usage_metadata: Usage metadata from the chunk, if present.

    """

    text: str
    usage_metadata: dict | None
