"""Chat model interface implemented by every chat provider."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from typing import Any, ClassVar
import uuid

from pydantic import BaseModel

from radicalbit_ai_gateway.llm.messages import AIMessage, AIMessageChunk, BaseMessage
from radicalbit_ai_gateway.llm.tracing import ChatTrace


def _run_id() -> str:
    return f'run-{uuid.uuid4()}'


class ChatModel(ABC):
    """A provider chat model.

    Providers implement ``_agenerate`` and ``_astream``; the public methods add
    the behaviour every provider shares: a missing message id is filled with a
    per-call run id, a stream always ends with an empty ``chunk_position='last'``
    chunk, and a stream that yields nothing is an error (so fallbacks engage).
    Every call is traced (``llm/tracing.py``).
    """

    # Reported as ``gen_ai.provider.name`` (see llm/tracing.py).
    _gen_ai_provider: ClassVar[str] = 'unknown'

    async def ainvoke(self, input: Sequence[BaseMessage], **kwargs: Any) -> AIMessage:  # noqa: A002
        messages = list(input)
        trace = ChatTrace.start(self, messages, kwargs)
        try:
            message = await self._agenerate(messages, **kwargs)
        except Exception as e:
            if trace:
                trace.fail(e)
            raise
        if message.id is None:
            message.id = _run_id()
        if trace:
            trace.end(message)
        return message

    async def astream(
        self,
        input: Sequence[BaseMessage],  # noqa: A002
        **kwargs: Any,
    ) -> AsyncIterator[AIMessageChunk]:
        messages = list(input)
        trace = ChatTrace.start(self, messages, kwargs)
        run_id = _run_id()
        # The provider's chunks, without the closing one added here.
        chunks: list[AIMessageChunk] = []
        try:
            async for chunk in self._astream(messages, **kwargs):
                if chunk.id is None:
                    chunk.id = run_id
                chunks.append(chunk)
                if trace:
                    trace.add_chunk(chunk)
                yield chunk
            if not chunks:
                raise ValueError('No generation chunks were returned')  # noqa: TRY301
            if not chunks[-1].chunk_position:
                yield AIMessageChunk(
                    content='' if isinstance(chunks[-1].content, str) else [],
                    chunk_position='last',
                    id=run_id,
                )
        except BaseException as e:
            # Also when the consumer stops early (GeneratorExit).
            if trace:
                trace.fail(e)
            raise
        if trace:
            trace.end_stream(chunks)

    @abstractmethod
    async def _agenerate(self, messages: list[BaseMessage], **kwargs: Any) -> AIMessage:
        """Call the provider and return its complete reply."""

    @abstractmethod
    def _astream(
        self, messages: list[BaseMessage], **kwargs: Any
    ) -> AsyncIterator[AIMessageChunk]:
        """Call the provider in streaming mode and yield its reply chunks."""

    # ── Native OpenAI Responses API ──────────────────────────────────────
    # A provider that serves the Responses API takes a client's request body
    # as is, so nothing is lost translating it to and from messages.

    def supports_native_responses(self) -> bool:
        """Whether this model can serve a Responses API request body as is."""
        return False

    async def ainvoke_native_responses(self, body: dict) -> dict:
        """Send a Responses API request body and return the response object."""
        raise NotImplementedError(
            f'{type(self).__name__} does not serve the Responses API'
        )

    def astream_native_responses(self, body: dict) -> AsyncIterator[tuple[str, str]]:
        """Send a streaming Responses API request; yield ``(event, data)`` pairs."""
        raise NotImplementedError(
            f'{type(self).__name__} does not serve the Responses API'
        )

    def bind_tools(self, tools: list[dict], tool_choice: Any = None) -> 'ChatModel':
        """Return a model that offers ``tools`` on every call."""
        raise NotImplementedError(f'{type(self).__name__} does not support tools')

    def with_structured_output(
        self, schema: type[BaseModel], include_raw: bool = False
    ) -> 'StructuredChatModel':
        """Return a model whose replies are parsed into ``schema``."""
        raise NotImplementedError(
            f'{type(self).__name__} does not support structured output'
        )

    # ── Tracing hooks ─────────────────────────────────────────────────────
    # What LangChain derived from its internals for its spans (llm/tracing.py).

    def _invocation_params(self, stop: list[str] | None = None, **kwargs: Any) -> dict:
        """LangChain's invocation params of a call with ``kwargs``.

        The tracer reads ``model``/``model_id``/``model_name``, ``max_tokens``,
        ``temperature``, ``top_p``, ``tools`` and ``functions``: the model's
        own settings overridden by the bound and call kwargs.
        """
        return {'stop': stop, **kwargs}

    def _serialized_kwargs(self) -> dict:
        """Return the constructor params LangChain serialized for tracing.

        They override the call's params in the span (``model``/``model_name``,
        ``max_tokens``, ``temperature``, ``top_p``).
        """
        names = ('model', 'model_name', 'max_tokens', 'temperature', 'top_p')
        return {
            name: value
            for name in names
            if (value := getattr(self, name, None)) is not None
        }

    def _llm_output(self, message: AIMessage) -> dict | None:
        """LangChain's ``llm_output`` of a (non-streamed) reply.

        The tracer reads ``model_name``, ``id`` and the provider's raw usage
        (``token_usage`` or ``usage``).
        """
        return None

    def _generation_info(self, message: AIMessage) -> dict | None:
        """LangChain's ``generation_info`` of a reply or of a stream chunk.

        The tracer reads ``finish_reason``; a stream's infos are merged.
        """
        return None

    def _error_type(self, error: BaseException) -> str:
        """Return the ``error.type`` of a failed call: the error's class name.

        Where LangChain re-raised the SDK's errors, the class it raised.
        """
        return type(error).__name__


class StructuredChatModel(ABC):
    """A chat model that answers with an instance of a pydantic schema.

    With ``include_raw`` the reply is ``{'raw': AIMessage, 'parsed': schema |
    None, 'parsing_error': Exception | None}``; otherwise it is the parsed
    instance and a parsing failure raises.
    """

    @abstractmethod
    async def ainvoke(self, input: Sequence[BaseMessage], **kwargs: Any) -> Any:  # noqa: A002
        """Return the parsed reply to ``input``."""
