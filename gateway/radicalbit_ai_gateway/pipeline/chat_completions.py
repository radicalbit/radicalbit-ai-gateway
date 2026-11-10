"""Chat completions: the order a request goes through the route's policies."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
import logging

from openai.types.chat import ChatCompletionToolChoiceOptionParam
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk
from openai.types.chat.chat_completion_tool_param import ChatCompletionToolParam
from traceloop.sdk.decorators import workflow

from radicalbit_ai_gateway.caching.route_cache import ChatEntry, StreamedReply
from radicalbit_ai_gateway.guardrails.guardrails import Conversation, Reply
from radicalbit_ai_gateway.limiting.limits import Usage
from radicalbit_ai_gateway.llm.messages import AIMessage, AIMessageChunk, BaseMessage
from radicalbit_ai_gateway.llm.tracing import merge_chunks
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.pipeline.chat_streaming import StreamingUtils
from radicalbit_ai_gateway.pipeline.conversation import (
    apply_config_prompt,
    check_chat_limits,
    route_chat,
)
from radicalbit_ai_gateway.pipeline.openai_messages import convert_openai_messages
from radicalbit_ai_gateway.pipeline.scope import RequestScope
from radicalbit_ai_gateway.preprocessing import run_preprocessing
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.content_utils import ContentUtils
from radicalbit_ai_gateway.utils.exceptions import (
    GatewayBadRequest,
    GuardrailBadRequest,
)
from radicalbit_ai_gateway.utils.open_ai_types import CompletionCreateParams
from radicalbit_ai_gateway.utils.trace_attributes import (
    OperationCategory,
    set_operation_category,
    set_streaming,
)

logger = logging.getLogger(get_app_config().log_config.logger_name)

CHAT_FIELDS = {'model', 'messages', 'tools', 'tool_choice'}


@dataclass
class ChatRequest:
    """A chat completion request: its messages, its tools, and the other
    parameters the client sent, passed to the model as they are.
    """

    messages: list[BaseMessage]
    tools: list[ChatCompletionToolParam] | None = None
    tool_choice: ChatCompletionToolChoiceOptionParam | None = None
    params: dict = field(default_factory=dict)

    @classmethod
    def of(cls, params: CompletionCreateParams) -> 'ChatRequest':
        return cls(
            messages=convert_openai_messages(list(params.get('messages'))),
            tools=list(params.get('tools') or []),
            tool_choice=params.get('tool_choice', 'auto'),
            params={k: v for k, v in params.items() if k not in CHAT_FIELDS},
        )

    @property
    def stream(self) -> bool:
        return bool(self.params.get('stream'))


class _Prepared:
    """A request after its input policies: the model it goes to, its
    messages, and the soft block that answers it in the model's place.

    Not a dataclass: tracing would record its model whole, credentials
    included. Tracing records it by ``to_json``.
    """

    def __init__(
        self,
        model: Model,
        messages: list[BaseMessage],
        soft_block: ChatCompletion | None = None,
    ) -> None:
        self.model = model
        self.messages = messages
        self.soft_block = soft_block

    def to_json(self) -> dict:
        """Return what a span records: the model by its id, and the messages."""
        return {'model_id': self.model.model_id, 'messages': self.messages}


async def complete(scope: RequestScope, chat: ChatRequest) -> ChatCompletion:
    """Answer a chat request with one completion."""
    route = scope.route
    prepared = await _prepare(scope, chat)
    if prepared.soft_block:
        return prepared.soft_block

    if scope.cached.hit:
        reply = scope.cached.value
    else:
        set_operation_category(OperationCategory.INVOCATION)
        reply = await _invoke(scope, chat, prepared)

    # A hit is screened as a model's reply is; only screened replies are
    # stored.
    if route.guardrails.has_output:
        reply = await _screen_output(scope, reply)
    await scope.cached.store(reply)
    return reply.model_copy(update={'model': route.gateway_route_config.route_name})


async def stream(
    scope: RequestScope, chat: ChatRequest
) -> AsyncIterator[ChatCompletionChunk]:
    """Answer a chat request with chunks.

    The model's chunks are relayed as they come, unless the output
    guardrails must read the whole reply first: then it is buffered, and
    its chunks are known when this returns.
    """
    prepared = await _prepare(scope, chat)
    if scope.route.guardrails.has_output:
        return _aiter(await _buffered(scope, chat, prepared))
    return _live(scope, chat, prepared)


async def _prepare(scope: RequestScope, chat: ChatRequest) -> _Prepared:
    route = scope.route
    route_name = route.gateway_route_config.route_name
    if not route.chat_invoker:
        raise GatewayBadRequest(f'Route {route_name} has no chat models defined')

    # Limits come first, before anything that spends. A judge's spend then
    # counts toward the next request.
    await check_chat_limits(scope, chat.messages)

    # Preprocessing plugins see only the client's messages: before routing
    # and before the configured system prompt. Fail-closed if one raises.
    set_operation_category(OperationCategory.PREPROCESSING)
    messages = await run_preprocessing(
        chat.messages, route.gateway_route_config.plugins
    )

    # Redact before routing: no router sees text a redaction masks.
    redaction = await scope.guardrails.redact_input(Conversation(messages))
    messages = redaction.payload.messages()
    model = await route_chat(scope, messages)

    # The system prompt goes in after routing and redaction; the input
    # checks see it but skip it: it is not part of the conversation.
    added = apply_config_prompt(messages, model)
    screened = await scope.guardrails.check_input(
        Conversation(messages, skip=added), redaction.flags
    )
    scope.flags |= screened.flags
    if screened.soft_block:
        return _Prepared(
            model, messages, screened.soft_block.build_soft_block_response(route_name)
        )

    # The cache reads the redacted messages, as the model does (ADR 0010).
    scope.cached = await scope.cache.lookup(
        ChatEntry(
            messages, chat.tools, chat.tool_choice, chat.params, stream=chat.stream
        )
    )
    return _Prepared(model, messages)


async def _invoke(
    scope: RequestScope, chat: ChatRequest, prepared: _Prepared
) -> ChatCompletion:
    logger.debug(
        'Processing request for model %s with %d messages.',
        prepared.model.model_id,
        len(prepared.messages),
    )
    response = await scope.route.chat_invoker.complete(
        identity=scope.identity,
        messages=prepared.messages,
        model_id=prepared.model.model_id,
        tools=chat.tools,
        tool_choice=chat.tool_choice,
        **chat.params,
    )
    if response.usage:
        await scope.limits.count(
            Usage.priced(
                prepared.model,
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
            )
        )
    return response


@workflow(name='apply_output_guardrails')
async def _screen_output(
    scope: RequestScope, response: ChatCompletion
) -> ChatCompletion:
    """Apply the output guardrails to a chat completion."""
    screened = await scope.guardrails.screen_output(
        Reply(response.choices[0].message.content)
    )
    scope.flags |= screened.flags
    if screened.soft_block:
        blocked = screened.soft_block.build_soft_block_response(
            scope.route.gateway_route_config.route_name
        )
        return blocked.model_copy(
            update={
                'usage': response.usage,
                'created': response.created,
                'id': response.id,
            }
        )
    return _with_content(
        response, ContentUtils.normalize_openai_message_content(screened.payload.text)
    )


# ---------------------------------------------------------------------------
# Streams
# ---------------------------------------------------------------------------


async def _live(
    scope: RequestScope, chat: ChatRequest, prepared: _Prepared
) -> AsyncIterator[ChatCompletionChunk]:
    """Relay the model's chunks, then count the usage and store the reply."""
    set_streaming()
    route_name = scope.route.gateway_route_config.route_name
    if prepared.soft_block:
        # The soft block is the stream's one chunk.
        yield StreamingUtils.build_soft_block_chunk(prepared.soft_block, route_name)
        return

    # Upstream always streams its usage; the client gets it if it asked.
    params = dict(chat.params)
    user_stream_options = StreamingUtils.prepare_stream_options(params)

    if scope.cached.hit:
        # A live stream's route has no output guardrails (a route with them
        # streams through _buffered): the hit is sent as is, in one chunk.
        yield StreamingUtils.cached_response_to_chunk(scope.cached.value, route_name)
        return

    set_operation_category(OperationCategory.INVOCATION)
    full_content_text = ''
    final_usage = None
    received: list[AIMessageChunk] = []
    async for chunk in scope.route.chat_invoker.stream(
        identity=scope.identity,
        messages=prepared.messages,
        model_id=prepared.model.model_id,
        tools=chat.tools,
        tool_choice=chat.tool_choice,
        **params,
    ):
        if isinstance(chunk, AIMessageChunk):
            received.append(chunk)
            result = StreamingUtils.accumulate_chunk_content(chunk, full_content_text)
            full_content_text = result.text
            if result.usage_metadata:
                final_usage = result.usage_metadata
            yield StreamingUtils.to_openai_chat_completion_chunk(
                chunk, model_id_invoked=route_name
            )
        else:
            logger.warning('Unexpected chunk type during stream: %s', type(chunk))

    if final_usage:
        await scope.limits.count(
            Usage.priced(
                prepared.model,
                final_usage.get('input_tokens', 0),
                final_usage.get('output_tokens', 0),
            )
        )
    if final_usage and _wants_usage(user_stream_options):
        yield StreamingUtils.build_usage_chunk(
            final_usage=final_usage,
            model_id_invoked=route_name,
            request_id=scope.identity.request_uuid,
        )
    # A live stream's route has no output guardrails: its text is the
    # screened text.
    if reply := _streamed_reply(
        received, full_content_text, final_usage, prepared.model.model_id
    ):
        await scope.cached.store(reply)


