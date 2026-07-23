import datetime
import json
import logging

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
import numpy as np
from openai.types.chat import ChatCompletionToolChoiceOptionParam
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.chat.chat_completion_tool_param import ChatCompletionToolParam
from openai.types.create_embedding_response import CreateEmbeddingResponse
from traceloop.sdk.decorators import task, workflow

from radicalbit_ai_gateway.caching.gateway_cache import GatewayCache
from radicalbit_ai_gateway.events.events_processor import emit_event
from radicalbit_ai_gateway.guardrails.guardrail_engine import GuardrailEngine
from radicalbit_ai_gateway.invocation.chat_model_invoker import ChatModelInvoker
from radicalbit_ai_gateway.invocation.embedding_model_invoker import (
    EmbeddingModelInvoker,
)
from radicalbit_ai_gateway.invocation.transcription_model_invoker import (
    TranscriptionModelInvoker,
    TranscriptionResult,
)
from radicalbit_ai_gateway.limiting.budget_limiting import BudgetLimiter
from radicalbit_ai_gateway.limiting.rate_limiter import RequestRateLimiter
from radicalbit_ai_gateway.limiting.token_limiter import TokenLimiter
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
from radicalbit_ai_gateway.models.guardrails import GuardrailClass, GuardrailWhereType
from radicalbit_ai_gateway.models.model import ENABLE_PROMPT_CACHE_PARAM, Model
from radicalbit_ai_gateway.preprocessing import run_preprocessing
from radicalbit_ai_gateway.routing import (
    DeterministicRouter,
    SemanticRouter,
    TextClassificationRouter,
)
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.ai_gateway_types import (
    CacheResult,
    InvokeResponse,
    OutputProcessResult,
    PrepareAndValidateResult,
    StreamBufferedResult,
    StreamGenerator,
)
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.build_user_content import (
    build_user_content,
    build_user_content_from_texts,
)
from radicalbit_ai_gateway.utils.chat_utils import ChatUtils
from radicalbit_ai_gateway.utils.content_utils import ContentUtils
from radicalbit_ai_gateway.utils.exceptions import (
    GatewayBadRequest,
    GatewayInternalError,
    GuardrailBadRequest,
)
from radicalbit_ai_gateway.utils.streaming_utils import StreamingUtils
from radicalbit_ai_gateway.utils.trace_attributes import (
    OperationCategory,
    set_operation_category,
    set_streaming,
)

app_config = get_app_config()
logging_config_dict = app_config.log_config.model_dump()
logger = logging.getLogger(app_config.log_config.logger_name)


