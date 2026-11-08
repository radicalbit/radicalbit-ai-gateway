from collections.abc import AsyncIterator
import logging
from typing import NoReturn

from openai.types.chat import ChatCompletionToolChoiceOptionParam
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.chat.chat_completion_tool_param import ChatCompletionToolParam
from traceloop.sdk.decorators import task

from radicalbit_ai_gateway.invocation.errors import (
    Surface,
    final_messages_refusal,
    raising,
)
from radicalbit_ai_gateway.invocation.fallback_chain import (
    Attempt,
    CallContext,
    Candidate,
    FallbackChain,
    Reply,
    candidates,
)
from radicalbit_ai_gateway.invocation.model_invoker import ModelInvoker
from radicalbit_ai_gateway.invocation.recorder import Call, Tokens
from radicalbit_ai_gateway.llm.chat_model import ChatModel
from radicalbit_ai_gateway.llm.factory import init_chat_model
from radicalbit_ai_gateway.llm.messages import AIMessage, AIMessageChunk, BaseMessage
from radicalbit_ai_gateway.messages.events import stream_usage
from radicalbit_ai_gateway.messages.thinking import (
    is_invalid_thinking_signature,
    without_old_thinking,
)
from radicalbit_ai_gateway.models.fallback import Fallback
from radicalbit_ai_gateway.models.model import (
    ENABLE_PROMPT_CACHE_PARAM,
    MockGatewayChatModel,
    Model,
)
from radicalbit_ai_gateway.models.request_identity import RequestIdentity
from radicalbit_ai_gateway.responses.events import NativeResponsesEvent
from radicalbit_ai_gateway.responses.output import usage_token_counts
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.chat_utils import ChatUtils
from radicalbit_ai_gateway.utils.exceptions import (
    ModelInvokerBadRequest,
    ModelInvokerInternalError,
    ModelInvokerUpstreamError,
)
from radicalbit_ai_gateway.utils.parse_provider_and_model import (
    parse_provider_and_model,
)

app_config = get_app_config()

logger = logging.getLogger(app_config.log_config.logger_name)

CHAT_MODEL_TYPE = 'chat-model'
# What a stream counts, in the order of ``Tokens``' fields.
STREAM_STATS = (
    'token_input_count',
    'token_output_count',
    'cached_token_count',
    'cache_creation_5m_token_count',
    'cache_creation_1h_token_count',
)


