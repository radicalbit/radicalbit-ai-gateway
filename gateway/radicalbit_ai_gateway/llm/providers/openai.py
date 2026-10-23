"""OpenAI and Azure OpenAI chat and embedding models, on the official SDK.

The settings, defaults and request building follow the LangChain OpenAI
integration the gateway used before, so every model configuration keeps
producing the same requests: unknown settings are sent as extra request
parameters, ``max_tokens`` is sent as ``max_completion_tokens``, some models
and parameters are routed to the Responses API, and so on.
"""

from collections.abc import AsyncIterator, Callable, Mapping
import os
import re
from typing import Any, ClassVar

import openai
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    SecretStr,
    field_validator,
    model_validator,
)
import tiktoken

from radicalbit_ai_gateway.llm.chat_model import ChatModel, StructuredChatModel
from radicalbit_ai_gateway.llm.embeddings import Embeddings, _run_in_executor
from radicalbit_ai_gateway.llm.messages import AIMessage, AIMessageChunk, BaseMessage
from radicalbit_ai_gateway.llm.providers import _openai_responses as responses_api
from radicalbit_ai_gateway.llm.providers._openai_common import (
    delta_to_chunk,
    dict_to_ai_message,
    message_to_dict,
    parse_first_tool_call,
    pydantic_to_function,
    strip_v1_blocks,
    to_openai_tool,
    to_response_format,
    tool_choice_kwarg,
    usage_metadata,
    with_chunk_timeout,
)

_DEFAULT_STREAM_CHUNK_TIMEOUT = 120.0


def _env(*names: str, default: Any = None) -> Callable[[], Any]:
    def factory() -> Any:
        for name in names:
            if (value := os.environ.get(name)) is not None:
                return value
        return default

    return factory


def _secret_env(*names: str) -> Callable[[], SecretStr | None]:
    def factory() -> SecretStr | None:
        value = _env(*names)()
        return SecretStr(value) if value is not None else None

    return factory


def _stream_chunk_timeout_default() -> float:
    raw = os.environ.get('LANGCHAIN_OPENAI_STREAM_CHUNK_TIMEOUT_S')
    if raw is None:
        return _DEFAULT_STREAM_CHUNK_TIMEOUT
    try:
        value = float(raw)
    except ValueError:
        return _DEFAULT_STREAM_CHUNK_TIMEOUT
    return _DEFAULT_STREAM_CHUNK_TIMEOUT if value < 0 else value


def _secret_value(value: SecretStr | None) -> str | None:
    return value.get_secret_value() if value is not None else None


def _field_names(cls: type[BaseModel]) -> set[str]:
    names = set()
    for name, field in cls.model_fields.items():
        names.add(name)
        if field.alias:
            names.add(field.alias)
    return names


def _collect_model_kwargs(cls: type[BaseModel], values: Any) -> Any:
    """Move settings that are not fields into ``model_kwargs``.

    They are sent as extra request parameters, as LangChain did.
    """
    if not isinstance(values, dict):
        return values
    values = dict(values)
    known = _field_names(cls)
    extra = dict(values.get('model_kwargs') or {})
    for name in list(values):
        if name in extra:
            raise ValueError(f'Found {name} supplied twice.')
        if name not in known:
            extra[name] = values.pop(name)
    for name in known.intersection(extra):
        values[name] = extra.pop(name)
    values['model_kwargs'] = extra
    return values


# The classes LangChain re-raised the SDK's errors as, by SDK error class.
_LANGCHAIN_ERROR_TYPES = (
    (openai.AuthenticationError, 'OpenAIAuthenticationError'),
    (openai.PermissionDeniedError, 'OpenAIPermissionDeniedError'),
    (openai.NotFoundError, 'OpenAIModelNotFoundError'),
    (openai.RateLimitError, 'OpenAIRateLimitError'),
    (openai.InternalServerError, 'OpenAIAPIError'),
    (openai.APITimeoutError, 'OpenAITimeoutError'),
    (openai.APIConnectionError, 'OpenAIConnectionError'),
)


def _langchain_error_type(error: BaseException) -> str:
    """Return the name of the error class LangChain raised for an SDK ``error``."""
    if isinstance(error, openai.BadRequestError):
        if (
            'context_length_exceeded' in str(error)
            or 'Input tokens exceed the configured limit' in error.message
            or 'prompt is too long' in error.message
            or 'ContextWindowExceededError' in error.message
        ):
            return 'OpenAIContextOverflowError'
        return 'OpenAIInvalidRequestError'
    if isinstance(error, openai.APIError):
        if 'exceeds the context window' in str(error):
            return 'OpenAIAPIContextOverflowError'
        for error_class, name in _LANGCHAIN_ERROR_TYPES:
            if isinstance(error, error_class):
                return name
    return type(error).__name__


class OpenAIRefusalError(Exception):
    """The model refused to produce the requested structured output."""


def _parse_structured_output(message: AIMessage, schema: type[BaseModel]) -> Any:
    if (parsed := message.additional_kwargs.get('parsed')) is not None:
        if isinstance(parsed, dict):
            return schema(**parsed)
        return parsed
    if message.additional_kwargs.get('refusal'):
        raise OpenAIRefusalError(message.additional_kwargs['refusal'])
    if message.tool_calls:
        return None
    raise ValueError(
        "Structured Output response does not have a 'parsed' field nor a 'refusal' "
        f'field. Received message:\n\n{message}'
    )


class _Structured(StructuredChatModel):
    def __init__(
        self,
        model: '_BaseChatOpenAI',
        parser: Callable[[AIMessage], Any],
        include_raw: bool,
    ):
        self.model = model
        self.parser = parser
        self.include_raw = include_raw

    async def ainvoke(self, input, **kwargs: Any) -> Any:  # noqa: A002
        raw = await self.model.ainvoke(input, **kwargs)
        if not self.include_raw:
            return self.parser(raw)
        try:
            return {'raw': raw, 'parsed': self.parser(raw), 'parsing_error': None}
        except Exception as e:
            return {'raw': raw, 'parsed': None, 'parsing_error': e}