class GatewayRoute:
    def __init__(
        self,
        gateway_route_config: GatewayRouteConfig,
        chat_models: list[Model],
        embedding_models: list[Model] | None,
        guardrail_engine: GuardrailEngine,
        cost_service: CostService,
        gateway_cache: GatewayCache | None,
        httpx_client=None,
        router: DeterministicRouter
        | SemanticRouter
        | TextClassificationRouter
        | None = None,
        token_limiter: TokenLimiter | None = None,
        rate_limiter: RequestRateLimiter | None = None,
        budget_limiter: BudgetLimiter | None = None,
        transcription_models: list[Model] | None = None,
        project_uuid: str = '',
        project_name: str = '',
    ):
        self.gateway_route_config = gateway_route_config
        self.project_uuid = project_uuid
        self.project_name = project_name
        self._chat_models = chat_models
        self._embedding_models = embedding_models or []
        self._transcription_models = transcription_models or []
        self.router = router
        self.guardrail_engine = guardrail_engine
        self.gateway_cache = gateway_cache
        self.token_limiter = token_limiter
        self.budget_limiter = budget_limiter
        self.request_rate_limiter = rate_limiter
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
            # No fallback support yet for transcription models (AG-901);
            # TranscriptionModelInvoker already extends ModelInvoker so wiring
            # a fallback list in later (mirroring chat/embedding above) needs
            # no further refactor.
            self.transcription_invoker = TranscriptionModelInvoker(
                models=transcription_models,
                fallbacks=None,
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
        **kwargs,
    ) -> InvokeResponse:
        if route_name != self.gateway_route_config.route_name:
            raise GatewayBadRequest(f'{route_name} must be the route name')

        prepared = await self._prepare_and_validate_request(
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
            # Soft block: return content and mark guardrails header
            return InvokeResponse(
                content=prepared.input_soft_block,
                headers={'X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED': 'true'},
            )

        if prepared.cached_response:
            # Cache hit: return content with cache hit header
            if self.has_output_guardrails():
                output = await self._process_output(
                    request_uuid=request_uuid,
                    api_key_uuid=api_key_uuid,
                    group_uuid=group_uuid,
                    api_key_name=api_key_name,
                    group_name=group_name,
                    response=prepared.cached_response,
                )
                content = output.response.model_copy(update={'model': route_name})
                headers: dict[str, str] = {'X-RB-AIGATEWAY-CACHE-HIT': 'true'}
                if (
                    output.guardrails_block_triggered
                    or prepared.guardrails_block_triggered
                ):
                    headers['X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED'] = 'true'
                    if prepared.guardrails_block_triggered:
                        headers['X-RB-AIGATEWAY-GUARDRAILS-INPUT-TRIGGERED'] = 'true'
                    if output.guardrails_block_triggered:
                        headers['X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-TRIGGERED'] = 'true'
                if output.guardrails_triggered or prepared.guardrails_input_triggered:
                    headers['X-RB-AIGATEWAY-GUARDRAILS-WARN'] = 'true'
                    if prepared.guardrails_input_triggered:
                        headers['X-RB-AIGATEWAY-GUARDRAILS-INPUT-WARN'] = 'true'
                    if output.guardrails_triggered:
                        headers['X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-WARN'] = 'true'
                return InvokeResponse(content=content, headers=headers)
            content = prepared.cached_response.model_copy(update={'model': route_name})
            headers: dict[str, str] = {'X-RB-AIGATEWAY-CACHE-HIT': 'true'}
            if prepared.guardrails_block_triggered:
                headers['X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED'] = 'true'
                headers['X-RB-AIGATEWAY-GUARDRAILS-INPUT-TRIGGERED'] = 'true'
            if prepared.guardrails_input_triggered:
                headers['X-RB-AIGATEWAY-GUARDRAILS-WARN'] = 'true'
                headers['X-RB-AIGATEWAY-GUARDRAILS-INPUT-WARN'] = 'true'
            return InvokeResponse(content=content, headers=headers)

        # Process the request
        set_operation_category(OperationCategory.INVOCATION)
        response = await self._process_request(
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
        if self.has_output_guardrails():
            output = await self._process_output(
                request_uuid=request_uuid,
                api_key_uuid=api_key_uuid,
                group_uuid=group_uuid,
                api_key_name=api_key_name,
                group_name=group_name,
                response=response,
            )
        else:
            output = OutputProcessResult(
                response=response,
                guardrails_triggered=False,
                guardrails_block_triggered=False,
            )

        # Cache the response
        if self.gateway_cache and prepared.cache_key:
            set_operation_category(OperationCategory.CACHE)
            await self._cache_response(
                output.response,
                prepared.cache_key,
                api_key_uuid,
                prepared.embeddings,
            )
        # Cache miss: return content, include guardrail header if triggered
        headers: dict[str, str] = {}
        if output.guardrails_block_triggered or prepared.guardrails_block_triggered:
            headers['X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED'] = 'true'
            if prepared.guardrails_block_triggered:
                headers['X-RB-AIGATEWAY-GUARDRAILS-INPUT-TRIGGERED'] = 'true'
            if output.guardrails_block_triggered:
                headers['X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-TRIGGERED'] = 'true'
        if output.guardrails_triggered or prepared.guardrails_input_triggered:
            headers['X-RB-AIGATEWAY-GUARDRAILS-WARN'] = 'true'
            if prepared.guardrails_input_triggered:
                headers['X-RB-AIGATEWAY-GUARDRAILS-INPUT-WARN'] = 'true'
            if output.guardrails_triggered:
                headers['X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-WARN'] = 'true'
        return InvokeResponse(
            content=output.response.model_copy(update={'model': route_name}),
            headers=headers,
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
        **kwargs,
    ) -> PrepareAndValidateResult:
        return await self._prepare_and_validate_request(
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
        **kwargs,
    ) -> StreamBufferedResult:
        set_streaming()
        if prepared.input_soft_block:
            # For buffered streaming, return the soft block as a single chunk
            chunk = StreamingUtils.build_soft_block_chunk(
                prepared.input_soft_block, route_name
            )
            headers = {'X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED': 'true'}
            return [chunk], headers

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

            headers = {'X-RB-AIGATEWAY-CACHE-HIT': 'true'}
            return chunks, headers

        # Prepare stream options (forces include_usage=True upstream)
        user_stream_options = StreamingUtils.prepare_stream_options(kwargs)
        # Pass original options for the handler to decide on yielding
        kwargs['original_stream_options'] = user_stream_options

        # Buffer Outcome
        return [
            chunk
            async for chunk in self._handle_buffered_stream(
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
        ], {
            **(
                {
                    'X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED': 'true',
                    'X-RB-AIGATEWAY-GUARDRAILS-INPUT-TRIGGERED': 'true',
                }
                if prepared.guardrails_block_triggered
                else {}
            ),
            **(
                {
                    'X-RB-AIGATEWAY-GUARDRAILS-WARN': 'true',
                    'X-RB-AIGATEWAY-GUARDRAILS-INPUT-WARN': 'true',
                }
                if prepared.guardrails_input_triggered
                else {}
            ),
        }

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
            await self._count_usage(
                prompt_tokens=final_usage.get('input_tokens', 0),
                completion_tokens=final_usage.get('output_tokens', 0),
                model_selected=prepared.model_selected,
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
                key_uuid=api_key_uuid,
                embeddings=prepared.embeddings,
            )

    async def invoke_embeddings(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        route_name: str,
        input_texts: list[str],
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

        if self.gateway_route_config.guardrails:
            redacted_texts = input_texts
            has_redact_input = self.guardrail_engine.has_guardrails_for_route(
                self.gateway_route_config,
                GuardrailWhereType.INPUT,
                GuardrailClass.REDACT,
            )
            if has_redact_input:
                set_operation_category(OperationCategory.GUARDRAIL_INPUT)
                redacted_texts = await self._apply_redact_guardrail_to_embeddings(
                    request_uuid=request_uuid,
                    api_key_uuid=api_key_uuid,
                    group_uuid=group_uuid,
                    api_key_name=api_key_name,
                    group_name=group_name,
                    input_texts=input_texts,
                )

            if self.guardrail_engine.has_guardrails_for_route(
                self.gateway_route_config,
                GuardrailWhereType.INPUT,
                GuardrailClass.CHECK,
            ):
                if not has_redact_input:
                    set_operation_category(OperationCategory.GUARDRAIL_INPUT)

                input_soft_block = await self._apply_check_guardrails_for_embeddings(
                    request_uuid=request_uuid,
                    api_key_uuid=api_key_uuid,
                    group_uuid=group_uuid,
                    api_key_name=api_key_name,
                    group_name=group_name,
                    input_texts=redacted_texts,
                )

                if input_soft_block:
                    return input_soft_block
        else:
            redacted_texts = input_texts

        # Check cache
        use_cache = self.gateway_cache and self.gateway_cache.cache_type in (
            CacheType.EXACT,
            CacheType.IN_MEMORY,
        )
        cache_key = ''
        if use_cache:
            set_operation_category(OperationCategory.CACHE)
            cache_key = self.gateway_cache.generate_embedding_cache_key(
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

        # Validate limiters
        if self.token_limiter or self.budget_limiter:
            set_operation_category(OperationCategory.LIMITING)
            await self._validate_embedding_limiters(
                request_uuid=request_uuid,
                api_key_uuid=api_key_uuid,
                group_uuid=group_uuid,
                api_key_name=api_key_name,
                group_name=group_name,
                input_texts=redacted_texts,
                model_selected=model_selected,
            )

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
            if self.token_limiter:
                await self.token_limiter.count_input(
                    prompt_tokens=response.usage.prompt_tokens
                )
            if self.budget_limiter and model_selected.input_cost_per_token:
                await self.budget_limiter.count_input(
                    token_count=response.usage.prompt_tokens,
                    input_cost_per_token=model_selected.input_cost_per_token,
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
        requested_response_format: str,
        language: str | None = None,
        prompt: str | None = None,
        temperature: float | None = None,
    ) -> TranscriptionResult:
        """Invoke a transcription model for the route.

        Mirrors `invoke_embeddings` but deliberately excludes guardrails
        (excluded by the epic for raw audio input), caching (AG-902) and
        token limiting (not applicable — see AG-887 analysis: there is no
        way to estimate audio/token usage before calling the provider).
        Cost tracking (AG-892) is also not wired here yet: see the
        `_record_metrics` call below for why calling it with token counts
        would crash against `CostService` today.
        """
        if route_name != self.gateway_route_config.route_name:
            raise GatewayBadRequest(f'{route_name} must be the route name')

        if not self.transcription_invoker:
            raise GatewayBadRequest(
                f'Route {route_name} has no transcription models defined'
            )

        set_operation_category(OperationCategory.ROUTING)
        model_selected = self._select_and_prepare_transcription_model()

        if self.budget_limiter:
            set_operation_category(OperationCategory.LIMITING)
            await self.budget_limiter.check_budget()

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

        # Record that an invocation happened (event_type=MODEL_INVOCATION),
        # without token_input_count/token_output_count: passing them would
        # call `CostService.compute_cost` for a model_id it doesn't know
        # about (transcription models aren't in `self.prices`, only chat/
        # embedding are), which raises UnboundLocalError today. AG-892 will
        # extend CostService and pass real counts here.
        self.transcription_invoker._record_metrics(
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            group_uuid=group_uuid,
            api_key_name=api_key_name,
            group_name=group_name,
            route_name=route_name,
            target_model_id=model_selected.model_id,
            model=result.model_invoked,
            latency_ms=result.latency_ms,
            model_type='transcription',
            project_uuid=self.project_uuid,
            project_name=self.project_name,
        )

        if self.budget_limiter:
            # Placeholder pass-through (no-op: int(0.0 * BUDGET_MULTIPLIER) == 0)
            # so the wiring is exercised end-to-end now. TODO(AG-892): replace
            # 0.0 with the real dollar cost once CostService supports
            # transcription pricing.
            await self.budget_limiter.count_cost(cost=0.0)

        return result

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
        **kwargs,
    ) -> PrepareAndValidateResult:
        """Prepare a common pre-invocation logic: validation, guardrails, cache, limiters."""
        if route_name != self.gateway_route_config.route_name:
            raise GatewayBadRequest(f'{route_name} must be the route name')

        if not self.chat_invoker:
            raise GatewayBadRequest(f'Route {route_name} has no chat models defined')

        # Preprocessing plugins: transform the raw client messages first, before
        # routing and before the configured system prompt is injected, so plugins
        # only ever see the client's messages. No-op when no plugin is enabled;
        # fail-closed if a plugin raises.
        set_operation_category(OperationCategory.PREPROCESSING)
        messages = await run_preprocessing(messages, self.gateway_route_config.plugins)

        # Prepare request for processing: route on the preprocessed messages.
        set_operation_category(OperationCategory.ROUTING)
        model_selected = await self._select_chat_model(messages)

        if self.router and self.gateway_route_config.routing:
            emit_event(
                RoutingEventPayload(
                    value=1.0,
                    request_uuid=request_uuid,
                    event_type=EventType.ROUTING,
                    route_name=route_name,
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

        # Inject the route's configured system prompt AFTER preprocessing, so
        # preprocessing plugins can never see or modify it.
        self._apply_config_prompt(messages, model_selected)

        guardrails_input_triggered = False
        guardrails_block_triggered = (
            False  # Only tracks BLOCK/SOFT_BLOCK, not REDACT or WARN
        )
        redacted_messages = messages

        if self.gateway_route_config.guardrails:
            has_redact_input = self.guardrail_engine.has_guardrails_for_route(
                self.gateway_route_config,
                GuardrailWhereType.INPUT,
                GuardrailClass.REDACT,
            )
            if has_redact_input:
                set_operation_category(OperationCategory.GUARDRAIL_INPUT)
                redacted_messages = await self._apply_redact_guardrails(
                    request_uuid=request_uuid,
                    api_key_uuid=api_key_uuid,
                    group_uuid=group_uuid,
                    group_name=group_name,
                    api_key_name=api_key_name,
                    messages=messages,
                    where=GuardrailWhereType.INPUT,
                )

                # Mark as triggered if input was redacted (but NOT for block header)
                try:
                    if (len(messages) != len(redacted_messages)) or any(
                        (m1.content != m2.content)
                        for m1, m2 in zip(messages, redacted_messages)
                    ):
                        guardrails_input_triggered = True
                except Exception:
                    pass

            if self.guardrail_engine.has_guardrails_for_route(
                self.gateway_route_config,
                GuardrailWhereType.INPUT,
                GuardrailClass.CHECK,
            ):
                if not has_redact_input:
                    set_operation_category(OperationCategory.GUARDRAIL_INPUT)

                input_soft_block = await self._apply_check_guardrails(
                    request_uuid=request_uuid,
                    api_key_uuid=api_key_uuid,
                    group_uuid=group_uuid,
                    group_name=group_name,
                    api_key_name=api_key_name,
                    messages=redacted_messages,
                    where=GuardrailWhereType.INPUT,
                )

                if input_soft_block:
                    # SOFT_BLOCK triggers the block header
                    return PrepareAndValidateResult(
                        model_selected=model_selected,
                        redacted_messages=redacted_messages,
                        cache_key='',
                        embeddings=None,
                        cached_response=None,
                        input_soft_block=input_soft_block,
                        guardrails_input_triggered=guardrails_input_triggered,
                        guardrails_block_triggered=True,
                    )

                # Evaluate WARN-only guardrails on input (does NOT trigger block header)
                try:
                    if await self.guardrail_engine.guardrail_check.evaluate_warn_triggered(
                        self.gateway_route_config,
                        redacted_messages,
                        GuardrailWhereType.INPUT,
                        request_uuid=request_uuid,
                        api_key_uuid=api_key_uuid,
                        group_uuid=group_uuid,
                        api_key_name=api_key_name,
                        group_name=group_name,
                    ):
                        guardrails_input_triggered = True
                except Exception:
                    pass

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

        # Validate Limiters
        if self.token_limiter or self.budget_limiter:
            set_operation_category(OperationCategory.LIMITING)
            await self._validate_limiters(
                request_uuid=request_uuid,
                api_key_uuid=api_key_uuid,
                group_uuid=group_uuid,
                group_name=group_name,
                api_key_name=api_key_name,
                messages=redacted_messages,
                model_selected=model_selected,
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
    async def _select_chat_model(self, messages: list[BaseMessage]) -> Model:
        """Select the chat model for this request based on the routing config."""
        if self.router:
            model_selected = await self.router.select_model(messages)
        else:
            model_selected = self._chat_models[0]

        logger.debug('Selected chat model: %s', model_selected.model_id)

        return model_selected

    def _apply_config_prompt(
        self, messages: list[BaseMessage], model_selected: Model
    ) -> None:
        """Prepend the route's configured system prompt to *messages* in place.

        Runs *after* preprocessing so the configured prompt is never exposed to
        preprocessing plugins.
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
        """Select transcription model for transcription invocation.

        v1 always selects the first model configured on the route (same
        pattern as `/v1/embeddings` today) — no client-side model selection
        within a route, no multi-model routing for transcription yet.
        """
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
            await self._count_usage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                model_selected=model_selected,
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
    ) -> OutputProcessResult:
        """Process output with guardrails. Returns (response, guardrails_triggered, guardrails_block_triggered)."""
        original_output = response.choices[0].message.content
        redacted_output = original_output
        guardrails_triggered = False
        guardrails_block_triggered = (
            False  # Only tracks BLOCK/SOFT_BLOCK, not REDACT or WARN
        )

        if self.gateway_route_config.guardrails:
            has_redact_output = self.guardrail_engine.has_guardrails_for_route(
                self.gateway_route_config,
                GuardrailWhereType.OUTPUT,
                GuardrailClass.REDACT,
            )
            if has_redact_output:
                set_operation_category(OperationCategory.GUARDRAIL_OUTPUT)
                if redacted_output:
                    redacted_output = (
                        await self._apply_redact_guardrails(
                            request_uuid=request_uuid,
                            api_key_uuid=api_key_uuid,
                            group_uuid=group_uuid,
                            api_key_name=api_key_name,
                            group_name=group_name,
                            messages=[AIMessage(content=redacted_output)],
                            where=GuardrailWhereType.OUTPUT,
                        )
                    )[0].content
                    # Mark as triggered if output was redacted (but NOT for block header)
                    if redacted_output != original_output:
                        guardrails_triggered = True

            if self.guardrail_engine.has_guardrails_for_route(
                self.gateway_route_config,
                GuardrailWhereType.OUTPUT,
                GuardrailClass.CHECK,
            ):
                if not has_redact_output:
                    set_operation_category(OperationCategory.GUARDRAIL_OUTPUT)

                output_soft_block = await self._apply_check_guardrails(
                    request_uuid=request_uuid,
                    api_key_uuid=api_key_uuid,
                    group_uuid=group_uuid,
                    api_key_name=api_key_name,
                    group_name=group_name,
                    messages=[AIMessage(content=redacted_output)],
                    where=GuardrailWhereType.OUTPUT,
                )

                if output_soft_block:
                    # SOFT_BLOCK triggers the block header
                    guardrails_triggered = True
                    guardrails_block_triggered = True
                    return OutputProcessResult(
                        response=output_soft_block.model_copy(
                            update={
                                'usage': response.usage,
                                'created': response.created,
                                'id': response.id,
                            }
                        ),
                        guardrails_triggered=guardrails_triggered,
                        guardrails_block_triggered=guardrails_block_triggered,
                    )
                # Evaluate WARN-only guardrails on output (does NOT trigger block header)
                try:
                    if await self.guardrail_engine.guardrail_check.evaluate_warn_triggered(
                        self.gateway_route_config,
                        [AIMessage(content=redacted_output)],
                        GuardrailWhereType.OUTPUT,
                        request_uuid=request_uuid,
                        api_key_uuid=api_key_uuid,
                        group_uuid=group_uuid,
                        api_key_name=api_key_name,
                        group_name=group_name,
                    ):
                        guardrails_triggered = True
                except Exception:
                    pass

        normalized_output = ContentUtils.normalize_openai_message_content(
            redacted_output
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
            guardrails_triggered=guardrails_triggered,
            guardrails_block_triggered=guardrails_block_triggered,
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
            cached_response = ChatCompletion.model_validate(
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
        key_uuid: str | None,
        embeddings: np.ndarray | None,
    ) -> None:
        """Cache the response if caching is enabled."""
        kwargs = {
            'embeddings': embeddings,
            'key_uuid': key_uuid,
        }
        await self.gateway_cache.set(
            cache_key=cache_key,
            response=redacted_response.model_dump_json(indent=None),
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
    async def _apply_redact_guardrails(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        messages: list[BaseMessage],
        where: GuardrailWhereType,
    ) -> list[BaseMessage]:
        """Apply redaction guardrails."""
        return await self.guardrail_engine.guardrail_redact.apply_guardrails(
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            group_uuid=group_uuid,
            api_key_name=api_key_name,
            group_name=group_name,
            route_config=self.gateway_route_config,
            messages=messages,
            where=where,
            project_uuid=self.project_uuid,
            project_name=self.project_name,
        )

    async def _apply_redact_guardrail_to_embeddings(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        input_texts: list[str],
        where: GuardrailWhereType = GuardrailWhereType.INPUT,
    ) -> list[str]:
        """Apply redaction guardrails to embedding input texts."""

        wrapped_messages = [HumanMessage(content=text) for text in input_texts]
        redacted_messages = (
            await self.guardrail_engine.guardrail_redact.apply_guardrails(
                request_uuid=request_uuid,
                api_key_uuid=api_key_uuid,
                group_uuid=group_uuid,
                api_key_name=api_key_name,
                group_name=group_name,
                route_config=self.gateway_route_config,
                messages=wrapped_messages,
                where=where,
                project_uuid=self.project_uuid,
                project_name=self.project_name,
            )
        )

        return [
            msg.content if isinstance(msg.content, str) else str(msg.content)
            for msg in redacted_messages
        ]

    async def _apply_check_guardrails(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        messages: list[BaseMessage],
        where: GuardrailWhereType,
    ) -> ChatCompletion | None:
        """Handle check guardrails"""
        try:
            soft_block = await self.guardrail_engine.guardrail_check.apply_guardrails(
                request_uuid=request_uuid,
                api_key_uuid=api_key_uuid,
                group_uuid=group_uuid,
                api_key_name=api_key_name,
                group_name=group_name,
                route_config=self.gateway_route_config,
                messages=messages,
                where=where,
                project_uuid=self.project_uuid,
                project_name=self.project_name,
            )
        except GuardrailBadRequest:
            raise

        except Exception as e:
            logger.error('Unexpected error during guardrail application: %s', e)
            raise GatewayInternalError(
                f'Error during guardrail application: {e}'
            ) from e

        if soft_block:
            # Build soft block response; caller will attach GUARDRAILS header
            return soft_block.build_soft_block_response(
                self.gateway_route_config.route_name
            )

        return None

    async def _apply_check_guardrails_for_embeddings(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        input_texts: list[str],
        where: GuardrailWhereType = GuardrailWhereType.INPUT,
    ) -> CreateEmbeddingResponse | None:
        """Apply check guardrails to embedding input texts."""
        wrapped_messages = [HumanMessage(content=text) for text in input_texts]
        try:
            input_soft_block = (
                await self.guardrail_engine.guardrail_check.apply_guardrails(
                    request_uuid=request_uuid,
                    api_key_uuid=api_key_uuid,
                    group_uuid=group_uuid,
                    api_key_name=api_key_name,
                    group_name=group_name,
                    route_config=self.gateway_route_config,
                    messages=wrapped_messages,
                    where=where,
                    project_uuid=self.project_uuid,
                    project_name=self.project_name,
                )
            )
        except GuardrailBadRequest as e:
            logger.warning('Guardrail BLOCK triggered: %s', e.log_message)
            raise

        except Exception as e:
            logger.error('Unexpected error during guardrail application: %s', e)
            raise GatewayInternalError(
                f'Error during guardrail application: {e}'
            ) from e

        if input_soft_block:
            return input_soft_block.build_soft_block_embedding_response(
                self.gateway_route_config.route_name
            )

        return None

    def has_output_guardrails(self) -> bool:
        """Check if any output guardrails are configured for the route."""
        return self.guardrail_engine.has_guardrails_for_route(
            self.gateway_route_config,
            GuardrailWhereType.OUTPUT,
            GuardrailClass.CHECK,
        ) or self.guardrail_engine.has_guardrails_for_route(
            self.gateway_route_config,
            GuardrailWhereType.OUTPUT,
            GuardrailClass.REDACT,
        )

    # ============================================================================
    # Limiting
    # ============================================================================
    @task(name='check_limiters')
    async def _validate_limiters(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        messages: list[BaseMessage],
        model_selected: Model,
    ) -> None:
        user_content = build_user_content(messages)
        if self.token_limiter:
            if self.token_limiter.input_config:
                await self.token_limiter.check_input(
                    text=user_content,
                    request_uuid=request_uuid,
                    api_key_uuid=api_key_uuid,
                    group_uuid=group_uuid,
                    group_name=group_name,
                    api_key_name=api_key_name,
                    model_string=model_selected.model,
                    project_uuid=self.project_uuid,
                    project_name=self.project_name,
                )
            if self.token_limiter.output_config:
                await self.token_limiter.check_output(
                    request_uuid=request_uuid,
                    api_key_uuid=api_key_uuid,
                    group_uuid=group_uuid,
                    group_name=group_name,
                    api_key_name=api_key_name,
                    project_uuid=self.project_uuid,
                    project_name=self.project_name,
                )
        if self.budget_limiter and self.budget_limiter.config:
            await self.budget_limiter.check_budget()

    @task(name='check_embedding_limiters')
    async def _validate_embedding_limiters(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        group_name: str,
        api_key_name: str,
        input_texts: list[str],
        model_selected: Model,
    ) -> None:
        """Apply token and budget limiting for embedding requests (input only)."""

        user_content = build_user_content_from_texts(input_texts)
        if self.token_limiter and self.token_limiter.input_config:
            await self.token_limiter.check_input(
                text=user_content,
                request_uuid=request_uuid,
                api_key_uuid=api_key_uuid,
                group_uuid=group_uuid,
                api_key_name=api_key_name,
                group_name=group_name,
                model_string=model_selected.model,
                project_uuid=self.project_uuid,
                project_name=self.project_name,
            )

        if self.budget_limiter and self.budget_limiter.config:
            await self.budget_limiter.check_budget()

    async def _count_usage(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model_selected: Model,
    ) -> None:
        """Count token and budget usage from a response."""
        if self.token_limiter:
            await self.token_limiter.count_input(prompt_tokens=prompt_tokens)
            await self.token_limiter.count_output(token_count=completion_tokens)

        if self.budget_limiter and model_selected.input_cost_per_token:
            await self.budget_limiter.count_input(
                token_count=prompt_tokens,
                input_cost_per_token=model_selected.input_cost_per_token,
            )
        if self.budget_limiter and model_selected.output_cost_per_token:
            await self.budget_limiter.count_output(
                token_count=completion_tokens,
                output_cost_per_token=model_selected.output_cost_per_token,
            )

    # ============================================================================
    # Streaming
    # ============================================================================

    @workflow(name='stream_with_output_guardrails')
    async def _handle_buffered_stream(
        self,
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
        """Handle streaming with buffering for output guardrails."""
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

        # Validate output guardrails
        full_ai_message = AIMessage(
            content=full_content_text, usage_metadata=final_usage
        )

        # Check guardrails
        output_soft_block = None
        if self.guardrail_engine.has_guardrails_for_route(
            self.gateway_route_config,
            GuardrailWhereType.OUTPUT,
            GuardrailClass.CHECK,
        ):
            set_operation_category(OperationCategory.GUARDRAIL_OUTPUT)
            output_soft_block = await self._apply_check_guardrails(
                request_uuid=request_uuid,
                api_key_uuid=api_key_uuid,
                group_uuid=group_uuid,
                group_name=group_name,
                api_key_name=api_key_name,
                messages=[full_ai_message],
                where=GuardrailWhereType.OUTPUT,
            )

        if output_soft_block:
            # If triggered (soft block), raise exception to return HTTP 400 + Header
            # We reconstruct the exception to leverage the global handler
            mock_guardrail = next(
                (
                    self.guardrail_engine._guardrails_by_name.get(gid)
                    for gid in self.gateway_route_config.guardrails
                    if self.guardrail_engine._guardrails_by_name.get(gid).where
                    == GuardrailWhereType.OUTPUT
                ),
                None,
            )
            # Use the detailed refusal content as the error message
            raise GuardrailBadRequest(
                message=output_soft_block.choices[0].message.content,
                guardrail=mock_guardrail,  # Best effort to identify which one
                reason={'action': 'soft_block'},
            )

        # Cache if applicable
        if self.gateway_cache and cache_key and api_key_uuid:
            set_operation_category(OperationCategory.CACHE)
            await self._build_and_cache_stream_response(
                full_content_text=full_content_text,
                final_usage=final_usage,
                model_id_invoked=model_id_invoked,
                cache_key=cache_key,
                key_uuid=api_key_uuid,
                embeddings=embeddings,
                request_id=request_uuid,
            )

        # Count usage for token and budget limiting
        if final_usage:
            await self._count_usage(
                prompt_tokens=final_usage.get('input_tokens', 0),
                completion_tokens=final_usage.get('output_tokens', 0),
                model_selected=model_selected,
            )

        # If passed, yield the buffered chunks
        for chunk in buffered_chunks:
            openai_chunk = StreamingUtils.to_openai_chat_completion_chunk(
                chunk, model_id_invoked=route_name
            )
            yield openai_chunk

        if (
            final_usage
            and original_stream_options
            and isinstance(original_stream_options, dict)
            and original_stream_options.get('include_usage')
        ):
            yield StreamingUtils.build_usage_chunk(
                final_usage=final_usage,
                model_id_invoked=route_name,
                request_id=request_uuid,
            )

    @task(name='set_cached_stream_response')
    async def _build_and_cache_stream_response(
        self,
        full_content_text: str,
        final_usage: dict | None,
        model_id_invoked: str,
        cache_key: str,
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
