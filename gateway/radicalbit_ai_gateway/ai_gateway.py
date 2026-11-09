from collections.abc import AsyncIterator
import logging
from typing import Any

from openai.types.audio.transcription import Transcription
from openai.types.audio.transcription_stream_event import TranscriptionStreamEvent
from openai.types.audio.transcription_verbose import TranscriptionVerbose
from openai.types.chat import ChatCompletionToolChoiceOptionParam
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.chat.chat_completion_tool_param import ChatCompletionToolParam
from openai.types.create_embedding_response import CreateEmbeddingResponse
from traceloop.sdk.decorators import task, workflow

from radicalbit_ai_gateway.caching.gateway_cache import GatewayCache
from radicalbit_ai_gateway.caching.route_cache import (
    Cached,
    ChatEntry,
    DecisionEntry,
    EmbeddingEntry,
    RequestCache,
    ResponsesEntry,
    RouteCache,
    StreamedReply,
    TranscriptionEntry,
)
from radicalbit_ai_gateway.events.events_processor import emit_event
from radicalbit_ai_gateway.guardrails.guardrails import (
    Conversation,
    GuardrailFlags,
    Reply,
    RequestGuardrails,
    ResponsesReply,
    RouteGuardrails,
    Texts,
)
from radicalbit_ai_gateway.invocation.chat_model_invoker import ChatModelInvoker
from radicalbit_ai_gateway.invocation.decision_model_invoker import (
    DecisionModelInvoker,
    DecisionResponse,
)
from radicalbit_ai_gateway.invocation.embedding_model_invoker import (
    EmbeddingModelInvoker,
)
from radicalbit_ai_gateway.invocation.model_invoker import ModelInvoker
from radicalbit_ai_gateway.invocation.recorder import Call, Tokens
from radicalbit_ai_gateway.invocation.transcription_model_invoker import (
    TranscriptionModelInvoker,
)
from radicalbit_ai_gateway.limiting.limits import (
    Demand,
    InputEstimate,
    RequestLimits,
    RouteLimits,
    Usage,
)
from radicalbit_ai_gateway.llm.messages import (
    AIMessageChunk,
    BaseMessage,
    SystemMessage,
)
from radicalbit_ai_gateway.messages.events import relay_frame
from radicalbit_ai_gateway.messages.request import MessagesRequest
from radicalbit_ai_gateway.models.chat_request import select_message_by_role
from radicalbit_ai_gateway.models.event_payload import RoutingEventPayload
from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.models.fallback import FallbackModelType
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.models.model import ENABLE_PROMPT_CACHE_PARAM, Model
from radicalbit_ai_gateway.models.request_identity import RequestIdentity
from radicalbit_ai_gateway.preprocessing import run_preprocessing
from radicalbit_ai_gateway.responses.events import response_events
from radicalbit_ai_gateway.responses.output import (
    gateway_response,
    message_item,
    usage_token_counts,
)
from radicalbit_ai_gateway.responses.request import (
    ResponsesRequest,
    apply_governance,
    check_supported,
    references_stored_state,
)
from radicalbit_ai_gateway.routing import (
    DecisionRouter,
    DeterministicRouter,
    LLMRouter,
    SemanticRouter,
    TextClassificationRouter,
)
from radicalbit_ai_gateway.routing.common import RoutingSpendRecorder
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.ai_gateway_types import (
    InvokeResponse,
    MessagesPrepared,
    OutputProcessResult,
    PrepareAndValidateResult,
    ResponsesPrepared,
    StreamBufferedResult,
    StreamGenerator,
)
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.audio_duration import estimate_audio_duration_seconds
from radicalbit_ai_gateway.utils.build_user_content import (
    build_user_content,
    build_user_content_from_texts,
)
from radicalbit_ai_gateway.utils.content_utils import ContentUtils
from radicalbit_ai_gateway.utils.exceptions import (
    GatewayBadRequest,
    GuardrailBadRequest,
)
from radicalbit_ai_gateway.utils.state_leaves import string_leaves, with_string_leaves
from radicalbit_ai_gateway.utils.streaming_utils import StreamingUtils
from radicalbit_ai_gateway.utils.trace_attributes import (
    OperationCategory,
    set_operation_category,
    set_streaming,
)

app_config = get_app_config()
logging_config_dict = app_config.log_config.model_dump()
logger = logging.getLogger(app_config.log_config.logger_name)

DECISION_SCREENED_FIELDS = ('state', 'questions')


async def _aiter_list(items: list) -> AsyncIterator:
    for item in items:
        yield item


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


def _chat_demand(messages: list[BaseMessage], model: Model) -> Demand:
    """Return what a chat request demands; ``model`` picks the tokenizer."""
    return Demand(
        input=InputEstimate(build_user_content(messages), model.model),
        output_room=True,
        cost_room=True,
    )


async def _check_limits(limits: RequestLimits, demand: Demand, check=None) -> None:
    """Check ``demand`` on the request's limits, if any applies.

    ``check`` runs the check in a trace span of its own.
    """
    if limits.applies(demand):
        await (check or _check)(limits, demand)


async def _check(limits: RequestLimits, demand: Demand) -> None:
    await limits.check(demand)


def _transcription_demand(audio_bytes: bytes) -> Demand:
    """Return what a transcription demands: its cost and its audio seconds,
    read from the file's header ('unknown' when they can't be).
    """
    seconds = estimate_audio_duration_seconds(audio_bytes)
    return Demand(
        cost_room=True, audio_seconds='unknown' if seconds is None else seconds
    )


_check_in_chat_span = task(name='check_limiters')(_check)
_check_in_embedding_span = task(name='check_embedding_limiters')(_check)


class _RoutingSpend:
    """Charges a request for its routing calls: see ``RoutingSpendRecorder``."""

    def __init__(self, limits: RequestLimits, metrics: ModelInvoker):
        self._limits = limits
        self._metrics = metrics

    async def __call__(
        self,
        model: Model,
        input_tokens: int,
        latency_ms: float,
        *,
        model_type: str,
        target_model_id: str | None = None,
        output_tokens: int | None = None,
    ) -> None:
        target_model_id = target_model_id or model.model_id
        self._metrics.recorder.invocation(
            Call(
                identity=self._limits.identity,
                model_type=model_type,
                target_model_id=target_model_id,
                is_routing=True,
            ),
            model,
            latency_ms,
            tokens=Tokens(input=input_tokens, output=output_tokens),
            fallback_triggered=target_model_id != model.model_id,
        )
        if output_tokens is None:
            # Embedding and decision calls bill input tokens only.
            if input_tokens > 0:
                await self._limits.count(Usage.priced(model, input_tokens))
        else:
            # A chat model router also bills the tokens it answers with.
            await self._limits.charge_call(model, input_tokens, output_tokens)

    def failed(
        self, model: Model, latency_ms: float, *, model_type: str, target_model_id: str
    ) -> None:
        self._metrics.recorder.failure(
            Call(
                identity=self._limits.identity,
                model_type=model_type,
                target_model_id=target_model_id,
                is_routing=True,
            ),
            model,
            latency_ms,
            fallback_triggered=model.model_id != target_model_id,
        )


