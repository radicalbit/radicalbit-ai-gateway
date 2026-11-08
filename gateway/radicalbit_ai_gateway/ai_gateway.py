from collections.abc import AsyncIterator
import datetime
import json
import logging
import time
from typing import Any

import numpy as np
from openai.types.audio.transcription import Transcription
from openai.types.audio.transcription_stream_event import TranscriptionStreamEvent
from openai.types.audio.transcription_verbose import TranscriptionVerbose
from openai.types.chat import ChatCompletionToolChoiceOptionParam
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.chat.chat_completion_tool_param import ChatCompletionToolParam
from openai.types.completion_usage import CompletionUsage
from openai.types.create_embedding_response import CreateEmbeddingResponse
from traceloop.sdk.decorators import task, workflow

from radicalbit_ai_gateway.caching.gateway_cache import GatewayCache
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
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from radicalbit_ai_gateway.messages.events import relay_frame
from radicalbit_ai_gateway.messages.request import MessagesRequest
from radicalbit_ai_gateway.metrics.define_metrics import (
    cache_hit_counter,
    cache_input_tokens,
    cache_output_tokens,
)
from radicalbit_ai_gateway.models.caching import CacheType
from radicalbit_ai_gateway.models.chat_request import select_message_by_role
from radicalbit_ai_gateway.models.event_payload import (
    CacheEventPayload,
    RoutingEventPayload,
)
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
    cache_signature,
    check_supported,
    last_user_text,
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
    CacheResult,
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
from radicalbit_ai_gateway.utils.chat_utils import ChatUtils
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