async def _buffered(
    scope: RequestScope, chat: ChatRequest, prepared: _Prepared
) -> list[ChatCompletionChunk]:
    """Return the chunks of a reply the output guardrails read whole."""
    set_streaming()
    route_name = scope.route.gateway_route_config.route_name
    if prepared.soft_block:
        return [StreamingUtils.build_soft_block_chunk(prepared.soft_block, route_name)]

    if scope.cached.hit:
        # A hit is screened as a model's reply is, then sent as one chunk.
        cached = scope.cached.value
        text = await _screen_streamed(scope, cached.choices[0].message.content)
        cached = _with_content(cached, text)
        chunks = [StreamingUtils.cached_response_to_chunk(cached, route_name)]
        if _wants_usage(chat.params.get('stream_options')) and cached.usage:
            chunks.append(
                StreamingUtils.build_usage_chunk(
                    final_usage={
                        'input_tokens': cached.usage.prompt_tokens,
                        'output_tokens': cached.usage.completion_tokens,
                        'total_tokens': cached.usage.total_tokens,
                    },
                    model_id_invoked=route_name,
                    request_id=cached.id,
                )
            )
        return chunks

    params = dict(chat.params)
    user_stream_options = StreamingUtils.prepare_stream_options(params)
    return await _stream_whole(scope, chat, prepared, params, user_stream_options)