class _BaseChatOpenAI(ChatModel, BaseModel):
    """Chat model on an OpenAI-compatible Chat Completions (or Responses) API."""

    model_config = ConfigDict(
        populate_by_name=True, arbitrary_types_allowed=True, protected_namespaces=()
    )

    model_name: str | None = Field(default='gpt-3.5-turbo', alias='model')
    temperature: float | None = None
    model_kwargs: dict[str, Any] = Field(default_factory=dict)
    openai_api_key: SecretStr | None = Field(default=None, alias='api_key')
    openai_api_base: str | None = Field(default=None, alias='base_url')
    openai_organization: str | None = Field(default=None, alias='organization')
    openai_proxy: str | None = Field(default_factory=_env('OPENAI_PROXY'))
    request_timeout: float | tuple[float, float] | Any | None = Field(
        default=None, alias='timeout'
    )
    stream_usage: bool | None = None
    max_retries: int | None = None
    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    seed: int | None = None
    logprobs: bool | None = None
    top_logprobs: int | None = None
    logit_bias: dict[int, int] | None = None
    streaming: bool = False
    n: int | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    reasoning_effort: str | None = None
    reasoning: dict[str, Any] | None = None
    verbosity: str | None = None
    tiktoken_model_name: str | None = None
    default_headers: Mapping[str, str] | None = None
    default_query: Mapping[str, object] | None = None
    http_client: Any | None = None
    http_async_client: Any | None = None
    http_socket_options: Any | None = None
    stream_chunk_timeout: float | None = Field(
        default_factory=_stream_chunk_timeout_default
    )
    stop: list[str] | str | None = Field(default=None, alias='stop_sequences')
    extra_body: Mapping[str, Any] | None = None
    include_response_headers: bool = False
    disabled_params: dict[str, Any] | None = None
    context_management: list[dict[str, Any]] | None = None
    include: list[str] | None = None
    prompt_cache_options: dict[str, Any] | None = None
    service_tier: str | None = None
    store: bool | None = None
    truncation: str | None = None
    use_previous_response_id: bool = False
    use_responses_api: bool | None = None
    output_version: str | None = Field(default_factory=_env('LC_OUTPUT_VERSION'))
    # LangChain runnable settings: accepted, without effect.
    client: Any = None
    async_client: Any = None
    root_client: Any = None
    root_async_client: Any = None
    cache: Any = None
    callbacks: Any = None
    custom_get_token_ids: Any = None
    disable_streaming: Any = False
    metadata: Any = None
    name: str | None = None
    profile: Any = None
    rate_limiter: Any = None
    tags: Any = None
    verbose: Any = None

    _client: Any = PrivateAttr(default=None)
    # Arguments bound by bind_tools/with_structured_output.
    _bound: dict[str, Any] = PrivateAttr(default_factory=dict)

    _gen_ai_provider: ClassVar[str] = 'openai'

    @model_validator(mode='before')
    @classmethod
    def _build_extra(cls, values: Any) -> Any:
        return _collect_model_kwargs(cls, values)

    @model_validator(mode='before')
    @classmethod
    def _validate_temperature(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        model = (values.get('model_name') or values.get('model') or '').lower()
        # o1 models only support the default temperature.
        if model.startswith('o1') and 'temperature' not in values:
            values['temperature'] = 1
        # gpt-5 reasoning models only accept temperature=1.
        if (
            model.startswith('gpt-5')
            and 'chat' not in model
            and values.get('reasoning_effort') != 'none'
            and (values.get('reasoning') or {}).get('effort') != 'none'
        ):
            temperature = values.get('temperature')
            if temperature is not None and temperature != 1:
                values.pop('temperature', None)
        return values

    @field_validator('stream_chunk_timeout', mode='after')
    @classmethod
    def _validate_stream_chunk_timeout(cls, value: float | None) -> float | None:
        if value is not None and value < 0:
            return _stream_chunk_timeout_default()
        return value

    def _check_n(self) -> None:
        if self.n is not None and self.n < 1:
            raise ValueError('n must be at least 1.')
        if self.n is not None and self.n > 1 and self.streaming:
            raise ValueError('n must be 1 when streaming.')

    # ── Request ──────────────────────────────────────────────────────────

    @property
    def _default_params(self) -> dict[str, Any]:
        exclude_if_none = {
            'presence_penalty': self.presence_penalty,
            'frequency_penalty': self.frequency_penalty,
            'seed': self.seed,
            'top_p': self.top_p,
            'logprobs': self.logprobs,
            'top_logprobs': self.top_logprobs,
            'logit_bias': self.logit_bias,
            'stop': self.stop or None,
            'max_tokens': self.max_tokens,
            'extra_body': self.extra_body,
            'n': self.n,
            'temperature': self.temperature,
            'reasoning_effort': self.reasoning_effort,
            'reasoning': self.reasoning,
            'verbosity': self.verbosity,
            'context_management': self.context_management,
            'include': self.include,
            'prompt_cache_options': self.prompt_cache_options,
            'service_tier': self.service_tier,
            'truncation': self.truncation,
            'store': self.store,
        }
        return {
            'model': self.model_name,
            'stream': self.streaming,
            **{k: v for k, v in exclude_if_none.items() if v is not None},
            **self.model_kwargs,
        }

    def _use_responses_api(self, payload: dict) -> bool:
        if isinstance(self.use_responses_api, bool):
            return self.use_responses_api
        if (
            self.output_version == 'responses/v1'
            or self.context_management is not None
            or self.include is not None
            or self.reasoning is not None
            or self.truncation is not None
            or self.use_previous_response_id
            or responses_api.model_prefers_responses_api(self.model_name)
        ):
            return True
        return responses_api.payload_uses_responses_api(payload)

    def _get_request_payload(self, messages: list[BaseMessage], **kwargs: Any) -> dict:
        payload = {**self._default_params, **kwargs}
        if self._use_responses_api(payload):
            if self.use_previous_response_id:
                messages, previous_id = _messages_after_last_response(messages)
                if previous_id:
                    payload['previous_response_id'] = previous_id
            return responses_api.build_payload(messages, payload)
        payload['messages'] = [
            message_to_dict(strip_v1_blocks(m))
            if isinstance(m, AIMessage)
            else message_to_dict(m)
            for m in messages
        ]
        return payload

    def _call_kwargs(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        kwargs = {**self._bound, **kwargs}
        # A None stop keeps the configured stop sequences.
        if 'stop' in kwargs and kwargs['stop'] is None:
            del kwargs['stop']
        return kwargs

    def _should_stream_usage(
        self, stream_usage: bool | None = None, **kwargs: Any
    ) -> bool:
        for source in (
            stream_usage,
            kwargs.get('stream_options', {}).get('include_usage'),
            self.model_kwargs.get('stream_options', {}).get('include_usage'),
            self.stream_usage,
        ):
            if isinstance(source, bool):
                return source
        return self.stream_usage or False

    # ── Reply ────────────────────────────────────────────────────────────

    def _chat_result(
        self, response: Any, generation_info: dict | None = None
    ) -> tuple[list[tuple[AIMessage, dict]], dict]:
        """Messages (with their generation info) and the reply-level info."""
        if not isinstance(response, dict | openai.BaseModel):
            # A non-JSON body (e.g. an HTML error page) parses to a string.
            preview = repr(response)
            if len(preview) > 200:
                preview = f'{preview[:200]}...'
            raise ValueError(  # noqa: TRY004 - LangChain raised ValueError
                'Unexpected response type from OpenAI-compatible endpoint. '
                'Expected a dict or openai.BaseModel, got '
                f'{type(response).__name__}: {preview}'
            )
        response_dict = (
            response
            if isinstance(response, dict)
            else response.model_dump(
                exclude={'choices': {'__all__': {'message': {'parsed'}}}},
                warnings=False,
            )
        )
        if response_dict.get('error'):
            raise ValueError(response_dict.get('error'))
        try:
            choices = response_dict['choices']
        except KeyError as e:
            raise KeyError(
                f"Response missing 'choices' key: {response_dict.keys()}"
            ) from e
        if choices is None:
            raise TypeError(
                "Received response with null value for 'choices'. "
                'This can happen when using OpenAI-compatible APIs (e.g., vLLM) '
                'that return a response in an unexpected format. '
                f'Full response keys: {list(response_dict.keys())}'
            )

        token_usage = response_dict.get('usage')
        service_tier = response_dict.get('service_tier')
        generations = []
        for choice in choices:
            message = dict_to_ai_message(choice['message'])
            if token_usage:
                message.usage_metadata = usage_metadata(token_usage, service_tier)
            info = dict(generation_info or {})
            info['finish_reason'] = (
                choice.get('finish_reason')
                if choice.get('finish_reason') is not None
                else info.get('finish_reason')
            )
            if 'logprobs' in choice:
                info['logprobs'] = choice['logprobs']
            generations.append((message, info))
        llm_output = {
            'token_usage': token_usage,
            'model_provider': 'openai',
            'model_name': response_dict.get('model', self.model_name),
            'system_fingerprint': response_dict.get('system_fingerprint', ''),
        }
        if 'id' in response_dict:
            llm_output['id'] = response_dict['id']
        if service_tier:
            llm_output['service_tier'] = service_tier

        if isinstance(response, openai.BaseModel) and getattr(
            response, 'choices', None
        ):
            first = response.choices[0].message
            if hasattr(first, 'parsed'):
                generations[0][0].additional_kwargs['parsed'] = first.parsed
            if hasattr(first, 'refusal'):
                generations[0][0].additional_kwargs['refusal'] = first.refusal
        return generations, llm_output

    def _create_chat_result(
        self, response: Any, generation_info: dict | None = None
    ) -> AIMessage:
        generations, llm_output = self._chat_result(response, generation_info)
        message, info = generations[0]
        message.response_metadata = {**info, **message.response_metadata}
        if len(generations) == 1:
            message.response_metadata = {**llm_output, **message.response_metadata}
        return message

    def _convert_chunk(
        self, chunk: dict, base_generation_info: dict
    ) -> tuple[AIMessageChunk, dict | None] | None:
        if chunk.get('type') == 'content.delta':
            return None
        token_usage = chunk.get('usage')
        # Events of the structured-output stream helper wrap the chunk.
        choices = chunk.get('choices', []) or chunk.get('chunk', {}).get('choices', [])
        usage = (
            usage_metadata(token_usage, chunk.get('service_tier'))
            if token_usage
            else None
        )
        if len(choices) == 0:
            return AIMessageChunk(
                content='', usage_metadata=usage
            ), base_generation_info

        choice = choices[0]
        if choice['delta'] is None:
            return None
        message = delta_to_chunk(choice['delta'])
        generation_info = {**base_generation_info} if base_generation_info else {}
        if finish_reason := choice.get('finish_reason'):
            generation_info['finish_reason'] = finish_reason
            if model_name := chunk.get('model'):
                generation_info['model_name'] = model_name
            if system_fingerprint := chunk.get('system_fingerprint'):
                generation_info['system_fingerprint'] = system_fingerprint
            if service_tier := chunk.get('service_tier'):
                generation_info['service_tier'] = service_tier
        if logprobs := choice.get('logprobs'):
            generation_info['logprobs'] = logprobs
        if usage:
            message.usage_metadata = usage
        message.response_metadata['model_provider'] = 'openai'
        return message, generation_info or None

    def _chunk_from_completion(self, completion: Any) -> AIMessageChunk:
        """Build the closing chunk of a structured-output stream."""
        generations, llm_output = self._chat_result(completion)
        message = generations[0][0]
        # Tool calls were already streamed as chunks.
        message.additional_kwargs.pop('tool_calls', None)
        chunk = AIMessageChunk(
            content='',
            additional_kwargs=message.additional_kwargs,
            usage_metadata=message.usage_metadata,
        )
        chunk.response_metadata = {**llm_output, **chunk.response_metadata}
        return chunk

    # ── Calls ────────────────────────────────────────────────────────────

    async def _agenerate(self, messages: list[BaseMessage], **kwargs: Any) -> AIMessage:
        kwargs = self._call_kwargs(kwargs)
        payload = self._get_request_payload(messages, **kwargs)
        generation_info: dict = {}
        if 'response_format' in payload:
            payload.pop('stream')
            raw = await self._client.chat.completions.with_raw_response.parse(**payload)
        elif self._use_responses_api(payload):
            schema = kwargs.get('response_format')
            if schema and responses_api.is_pydantic_class(schema):
                raw = await self._client.responses.with_raw_response.parse(**payload)
            else:
                raw = await self._client.responses.with_raw_response.create(**payload)
            if self.include_response_headers:
                generation_info = {'headers': dict(raw.headers)}
            return responses_api.response_to_message(
                raw.parse(), schema=schema, metadata=generation_info
            )
        else:
            raw = await self._client.chat.completions.with_raw_response.create(
                **payload
            )
        if self.include_response_headers:
            generation_info = {'headers': dict(raw.headers)}
        return self._create_chat_result(raw.parse(), generation_info)

    def _routes_stream_to_responses_api(self, kwargs: dict) -> bool:
        return False

    async def _astream(
        self, messages: list[BaseMessage], **kwargs: Any
    ) -> AsyncIterator[AIMessageChunk]:
        kwargs = self._call_kwargs(kwargs)
        if self._routes_stream_to_responses_api(kwargs):
            async for chunk in self._astream_responses(messages, **kwargs):
                yield chunk
            return
        stream_usage = kwargs.pop('stream_usage', None)
        kwargs['stream'] = True
        if stream_usage := self._should_stream_usage(stream_usage, **kwargs):
            kwargs['stream_options'] = {'include_usage': stream_usage}
        payload = self._get_request_payload(messages, **kwargs)
        base_generation_info: dict = {}
        if 'response_format' in payload:
            payload.pop('stream')
            context = self._client.beta.chat.completions.stream(**payload)
        elif self.include_response_headers:
            raw = await self._client.chat.completions.with_raw_response.create(
                **payload
            )
            context = raw.parse()
            base_generation_info = {'headers': dict(raw.headers)}
        else:
            context = await self._client.chat.completions.create(**payload)
        async with context as response:
            is_first_chunk = True
            async for event in with_chunk_timeout(
                response, self.stream_chunk_timeout, self.model_name
            ):
                data = event if isinstance(event, dict) else event.model_dump()
                converted = self._convert_chunk(
                    data, base_generation_info if is_first_chunk else {}
                )
                if converted is None:
                    continue
                chunk, generation_info = converted
                chunk.response_metadata = {
                    **(generation_info or {}),
                    **chunk.response_metadata,
                }
                is_first_chunk = False
                yield chunk
        if hasattr(response, 'get_final_completion') and 'response_format' in payload:
            yield self._chunk_from_completion(await response.get_final_completion())

    async def _astream_responses(
        self, messages: list[BaseMessage], **kwargs: Any
    ) -> AsyncIterator[AIMessageChunk]:
        kwargs['stream'] = True
        payload = self._get_request_payload(messages, **kwargs)
        headers: dict = {}
        if self.include_response_headers:
            raw = await self._client.with_raw_response.responses.create(**payload)
            context = raw.parse()
            headers = {'headers': dict(raw.headers)}
        else:
            context = await self._client.responses.create(**payload)
        schema = kwargs.get('response_format')
        async with context as response:
            is_first_chunk = True
            state = responses_api.StreamState()
            async for event in with_chunk_timeout(
                response, self.stream_chunk_timeout, self.model_name
            ):
                chunk = responses_api.event_to_chunk(
                    event, state, schema, headers if is_first_chunk else {}
                )
                if chunk is not None:
                    is_first_chunk = False
                    yield chunk

    # ── Tracing ──────────────────────────────────────────────────────────

    def _invocation_params(self, stop: list[str] | None = None, **kwargs: Any) -> dict:
        return {
            'model': self.model_name,
            'model_name': self.model_name,
            'stop': stop,
            **self._default_params,
            **self._bound,
            **kwargs,
        }

    def _llm_output(self, message: AIMessage) -> dict | None:
        metadata = message.response_metadata
        # Responses API replies had no llm_output.
        if 'token_usage' not in metadata:
            return None
        return {
            'model_name': metadata.get('model_name'),
            'id': metadata.get('id'),
            'token_usage': metadata.get('token_usage'),
        }

    def _generation_info(self, message: AIMessage) -> dict | None:
        return {'finish_reason': message.response_metadata.get('finish_reason')}

    def _error_type(self, error: BaseException) -> str:
        return _langchain_error_type(error)

    # ── Tools and structured output ──────────────────────────────────────

    def _bind(self, **kwargs: Any) -> '_BaseChatOpenAI':
        bound = self.model_copy()
        bound._bound = {**self._bound, **kwargs}
        return bound

    def bind_tools(
        self, tools: list, tool_choice: Any = None, **kwargs: Any
    ) -> '_BaseChatOpenAI':
        formatted = [to_openai_tool(tool) for tool in tools]
        if tool_choice:
            kwargs['tool_choice'] = tool_choice_kwarg(tool_choice, formatted)
        return self._bind(tools=formatted, **kwargs)

    def _filter_disabled_params(self, **kwargs: Any) -> dict[str, Any]:
        if not self.disabled_params:
            return kwargs
        return {
            k: v
            for k, v in kwargs.items()
            if not (
                k in self.disabled_params
                and (self.disabled_params[k] is None or v in self.disabled_params[k])
            )
        }

    def _structured_method(self) -> str:
        """How structured output is requested: json_schema or function_calling."""
        # Older models do not support structured outputs.
        if self.model_name and (
            self.model_name.startswith('gpt-3')
            or self.model_name.startswith('gpt-4-')
            or self.model_name == 'gpt-4'
        ):
            return 'function_calling'
        return 'json_schema'

    def with_structured_output(
        self, schema: type[BaseModel], include_raw: bool = False
    ) -> StructuredChatModel:
        if self._structured_method() == 'function_calling':
            tool_name = pydantic_to_function(schema)['name']
            bind_kwargs = self._filter_disabled_params(
                tool_choice=tool_name, parallel_tool_calls=False
            )
            model = self.bind_tools([schema], **bind_kwargs)

            def parser(message: AIMessage) -> Any:
                return parse_first_tool_call(message, schema)

        else:
            model = self._bind(response_format=to_response_format(schema))

            def parser(message: AIMessage) -> Any:
                return _parse_structured_output(message, schema)

        return _Structured(model, parser, include_raw)


def _messages_after_last_response(
    messages: list[BaseMessage],
) -> tuple[list[BaseMessage], str | None]:
    for i in range(len(messages) - 1, -1, -1):
        message = messages[i]
        if isinstance(message, AIMessage):
            response_id = message.response_metadata.get('id')
            if response_id and response_id.startswith('resp_'):
                return messages[i + 1 :], response_id
    return messages, None


class ChatOpenAI(_BaseChatOpenAI):
    """OpenAI chat model (also any OpenAI-compatible endpoint via ``base_url``)."""

    max_tokens: int | None = Field(default=None, alias='max_completion_tokens')

    @model_validator(mode='after')
    def _build_client(self) -> 'ChatOpenAI':
        self._check_n()
        self.openai_organization = (
            self.openai_organization
            or os.getenv('OPENAI_ORG_ID')
            or os.getenv('OPENAI_ORGANIZATION')
        )
        if self.openai_api_base is None:
            self.openai_api_base = os.getenv('OPENAI_API_BASE')
        # Usage is streamed by default only for the official endpoint.
        if (
            all(
                getattr(self, key) is None
                for key in (
                    'stream_usage',
                    'openai_proxy',
                    'client',
                    'root_client',
                    'async_client',
                    'root_async_client',
                    'http_client',
                    'http_async_client',
                )
            )
            and self.openai_api_base is None
            and 'OPENAI_BASE_URL' not in os.environ
        ):
            self.stream_usage = True
        client_params: dict = {
            'organization': self.openai_organization,
            'base_url': self.openai_api_base,
            'timeout': self.request_timeout,
            'default_headers': self.default_headers,
            'default_query': self.default_query,
        }
        if self.max_retries is not None:
            client_params['max_retries'] = self.max_retries
        if self.openai_proxy and self.http_async_client:
            raise ValueError(
                "Cannot specify 'openai_proxy' if 'http_async_client' is already "
                f'specified. Received:\nopenai_proxy={self.openai_proxy!r}\n'
                f'http_async_client={self.http_async_client!r}'
            )
        http_client = self.http_async_client
        if self.openai_proxy:
            http_client = openai.DefaultAsyncHttpxClient(proxy=self.openai_proxy)
        self._client = openai.AsyncOpenAI(
            **client_params,
            http_client=http_client,
            api_key=_secret_value(self.openai_api_key),
        )
        return self

    @property
    def _default_params(self) -> dict[str, Any]:
        params = super()._default_params
        if 'max_tokens' in params:
            params['max_completion_tokens'] = params.pop('max_tokens')
        return params

    def _routes_stream_to_responses_api(self, kwargs: dict) -> bool:
        return self._use_responses_api({**kwargs, **self.model_kwargs})

    def _get_request_payload(self, messages: list[BaseMessage], **kwargs: Any) -> dict:
        payload = super()._get_request_payload(messages, **kwargs)
        # max_tokens is deprecated in favour of max_completion_tokens.
        if 'max_tokens' in payload:
            payload['max_completion_tokens'] = payload.pop('max_tokens')
        # o-series models take the system prompt as a developer message.
        if self.model_name and re.match(r'^o\d', self.model_name):
            for message in payload.get('messages', []):
                if message['role'] == 'system':
                    message['role'] = 'developer'
        return payload


class AzureChatOpenAI(_BaseChatOpenAI):
    """Azure OpenAI chat model; the model name is the deployment name."""

    _gen_ai_provider: ClassVar[str] = 'azure.ai.openai'

    model_name: str | None = Field(default=None, alias='model')
    max_tokens: int | None = Field(default=None, alias='max_completion_tokens')
    azure_endpoint: str | None = Field(default_factory=_env('AZURE_OPENAI_ENDPOINT'))
    deployment_name: str | None = Field(default=None, alias='azure_deployment')
    openai_api_version: str | None = Field(
        default_factory=_env('OPENAI_API_VERSION'), alias='api_version'
    )
    openai_api_key: SecretStr | None = Field(
        default_factory=_secret_env('AZURE_OPENAI_API_KEY', 'OPENAI_API_KEY'),
        alias='api_key',
    )
    azure_ad_token: SecretStr | None = Field(
        default_factory=_secret_env('AZURE_OPENAI_AD_TOKEN')
    )
    azure_ad_token_provider: Callable[[], str] | None = None
    azure_ad_async_token_provider: Callable[[], Any] | None = None
    model_version: str = ''
    openai_api_type: str | None = Field(
        default_factory=_env('OPENAI_API_TYPE', default='azure')
    )
    validate_base_url: bool = True

    @model_validator(mode='after')
    def _build_client(self) -> 'AzureChatOpenAI':
        self._check_n()
        if self.disabled_params is None and self.model_name != 'gpt-4o':
            # parallel_tool_calls was only supported by gpt-4o when LangChain
            # introduced this default.
            self.disabled_params = {'parallel_tool_calls': None}
        self.openai_organization = (
            self.openai_organization
            or os.getenv('OPENAI_ORG_ID')
            or os.getenv('OPENAI_ORGANIZATION')
        )
        if all(
            getattr(self, key) is None
            for key in (
                'stream_usage',
                'openai_proxy',
                'openai_api_base',
                'client',
                'root_client',
                'async_client',
                'root_async_client',
                'http_client',
                'http_async_client',
            )
        ):
            self.stream_usage = True
        if self.openai_api_base and self.validate_base_url:
            if '/openai' not in self.openai_api_base:
                raise ValueError(
                    'As of openai>=1.0.0, Azure endpoints should be specified via '
                    'the `azure_endpoint` param not `openai_api_base` '
                    '(or alias `base_url`).'
                )
            if self.deployment_name:
                raise ValueError(
                    'As of openai>=1.0.0, if `azure_deployment` (or alias '
                    '`deployment_name`) is specified then '
                    '`base_url` (or alias `openai_api_base`) should not be. '
                    'If specifying `azure_deployment`/`deployment_name` then use '
                    '`azure_endpoint` instead of `base_url`.'
                )
        uses_ad_token = (
            self.azure_ad_token
            or self.azure_ad_token_provider
            or self.azure_ad_async_token_provider
        )
        client_params: dict = {
            'api_version': self.openai_api_version,
            'azure_endpoint': self.azure_endpoint,
            'azure_deployment': self.deployment_name,
            'api_key': None if uses_ad_token else _secret_value(self.openai_api_key),
            'azure_ad_token': _secret_value(self.azure_ad_token),
            'azure_ad_token_provider': self.azure_ad_async_token_provider
            or self.azure_ad_token_provider,
            'organization': self.openai_organization,
            'base_url': self.openai_api_base,
            'timeout': self.request_timeout,
            'default_headers': self.default_headers,
            'default_query': self.default_query,
        }
        if self.max_retries is not None:
            client_params['max_retries'] = self.max_retries
        self._client = openai.AsyncAzureOpenAI(
            **client_params, http_client=self.http_async_client
        )
        return self

    @property
    def _default_params(self) -> dict[str, Any]:
        params = super()._default_params
        if 'max_tokens' in params:
            params['max_completion_tokens'] = params.pop('max_tokens')
        return params

    def _routes_stream_to_responses_api(self, kwargs: dict) -> bool:
        return self._use_responses_api({**kwargs, **self.model_kwargs})

    def _get_request_payload(self, messages: list[BaseMessage], **kwargs: Any) -> dict:
        payload = super()._get_request_payload(messages, **kwargs)
        # The Responses API addresses the deployment through the model field.
        if (
            self._use_responses_api(payload)
            and not payload.get('model')
            and self.deployment_name
        ):
            payload['model'] = self.deployment_name
        return payload

    def _chat_result(
        self, response: Any, generation_info: dict | None = None
    ) -> tuple[list[tuple[AIMessage, dict]], dict]:
        generations, llm_output = super()._chat_result(response, generation_info)
        if not isinstance(response, dict):
            response = response.model_dump(warnings=False)
        for choice in response['choices']:
            if choice.get('finish_reason', None) == 'content_filter':
                raise ValueError(
                    'Azure has not provided the response due to a content filter '
                    'being triggered'
                )
        if 'model' in response:
            model = response['model']
            if self.model_version:
                model = f'{model}-{self.model_version}'
            llm_output['model_name'] = model
        if 'prompt_filter_results' in response:
            llm_output['prompt_filter_results'] = response['prompt_filter_results']
        for (_, info), choice in zip(generations, response['choices'], strict=False):
            info['content_filter_results'] = choice.get('content_filter_results', {})
        return generations, llm_output


def build_chat_model(model_name: str, **kwargs: Any) -> ChatOpenAI:
    return ChatOpenAI(model=model_name, **kwargs)


def build_azure_chat_model(model_name: str, **kwargs: Any) -> AzureChatOpenAI:
    return AzureChatOpenAI(model=model_name, **kwargs)


def build_azure_deployment_chat_model(
    model_name: str, **kwargs: Any
) -> AzureChatOpenAI:
    """Build the model for the documented ``azure/<deployment>`` prefix.

    Same credentials as the azure transcription models: the endpoint is
    ``api_base`` or ``base_url``.
    """
    api_base = kwargs.pop('api_base', None)
    base_url = kwargs.pop('base_url', None)
    if endpoint := api_base or base_url:
        kwargs['azure_endpoint'] = endpoint
    return AzureChatOpenAI(model=model_name, **kwargs)


# ── Embeddings ───────────────────────────────────────────────────────────────

# API limit of embedding tokens per request.
_MAX_TOKENS_PER_REQUEST = 300000


class OpenAIEmbeddings(Embeddings, BaseModel):
    """OpenAI embeddings.

    Inputs are tokenized with tiktoken and sent as token ids; texts longer than
    the model context are split, embedded in chunks and recombined as the
    normalized, token-weighted average of the chunk vectors.
    """

    model_config = ConfigDict(
        populate_by_name=True, arbitrary_types_allowed=True, protected_namespaces=()
    )

    model: str = 'text-embedding-ada-002'
    dimensions: int | None = None
    deployment: str | None = 'text-embedding-ada-002'
    openai_api_version: str | None = Field(
        default_factory=_env('OPENAI_API_VERSION'), alias='api_version'
    )
    openai_api_base: str | None = Field(
        default_factory=_env('OPENAI_API_BASE'), alias='base_url'
    )
    openai_api_type: str | None = Field(default_factory=_env('OPENAI_API_TYPE'))
    openai_proxy: str | None = Field(default_factory=_env('OPENAI_PROXY'))
    embedding_ctx_length: int = 8191
    openai_api_key: SecretStr | None = Field(
        default_factory=_secret_env('OPENAI_API_KEY'), alias='api_key'
    )
    openai_organization: str | None = Field(
        default_factory=_env('OPENAI_ORG_ID', 'OPENAI_ORGANIZATION'),
        alias='organization',
    )
    allowed_special: Any = None
    disallowed_special: Any = None
    chunk_size: int = 1000
    max_retries: int = 2
    request_timeout: float | tuple[float, float] | Any | None = Field(
        default=None, alias='timeout'
    )
    headers: Any = None
    tiktoken_enabled: bool = True
    tiktoken_model_name: str | None = None
    show_progress_bar: bool = False
    model_kwargs: dict[str, Any] = Field(default_factory=dict)
    skip_empty: bool = False
    default_headers: Mapping[str, str] | None = None
    default_query: Mapping[str, object] | None = None
    retry_min_seconds: int = 4
    retry_max_seconds: int = 20
    http_client: Any | None = None
    http_async_client: Any | None = None
    check_embedding_ctx_length: bool = True
    client: Any = None
    async_client: Any = None

    _client: Any = PrivateAttr(default=None)
    _sync_client: Any = PrivateAttr(default=None)

    @model_validator(mode='before')
    @classmethod
    def _build_extra(cls, values: Any) -> Any:
        return _collect_model_kwargs(cls, values)

    @model_validator(mode='after')
    def _build_client(self) -> 'OpenAIEmbeddings':
        if self.openai_api_type in ('azure', 'azure_ad', 'azuread'):
            raise ValueError(
                'If you are using Azure, please use the `AzureOpenAIEmbeddings` class.'
            )
        if self.openai_proxy and (self.http_client or self.http_async_client):
            raise ValueError(
                "Cannot specify 'openai_proxy' if one of "
                "'http_client'/'http_async_client' is already specified."
            )
        http_client = self.http_async_client
        if self.openai_proxy:
            http_client = openai.DefaultAsyncHttpxClient(proxy=self.openai_proxy)
        self._client = openai.AsyncOpenAI(
            **self._client_params(),
            http_client=http_client,
            api_key=_secret_value(self.openai_api_key),
        ).embeddings
        return self

    def _client_params(self) -> dict[str, Any]:
        return {
            'organization': self.openai_organization,
            'base_url': self.openai_api_base,
            'timeout': self.request_timeout,
            'max_retries': self.max_retries,
            'default_headers': self.default_headers,
            'default_query': self.default_query,
        }

    def _sync_embeddings(self) -> Any:
        if self._sync_client is None:
            self._sync_client = openai.OpenAI(
                **self._client_params(),
                http_client=self.http_client,
                api_key=_secret_value(self.openai_api_key),
            ).embeddings
        return self._sync_client

    @property
    def _invocation_params(self) -> dict[str, Any]:
        params: dict = {'model': self.model, **self.model_kwargs}
        if self.dimensions is not None:
            params['dimensions'] = self.dimensions
        return params

    def _tokenize(self, texts: list[str]) -> tuple[list[list[int]], list[int]]:
        """Token chunks of at most ``embedding_ctx_length`` and their text index."""
        if not self.tiktoken_enabled:
            raise ValueError(
                'Could not import transformers python package. '
                'This is needed for OpenAIEmbeddings to work without '
                '`tiktoken`. Please install it with `pip install transformers`. '
            )
        model_name = self.tiktoken_model_name or self.model
        try:
            encoding = tiktoken.encoding_for_model(model_name)
        except KeyError:
            encoding = tiktoken.get_encoding('cl100k_base')
        encoder_kwargs = {
            k: v
            for k, v in {
                'allowed_special': self.allowed_special,
                'disallowed_special': self.disallowed_special,
            }.items()
            if v is not None
        }
        tokens: list[list[int]] = []
        indices: list[int] = []
        for i, text in enumerate(texts):
            if self.model.endswith('001'):
                # Newlines degrade the first-generation models.
                text = text.replace('\n', ' ')
            if encoder_kwargs:
                token = encoding.encode(text, **encoder_kwargs)
            else:
                token = encoding.encode_ordinary(text)
            for j in range(0, len(token), self.embedding_ctx_length):
                tokens.append(token[j : j + self.embedding_ctx_length])
                indices.append(i)
        return tokens, indices

    def _batches(self, tokens: list[list[int]]) -> list[list[list[int]]]:
        """Group chunks into requests of ``chunk_size`` within the token limit."""
        batches = []
        i = 0
        while i < len(tokens):
            batch_token_count = 0
            batch_end = i
            for j in range(i, min(i + self.chunk_size, len(tokens))):
                if batch_token_count + len(tokens[j]) > _MAX_TOKENS_PER_REQUEST:
                    if batch_end == i:
                        # A single chunk over the limit is sent anyway.
                        batch_end = j + 1
                    break
                batch_token_count += len(tokens[j])
                batch_end = j + 1
            batches.append(tokens[i:batch_end])
            i = batch_end
        return batches

    def _combine(
        self,
        num_texts: int,
        tokens: list[list[int]],
        vectors: list[list[float]],
        indices: list[int],
    ) -> list[list[float] | None]:
        results: list[list[list[float]]] = [[] for _ in range(num_texts)]
        weights: list[list[int]] = [[] for _ in range(num_texts)]
        for i in range(len(indices)):
            if self.skip_empty and len(vectors[i]) == 1:
                continue
            results[indices[i]].append(vectors[i])
            weights[indices[i]].append(len(tokens[i]))
        embeddings: list[list[float] | None] = []
        for i in range(num_texts):
            chunks = results[i]
            if len(chunks) == 0:
                # Filled with the embedding of an empty string by the caller.
                embeddings.append(None)
            elif len(chunks) == 1:
                embeddings.append(chunks[0])
            else:
                total_weight = sum(weights[i])
                average = [
                    sum(v * w for v, w in zip(values, weights[i], strict=False))
                    / total_weight
                    for values in zip(*chunks, strict=False)
                ]
                magnitude = sum(v**2 for v in average) ** 0.5
                embeddings.append([v / magnitude for v in average])
        return embeddings

    @staticmethod
    def _vectors(response: Any) -> list[list[float]]:
        if not isinstance(response, dict):
            response = response.model_dump()
        return [r['embedding'] for r in response['data']]

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        params = self._invocation_params
        if not self.check_embedding_ctx_length:
            embeddings: list[list[float]] = []
            for i in range(0, len(texts), self.chunk_size):
                response = await self._client.create(
                    input=texts[i : i + self.chunk_size], **params
                )
                embeddings.extend(self._vectors(response))
            return embeddings

        tokens, indices = await _run_in_executor(self._tokenize, texts)
        vectors: list[list[float]] = []
        for batch in self._batches(tokens):
            vectors.extend(
                self._vectors(await self._client.create(input=batch, **params))
            )
        combined = self._combine(len(texts), tokens, vectors, indices)
        empty: list[float] | None = None
        result = []
        for embedding in combined:
            if embedding is None:
                if empty is None:
                    response = await self._client.create(input='', **params)
                    empty = self._vectors(response)[0]
                embedding = empty
            result.append(embedding)
        return result

    async def aembed_query(self, text: str) -> list[float]:
        return (await self.aembed_documents([text]))[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        client = self._sync_embeddings()
        params = self._invocation_params
        if not self.check_embedding_ctx_length:
            embeddings: list[list[float]] = []
            for i in range(0, len(texts), self.chunk_size):
                response = client.create(input=texts[i : i + self.chunk_size], **params)
                embeddings.extend(self._vectors(response))
            return embeddings

        tokens, indices = self._tokenize(texts)
        vectors: list[list[float]] = []
        for batch in self._batches(tokens):
            vectors.extend(self._vectors(client.create(input=batch, **params)))
        combined = self._combine(len(texts), tokens, vectors, indices)
        empty: list[float] | None = None
        result = []
        for embedding in combined:
            if embedding is None:
                if empty is None:
                    empty = self._vectors(client.create(input='', **params))[0]
                embedding = empty
            result.append(embedding)
        return result

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


class AzureOpenAIEmbeddings(OpenAIEmbeddings):
    """Azure OpenAI embeddings; the model name is the deployment name."""

    azure_endpoint: str | None = Field(default_factory=_env('AZURE_OPENAI_ENDPOINT'))
    deployment: str | None = Field(default=None, alias='azure_deployment')
    openai_api_key: SecretStr | None = Field(
        default_factory=_secret_env('AZURE_OPENAI_API_KEY', 'OPENAI_API_KEY'),
        alias='api_key',
    )
    openai_api_version: str | None = Field(
        default_factory=_env('OPENAI_API_VERSION', default='2023-05-15'),
        alias='api_version',
    )
    azure_ad_token: SecretStr | None = Field(
        default_factory=_secret_env('AZURE_OPENAI_AD_TOKEN')
    )
    azure_ad_token_provider: Callable[[], str] | None = None
    azure_ad_async_token_provider: Callable[[], Any] | None = None
    openai_api_type: str | None = Field(
        default_factory=_env('OPENAI_API_TYPE', default='azure')
    )
    validate_base_url: bool = True
    chunk_size: int = 2048

    @model_validator(mode='after')
    def _build_client(self) -> 'AzureOpenAIEmbeddings':
        if self.openai_api_base and self.validate_base_url:
            if not self.azure_endpoint and '/openai' not in self.openai_api_base:
                raise ValueError(
                    'As of openai>=1.0.0, Azure endpoints should be specified via '
                    'the `azure_endpoint` param not `openai_api_base` '
                    '(or alias `base_url`). '
                )
            if self.deployment:
                raise ValueError(
                    'As of openai>=1.0.0, if `deployment` (or alias '
                    '`azure_deployment`) is specified then '
                    '`openai_api_base` (or alias `base_url`) should not be. '
                    'Instead use `deployment` (or alias `azure_deployment`) '
                    'and `azure_endpoint`.'
                )
        self._client = openai.AsyncAzureOpenAI(
            **self._client_params(), http_client=self.http_async_client
        ).embeddings
        return self

    def _client_params(self) -> dict[str, Any]:
        uses_ad_token = (
            self.azure_ad_token
            or self.azure_ad_token_provider
            or self.azure_ad_async_token_provider
        )
        return {
            'api_version': self.openai_api_version,
            'azure_endpoint': self.azure_endpoint,
            'azure_deployment': self.deployment,
            'api_key': None if uses_ad_token else _secret_value(self.openai_api_key),
            'azure_ad_token': _secret_value(self.azure_ad_token),
            'azure_ad_token_provider': self.azure_ad_async_token_provider
            or self.azure_ad_token_provider,
            'organization': self.openai_organization,
            'base_url': self.openai_api_base,
            'timeout': self.request_timeout,
            'max_retries': self.max_retries,
            'default_headers': self.default_headers,
            'default_query': self.default_query,
        }

    def _sync_embeddings(self) -> Any:
        if self._sync_client is None:
            params = self._client_params()
            params['azure_ad_token_provider'] = self.azure_ad_token_provider
            self._sync_client = openai.AzureOpenAI(
                **params, http_client=self.http_client
            ).embeddings
        return self._sync_client


def build_embeddings(model_name: str, **kwargs: Any) -> OpenAIEmbeddings:
    return OpenAIEmbeddings(model=model_name, **kwargs)


def build_azure_embeddings(model_name: str, **kwargs: Any) -> AzureOpenAIEmbeddings:
    return AzureOpenAIEmbeddings(model=model_name, **kwargs)
