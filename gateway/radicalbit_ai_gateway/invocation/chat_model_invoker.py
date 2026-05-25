from collections.abc import AsyncIterator
import logging
import time

from langchain.chat_models.base import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from openai.types.chat import ChatCompletionToolChoiceOptionParam
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.chat.chat_completion_tool_param import ChatCompletionToolParam
from traceloop.sdk.decorators import task

from radicalbit_ai_gateway.invocation.model_invoker import ModelInvoker
from radicalbit_ai_gateway.models.fallback import Fallback
from radicalbit_ai_gateway.models.model import (
    ENABLE_PROMPT_CACHE_PARAM,
    GatewayDeepSeekChatModel,
    MockGatewayChatModel,
    Model,
)
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.chat_utils import ChatUtils
from radicalbit_ai_gateway.utils.exceptions import (
    ModelInvokerBadRequest,
    ModelInvokerInternalError,
)
from radicalbit_ai_gateway.utils.parse_provider_and_model import (
    parse_provider_and_model,
)

app_config = get_app_config()

logger = logging.getLogger(app_config.log_config.logger_name)


class ChatModelInvoker(ModelInvoker):
    def __init__(
        self,
        models: list[Model],
        cost_service: CostService,
        fallbacks: list[Fallback] | None,
        httpx_client=None,
    ):
        super().__init__(
            models=models,
            cost_service=cost_service,
            fallbacks=fallbacks,
            httpx_client=httpx_client,
        )
        self._initialize_models(self._build_model)

    def _build_model(self, model: Model) -> BaseChatModel:
        """Build a chat model from configuration.

        Returns:
            BaseChatModel: A chat model instance.

        """
        provider, model_name = parse_provider_and_model(model.model)
        params = model.params or {}
        credentials = (
            model.credentials.model_dump(exclude_none=True) if model.credentials else {}
        )

        # Handle mock provider (gateway-specific)
        if provider == 'mock':
            latency_ms: int = int(params.get('latency_ms', 0))
            response_text: str = params.get('response_text', 'ok')
            return MockGatewayChatModel(
                model_name=model_name,
                latency_ms=latency_ms,
                response_text=response_text,
            )

        # Strip gateway-only params that must not reach LangChain
        _GATEWAY_PARAMS = {ENABLE_PROMPT_CACHE_PARAM}
        init_kwargs = {
            k: v
            for k, v in {**params, **credentials}.items()
            if k not in _GATEWAY_PARAMS
        }

        if provider == 'deepseek':
            return GatewayDeepSeekChatModel(
                model=model_name,
                http_async_client=self.httpx_client,
                **init_kwargs,
            )

        # Map gateway provider names to LangChain provider names
        # LangChain uses underscore (google_genai) while gateway uses hyphen (google-genai)
        langchain_provider = provider.replace('-', '_')

        if provider not in ('anthropic', 'mistralai'):
            init_kwargs['http_async_client'] = self.httpx_client
        return init_chat_model(
            model=f'{langchain_provider}:{model_name}',
            **init_kwargs,
        )

    @staticmethod
    def _normalize_kwargs_for_model(model: Model, kwargs: dict) -> dict:
        """Translate or strip kwargs to match what each provider accepts.

        - max_completion_tokens → provider-native name
        - stream_options, original_stream_options → stripped for Anthropic
          (OpenAI-specific; Anthropic returns usage in chunks by default)
        """
        provider, _ = parse_provider_and_model(model.model)
        normalized = dict(kwargs)

        if 'max_completion_tokens' in normalized:
            value = normalized.pop('max_completion_tokens')
            if provider == 'google-genai':
                normalized['max_output_tokens'] = value
            elif provider == 'anthropic':
                normalized['max_tokens'] = value
            else:
                normalized['max_completion_tokens'] = value

        # stream_options is OpenAI-specific; Anthropic rejects it
        if provider == 'anthropic':
            normalized.pop('stream_options', None)
            normalized.pop('original_stream_options', None)

        return normalized

    @staticmethod
    def _extract_cache_token_counts(
        usage_metadata,
        response_metadata,
    ) -> tuple[int | None, int | None, int | None]:
        """Extract cache token counts from message metadata.

        Returns:
            Tuple of (cached_read, cache_creation_5m, cache_creation_1h).
            Each value is None when not present in the response.

        """
        cached_token_count: int | None = None
        cache_creation_5m_token_count: int | None = None
        cache_creation_1h_token_count: int | None = None

        if usage_metadata:
            input_token_details = usage_metadata.get('input_token_details')
            if input_token_details:
                cache_read = input_token_details.get('cache_read')
                if cache_read:
                    cached_token_count = cache_read

                # Prefer granular TTL breakdown when available
                ephem_5m = input_token_details.get('ephemeral_5m_input_tokens')
                ephem_1h = input_token_details.get('ephemeral_1h_input_tokens')
                if ephem_5m or ephem_1h:
                    if ephem_5m:
                        cache_creation_5m_token_count = ephem_5m
                    if ephem_1h:
                        cache_creation_1h_token_count = ephem_1h
                else:
                    # Fallback: treat total cache_creation as 5-min cost
                    cache_creation = input_token_details.get('cache_creation')
                    if cache_creation:
                        cache_creation_5m_token_count = cache_creation

        # Fallback to response_metadata for providers using legacy format (e.g. OpenAI)
        if cached_token_count is None and response_metadata:
            token_usage = response_metadata.get('token_usage')
            if token_usage:
                prompt_tokens_details = token_usage.get('prompt_tokens_details')
                if prompt_tokens_details:
                    cached_token_count = prompt_tokens_details.get('cached_tokens')

        return (
            cached_token_count,
            cache_creation_5m_token_count,
            cache_creation_1h_token_count,
        )

    async def _execute_with_fallbacks(
        self,
        route_name: str,
        model_id: str,
        messages: list[BaseMessage],
        tools: list[ChatCompletionToolParam] | None,
        tool_choice: ChatCompletionToolChoiceOptionParam | None,
        **kwargs,
    ) -> tuple[AIMessage, Model, bool]:
        if model_id not in self.model_map:
            raise ModelInvokerBadRequest(f'Chat model {model_id} not defined')

        model, chat_model, fallbacks = self.model_map[model_id]
        if tools and tool_choice:
            chat_model = chat_model.bind_tools(tools=tools, tool_choice=tool_choice)
        logger.debug(
            'Invoking model %s with messages: %s',
            model_id,
            messages,
        )
        fallback_triggered = False
        result = None
        model_invoked = model
        try:
            result = await chat_model.ainvoke(
                input=messages, **self._normalize_kwargs_for_model(model, kwargs)
            )
        except Exception as primary_chat_model_exception:
            logger.warning(
                'Primary chat model %s failed: %s. Trying fallbacks...',
                model_id,
                str(primary_chat_model_exception),
            )
            for fallback_model, fallback_chat_model in fallbacks or []:
                try:
                    if tools and tool_choice:
                        fallback_chat_model = fallback_chat_model.bind_tools(
                            tools=tools, tool_choice=tool_choice
                        )
                    result = await fallback_chat_model.ainvoke(
                        input=messages,
                        **self._normalize_kwargs_for_model(fallback_model, kwargs),
                    )
                    fallback_triggered = True
                    model_invoked = fallback_model
                    break
                except Exception as fallback_chat_model_exception:
                    logger.warning(
                        'Fallback chat model %s failed: %s',
                        fallback_model.model_id,
                        str(fallback_chat_model_exception),
                    )
            if result is None:
                logger.error(
                    'All chat models failed for route %s',
                    route_name,
                    exc_info=primary_chat_model_exception,
                )
                raise ModelInvokerInternalError(
                    f'All chat models failed for model {route_name}: {str(primary_chat_model_exception)}'
                ) from primary_chat_model_exception
            return result, model_invoked, fallback_triggered
        return result, model_invoked, fallback_triggered

    @task(name='llm_complete')
    async def complete(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        route_name: str,
        messages: list[BaseMessage],
        model_id: str,
        tools: list[ChatCompletionToolParam] | None,
        tool_choice: ChatCompletionToolChoiceOptionParam | None,
        project_uuid: str = '',
        project_name: str = '',
        **kwargs,
    ) -> ChatCompletion:
        start_time = time.monotonic()
        result, model_invoked, fallback_triggered = await self._execute_with_fallbacks(
            route_name=route_name,
            model_id=model_id,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            **kwargs,
        )
        latency_ms = (time.monotonic() - start_time) * 1000

        usage_metadata = (
            result.usage_metadata if isinstance(result, AIMessage) else None
        )
        response_metadata = (
            result.response_metadata if isinstance(result, AIMessage) else None
        )
        (
            cached_token_count,
            cache_creation_5m_token_count,
            cache_creation_1h_token_count,
        ) = self._extract_cache_token_counts(usage_metadata, response_metadata)

        token_input_count: int | None = None

        if isinstance(result, AIMessage) and result.usage_metadata:
            input_tokens = result.usage_metadata.get('input_tokens')
            if input_tokens is not None:
                token_input_count = (
                    input_tokens
                    - (cached_token_count or 0)
                    - (cache_creation_5m_token_count or 0)
                    - (cache_creation_1h_token_count or 0)
                )

        if isinstance(result, AIMessage) and result.usage_metadata:
            token_output_count = result.usage_metadata.get('output_tokens')

            self._record_metrics(
                request_uuid=request_uuid,
                api_key_uuid=api_key_uuid,
                group_uuid=group_uuid,
                api_key_name=api_key_name,
                group_name=group_name,
                route_name=route_name,
                model=model_invoked,
                target_model_id=model_id,
                latency_ms=latency_ms,
                model_type='chat-model',
                token_input_count=token_input_count,
                token_output_count=token_output_count,
                cached_token_count=cached_token_count,
                cache_creation_5m_token_count=cache_creation_5m_token_count,
                cache_creation_1h_token_count=cache_creation_1h_token_count,
                fallback_triggered=fallback_triggered,
                project_uuid=project_uuid,
                project_name=project_name,
            )

        if isinstance(result, AIMessage):
            return ChatUtils.to_openai_chat_completion(
                result,
                model_id_invoked=model_invoked.model_id,
                request_id=request_uuid,
            )
        if isinstance(result, BaseMessage):
            ai_message = AIMessage(content=result.content)
            return ChatUtils.to_openai_chat_completion(
                ai_message,
                model_id_invoked=model_invoked.model_id,
                request_id=request_uuid,
            )
        raise ModelInvokerInternalError(
            f'Expected AIMessage or BaseMessage, got {type(result)}'
        )

    async def _stream_with_metrics(
        self,
        chat_model: BaseChatModel,
        messages: list[BaseMessage],
        stats: dict[str, int],
        **kwargs,
    ) -> AsyncIterator[AIMessageChunk]:
        """Help generator to stream chunks and update metrics stats."""
        async for chunk in chat_model.astream(input=messages, **kwargs):
            if chunk.usage_metadata:
                input_tokens = chunk.usage_metadata.get('input_tokens') or 0
                stats['token_output_count'] += (
                    chunk.usage_metadata.get('output_tokens') or 0
                )

                cached, creation_5m, creation_1h = self._extract_cache_token_counts(
                    usage_metadata=chunk.usage_metadata,
                    response_metadata=chunk.response_metadata,
                )
                if cached is not None:
                    stats['cached_token_count'] = cached
                if creation_5m is not None:
                    stats['cache_creation_5m_token_count'] = creation_5m
                if creation_1h is not None:
                    stats['cache_creation_1h_token_count'] = creation_1h

                if input_tokens:
                    stats['token_input_count'] = (
                        input_tokens
                        - (stats['cached_token_count'] or 0)
                        - (stats['cache_creation_5m_token_count'] or 0)
                        - (stats['cache_creation_1h_token_count'] or 0)
                    )

            yield chunk

    @task(name='llm_stream')
    async def stream(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        route_name: str,
        messages: list[BaseMessage],
        model_id: str,
        tools: list[ChatCompletionToolParam] | None,
        tool_choice: ChatCompletionToolChoiceOptionParam | None,
        project_uuid: str = '',
        project_name: str = '',
        **kwargs,
    ) -> AsyncIterator[AIMessageChunk]:
        if model_id not in self.model_map:
            raise ModelInvokerBadRequest(f'Chat model {model_id} not defined')

        model, chat_model, fallbacks = self.model_map[model_id]
        if tools and tool_choice:
            chat_model = chat_model.bind_tools(tools=tools, tool_choice=tool_choice)

        start_time = time.monotonic()
        # Shared mutable stats object
        stats = {
            'token_input_count': 0,
            'token_output_count': 0,
            'cached_token_count': 0,
            'cache_creation_5m_token_count': 0,
            'cache_creation_1h_token_count': 0,
        }
        fallback_triggered = False
        model_invoked = model

        try:
            # Primary model stream
            async for chunk in self._stream_with_metrics(
                chat_model,
                messages,
                stats,
                **self._normalize_kwargs_for_model(model, kwargs),
            ):
                yield chunk

        except Exception as primary_error:
            logger.warning(
                'Primary model %s stream failed: %s', model_id, str(primary_error)
            )
            fallback_success = False
            for fb_model, fb_chat_model in fallbacks or []:
                try:
                    logger.info(
                        'Trying fallback model %s for streaming', fb_model.model_id
                    )
                    if tools and tool_choice:
                        fb_chat_model = fb_chat_model.bind_tools(
                            tools=tools, tool_choice=tool_choice
                        )

                    # Reset stats for fallback attempt
                    stats['token_input_count'] = 0
                    stats['token_output_count'] = 0
                    stats['cached_token_count'] = 0
                    stats['cache_creation_5m_token_count'] = 0
                    stats['cache_creation_1h_token_count'] = 0

                    model_invoked = fb_model

                    async for chunk in self._stream_with_metrics(
                        fb_chat_model,
                        messages,
                        stats,
                        **self._normalize_kwargs_for_model(fb_model, kwargs),
                    ):
                        yield chunk

                    fallback_success = True
                    fallback_triggered = True
                    break
                except Exception as fb_error:
                    logger.warning(
                        'Fallback %s stream failed: %s',
                        fb_model.model_id,
                        str(fb_error),
                    )

            if not fallback_success:
                raise ModelInvokerInternalError(
                    f'All models failed for streaming {route_name}'
                ) from primary_error

        finally:
            latency_ms = (time.monotonic() - start_time) * 1000

            self._record_metrics(
                request_uuid=request_uuid,
                api_key_uuid=api_key_uuid,
                group_uuid=group_uuid,
                api_key_name=api_key_name,
                group_name=group_name,
                route_name=route_name,
                model=model_invoked,
                target_model_id=model_id,
                latency_ms=latency_ms,
                model_type='chat-model',
                token_input_count=stats['token_input_count']
                if stats['token_input_count'] > 0
                else None,
                token_output_count=stats['token_output_count']
                if stats['token_output_count'] > 0
                else None,
                cached_token_count=stats['cached_token_count']
                if stats['cached_token_count'] > 0
                else None,
                cache_creation_5m_token_count=stats['cache_creation_5m_token_count']
                if stats['cache_creation_5m_token_count'] > 0
                else None,
                cache_creation_1h_token_count=stats['cache_creation_1h_token_count']
                if stats['cache_creation_1h_token_count'] > 0
                else None,
                fallback_triggered=fallback_triggered,
                project_uuid=project_uuid,
                project_name=project_name,
            )