@workflow(name='stream_with_output_guardrails')
async def _stream_whole(
    scope: RequestScope,
    chat: ChatRequest,
    prepared: _Prepared,
    params: dict,
    user_stream_options: dict | None,
) -> list[ChatCompletionChunk]:
    """Stream the model's reply whole, so the output guardrails can read it."""
    route_name = scope.route.gateway_route_config.route_name
    model_id = prepared.model.model_id
    full_content_text = ''
    final_usage = None
    buffered_chunks = []

    set_operation_category(OperationCategory.INVOCATION)
    async for chunk in scope.route.chat_invoker.stream(
        identity=scope.identity,
        messages=prepared.messages,
        model_id=model_id,
        tools=chat.tools,
        tool_choice=chat.tool_choice,
        **params,
    ):
        if isinstance(chunk, AIMessageChunk):
            buffered_chunks.append(chunk)
            result = StreamingUtils.accumulate_chunk_content(chunk, full_content_text)
            full_content_text = result.text
            if result.usage_metadata:
                final_usage = result.usage_metadata

    # The model was paid for: count it before the output guardrails, which
    # may refuse the reply (ADR 0006).
    if final_usage:
        await scope.limits.count(
            Usage.priced(
                prepared.model,
                final_usage.get('input_tokens', 0),
                final_usage.get('output_tokens', 0),
            )
        )

    # Output guardrails read the whole reply: redact, then check.
    text = await _screen_streamed(scope, full_content_text, usage=final_usage)
    if text != full_content_text:
        buffered_chunks = _with_text(buffered_chunks, text)

    # Cache the screened reply.
    if reply := _streamed_reply(
        buffered_chunks, text, final_usage, model_id, scope.identity.request_uuid
    ):
        await scope.cached.store(reply)

    chunks = [
        StreamingUtils.to_openai_chat_completion_chunk(
            chunk, model_id_invoked=route_name
        )
        for chunk in buffered_chunks
    ]
    if final_usage and _wants_usage(user_stream_options):
        chunks.append(
            StreamingUtils.build_usage_chunk(
                final_usage=final_usage,
                model_id_invoked=route_name,
                request_id=scope.identity.request_uuid,
            )
        )
    return chunks


