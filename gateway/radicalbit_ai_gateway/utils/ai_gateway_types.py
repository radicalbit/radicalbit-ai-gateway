from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import TypeAlias

from langchain_core.messages import BaseMessage
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk

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
    cache_key: str
    embeddings: list[float] | None
    cached_response: ChatCompletion | None
    input_soft_block: ChatCompletion | None
    guardrails_input_triggered: bool
    guardrails_block_triggered: bool


@dataclass
class CacheResult:
    """Result of cache lookup operation.

    Attributes:
        cache_key: The generated cache key for this request.
        embeddings: Embeddings for semantic cache (if applicable).
        cached_response: The cached response if found, None otherwise.

    """

    cache_key: str
    embeddings: list[float] | None
    cached_response: ChatCompletion | None


@dataclass
class OutputProcessResult:
    """Result of output processing with guardrails.

    Attributes:
        response: The processed ChatCompletion (possibly redacted).
        guardrails_triggered: Whether any guardrail was triggered during processing.
        guardrails_block_triggered: Whether a BLOCK or SOFT_BLOCK guardrail was triggered.

    """

    response: ChatCompletion
    guardrails_triggered: bool
    guardrails_block_triggered: bool


@dataclass
class ChunkAccumulationResult:
    """Result of chunk content accumulation during streaming.

    Attributes:
        text: The accumulated text content.
        usage_metadata: Usage metadata from the chunk, if present.

    """

    text: str
    usage_metadata: dict | None