def build_chat_model(model: Model, httpx_client=None) -> ChatModel:
    """Build a chat model from configuration.

    Shared by the chat invoker and by the routers that call a chat model.

    Returns:
        ChatModel: A chat model instance.

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

    # Strip gateway-only params that must not reach the provider
    _GATEWAY_PARAMS = {ENABLE_PROMPT_CACHE_PARAM}
    init_kwargs = {
        k: v for k, v in {**params, **credentials}.items() if k not in _GATEWAY_PARAMS
    }

    # Factory provider keys use underscores (google_genai) where the gateway
    # config uses hyphens (google-genai)
    factory_provider = provider.replace('-', '_')

    if provider not in ('anthropic', 'mistralai'):
        init_kwargs['http_async_client'] = httpx_client
    return init_chat_model(
        model=f'{factory_provider}:{model_name}',
        **init_kwargs,
    )


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

    def _build_model(self, model: Model) -> ChatModel:
        return build_chat_model(model, self.httpx_client)

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

    def _call(self, model_id: str, route_name: str, **request: str) -> Call:
        return Call(
            identity=RequestIdentity(route_name=route_name, **request),
            model_type=CHAT_MODEL_TYPE,
            target_model_id=model_id,
        )

    def _chain(
        self,
        model_id: str,
        tools: list[ChatCompletionToolParam] | None,
        tool_choice: ChatCompletionToolChoiceOptionParam | None,
        call: Call,
        **context,
    ) -> FallbackChain:
        """Return the chain of ``model_id``, each model offering the tools.

        The target is bound here: a tool it cannot take fails the request.
        A fallback is bound when its turn comes (see ``_bound``).
        """
        if model_id not in self.model_map:
            raise ModelInvokerBadRequest(f'Chat model {model_id} not defined')
        model, chat_model, fallbacks = self.model_map[model_id]
        if tools and tool_choice:
            chat_model = chat_model.bind_tools(tools=tools, tool_choice=tool_choice)
        return FallbackChain(
            candidates((model, chat_model), fallbacks),
            CallContext(call=call, recorder=self.recorder, **context),
        )

    @staticmethod
    def _bound(candidate: Candidate, tools, tool_choice) -> ChatModel:
        if candidate.is_fallback and tools and tool_choice:
            return candidate.client.bind_tools(tools=tools, tool_choice=tool_choice)
        return candidate.client

    @classmethod
    def _tokens(cls, message: AIMessage) -> Tokens | None:
        """Return the tokens of a reply; None when it reports no usage."""
        if not isinstance(message, AIMessage) or not message.usage_metadata:
            return None
        cached, creation_5m, creation_1h = cls._extract_cache_token_counts(
            message.usage_metadata, message.response_metadata
        )
        input_tokens = message.usage_metadata.get('input_tokens')
        if input_tokens is not None:
            input_tokens -= (cached or 0) + (creation_5m or 0) + (creation_1h or 0)
        return Tokens(
            input=input_tokens,
            output=message.usage_metadata.get('output_tokens'),
            cached=cached,
            cache_5m=creation_5m,
            cache_1h=creation_1h,
        )

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
        call = self._call(
            model_id,
            route_name,
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            api_key_name=api_key_name,
            group_uuid=group_uuid,
            group_name=group_name,
            project_uuid=project_uuid,
            project_name=project_name,
        )

        def log_failure(candidate: Candidate, error: BaseException) -> None:
            if candidate.is_fallback:
                logger.warning(
                    'Fallback chat model %s failed: %s',
                    candidate.model.model_id,
                    str(error),
                )
            else:
                logger.warning(
                    'Primary chat model %s failed: %s. Trying fallbacks...',
                    model_id,
                    str(error),
                )

        chain = self._chain(
            model_id,
            tools,
            tool_choice,
            call,
            on_failure=log_failure,
            on_exhausted=raising(Surface.CHAT, route_name),
        )
        logger.debug('Invoking model %s with messages: %s', model_id, messages)

        async def ask(candidate: Candidate) -> Reply:
            result = await self._bound(candidate, tools, tool_choice).ainvoke(
                input=messages,
                **self._normalize_kwargs_for_model(candidate.model, kwargs),
            )
            return Reply((result, candidate.model), usage=self._tokens(result))

        result, model_invoked = await chain.call(ask)
        if not isinstance(result, AIMessage) and isinstance(result, BaseMessage):
            result = AIMessage(content=result.content)
        if not isinstance(result, AIMessage):
            raise ModelInvokerInternalError(
                f'Expected AIMessage or BaseMessage, got {type(result)}'
            )
        return ChatUtils.to_openai_chat_completion(
            result,
            model_id_invoked=model_invoked.model_id,
            request_id=request_uuid,
        )

    async def _stream_with_metrics(
        self,
        chat_model: ChatModel,
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

    @staticmethod
    def _stream_tokens(stats: dict[str, int] | None) -> Tokens:
        """Return a stream's tokens: a count of 0 is not reported."""
        stats = stats or {}
        return Tokens(*(stats.get(key) or None for key in STREAM_STATS))

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
        call = self._call(
            model_id,
            route_name,
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            api_key_name=api_key_name,
            group_uuid=group_uuid,
            group_name=group_name,
            project_uuid=project_uuid,
            project_name=project_name,
        )

        def log_failure(candidate: Candidate, error: BaseException) -> None:
            if candidate.is_fallback:
                logger.warning(
                    'Fallback %s stream failed: %s',
                    candidate.model.model_id,
                    str(error),
                )
            else:
                logger.warning(
                    'Primary model %s stream failed: %s', model_id, str(error)
                )

        def record(candidate: Candidate, stats, latency_ms: float) -> None:
            self.recorder.invocation(
                call,
                candidate.model,
                latency_ms,
                tokens=self._stream_tokens(stats),
                fallback_triggered=candidate.is_fallback,
            )

        chain = self._chain(
            model_id,
            tools,
            tool_choice,
            call,
            record=record,
            on_failure=log_failure,
            on_exhausted=raising(Surface.CHAT_STREAM, route_name),
        )

        async def stream(attempt: Attempt) -> AsyncIterator[AIMessageChunk]:
            candidate = attempt.candidate
            if candidate.is_fallback:
                logger.info(
                    'Trying fallback model %s for streaming', candidate.model.model_id
                )
            attempt.usage = dict.fromkeys(STREAM_STATS, 0)
            async for chunk in self._stream_with_metrics(
                self._bound(candidate, tools, tool_choice),
                messages,
                attempt.usage,
                **self._normalize_kwargs_for_model(candidate.model, kwargs),
            ):
                yield chunk

        async for chunk in chain.stream(stream):
            yield chunk

    # ── Responses API ────────────────────────────────────────────────────

    def supports_responses(self, model_id: str) -> bool:
        """Whether the model serves the Responses API."""
        if model_id not in self.model_map:
            return False
        _, chat_model, _ = self.model_map[model_id]
        return chat_model.supports_native_responses()

    def _responses_chain(
        self,
        model_id: str,
        allow_fallback: bool,
        body: dict,
        call: Call,
        route_name: str,
    ) -> FallbackChain:
        """Return the chain of the model, then its fallbacks that serve the
        Responses API. Each candidate's client is the model and the body to
        send it.

        The history may hold items another provider produced: each model, the
        first included, gets the input adapted to what it accepts.
        """
        if not self.supports_responses(model_id):
            raise ModelInvokerBadRequest(
                f'Chat model {model_id} does not serve the Responses API'
            )
        model, chat_model, fallbacks = self.model_map[model_id]
        served = [
            (fallback, fallback_model)
            for fallback, fallback_model in (fallbacks if allow_fallback else [])
            if fallback_model.supports_native_responses()
        ]
        pairs = [
            (candidate, (candidate_model, self._responses_body(candidate_model, body)))
            for candidate, candidate_model in [(model, chat_model), *served]
        ]

        def record(candidate: Candidate, usage: dict | None, latency_ms: float):
            self._record_responses(call, candidate, usage, latency_ms)

        return FallbackChain(
            candidates(pairs[0], pairs[1:]),
            CallContext(
                call=call,
                recorder=self.recorder,
                record=record,
                on_failure=_log_responses_failure,
                on_exhausted=raising(Surface.RESPONSES, route_name),
            ),
        )

    @staticmethod
    def _responses_body(chat_model: ChatModel, body: dict) -> dict:
        """Return the body with its input adapted for ``chat_model``."""
        items = body.get('input')
        if not isinstance(items, list):
            return body
        return {**body, 'input': chat_model.adapt_responses_input(items)}

    def _record_responses(
        self, call: Call, candidate: Candidate, usage: dict | None, latency_ms: float
    ) -> None:
        input_tokens, cached, output = usage_token_counts(usage)
        self.recorder.invocation(
            call,
            candidate.model,
            latency_ms,
            tokens=Tokens(
                input=(input_tokens - cached) or None,
                output=output or None,
                cached=cached or None,
            ),
            fallback_triggered=candidate.is_fallback,
        )

    @task(name='llm_stream_responses')
    async def stream_responses(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        route_name: str,
        body: dict,
        model_id: str,
        allow_fallback: bool = True,
        project_uuid: str = '',
        project_name: str = '',
    ) -> AsyncIterator[NativeResponsesEvent]:
        """Stream a Responses API request and yield the upstream's events.

        A fallback is tried only while nothing has been yielded: once the
        client has part of a reply, an error ends the stream.
        """
        call = self._call(
            model_id,
            route_name,
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            api_key_name=api_key_name,
            group_uuid=group_uuid,
            group_name=group_name,
            project_uuid=project_uuid,
            project_name=project_name,
        )
        chain = self._responses_chain(model_id, allow_fallback, body, call, route_name)

        async def stream(attempt: Attempt) -> AsyncIterator[NativeResponsesEvent]:
            chat_model, candidate_body = attempt.candidate.client
            async for event, data in chat_model.astream_native_responses(
                candidate_body
            ):
                native_event = NativeResponsesEvent.parse(event, data)
                if native_event.is_final:
                    attempt.usage = native_event.usage
                yield native_event

        async for event in chain.stream(stream):
            yield event

    @task(name='llm_complete_responses')
    async def complete_responses(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        route_name: str,
        body: dict,
        model_id: str,
        allow_fallback: bool = True,
        project_uuid: str = '',
        project_name: str = '',
    ) -> tuple[dict, Model]:
        """Answer a Responses API request; return the upstream's response
        object and the model that answered.
        """
        call = self._call(
            model_id,
            route_name,
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            api_key_name=api_key_name,
            group_uuid=group_uuid,
            group_name=group_name,
            project_uuid=project_uuid,
            project_name=project_name,
        )
        chain = self._responses_chain(model_id, allow_fallback, body, call, route_name)

        async def ask(candidate: Candidate) -> Reply:
            chat_model, candidate_body = candidate.client
            result = await chat_model.ainvoke_native_responses(candidate_body)
            # A reply without usage is recorded too: {} is not None.
            return Reply((result, candidate.model), usage=result.get('usage') or {})

        return await chain.call(ask)

    # ── Messages API ─────────────────────────────────────────────────────

    def supports_messages(self, model_id: str) -> bool:
        """Whether the model serves the Anthropic Messages API."""
        if model_id not in self.model_map:
            return False
        _, chat_model, _ = self.model_map[model_id]
        return chat_model.supports_native_messages()

    def _messages_chain(
        self, model_id: str, call: Call, route_name: str
    ) -> FallbackChain:
        """Return the chain of the model, then its fallbacks in order.

        A fallback that does not serve the Messages API ends the chain: the
        request fails when it gets there, it is never translated.
        """
        if not self.supports_messages(model_id):
            raise ModelInvokerBadRequest(
                f'Chat model {model_id} does not serve the Messages API'
            )
        model, chat_model, fallbacks = self.model_map[model_id]
        served: list[tuple[Model, ChatModel]] = []
        unserved: Model | None = None
        for fallback, fallback_model in fallbacks or []:
            if not fallback_model.supports_native_messages():
                unserved = fallback
                break
            served.append((fallback, fallback_model))
        raise_exhausted = raising(Surface.MESSAGES, route_name)

        def on_exhausted(failures: list) -> NoReturn:
            if unserved is not None:
                raise ModelInvokerBadRequest(
                    f'Model {unserved.model_id} of route {route_name} '
                    'does not serve the Messages API'
                ) from failures[0].error
            raise_exhausted(failures)

        def record(candidate: Candidate, usage: dict | None, latency_ms: float):
            self.recorder.invocation(
                call,
                candidate.model,
                latency_ms,
                tokens=_messages_tokens(usage),
                fallback_triggered=candidate.is_fallback,
            )

        return FallbackChain(
            candidates((model, chat_model), served),
            CallContext(
                call=call,
                recorder=self.recorder,
                record=record,
                on_failure=_log_messages_failure,
                # A refusal of the request itself, raised as the client gets it.
                final=lambda error: isinstance(error, ModelInvokerUpstreamError),
                on_exhausted=on_exhausted,
            ),
        )

    @staticmethod
    def _signature_retry_body(model: Model, body: dict, error: Exception) -> dict:
        """Return the body to retry when the upstream refused a thinking signature.

        A client that switched models sends thinking that another provider
        signed. The retry goes to the same model without that thinking. Without
        such a refusal, or with nothing to strip, ``error`` is raised again.
        """
        if not is_invalid_thinking_signature(error):
            raise error
        retry_body, stripped = without_old_thinking(body)
        if not stripped:
            raise error
        logger.warning(
            'Messages model %s refused a thinking signature: '
            'retrying without %d old thinking blocks',
            model.model_id,
            stripped,
        )
        return retry_body

    async def _invoke_messages(
        self, model: Model, chat_model: ChatModel, body: dict, headers: dict[str, str]
    ) -> dict:
        """Make one Messages call to one model (see ``_signature_retry_body``)."""
        try:
            return await chat_model.ainvoke_native_messages(body, headers)
        except Exception as error:
            retry_body = self._signature_retry_body(model, body, error)
        return await chat_model.ainvoke_native_messages(retry_body, headers)

    async def _stream_messages(
        self, model: Model, chat_model: ChatModel, body: dict, headers: dict[str, str]
    ) -> AsyncIterator[tuple[str, str]]:
        """Stream one Messages call from one model (see ``_signature_retry_body``).

        The refusal comes before the first event, so the retry is safe.
        """
        started = False
        try:
            async for event, data in chat_model.astream_native_messages(body, headers):
                started = True
                yield event, data
        except Exception as error:
            if started:
                raise
            retry_body = self._signature_retry_body(model, body, error)
        else:
            return
        async for event, data in chat_model.astream_native_messages(
            retry_body, headers
        ):
            yield event, data

    @task(name='llm_complete_messages')
    async def complete_messages(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        route_name: str,
        body: dict,
        headers: dict[str, str],
        model_id: str,
        project_uuid: str = '',
        project_name: str = '',
    ) -> tuple[dict, Model]:
        """Answer a Messages API request; return the upstream's message object
        and the model that answered.
        """
        call = self._call(
            model_id,
            route_name,
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            api_key_name=api_key_name,
            group_uuid=group_uuid,
            group_name=group_name,
            project_uuid=project_uuid,
            project_name=project_name,
        )
        chain = self._messages_chain(model_id, call, route_name)

        async def ask(candidate: Candidate) -> Reply:
            try:
                result = await self._invoke_messages(
                    candidate.model, candidate.client, body, headers
                )
            except Exception as error:
                raise _final_or(error) from error
            # A reply without usage is recorded too: {} is not None.
            return Reply((result, candidate.model), usage=result.get('usage') or {})

        return await chain.call(ask)

    @task(name='llm_stream_messages')
    async def stream_messages(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        route_name: str,
        body: dict,
        headers: dict[str, str],
        model_id: str,
        project_uuid: str = '',
        project_name: str = '',
    ) -> AsyncIterator[tuple[str, str]]:
        """Stream a Messages API request and yield the upstream's ``(event, data)``.

        A fallback is tried only while nothing has been yielded: once the
        client has part of a reply, an error ends the stream.
        """
        call = self._call(
            model_id,
            route_name,
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            api_key_name=api_key_name,
            group_uuid=group_uuid,
            group_name=group_name,
            project_uuid=project_uuid,
            project_name=project_name,
        )
        chain = self._messages_chain(model_id, call, route_name)

        async def stream(attempt: Attempt) -> AsyncIterator[tuple[str, str]]:
            attempt.usage = {}
            started = False
            try:
                async for event, data in self._stream_messages(
                    attempt.candidate.model, attempt.candidate.client, body, headers
                ):
                    attempt.usage = stream_usage(event, data, attempt.usage)
                    started = True
                    yield event, data
            except Exception as error:
                if started:
                    raise
                raise _final_or(error) from error

        async for event in chain.stream(stream):
            yield event


def _log_responses_failure(candidate: Candidate, error: BaseException) -> None:
    logger.warning(
        'Responses model %s failed: %s', candidate.model.model_id, str(error)
    )


def _final_or(error: Exception) -> Exception:
    """Return the refusal a Messages client gets for ``error`` when no other
    model would serve the request, else ``error`` itself.
    """
    return final_messages_refusal(error) or error


def _messages_tokens(usage: dict | None) -> Tokens:
    """Return the tokens of a Messages API usage object; 0 is not reported."""
    usage = usage or {}
    cache_creation = usage.get('cache_creation') or {}
    return Tokens(
        input=usage.get('input_tokens') or None,
        output=usage.get('output_tokens') or None,
        cached=usage.get('cache_read_input_tokens') or None,
        cache_5m=cache_creation.get('ephemeral_5m_input_tokens') or None,
        cache_1h=cache_creation.get('ephemeral_1h_input_tokens') or None,
    )


def _log_messages_failure(candidate: Candidate, error: BaseException) -> None:
    logger.warning('Messages model %s failed: %s', candidate.model.model_id, str(error))