class GatewayRoute:
    def __init__(
        self,
        gateway_route_config: GatewayRouteConfig,
        chat_models: list[Model] | None,
        embedding_models: list[Model] | None,
        cost_service: CostService,
        gateway_cache: GatewayCache | None,
        httpx_client=None,
        router: DeterministicRouter
        | SemanticRouter
        | TextClassificationRouter
        | DecisionRouter
        | LLMRouter
        | None = None,
        route_limits: RouteLimits = RouteLimits(),
        transcription_models: list[Model] | None = None,
        decision_models: list[Model] | None = None,
        guardrails: RouteGuardrails = RouteGuardrails(),
        project_uuid: str = '',
        project_name: str = '',
    ):
        self.gateway_route_config = gateway_route_config
        self.project_uuid = project_uuid
        self.project_name = project_name
        self._chat_models = chat_models or []
        self._embedding_models = embedding_models or []
        self._transcription_models = transcription_models or []
        self._decision_models = decision_models or []
        self.router = router
        self.guardrails = guardrails
        self.gateway_cache = gateway_cache
        self.route_limits = route_limits
        self.cost_service = cost_service
        fallback_models = self.gateway_route_config.fallback

        self.chat_invoker: ChatModelInvoker | None = None
        chat_models = self._chat_models

        if chat_models:
            chat_fallbacks = [
                fb
                for fb in (fallback_models or [])
                if fb.type == FallbackModelType.CHAT
            ]
            self.chat_invoker = ChatModelInvoker(
                models=chat_models,
                fallbacks=chat_fallbacks,
                cost_service=self.cost_service,
                httpx_client=httpx_client,
            )

        self.embedding_invoker: EmbeddingModelInvoker | None = None
        embedding_models = self._embedding_models

        if embedding_models:
            embedding_fallbacks = [
                fb
                for fb in (fallback_models or [])
                if fb.type == FallbackModelType.EMBEDDING
            ]
            self.embedding_invoker = EmbeddingModelInvoker(
                models=embedding_models,
                fallbacks=embedding_fallbacks,
                cost_service=self.cost_service,
                httpx_client=httpx_client,
            )

        self.transcription_invoker: TranscriptionModelInvoker | None = None
        transcription_models = self._transcription_models

        if transcription_models:
            transcription_fallbacks = [
                fb
                for fb in (fallback_models or [])
                if fb.type == FallbackModelType.TRANSCRIPTION
            ]
            self.transcription_invoker = TranscriptionModelInvoker(
                models=transcription_models,
                fallbacks=transcription_fallbacks,
                cost_service=self.cost_service,
                httpx_client=httpx_client,
            )

        self.decision_invoker: DecisionModelInvoker | None = None
        if self._decision_models:
            decision_fallbacks = [
                fb
                for fb in (fallback_models or [])
                if fb.type == FallbackModelType.DECISION
            ]
            self.decision_invoker = DecisionModelInvoker(
                models=self._decision_models,
                fallbacks=decision_fallbacks,
                cost_service=self.cost_service,
                httpx_client=httpx_client,
            )
        self.ttl = (
            self.gateway_route_config.caching.ttl
            if self.gateway_route_config.caching
            else None
        )
        self.cache = RouteCache.from_config(
            gateway_route_config,
            gateway_cache,
            cost_service,
            self.embedding_invoker,
            self._embedding_models,
        )

    # ============================================================================
    # Chat Invocation Entrypoints
    # ============================================================================

    async def invoke(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        messages: list[BaseMessage],
        route_name: str,
        tools: list[ChatCompletionToolParam] | None,
        tool_choice: ChatCompletionToolChoiceOptionParam | None,
        limits: RequestLimits,
        **kwargs,
    ) -> InvokeResponse:
        if route_name != self.gateway_route_config.route_name:
            raise GatewayBadRequest(f'{route_name} must be the route name')

        prepared = await self._prepare_and_validate_request(
            limits=limits,
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            group_uuid=group_uuid,
            api_key_name=api_key_name,
            group_name=group_name,
            route_name=route_name,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            **kwargs,
        )

        if prepared.input_soft_block:
            return InvokeResponse(
                content=prepared.input_soft_block,
                headers=prepared.guardrail_flags.headers(),
            )

        cached = prepared.cached
        if cached.hit:
            response = cached.value
        else:
            set_operation_category(OperationCategory.INVOCATION)
            response = await self._process_request(
                limits=limits,
                request_uuid=request_uuid,
                api_key_uuid=api_key_uuid,
                group_uuid=group_uuid,
                api_key_name=api_key_name,
                group_name=group_name,
                route_name=route_name,
                redacted_messages=prepared.redacted_messages,
                model_selected=prepared.model_selected,
                tools=tools,
                tool_choice=tool_choice,
                **kwargs,
            )

        # A hit is screened as a model's reply is; only screened replies are
        # stored.
        if self.guardrails.has_output:
            output = await self._process_output(
                limits=limits,
                request_uuid=request_uuid,
                api_key_uuid=api_key_uuid,
                group_uuid=group_uuid,
                api_key_name=api_key_name,
                group_name=group_name,
                response=response,
            )
        else:
            output = OutputProcessResult(response=response)

        await cached.store(output.response)
        return InvokeResponse(
            content=output.response.model_copy(update={'model': route_name}),
            headers={
                **cached.headers(),
                **(prepared.guardrail_flags | output.guardrail_flags).headers(),
            },
        )

    async def prepare_stream(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        messages: list[BaseMessage],
        route_name: str,
        tools: list[ChatCompletionToolParam] | None,
        tool_choice: ChatCompletionToolChoiceOptionParam | None,
        limits: RequestLimits,
        **kwargs,
    ) -> PrepareAndValidateResult:
        return await self._prepare_and_validate_request(
            limits=limits,
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            group_uuid=group_uuid,
            api_key_name=api_key_name,
            group_name=group_name,
            route_name=route_name,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            **kwargs,
        )

    async def invoke_stream_buffered(
        self,
        prepared: PrepareAndValidateResult,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        route_name: str,
        tools: list[ChatCompletionToolParam] | None,
        tool_choice: ChatCompletionToolChoiceOptionParam | None,
        limits: RequestLimits,
        **kwargs,
    ) -> StreamBufferedResult:
        set_streaming()
        if prepared.input_soft_block:
            # For buffered streaming, return the soft block as a single chunk
            chunk = StreamingUtils.build_soft_block_chunk(
                prepared.input_soft_block, route_name
            )
            return [chunk], prepared.guardrail_flags.headers()

        if prepared.cached.hit:
            # Cache hit: screened as a model's reply is, then sent as one chunk.
            cached_response = prepared.cached.value
            text, output_flags = await self._screen_streamed_reply(
                limits,
                request_uuid=request_uuid,
                api_key_uuid=api_key_uuid,
                group_uuid=group_uuid,
                api_key_name=api_key_name,
                group_name=group_name,
                text=cached_response.choices[0].message.content,
            )
            cached_response = _with_content(cached_response, text)
            chunk = StreamingUtils.cached_response_to_chunk(cached_response, route_name)
            chunks = [chunk]

            stream_options = kwargs.get('stream_options')
            if (
                stream_options
                and isinstance(stream_options, dict)
                and stream_options.get('include_usage')
                and cached_response.usage
            ):
                chunks.append(
                    StreamingUtils.build_usage_chunk(
                        final_usage={
                            'input_tokens': cached_response.usage.prompt_tokens,
                            'output_tokens': cached_response.usage.completion_tokens,
                            'total_tokens': cached_response.usage.total_tokens,
                        },
                        model_id_invoked=route_name,
                        request_id=cached_response.id,
                    )
                )

            headers = {
                **prepared.cached.headers(),
                **(prepared.guardrail_flags | output_flags).headers(),
            }
            return chunks, headers

        # Prepare stream options (forces include_usage=True upstream)
        user_stream_options = StreamingUtils.prepare_stream_options(kwargs)
        # Pass original options for the handler to decide on yielding
        kwargs['original_stream_options'] = user_stream_options

        chunks, output_flags = await self._handle_buffered_stream(
            limits=limits,
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            group_uuid=group_uuid,
            api_key_name=api_key_name,
            group_name=group_name,
            route_name=route_name,
            messages=prepared.redacted_messages,
            model_id_invoked=prepared.model_selected.model_id,
            tools=tools,
            tool_choice=tool_choice,
            model_selected=prepared.model_selected,
            cached=prepared.cached,
            **kwargs,
        )
        return chunks, (prepared.guardrail_flags | output_flags).headers()

    async def invoke_stream(
        self,
        prepared: PrepareAndValidateResult,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        route_name: str,
        tools: list[ChatCompletionToolParam] | None,
        tool_choice: ChatCompletionToolChoiceOptionParam | None,
        limits: RequestLimits,
        **kwargs,
    ) -> StreamGenerator:
        set_streaming()
        if prepared.input_soft_block:
            # For streaming, we yield the soft block as a single chunk then stop
            yield StreamingUtils.build_soft_block_chunk(
                prepared.input_soft_block, route_name
            )
            return

        # Prepare stream options (forces include_usage=True upstream)
        user_stream_options = StreamingUtils.prepare_stream_options(kwargs)

        if prepared.cached.hit:
            # Cache hit: screened as a model's reply is, then sent as one
            # chunk. A live stream's route has no output guardrails: the
            # screening changes nothing there.
            text, _ = await self._screen_streamed_reply(
                limits,
                request_uuid=request_uuid,
                api_key_uuid=api_key_uuid,
                group_uuid=group_uuid,
                api_key_name=api_key_name,
                group_name=group_name,
                text=prepared.cached.value.choices[0].message.content,
            )
            yield StreamingUtils.cached_response_to_chunk(
                _with_content(prepared.cached.value, text), route_name
            )
            return

        # Process the request in streaming mode (Standard without buffering)
        set_operation_category(OperationCategory.INVOCATION)
        full_content_text = ''
        final_usage = None

        async for chunk in self.chat_invoker.stream(
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            group_uuid=group_uuid,
            api_key_name=api_key_name,
            group_name=group_name,
            route_name=route_name,
            messages=prepared.redacted_messages,
            model_id=prepared.model_selected.model_id,
            tools=tools,
            tool_choice=tool_choice,
            project_uuid=self.project_uuid,
            project_name=self.project_name,
            **kwargs,
        ):
            if isinstance(chunk, AIMessageChunk):
                result = StreamingUtils.accumulate_chunk_content(
                    chunk, full_content_text
                )
                full_content_text = result.text
                if result.usage_metadata:
                    final_usage = result.usage_metadata

                openai_chunk = StreamingUtils.to_openai_chat_completion_chunk(
                    chunk, model_id_invoked=route_name
                )
                yield openai_chunk
            else:
                logger.warning('Unexpected chunk type during stream: %s', type(chunk))

        # After stream ends, handle usage tracking, caching and events
        if final_usage:
            await limits.count(
                Usage.priced(
                    prepared.model_selected,
                    final_usage.get('input_tokens', 0),
                    final_usage.get('output_tokens', 0),
                )
            )

        # Yield usage chunk ONLY if originally requested by the user
        if (
            final_usage
            and user_stream_options
            and isinstance(user_stream_options, dict)
            and user_stream_options.get('include_usage')
        ):
            yield StreamingUtils.build_usage_chunk(
                final_usage=final_usage,
                model_id_invoked=route_name,
                request_id=request_uuid,
            )

        # A live stream's route has no output guardrails: its text is the
        # screened text. A reply with no text (a tool call) is not stored.
        if full_content_text:
            await prepared.cached.store(
                StreamedReply(
                    full_content_text, final_usage, prepared.model_selected.model_id
                )
            )

    # ============================================================================
    # Responses API
    # ============================================================================

    async def prepare_responses(
        self,
        body: dict,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        limits: RequestLimits,
    ) -> ResponsesPrepared:
        """Apply the route's policies to a Responses API request.

        The policies read the request's texts as chat messages (see
        ``ResponsesRequest``); what they change is written back into the body
        that goes upstream.
        """
        route_name = self.gateway_route_config.route_name
        if not self.chat_invoker:
            raise GatewayBadRequest(f'Route {route_name} has no chat models defined')
        identity = {
            'request_uuid': request_uuid,
            'api_key_uuid': api_key_uuid,
            'group_uuid': group_uuid,
            'api_key_name': api_key_name,
            'group_name': group_name,
        }

        check_supported(body)
        request = ResponsesRequest(body)
        apply_governance(request.body, self.gateway_route_config.responses, route_name)
        allow_fallback = not references_stored_state(request.body)

        set_operation_category(OperationCategory.PREPROCESSING)
        messages = await run_preprocessing(
            request.messages(), self.gateway_route_config.plugins
        )
        guardrails = self._request_guardrails(limits, **identity)
        redaction = await guardrails.redact_input(Conversation(messages))
        # Route on the redacted messages, as the chat path does.
        model_selected = await self._route_chat_request(
            limits=limits,
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            group_uuid=group_uuid,
            api_key_name=api_key_name,
            group_name=group_name,
            messages=redaction.payload.messages(),
        )
        if not self.chat_invoker.supports_responses(model_selected.model_id):
            raise GatewayBadRequest(
                f'Model {model_selected.model_id} of route {route_name} '
                'does not serve the Responses API'
            )

        redacted_messages = redaction.payload.messages()
        prompt_messages = self._apply_config_prompt(redacted_messages, model_selected)
        input_guardrails = await guardrails.check_input(
            Conversation(redacted_messages, skip=prompt_messages), redaction.flags
        )
        if input_guardrails.soft_block:
            return ResponsesPrepared(
                body=request.body,
                limits=limits,
                model_selected=model_selected,
                allow_fallback=allow_fallback,
                identity=identity,
                soft_block=gateway_response(
                    request_uuid,
                    route_name,
                    body,
                    input_guardrails.soft_block.get_soft_block_message(),
                ),
                guardrails_input_triggered=input_guardrails.flags.input_warned,
            )

        if model_selected.effective_prompt:
            request.write_back(redacted_messages[1:])
            request.insert_prompt(redacted_messages[0], model_selected.role)
        else:
            request.write_back(redacted_messages)

        prepared = ResponsesPrepared(
            body=request.body,
            limits=limits,
            model_selected=model_selected,
            allow_fallback=allow_fallback,
            identity=identity,
            guardrails_input_triggered=input_guardrails.flags.input_warned,
        )
        # Limits before the cache, as on chat: a caller over its limit is
        # not served, and the semantic cache's embedding call is not made.
        await _check_limits(
            limits, _chat_demand(redacted_messages, model_selected), _check_in_chat_span
        )
        prepared.cached = await self._request_cache(limits, **identity).lookup(
            ResponsesEntry(request.body)
        )
        return prepared

    async def invoke_responses(
        self, prepared: ResponsesPrepared
    ) -> tuple[dict, dict[str, str]]:
        """Answer a prepared Responses API request; return the response object
        and the gateway's headers.
        """
        route_name = self.gateway_route_config.route_name
        if prepared.soft_block:
            return prepared.soft_block, self._responses_headers(
                prepared, input_blocked=True
            )

        if prepared.cached.hit:
            response = prepared.cached.value
        else:
            set_operation_category(OperationCategory.INVOCATION)
            response, _ = await self.chat_invoker.complete_responses(
                **self._responses_call(prepared)
            )

        (
            response,
            output_triggered,
            output_blocked,
        ) = await self._process_responses_output(prepared, response)
        if not prepared.cached.hit:
            await self._account_responses(prepared, response)
        return {**response, 'model': route_name}, self._responses_headers(
            prepared,
            output_triggered=output_triggered,
            output_blocked=output_blocked,
        )

    async def open_responses_stream(
        self, prepared: ResponsesPrepared
    ) -> tuple[AsyncIterator[str], dict[str, str]]:
        """Stream a prepared Responses API request; return its SSE frames and the
        gateway's headers.

        The upstream's events are relayed as they come, unless the whole reply
        must be known first: a soft block, a cache hit, or a reply the output
        guardrails must pass.
        """
        if prepared.soft_block or prepared.cached.hit or self.guardrails.has_output:
            frames, headers = await self._buffered_responses_frames(prepared)
            return _aiter_list(frames), headers
        return self._live_responses_frames(prepared), self._responses_headers(prepared)

    def _responses_call(self, prepared: ResponsesPrepared) -> dict:
        """Return the arguments of the invoker's call for a prepared request."""
        return {
            **prepared.identity,
            'route_name': self.gateway_route_config.route_name,
            'body': prepared.body,
            'model_id': prepared.model_selected.model_id,
            'allow_fallback': prepared.allow_fallback,
            'project_uuid': self.project_uuid,
            'project_name': self.project_name,
        }

    async def _live_responses_frames(
        self, prepared: ResponsesPrepared
    ) -> AsyncIterator[str]:
        """Relay the upstream's events, then account for the final response."""
        set_streaming()
        set_operation_category(OperationCategory.INVOCATION)
        route_name = self.gateway_route_config.route_name
        final_response = None
        async for event in self.chat_invoker.stream_responses(
            **self._responses_call(prepared)
        ):
            if event.is_final:
                final_response = event.response
            yield event.to_sse(route_name)

        if final_response:
            await self._account_responses(prepared, final_response)

    async def _buffered_responses_frames(
        self, prepared: ResponsesPrepared
    ) -> tuple[list[str], dict[str, str]]:
        """Return the frames of a reply known whole before streaming.

        A reply the gateway changed or built is streamed as OpenAI streams it,
        each text in one delta; an unchanged one as the upstream sent it.
        """
        set_streaming()
        if prepared.soft_block or prepared.cached.hit:
            response, headers = await self.invoke_responses(prepared)
            return response_events(response), headers

        route_name = self.gateway_route_config.route_name
        set_operation_category(OperationCategory.INVOCATION)
        frames: list[str] = []
        final_response = None
        async for event in self.chat_invoker.stream_responses(
            **self._responses_call(prepared)
        ):
            if event.is_final:
                final_response = event.response
            frames.append(event.to_sse(route_name))
        if final_response is None:
            return frames, self._responses_headers(prepared)

        (
            response,
            output_triggered,
            output_blocked,
        ) = await self._process_responses_output(prepared, final_response)
        await self._account_responses(prepared, response)
        if response != final_response:
            frames = response_events({**response, 'model': route_name})
        return frames, self._responses_headers(
            prepared, output_triggered=output_triggered, output_blocked=output_blocked
        )

    def _responses_headers(
        self,
        prepared: ResponsesPrepared,
        input_blocked: bool = False,
        output_triggered: bool = False,
        output_blocked: bool = False,
    ) -> dict[str, str]:
        flags = GuardrailFlags(
            input_warned=prepared.guardrails_input_triggered,
            input_blocked=input_blocked,
            output_warned=output_triggered,
            output_blocked=output_blocked,
        )
        return {**prepared.cached.headers(), **flags.headers()}

    @workflow(name='apply_responses_output_guardrails')
    async def _process_responses_output(
        self, prepared: ResponsesPrepared, response: dict
    ) -> tuple[dict, bool, bool]:
        """Apply the output guardrails to the text of a response.

        Returns the response, whether a guardrail triggered, and whether a
        soft block replaced the reply.
        """
        if not self.guardrails.has_output:
            return response, False, False
        guardrails = self._request_guardrails(prepared.limits, **prepared.identity)
        screened = await guardrails.screen_output(ResponsesReply.of(response))
        if screened.soft_block:
            text = screened.soft_block.get_soft_block_message()
            return {**response, 'output': [message_item(text)]}, True, True
        return screened.payload.response(), screened.flags.output_warned, False

    async def _account_responses(
        self, prepared: ResponsesPrepared, response: dict
    ) -> None:
        """Count a model's response against the limits, and cache it."""
        input_tokens, _, output_tokens = usage_token_counts(response.get('usage'))
        await prepared.limits.count(
            Usage.priced(prepared.model_selected, input_tokens, output_tokens)
        )
        if response.get('status') == 'completed':
            await prepared.cached.store(
                {**response, 'model': prepared.model_selected.model_id}
            )

    # ============================================================================
    # Messages API
    # ============================================================================

    async def prepare_messages(
        self,
        body: dict,
        headers: dict[str, str],
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        limits: RequestLimits,
    ) -> MessagesPrepared:
        """Apply the route's policies to an Anthropic Messages API request.

        The policies read the request's texts as chat messages (see
        ``MessagesRequest``); what they change is written back into the body
        that goes upstream. ``limits`` are charged for the routing calls.
        """
        route_name = self.gateway_route_config.route_name
        if not self.chat_invoker:
            raise GatewayBadRequest(f'Route {route_name} has no chat models defined')
        identity = {
            'request_uuid': request_uuid,
            'api_key_uuid': api_key_uuid,
            'group_uuid': group_uuid,
            'api_key_name': api_key_name,
            'group_name': group_name,
        }

        request = MessagesRequest(body)
        set_operation_category(OperationCategory.PREPROCESSING)
        messages = await run_preprocessing(
            request.messages(), self.gateway_route_config.plugins
        )
        # Input guardrails (redact before routing, check, soft block) go here,
        # as on the Responses API: AG-1132.
        model_selected = await self._route_chat_request(
            **identity,
            messages=messages,
            limits=limits,
        )
        if not self.chat_invoker.supports_messages(model_selected.model_id):
            raise GatewayBadRequest(
                f'Model {model_selected.model_id} of route {route_name} '
                'does not serve the Messages API'
            )

        prompt_messages = self._apply_config_prompt(messages, model_selected)
        request.write_back(messages[prompt_messages:])
        if prompt_messages:
            # A deliberate choice, as on the Responses API: the configured
            # prompt goes first in ``system``. It changes the prefix the
            # client's prompt cache sees.
            request.insert_system_prompt(messages[0])

        # The cache lookup and the limits go here, as on the Responses API:
        # AG-1132.
        return MessagesPrepared(
            body=request.body,
            headers=headers,
            model_selected=model_selected,
            identity=identity,
        )

    def _messages_call(self, prepared: MessagesPrepared) -> dict:
        """Return the arguments of the invoker's call for a prepared request."""
        return {
            **prepared.identity,
            'route_name': self.gateway_route_config.route_name,
            'body': prepared.body,
            'headers': prepared.headers,
            'model_id': prepared.model_selected.model_id,
            'project_uuid': self.project_uuid,
            'project_name': self.project_name,
        }

    async def invoke_messages(self, prepared: MessagesPrepared) -> dict:
        """Answer a prepared Messages API request; return the message object."""
        set_operation_category(OperationCategory.INVOCATION)
        message, _ = await self.chat_invoker.complete_messages(
            **self._messages_call(prepared)
        )
        # Output guardrails and usage accounting go here: AG-1132.
        return {**message, 'model': self.gateway_route_config.route_name}

    async def stream_messages(self, prepared: MessagesPrepared) -> AsyncIterator[str]:
        """Relay a prepared Messages API request's upstream events as SSE frames."""
        set_streaming()
        set_operation_category(OperationCategory.INVOCATION)
        route_name = self.gateway_route_config.route_name
        async for event, data in self.chat_invoker.stream_messages(
            **self._messages_call(prepared)
        ):
            yield relay_frame(event, data, route_name)
        # Buffered mode, for output guardrails and the cache: AG-1132.

    async def invoke_embeddings(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        route_name: str,
        input_texts: list[str],
        limits: RequestLimits,
    ) -> CreateEmbeddingResponse:
        if route_name != self.gateway_route_config.route_name:
            raise GatewayBadRequest(f'{route_name} must be the route name')

        if not self.embedding_invoker:
            raise GatewayBadRequest(
                f'Route {route_name} has no embedding models defined'
            )

        # Prepare request for processing
        set_operation_category(OperationCategory.ROUTING)
        model_selected = self._select_and_prepare_embedding_model()

        # Limits come first, before the judges spend: see
        # _prepare_and_validate_request.
        demand = Demand(
            input=InputEstimate(
                build_user_content_from_texts(input_texts), model_selected.model
            ),
            cost_room=True,
        )
        await _check_limits(limits, demand, _check_in_embedding_span)

        guardrails = self._request_guardrails(
            limits,
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            group_uuid=group_uuid,
            api_key_name=api_key_name,
            group_name=group_name,
        )
        redaction = await guardrails.redact_input(Texts(input_texts))
        try:
            screened = await guardrails.check_input(redaction.payload)
        except GuardrailBadRequest as e:
            logger.warning('Guardrail BLOCK triggered: %s', e.log_message)
            raise
        if screened.soft_block:
            return screened.soft_block.build_soft_block_embedding_response(route_name)
        redacted_texts = screened.payload.items

        cached = await self._request_cache(
            limits,
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            group_uuid=group_uuid,
            api_key_name=api_key_name,
            group_name=group_name,
        ).lookup(EmbeddingEntry(redacted_texts))
        if cached.hit:
            return cached.value

        set_operation_category(OperationCategory.INVOCATION)
        response = await self.embedding_invoker.embed(
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            group_uuid=group_uuid,
            api_key_name=api_key_name,
            group_name=group_name,
            route_name=route_name,
            input_texts=redacted_texts,
            model_id=model_selected.model_id,
            project_uuid=self.project_uuid,
            project_name=self.project_name,
        )

        if response.usage:
            await limits.count(
                Usage.priced(model_selected, response.usage.prompt_tokens)
            )

        await cached.store(response)
        return response

    async def invoke_transcription(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        route_name: str,
        audio_bytes: bytes,
        filename: str,
        content_type: str | None,
        limits: RequestLimits,
        requested_response_format: str = 'json',
        language: str | None = None,
        prompt: str | None = None,
        temperature: float | None = None,
    ) -> Transcription | TranscriptionVerbose:
        if route_name != self.gateway_route_config.route_name:
            raise GatewayBadRequest(f'{route_name} must be the route name')

        if not self.transcription_invoker:
            raise GatewayBadRequest(
                f'Route {route_name} has no transcription models defined'
            )

        set_operation_category(OperationCategory.ROUTING)
        model_selected = self._select_and_prepare_transcription_model()

        # Limits before the cache, as on chat: a caller over its limit is not
        # served. A hit spends no audio: its seconds count only on a miss.
        demand = _transcription_demand(audio_bytes)
        if limits.applies(demand):
            await limits.check(demand, count=False)

        cached = await self._request_cache(
            limits,
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            group_uuid=group_uuid,
            api_key_name=api_key_name,
            group_name=group_name,
        ).lookup(
            TranscriptionEntry(
                audio_bytes,
                model_selected.model_id,
                requested_response_format,
                language,
                prompt,
                temperature,
            )
        )
        if cached.hit:
            return cached.value

        await limits.count_checked(demand)
        set_operation_category(OperationCategory.INVOCATION)
        result = await self.transcription_invoker.transcribe(
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            group_uuid=group_uuid,
            api_key_name=api_key_name,
            group_name=group_name,
            route_name=route_name,
            audio_bytes=audio_bytes,
            filename=filename,
            content_type=content_type,
            model_id=model_selected.model_id,
            requested_response_format=requested_response_format,
            language=language,
            prompt=prompt,
            temperature=temperature,
            project_uuid=self.project_uuid,
            project_name=self.project_name,
        )

        await limits.count(Usage.transcription(model_selected, result.usage))

        await cached.store(result)
        return result

    async def invoke_transcription_stream(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        route_name: str,
        audio_bytes: bytes,
        filename: str,
        content_type: str | None,
        limits: RequestLimits,
        language: str | None = None,
        prompt: str | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[TranscriptionStreamEvent]:
        if route_name != self.gateway_route_config.route_name:
            raise GatewayBadRequest(f'{route_name} must be the route name')

        if not self.transcription_invoker:
            raise GatewayBadRequest(
                f'Route {route_name} has no transcription models defined'
            )

        set_operation_category(OperationCategory.ROUTING)
        model_selected = self._select_and_prepare_transcription_model()

        await _check_limits(limits, _transcription_demand(audio_bytes))

        set_operation_category(OperationCategory.INVOCATION)
        final_event: TranscriptionStreamEvent | None = None
        async for event in self.transcription_invoker.stream(
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            group_uuid=group_uuid,
            api_key_name=api_key_name,
            group_name=group_name,
            route_name=route_name,
            audio_bytes=audio_bytes,
            filename=filename,
            content_type=content_type,
            model_id=model_selected.model_id,
            language=language,
            prompt=prompt,
            temperature=temperature,
            project_uuid=self.project_uuid,
            project_name=self.project_name,
        ):
            final_event = event
            yield event

        if final_event is not None:
            await limits.count(
                Usage.transcription(model_selected, getattr(final_event, 'usage', None))
            )

    async def invoke_decision(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        route_name: str,
        body: dict,
        limits: RequestLimits,
    ) -> DecisionResponse:
        if route_name != self.gateway_route_config.route_name:
            raise GatewayBadRequest(f'{route_name} must be the route name')

        if not self.decision_invoker:
            raise GatewayBadRequest(
                f'Route {route_name} has no decision models defined'
            )

        # The first decision model listed on the route serves its traffic.
        set_operation_category(OperationCategory.ROUTING)
        model_selected = self._decision_models[0]

        # Limits come first, before the judges spend: see
        # _prepare_and_validate_request. The input size is known only from
        # the response, so a limit blocks only when its counter is full.
        await _check_limits(limits, Demand(input='room', cost_room=True))

        screened = {f: body[f] for f in DECISION_SCREENED_FIELDS if f in body}
        if self.gateway_route_config.guardrails and screened:
            body = {
                **body,
                **await self._screen_decision_fields(
                    self._request_guardrails(
                        limits,
                        request_uuid=request_uuid,
                        api_key_uuid=api_key_uuid,
                        group_uuid=group_uuid,
                        api_key_name=api_key_name,
                        group_name=group_name,
                    ),
                    screened,
                ),
            }

        cached = await self._request_cache(
            limits,
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            group_uuid=group_uuid,
            api_key_name=api_key_name,
            group_name=group_name,
        ).lookup(
            DecisionEntry(
                body.get('state'), body.get('questions'), model_selected.model_id
            )
        )
        if cached.hit:
            return DecisionResponse(
                status_code=cached.value['status_code'],
                content=cached.value['content'].encode('utf-8'),
                media_type=cached.value['media_type'],
            )

        set_operation_category(OperationCategory.INVOCATION)
        response = await self.decision_invoker.decide(
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            group_uuid=group_uuid,
            api_key_name=api_key_name,
            group_name=group_name,
            route_name=route_name,
            body=body,
            model_id=model_selected.model_id,
            project_uuid=self.project_uuid,
            project_name=self.project_name,
        )
        if response.model_invoked is not None:
            # Typesafe bills input tokens only: output-token counters get nothing.
            if response.input_tokens > 0:
                await limits.count(
                    Usage.priced(response.model_invoked, response.input_tokens)
                )
            await cached.store(
                {
                    'status_code': response.status_code,
                    'content': response.content.decode('utf-8'),
                    'media_type': response.media_type,
                    'model_id': response.model_invoked.model_id,
                    'input_tokens': response.input_tokens,
                }
            )
        return response

    def _routing_spend_recorder(
        self, limits: RequestLimits, metrics: ModelInvoker
    ) -> RoutingSpendRecorder:
        """Charge a routing call to the request, as a judge call is (ADR 0006)."""
        return _RoutingSpend(limits, metrics)

    # ============================================================================
    # Pre Process Request
    # ============================================================================
    async def _prepare_and_validate_request(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        route_name: str,
        messages: list[BaseMessage],
        tools: list[ChatCompletionToolParam] | None,
        tool_choice: ChatCompletionToolChoiceOptionParam | None,
        limits: RequestLimits,
        **kwargs,
    ) -> PrepareAndValidateResult:
        """Prepare a common pre-invocation logic: validation, guardrails, cache, limiters."""
        if route_name != self.gateway_route_config.route_name:
            raise GatewayBadRequest(f'{route_name} must be the route name')

        if not self.chat_invoker:
            raise GatewayBadRequest(f'Route {route_name} has no chat models defined')

        # Limits come first, before anything that spends (routing, judges,
        # semantic cache, the model). A judge's spend then counts toward the
        # next request. Routing has not run yet: the first chat model only
        # picks the tokenizer for the input estimate.
        await _check_limits(
            limits, _chat_demand(messages, self._chat_models[0]), _check_in_chat_span
        )

        # Preprocessing plugins: transform the raw client messages first, before
        # routing and before the configured system prompt is injected, so plugins
        # only ever see the client's messages. No-op when no plugin is enabled;
        # fail-closed if a plugin raises.
        set_operation_category(OperationCategory.PREPROCESSING)
        messages = await run_preprocessing(messages, self.gateway_route_config.plugins)

        guardrails = self._request_guardrails(
            limits,
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            group_uuid=group_uuid,
            api_key_name=api_key_name,
            group_name=group_name,
        )
        redaction = await guardrails.redact_input(Conversation(messages))
        redacted_messages = redaction.payload.messages()

        # Route on the redacted messages, so no router (and no service it
        # calls) sees text a redact guardrail masks.
        model_selected = await self._route_chat_request(
            limits=limits,
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            group_uuid=group_uuid,
            api_key_name=api_key_name,
            group_name=group_name,
            messages=redacted_messages,
        )

        # Inject the route's configured system prompt after routing and after
        # redaction: plugins, routers and redact guardrails never see it.
        # Input guardrails skip the prompt: it is not part of the conversation.
        prompt_messages = self._apply_config_prompt(redacted_messages, model_selected)

        input_guardrails = await guardrails.check_input(
            Conversation(redacted_messages, skip=prompt_messages), redaction.flags
        )
        guardrails_input_triggered = input_guardrails.flags.input_warned
        guardrails_block_triggered = (
            False  # Only tracks BLOCK/SOFT_BLOCK, not REDACT or WARN
        )
        if input_guardrails.soft_block:
            # SOFT_BLOCK triggers the block header
            return PrepareAndValidateResult(
                model_selected=model_selected,
                redacted_messages=redacted_messages,
                input_soft_block=input_guardrails.soft_block.build_soft_block_response(
                    self.gateway_route_config.route_name
                ),
                guardrails_input_triggered=guardrails_input_triggered,
                guardrails_block_triggered=True,
            )

        # The cache reads the redacted messages, as the model does: no text a
        # redaction masks reaches the key or the semantic cache's embedding
        # provider (ADR 0010).
        cached = await self._request_cache(
            limits,
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            group_uuid=group_uuid,
            api_key_name=api_key_name,
            group_name=group_name,
        ).lookup(
            ChatEntry(
                redacted_messages,
                tools,
                tool_choice,
                kwargs,
                stream=bool(kwargs.get('stream')),
            )
        )
        return PrepareAndValidateResult(
            model_selected=model_selected,
            redacted_messages=redacted_messages,
            cached=cached,
            input_soft_block=None,
            guardrails_input_triggered=guardrails_input_triggered,
            guardrails_block_triggered=guardrails_block_triggered,
        )

    @task(name='select_model')
    async def _select_chat_model(
        self, messages: list[BaseMessage], limits: RequestLimits
    ) -> Model:
        """Select the chat model for this request based on the routing config."""
        if self.router:
            # Routing runs on chat routes: the chat invoker emits its cost events.
            model_selected = await self.router.select_model(
                messages,
                self._routing_spend_recorder(limits, self.chat_invoker)
                if self.chat_invoker
                else None,
            )
        else:
            model_selected = self._chat_models[0]

        logger.debug('Selected chat model: %s', model_selected.model_id)

        return model_selected

    async def _route_chat_request(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        messages: list[BaseMessage],
        limits: RequestLimits,
    ) -> Model:
        """Select the chat model of a request and record the routing decision."""
        set_operation_category(OperationCategory.ROUTING)
        model_selected = await self._select_chat_model(messages, limits)

        if self.router and self.gateway_route_config.routing:
            emit_event(
                RoutingEventPayload(
                    value=1.0,
                    request_uuid=request_uuid,
                    event_type=EventType.ROUTING,
                    route_name=self.gateway_route_config.route_name,
                    api_key_uuid=api_key_uuid,
                    api_key_name=api_key_name,
                    group_uuid=group_uuid,
                    group_name=group_name,
                    project_uuid=self.project_uuid,
                    project_name=self.project_name,
                    routing_name=self.gateway_route_config.routing,
                    selected_model_id=model_selected.model_id,
                )
            )
        return model_selected

    def _apply_config_prompt(
        self, messages: list[BaseMessage], model_selected: Model
    ) -> int:
        """Prepend the route's configured system prompt to *messages* in place.

        Runs *after* preprocessing so the configured prompt is never exposed to
        preprocessing plugins. Return how many messages it added (0 or 1).
        """
        config_prompt, role = model_selected.effective_prompt, model_selected.role

        logger.debug(
            'Config prompt for model %s: %s and role: %s',
            model_selected.model_id,
            config_prompt,
            role,
        )

        if config_prompt:
            logger.debug('Adding config prompt to messages')
            enable_prompt_cache = bool(
                (model_selected.params or {}).get(ENABLE_PROMPT_CACHE_PARAM, False)
            )
            if model_selected.model.startswith('anthropic/') and enable_prompt_cache:
                # Wrap the system prompt as a content block with cache_control so Anthropic
                # caches it across requests (requires enable_prompt_cache: true in model params)
                system_msg = SystemMessage(
                    content=[
                        {
                            'type': 'text',
                            'text': config_prompt,
                            'cache_control': {'type': 'ephemeral'},
                        }
                    ]
                )
            else:
                system_msg = select_message_by_role(
                    content=config_prompt, role=role, tool_calls=[], tool_call_id=None
                )
            messages[:] = [system_msg, *messages]
            return 1
        return 0

    def _get_first_embedding_model(self) -> Model | None:
        """Return the first embedding model"""
        if not self._embedding_models:
            return None
        return self._embedding_models[0]

    @task(name='select_embedding_model')
    def _select_and_prepare_embedding_model(self) -> Model:
        """Select embedding model for embedding invocation"""
        model_selected = self._get_first_embedding_model()
        if not model_selected:
            raise ValueError('Configuration for embedding model not found.')

        logger.debug(
            'Selected embedding model: %s',
            model_selected.model_id,
        )

        return model_selected

    def _get_first_transcription_model(self) -> Model | None:
        """Return the first transcription model"""
        if not self._transcription_models:
            return None
        return self._transcription_models[0]

    @task(name='select_transcription_model')
    def _select_and_prepare_transcription_model(self) -> Model:
        """Select transcription model for transcription invocation"""
        model_selected = self._get_first_transcription_model()
        if not model_selected:
            raise ValueError('Configuration for transcription model not found.')

        logger.debug(
            'Selected transcription model: %s',
            model_selected.model_id,
        )

        return model_selected

    # ============================================================================
    # Post Process Request
    # ============================================================================
    async def _process_request(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        route_name: str,
        redacted_messages: list[BaseMessage],
        model_selected: Model,
        tools: list[ChatCompletionToolParam] | None,
        tool_choice: ChatCompletionToolChoiceOptionParam | None,
        limits: RequestLimits,
        **kwargs,
    ) -> ChatCompletion:
        """Process the main request."""
        logger.debug(
            'Processing request for model %s with %d messages.',
            model_selected.model_id,
            len(redacted_messages),
        )

        response = await self.chat_invoker.complete(
            route_name=route_name,
            messages=redacted_messages,
            model_id=model_selected.model_id,
            tools=tools,
            tool_choice=tool_choice,
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            group_uuid=group_uuid,
            api_key_name=api_key_name,
            group_name=group_name,
            project_uuid=self.project_uuid,
            project_name=self.project_name,
            **kwargs,
        )

        # Handle usage tracking
        if response.usage:
            await limits.count(
                Usage.priced(
                    model_selected,
                    response.usage.prompt_tokens,
                    response.usage.completion_tokens,
                )
            )

        return response

    @workflow(name='apply_output_guardrails')
    async def _process_output(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        response: ChatCompletion,
        limits: RequestLimits,
    ) -> OutputProcessResult:
        """Apply the output guardrails to a chat completion."""
        guardrails = self._request_guardrails(
            limits,
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            group_uuid=group_uuid,
            api_key_name=api_key_name,
            group_name=group_name,
        )
        screened = await guardrails.screen_output(
            Reply(response.choices[0].message.content)
        )
        if screened.soft_block:
            blocked = screened.soft_block.build_soft_block_response(
                self.gateway_route_config.route_name
            )
            return OutputProcessResult(
                response=blocked.model_copy(
                    update={
                        'usage': response.usage,
                        'created': response.created,
                        'id': response.id,
                    }
                ),
                guardrail_flags=screened.flags,
            )

        normalized_output = ContentUtils.normalize_openai_message_content(
            screened.payload.text
        )
        return OutputProcessResult(
            response=response.model_copy(
                update={
                    'choices': [
                        response.choices[0].model_copy(
                            update={
                                'message': response.choices[0].message.model_copy(
                                    update={'content': normalized_output}
                                )
                            }
                        )
                    ],
                }
            ),
            guardrail_flags=screened.flags,
        )

    # ============================================================================
    # Guardrails
    # ============================================================================
    def _request_guardrails(
        self,
        limits: RequestLimits,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
    ) -> RequestGuardrails:
        """Return the guardrails of a request; its judges' calls are charged
        to its limits (ADR 0006).
        """
        return self.guardrails.for_request(
            self._identity(
                request_uuid, api_key_uuid, group_uuid, api_key_name, group_name
            ),
            limits.charge_call,
        )

    def _request_cache(
        self,
        limits: RequestLimits,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
    ) -> RequestCache:
        """Return the cache of a request; the semantic cache's embedding call
        is charged to its limits (ADR 0006).
        """
        return self.cache.for_request(
            self._identity(
                request_uuid, api_key_uuid, group_uuid, api_key_name, group_name
            ),
            limits,
        )

    def _identity(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
    ) -> RequestIdentity:
        return RequestIdentity(
            request_uuid=request_uuid,
            route_name=self.gateway_route_config.route_name,
            api_key_uuid=api_key_uuid,
            api_key_name=api_key_name,
            group_uuid=group_uuid,
            group_name=group_name,
            project_uuid=self.project_uuid,
            project_name=self.project_name,
        )

    @staticmethod
    async def _screen_decision_fields(
        guardrails: RequestGuardrails, fields: dict[str, Any]
    ) -> dict[str, Any]:
        """Screen each string leaf of `fields` (`state` and `questions`) as one
        text. Return `fields` with the leaves redacted.

        A soft block raises the 400 a block raises (ADR 0005): Typesafe's 200
        body has no room for it. It is still recorded as a soft block.
        """
        texts = string_leaves(fields)
        if not texts:
            return fields
        screened = await guardrails.screen_input(Texts(texts))
        if screened.soft_block:
            raise GuardrailBadRequest(
                screened.soft_block.get_soft_block_message(),
                screened.soft_block.guardrail,
            )
        return with_string_leaves(fields, screened.payload.items)

    # ============================================================================
    # Streaming
    # ============================================================================

    @workflow(name='stream_with_output_guardrails')
    async def _handle_buffered_stream(
        self,
        limits: RequestLimits,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        route_name: str,
        messages: list[BaseMessage],
        model_id_invoked: str,
        tools: list[ChatCompletionToolParam] | None,
        tool_choice: ChatCompletionToolChoiceOptionParam | None,
        model_selected: Model,
        cached: Cached,
        **kwargs,
    ):
        """Stream the model's reply whole, so the output guardrails can read
        it. Return its chunks and what the output guardrails did.
        """
        original_stream_options = kwargs.pop('original_stream_options', None)
        full_content_text = ''
        final_usage = None
        buffered_chunks = []

        set_operation_category(OperationCategory.INVOCATION)
        async for chunk in self.chat_invoker.stream(
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            group_uuid=group_uuid,
            api_key_name=api_key_name,
            group_name=group_name,
            route_name=route_name,
            messages=messages,
            model_id=model_id_invoked,
            tools=tools,
            tool_choice=tool_choice,
            project_uuid=self.project_uuid,
            project_name=self.project_name,
            **kwargs,
        ):
            if isinstance(chunk, AIMessageChunk):
                buffered_chunks.append(chunk)
                result = StreamingUtils.accumulate_chunk_content(
                    chunk, full_content_text
                )
                full_content_text = result.text
                if result.usage_metadata:
                    final_usage = result.usage_metadata

        # Output guardrails read the whole reply: redact, then check.
        text, output_flags = await self._screen_streamed_reply(
            limits,
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            group_uuid=group_uuid,
            api_key_name=api_key_name,
            group_name=group_name,
            text=full_content_text,
            usage=final_usage,
        )
        if text != full_content_text:
            buffered_chunks = _with_text(buffered_chunks, text)

        # Cache the screened reply. A reply with no text (a tool call) is not
        # stored: it would answer the next request with nothing.
        if text:
            await cached.store(
                StreamedReply(text, final_usage, model_id_invoked, request_uuid)
            )

        # Count usage for token and budget limiting
        if final_usage:
            await limits.count(
                Usage.priced(
                    model_selected,
                    final_usage.get('input_tokens', 0),
                    final_usage.get('output_tokens', 0),
                )
            )

        # If passed, send the buffered chunks
        chunks = [
            StreamingUtils.to_openai_chat_completion_chunk(
                chunk, model_id_invoked=route_name
            )
            for chunk in buffered_chunks
        ]
        if (
            final_usage
            and original_stream_options
            and isinstance(original_stream_options, dict)
            and original_stream_options.get('include_usage')
        ):
            chunks.append(
                StreamingUtils.build_usage_chunk(
                    final_usage=final_usage,
                    model_id_invoked=route_name,
                    request_id=request_uuid,
                )
            )
        return chunks, output_flags

    async def _screen_streamed_reply(
        self,
        limits: RequestLimits,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        text: str | None,
        usage: dict | None = None,
    ) -> tuple[str | None, GuardrailFlags]:
        """Apply the output guardrails to a streamed reply's text, or to a
        cache hit sent as a stream. Return the text to send and what the
        guardrails did.

        A reply already streamed cannot be replaced: a soft block answers
        with the 400 the global handler renders.
        """
        guardrails = self._request_guardrails(
            limits,
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            group_uuid=group_uuid,
            api_key_name=api_key_name,
            group_name=group_name,
        )
        screened = await guardrails.screen_output(Reply(text, usage=usage))
        if screened.soft_block:
            raise GuardrailBadRequest(
                message=screened.soft_block.get_soft_block_message(),
                guardrail=screened.soft_block.guardrail,
                reason={'action': 'soft_block'},
            )
        return screened.payload.text, screened.flags