def _parse_cached_response_object(raw: str | None) -> dict | None:
    """Return a cached Responses API response object; a chat completion is a miss.

    A semantic cache shares a route's entries between endpoints.
    """
    if not raw:
        return None
    try:
        cached = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(cached, dict) or cached.get('object') != 'response':
        return None
    return cached


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

        if prepared.cached_response:
            # Cache hit: return content with cache hit header
            if self.guardrails.has_output:
                output = await self._process_output(
                    limits=limits,
                    request_uuid=request_uuid,
                    api_key_uuid=api_key_uuid,
                    group_uuid=group_uuid,
                    api_key_name=api_key_name,
                    group_name=group_name,
                    response=prepared.cached_response,
                )
                content = output.response.model_copy(update={'model': route_name})
                flags = prepared.guardrail_flags | output.guardrail_flags
                return InvokeResponse(
                    content=content,
                    headers={'X-RB-AIGATEWAY-CACHE-HIT': 'true', **flags.headers()},
                )
            content = prepared.cached_response.model_copy(update={'model': route_name})
            return InvokeResponse(
                content=content,
                headers={
                    'X-RB-AIGATEWAY-CACHE-HIT': 'true',
                    **prepared.guardrail_flags.headers(),
                },
            )

        # Process the request
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

        # Handle output processing
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

        # Cache the response
        if self.gateway_cache and prepared.cache_key:
            set_operation_category(OperationCategory.CACHE)
            await self._cache_response(
                output.response,
                prepared.cache_key,
                route_name,
                api_key_uuid,
                prepared.embeddings,
            )
        return InvokeResponse(
            content=output.response.model_copy(update={'model': route_name}),
            headers=(prepared.guardrail_flags | output.guardrail_flags).headers(),
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

        cached_response = prepared.cached_response
        if cached_response:
            # Cache hit: return as a list containing a single chunk
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
                'X-RB-AIGATEWAY-CACHE-HIT': 'true',
                **prepared.guardrail_flags.headers(),
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
            cache_key=prepared.cache_key,
            embeddings=prepared.embeddings,
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

        if prepared.cached_response:
            # Cache hit: yield as a chunk
            yield StreamingUtils.cached_response_to_chunk(
                prepared.cached_response, route_name
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

        # Cache the full response if enabled
        if self.gateway_cache and prepared.cache_key and full_content_text:
            set_operation_category(OperationCategory.CACHE)
            await self._build_and_cache_stream_response(
                full_content_text=full_content_text,
                final_usage=final_usage,
                model_id_invoked=prepared.model_selected.model_id,
                cache_key=prepared.cache_key,
                route_name=route_name,
                key_uuid=api_key_uuid,
                embeddings=prepared.embeddings,
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
        if self.gateway_cache:
            set_operation_category(OperationCategory.CACHE)
            await self._lookup_responses_cache(prepared)
            if prepared.cached_response:
                return prepared

        await _check_limits(
            limits, _chat_demand(redacted_messages, model_selected), _check_in_chat_span
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

        cache_hit = prepared.cached_response is not None
        if cache_hit:
            response = prepared.cached_response
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
        if not cache_hit:
            await self._account_responses(prepared, response)
        return {**response, 'model': route_name}, self._responses_headers(
            prepared,
            output_triggered=output_triggered,
            output_blocked=output_blocked,
            cache_hit=cache_hit,
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
        if (
            prepared.soft_block
            or prepared.cached_response
            or self.guardrails.has_output
        ):
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
        if prepared.soft_block or prepared.cached_response:
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
        cache_hit: bool = False,
    ) -> dict[str, str]:
        flags = GuardrailFlags(
            input_warned=prepared.guardrails_input_triggered,
            input_blocked=input_blocked,
            output_warned=output_triggered,
            output_blocked=output_blocked,
        )
        cache = {'X-RB-AIGATEWAY-CACHE-HIT': 'true'} if cache_hit else {}
        return {**cache, **flags.headers()}

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
        if (
            self.gateway_cache
            and prepared.cache_key
            and response.get('status') == 'completed'
        ):
            set_operation_category(OperationCategory.CACHE)
            await self._cache_response_object(
                json.dumps({**response, 'model': prepared.model_selected.model_id}),
                prepared.cache_key,
                self.gateway_route_config.route_name,
                prepared.identity['api_key_uuid'],
                prepared.embeddings,
            )

    @task(name='lookup_responses_cache')
    async def _lookup_responses_cache(self, prepared: ResponsesPrepared) -> None:
        """Set the cache key of a prepared request, and its cached response on a hit."""
        signature = cache_signature(prepared.body)
        if signature is None:
            return
        route_name = self.gateway_route_config.route_name
        prepared.cache_key = self.gateway_cache.generate_responses_cache_key(
            project_uuid=self.project_uuid,
            route_name=route_name,
            key_uuid=prepared.identity['api_key_uuid'],
            signature=signature,
        )
        user_content = last_user_text(prepared.body)
        if self.gateway_cache.cache_type == CacheType.SEMANTIC:
            embedding_model_selected = self._get_first_embedding_model()
            if user_content and embedding_model_selected:
                prepared.embeddings = await self._generate_embedding_for_semantic_cache(
                    text=user_content,
                    **prepared.identity,
                    route_name=route_name,
                    model_id_selected=embedding_model_selected.model_id,
                )
            if prepared.embeddings is None:
                # Without embeddings the semantic cache can neither read nor write.
                prepared.cache_key = ''
                return

        raw_cached_response = await self.gateway_cache.get(
            cache_key=prepared.cache_key,
            embeddings=prepared.embeddings,
            user_content=user_content,
            project_uuid=self.project_uuid,
            route_name=route_name,
            key_uuid=prepared.identity['api_key_uuid'],
            k=1,
        )
        cached = _parse_cached_response_object(raw_cached_response)
        if cached is None:
            return

        input_tokens, _, output_tokens = usage_token_counts(cached.get('usage'))
        self._emit_cache_events_and_metrics(
            **prepared.identity,
            route_name=route_name,
            model_id=cached.get('model', ''),
            usage=CompletionUsage(
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
            ),
            cache_type=self.gateway_cache.cache_type,
        )
        now = int(time.time())
        prepared.cached_response = {
            **cached,
            'created_at': now,
            'completed_at': now if cached.get('completed_at') else None,
        }

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

        # Check cache
        use_cache = self.gateway_cache and self.gateway_cache.cache_type in (
            CacheType.EXACT,
            CacheType.IN_MEMORY,
        )
        cache_key = ''
        if use_cache:
            set_operation_category(OperationCategory.CACHE)
            cache_key = self.gateway_cache.generate_embedding_cache_key(
                project_uuid=self.project_uuid,
                route_name=route_name,
                key_uuid=api_key_uuid,
                input_texts=redacted_texts,
            )
            raw_cached_response = await self.gateway_cache.get(cache_key)
            if raw_cached_response:
                logger.debug(
                    'Embedding cache hit. Key: %s',
                    cache_key,
                )
                cached_response = CreateEmbeddingResponse.model_validate(
                    json.loads(raw_cached_response)
                )

                self._emit_cache_events_and_metrics(
                    request_uuid=request_uuid,
                    api_key_uuid=api_key_uuid,
                    group_uuid=group_uuid,
                    api_key_name=api_key_name,
                    group_name=group_name,
                    route_name=route_name,
                    model_id=cached_response.model,
                    usage=cached_response.usage,
                    cache_type=self.gateway_cache.cache_type,
                )

                return cached_response

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

        if use_cache and cache_key:
            await self.gateway_cache.set(
                cache_key=cache_key,
                response=response.model_dump_json(indent=None),
                ttl=self.ttl,
            )

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

        use_cache = self.gateway_cache and self.gateway_cache.cache_type in (
            CacheType.EXACT,
            CacheType.IN_MEMORY,
        )
        cache_key = ''
        if use_cache:
            set_operation_category(OperationCategory.CACHE)
            cache_key = self.gateway_cache.generate_transcription_cache_key(
                project_uuid=self.project_uuid,
                route_name=route_name,
                key_uuid=api_key_uuid,
                audio_bytes=audio_bytes,
                model_id=model_selected.model_id,
                response_format=requested_response_format,
                language=language,
                prompt=prompt,
                temperature=temperature,
            )
            raw_cached_response = await self.gateway_cache.get(cache_key)
            if raw_cached_response:
                logger.debug('Transcription cache hit. Key: %s', cache_key)
                cached_body: Transcription | TranscriptionVerbose
                if requested_response_format == 'verbose_json':
                    cached_body = TranscriptionVerbose.model_validate_json(
                        raw_cached_response
                    )
                else:
                    cached_body = Transcription.model_validate_json(raw_cached_response)

                self._emit_cache_events_and_metrics(
                    request_uuid=request_uuid,
                    api_key_uuid=api_key_uuid,
                    group_uuid=group_uuid,
                    api_key_name=api_key_name,
                    group_name=group_name,
                    route_name=route_name,
                    model_id=model_selected.model_id,
                    usage=None,
                    cache_type=self.gateway_cache.cache_type,
                )

                return cached_body

        await _check_limits(limits, _transcription_demand(audio_bytes))

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

        if use_cache and cache_key:
            await self.gateway_cache.set(
                cache_key=cache_key,
                response=result.model_dump_json(indent=None),
                ttl=self.ttl,
            )

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

        use_cache = self.gateway_cache and self.gateway_cache.cache_type in (
            CacheType.EXACT,
            CacheType.IN_MEMORY,
        )
        cache_key = ''
        if use_cache:
            set_operation_category(OperationCategory.CACHE)
            cache_key = self.gateway_cache.generate_decision_cache_key(
                project_uuid=self.project_uuid,
                route_name=route_name,
                key_uuid=api_key_uuid,
                state=body.get('state'),
                questions=body.get('questions'),
                model_id=model_selected.model_id,
            )
            raw_cached_response = await self.gateway_cache.get(cache_key)
            if raw_cached_response:
                logger.debug('Decision cache hit. Key: %s', cache_key)
                cached = json.loads(raw_cached_response)
                self._emit_decision_cache_hit(
                    request_uuid=request_uuid,
                    api_key_uuid=api_key_uuid,
                    group_uuid=group_uuid,
                    api_key_name=api_key_name,
                    group_name=group_name,
                    route_name=route_name,
                    model_id=cached['model_id'],
                    input_tokens=cached['input_tokens'],
                )
                return DecisionResponse(
                    status_code=cached['status_code'],
                    content=cached['content'].encode('utf-8'),
                    media_type=cached['media_type'],
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
            if use_cache and cache_key:
                await self.gateway_cache.set(
                    cache_key=cache_key,
                    response=json.dumps(
                        {
                            'status_code': response.status_code,
                            'content': response.content.decode('utf-8'),
                            'media_type': response.media_type,
                            'model_id': response.model_invoked.model_id,
                            'input_tokens': response.input_tokens,
                        }
                    ),
                    ttl=self.ttl,
                )
        return response

    def _emit_decision_cache_hit(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        route_name: str,
        model_id: str,
        input_tokens: int,
    ) -> None:
        """Record a hit. It costs nothing: cached input tokens are at $0."""
        self._emit_cache_events_and_metrics(
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            group_uuid=group_uuid,
            api_key_name=api_key_name,
            group_name=group_name,
            route_name=route_name,
            model_id=model_id,
            usage=None,
            cache_type=self.gateway_cache.cache_type,
        )
        if input_tokens <= 0:
            return
        emit_event(
            CacheEventPayload(
                value=input_tokens,
                request_uuid=request_uuid,
                api_key_uuid=api_key_uuid,
                group_uuid=group_uuid,
                api_key_name=api_key_name,
                event_type=EventType.CACHE_INPUT_TOKENS,
                route_name=route_name,
                group_name=group_name,
                project_uuid=self.project_uuid,
                project_name=self.project_name,
                cost=0.0,
                cache_type=str(self.gateway_cache.cache_type.value),
                model_id=model_id,
            )
        )
        cache_input_tokens.add(
            input_tokens, {'route_name': route_name, 'model_name': model_id}
        )

    def _routing_spend_recorder(
        self, limits: RequestLimits, metrics: ModelInvoker
    ) -> RoutingSpendRecorder:
        """Charge a routing call to the request, as a judge call is (ADR 0006)."""

        async def record(
            model: Model,
            input_tokens: int,
            latency_ms: float,
            *,
            model_type: str,
            target_model_id: str | None = None,
            output_tokens: int | None = None,
        ) -> None:
            metrics.record_routing_call(
                identity=limits.identity,
                model=model,
                target_model_id=target_model_id or model.model_id,
                input_tokens=input_tokens,
                latency_ms=latency_ms,
                model_type=model_type,
                output_tokens=output_tokens,
            )
            if output_tokens is None:
                # Embedding and decision calls bill input tokens only.
                if input_tokens > 0:
                    await limits.count(Usage.priced(model, input_tokens))
            else:
                # A chat model router also bills the tokens it answers with.
                await limits.charge_call(model, input_tokens, output_tokens)

        return record

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
        if redacted_messages is not messages:
            # The cache still reads the unredacted list: keep the prompt there too.
            self._apply_config_prompt(messages, model_selected)

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
                cache_key='',
                embeddings=None,
                cached_response=None,
                input_soft_block=input_guardrails.soft_block.build_soft_block_response(
                    self.gateway_route_config.route_name
                ),
                guardrails_input_triggered=guardrails_input_triggered,
                guardrails_block_triggered=True,
            )

        # Check cache
        if self.gateway_cache:
            set_operation_category(OperationCategory.CACHE)
            cache_result = await self._handle_cache(
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
        else:
            cache_result = CacheResult(
                cache_key='', embeddings=None, cached_response=None
            )

        if cache_result.cached_response:
            return PrepareAndValidateResult(
                model_selected=model_selected,
                redacted_messages=redacted_messages,
                cache_key=cache_result.cache_key,
                embeddings=cache_result.embeddings,
                cached_response=cache_result.cached_response,
                input_soft_block=None,
                guardrails_input_triggered=guardrails_input_triggered,
                guardrails_block_triggered=guardrails_block_triggered,
            )

        return PrepareAndValidateResult(
            model_selected=model_selected,
            redacted_messages=redacted_messages,
            cache_key=cache_result.cache_key,
            embeddings=cache_result.embeddings,
            cached_response=None,
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
    # Cache
    # ============================================================================
    @task(name='lookup_cache')
    async def _handle_cache(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        route_name: str,
        messages: list,
        tools: list[ChatCompletionToolParam] | None,
        tool_choice: ChatCompletionToolChoiceOptionParam | None,
        **kwargs,
    ) -> CacheResult:
        # Check cache
        cached_response = None
        embeddings = None
        cache_key = ''
        # Use messages from the last user message (HumanMessage) to the end for cache/embedding
        last_human_idx = -1
        for idx, m in enumerate(messages):
            if isinstance(m, HumanMessage):
                last_human_idx = idx

        last_human = messages[last_human_idx] if last_human_idx != -1 else None
        messages_for_cache: list[BaseMessage] = (
            messages[last_human_idx:] if last_human_idx != -1 else []
        )
        user_content = (
            ContentUtils.extract_text_content(last_human.content) if last_human else ''
        )
        logger.debug(
            'Cache input based on last user message only. has_last_human=%s, used_text="%s"',
            bool(last_human),
            user_content,
        )
        if self.gateway_cache:
            if messages_for_cache:
                cache_key = self.gateway_cache.generate_cache_key(
                    project_uuid=self.project_uuid,
                    route_name=route_name,
                    key_uuid=api_key_uuid,
                    messages=messages_for_cache,
                    tools=tools,
                    tool_choice=tool_choice,
                    **kwargs,
                )
                logger.debug('Generated cache key for last user message: %s', cache_key)
            else:
                logger.debug(
                    'No HumanMessage found: skipping cache key generation and embeddings.'
                )
            if self.gateway_cache.cache_type == CacheType.SEMANTIC:
                if messages_for_cache and user_content:
                    embedding_model_selected = self._get_first_embedding_model()
                    if embedding_model_selected:
                        embeddings = await self._generate_embedding_for_semantic_cache(
                            text=user_content,
                            request_uuid=request_uuid,
                            api_key_uuid=api_key_uuid,
                            group_uuid=group_uuid,
                            api_key_name=api_key_name,
                            group_name=group_name,
                            route_name=route_name,
                            model_id_selected=embedding_model_selected.model_id,
                        )
                        logger.debug(
                            'Generated embeddings for semantic cache based on last user message.'
                        )
            cached_response = await self._get_from_cache(
                request_uuid,
                api_key_uuid,
                group_uuid,
                api_key_name,
                group_name,
                route_name,
                cache_key,
                user_content,
                embeddings,
            )

        return CacheResult(
            cache_key=cache_key, embeddings=embeddings, cached_response=cached_response
        )

    @task(name='get_cached_response')
    async def _get_from_cache(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        route_name: str,
        cache_key: str,
        user_content: str,
        embeddings: np.ndarray | None,
    ) -> ChatCompletion | None:
        kwargs = {
            'embeddings': embeddings,
            'user_content': user_content,
            'project_uuid': self.project_uuid,
            'route_name': route_name,
            'key_uuid': api_key_uuid,
            'k': 1,
        }
        if self.gateway_cache:
            raw_cached_response = await self.gateway_cache.get(
                cache_key=cache_key, **kwargs
            )
        else:
            raw_cached_response = None
        if raw_cached_response:
            logger.debug(
                'Cache hit. Hash name: %s',
                cache_key if cache_key != '' else 'response:aigateway:cache:*',
            )
            try:
                cached_response = ChatCompletion.model_validate(
                    json.loads(raw_cached_response)
                )
            except ValueError:
                # A semantic cache shares a route's entries between endpoints:
                # a Responses API entry is a miss here.
                logger.debug('Cached entry is not a chat completion: cache miss')
                return None

            self._emit_cache_events_and_metrics(
                request_uuid=request_uuid,
                api_key_uuid=api_key_uuid,
                group_uuid=group_uuid,
                api_key_name=api_key_name,
                group_name=group_name,
                route_name=route_name,
                model_id=cached_response.model,
                usage=cached_response.usage,
                cache_type=self.gateway_cache.cache_type,
            )

            # Update timestamp of cached response to have current timestamp
            return cached_response.model_copy(
                update={'created': int(datetime.datetime.now().timestamp())}
            )
        return None

    @task(name='set_cached_response')
    async def _cache_response(
        self,
        redacted_response: ChatCompletion,
        cache_key: str,
        route_name: str,
        key_uuid: str | None,
        embeddings: np.ndarray | None,
    ) -> None:
        """Cache the response if caching is enabled."""
        await self._cache_response_object(
            redacted_response.model_dump_json(indent=None),
            cache_key,
            route_name,
            key_uuid,
            embeddings,
        )

    async def _cache_response_object(
        self,
        response: str,
        cache_key: str,
        route_name: str,
        key_uuid: str | None,
        embeddings: np.ndarray | None,
    ) -> None:
        """Cache a serialized response object."""
        kwargs = {
            'embeddings': embeddings,
            'project_uuid': self.project_uuid,
            'route_name': route_name,
            'key_uuid': key_uuid,
        }
        await self.gateway_cache.set(
            cache_key=cache_key,
            response=response,
            ttl=self.ttl,
            **kwargs,
        )

    @task(name='generate_semantic_cache_embedding')
    async def _generate_embedding_for_semantic_cache(
        self,
        text: str,
        route_name: str,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid,
        api_key_name: str,
        group_name: str,
        model_id_selected: str,
    ) -> np.ndarray | None:
        try:
            response = await self.embedding_invoker.embed(
                request_uuid=request_uuid,
                api_key_uuid=api_key_uuid,
                group_uuid=group_uuid,
                api_key_name=api_key_name,
                group_name=group_name,
                route_name=route_name,
                input_texts=[text],
                model_id=model_id_selected,
                is_semantic_search=True,
                project_uuid=self.project_uuid,
                project_name=self.project_name,
            )
            if not response.data or not response.data[0].embedding:
                logger.warning(
                    'Failed to generate embedding for semantic caching, continuing without cache'
                )
                return None
            return np.array(response.data[0].embedding, dtype=np.float32)
        except Exception as e:
            logger.error(
                'Error generating embedding for cache: %s, continuing without cache', e
            )
            return None

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
            RequestIdentity(
                request_uuid=request_uuid,
                route_name=self.gateway_route_config.route_name,
                api_key_uuid=api_key_uuid,
                api_key_name=api_key_name,
                group_uuid=group_uuid,
                group_name=group_name,
                project_uuid=self.project_uuid,
                project_name=self.project_name,
            ),
            limits.charge_call,
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
        embeddings: list[float] | None = None,
        cache_key: str | None = None,
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
        guardrails = self._request_guardrails(
            limits,
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            group_uuid=group_uuid,
            api_key_name=api_key_name,
            group_name=group_name,
        )
        screened = await guardrails.screen_output(
            Reply(full_content_text, usage=final_usage)
        )
        if screened.soft_block:
            # A reply already streamed cannot be replaced: a soft block
            # answers with the 400 the global handler renders.
            raise GuardrailBadRequest(
                message=screened.soft_block.get_soft_block_message(),
                guardrail=screened.soft_block.guardrail,
                reason={'action': 'soft_block'},
            )
        if screened.payload.text != full_content_text:
            buffered_chunks = _with_text(buffered_chunks, screened.payload.text)

        # Cache if applicable
        if self.gateway_cache and cache_key and api_key_uuid:
            set_operation_category(OperationCategory.CACHE)
            await self._build_and_cache_stream_response(
                full_content_text=full_content_text,
                final_usage=final_usage,
                model_id_invoked=model_id_invoked,
                cache_key=cache_key,
                route_name=route_name,
                key_uuid=api_key_uuid,
                embeddings=embeddings,
                request_id=request_uuid,
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
        return chunks, screened.flags

    @task(name='set_cached_stream_response')
    async def _build_and_cache_stream_response(
        self,
        full_content_text: str,
        final_usage: dict | None,
        model_id_invoked: str,
        cache_key: str,
        route_name: str,
        key_uuid: str,
        embeddings: list[float] | None,
        request_id: str | None = None,
    ) -> None:
        """Build a ChatCompletion from stream content and cache it."""
        full_ai_message = AIMessage(
            content=full_content_text, usage_metadata=final_usage
        )
        full_response = ChatUtils.to_openai_chat_completion(
            full_ai_message,
            model_id_invoked=model_id_invoked,
            request_id=request_id,
        )
        await self._cache_response(
            full_response,
            cache_key,
            route_name,
            key_uuid,
            embeddings,
        )

    # ============================================================================
    # Observability
    # ============================================================================
    def _emit_cache_events_and_metrics(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        route_name: str,
        model_id: str,
        usage,
        cache_type: CacheType,
    ) -> None:
        cache_type_str = str(cache_type.value)
        emit_event(
            CacheEventPayload(
                value=1.0,
                request_uuid=request_uuid,
                event_type=EventType.CACHE_HIT,
                route_name=route_name,
                api_key_uuid=api_key_uuid,
                api_key_name=api_key_name,
                group_uuid=group_uuid,
                group_name=group_name,
                project_uuid=self.project_uuid,
                project_name=self.project_name,
                cost=0.0,
                cache_type=cache_type_str,
                model_id=model_id,
            )
        )
        cache_hit_counter.add(
            1,
            {'route_name': route_name},
        )

        if usage and cache_type:
            prompt_tokens = getattr(usage, 'prompt_tokens', None)
            if prompt_tokens:
                cost = self.cost_service.compute_cost(
                    token_processed=prompt_tokens,
                    where='input',
                    model_id=model_id,
                )
                emit_event(
                    CacheEventPayload(
                        value=prompt_tokens,
                        request_uuid=request_uuid,
                        api_key_uuid=api_key_uuid,
                        group_uuid=group_uuid,
                        api_key_name=api_key_name,
                        event_type=EventType.CACHE_INPUT_TOKENS,
                        route_name=route_name,
                        group_name=group_name,
                        project_uuid=self.project_uuid,
                        project_name=self.project_name,
                        cost=cost,
                        cache_type=cache_type_str,
                        model_id=model_id,
                    )
                )
                cache_input_tokens.add(
                    prompt_tokens,
                    {
                        'route_name': route_name,
                        'model_name': model_id,
                    },
                )

            completion_tokens = getattr(usage, 'completion_tokens', None)
            if completion_tokens:
                cost = self.cost_service.compute_cost(
                    token_processed=completion_tokens,
                    where='output',
                    model_id=model_id,
                )
                emit_event(
                    CacheEventPayload(
                        value=completion_tokens,
                        request_uuid=request_uuid,
                        api_key_uuid=api_key_uuid,
                        group_uuid=group_uuid,
                        api_key_name=api_key_name,
                        event_type=EventType.CACHE_OUTPUT_TOKENS,
                        route_name=route_name,
                        group_name=group_name,
                        project_uuid=self.project_uuid,
                        project_name=self.project_name,
                        cost=cost,
                        cache_type=cache_type_str,
                        model_id=model_id,
                    )
                )
                cache_output_tokens.add(
                    completion_tokens,
                    {
                        'route_name': route_name,
                        'model_name': model_id,
                    },
                )