async def _screen_streamed(
    scope: RequestScope, text: str | None, usage: dict | None = None
) -> str | None:
    """Apply the output guardrails to a streamed reply's text, or to a cache
    hit sent as a stream. Return the text to send.

    A streamed reply cannot be replaced: a soft block answers with a 400
    that carries the request's headers.
    """
    screened = await scope.guardrails.screen_output(Reply(text, usage=usage))
    scope.flags |= screened.flags
    if screened.soft_block:
        raise GuardrailBadRequest(
            message=screened.soft_block.get_soft_block_message(),
            guardrail=screened.soft_block.guardrail,
            reason={'action': 'soft_block'},
            headers=scope.headers(),
        )
    return screened.payload.text


def _wants_usage(stream_options) -> bool:
    return bool(
        stream_options
        and isinstance(stream_options, dict)
        and stream_options.get('include_usage')
    )


async def _aiter(items: list) -> AsyncIterator:
    for item in items:
        yield item


def _streamed_reply(
    chunks: list[AIMessageChunk],
    text: str | None,
    usage: dict | None,
    model_id: str,
    request_id: str | None = None,
) -> StreamedReply | None:
    """Return a streamed reply as the cache stores it: the screened text with
    the stream's tool calls, reasoning and finish reason. None when the
    reply has neither text nor tool calls: it would answer with nothing.
    """
    merged = merge_chunks(chunks) if chunks else AIMessageChunk(content='')
    if not text and not merged.tool_calls:
        return None
    # The last finish reason wins: merging the chunks would join repeated ones.
    finish_reason = next(
        (
            chunk.response_metadata['finish_reason']
            for chunk in reversed(chunks)
            if chunk.response_metadata.get('finish_reason')
        ),
        None,
    )
    message = AIMessage(
        content=text or '',
        tool_calls=merged.tool_calls,
        additional_kwargs=merged.additional_kwargs,
        response_metadata={'finish_reason': finish_reason} if finish_reason else {},
        usage_metadata=usage,
    )
    return StreamedReply(message, model_id, request_id)


def _with_text(chunks: list[AIMessageChunk], text: str) -> list[AIMessageChunk]:
    """Rebuild the chunks of a streamed reply around a new text: the first
    chunk with text carries all of it, the later ones none.
    """
    rebuilt = []
    for chunk in chunks:
        if chunk.content:
            chunk = chunk.model_copy(update={'content': text})
            text = ''
        rebuilt.append(chunk)
    return rebuilt


def _with_content(completion: ChatCompletion, text: str | None) -> ChatCompletion:
    """Return a completion with its first choice's text replaced."""
    if text == completion.choices[0].message.content:
        return completion
    choice = completion.choices[0]
    message = choice.message.model_copy(update={'content': text})
    return completion.model_copy(
        update={'choices': [choice.model_copy(update={'message': message})]}
    )
