"""Google Gemini chat and embedding models on the ``google-genai`` SDK.

Requests are built from the SDK's own types, so the wire payload is what the
SDK serializes: messages become ``contents`` (the leading system message the
``system_instruction``), OpenAI-format tools become ``function_declarations``
and the generation settings a ``GenerateContentConfig``.
"""

import base64
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from contextlib import contextmanager
from copy import deepcopy
import io
import json
import logging
import mimetypes
import os
import re
import string
from typing import Any
from urllib.parse import urlparse
import uuid
import warnings
import wave

import filetype
from google.genai import errors, types
from google.genai.client import Client
import httpx
from pydantic import BaseModel

from radicalbit_ai_gateway.llm.chat_model import ChatModel, StructuredChatModel
from radicalbit_ai_gateway.llm.embeddings import Embeddings
from radicalbit_ai_gateway.llm.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    FunctionMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    UsageMetadata,
    parse_partial_json,
    tool_call,
    tool_call_chunk,
)
from radicalbit_ai_gateway.utils.app_config import get_app_config

app_config = get_app_config()

logger = logging.getLogger(app_config.log_config.logger_name)

_DEFAULT_TEMPERATURE = 0.7
_DEFAULT_MAX_RETRIES = 6
_NATIVE_PROVIDERS = frozenset({'google_genai', 'google_vertexai'})
# Placeholder accepted by Gemini 3+ in place of a missing thought signature.
_SKIP_THOUGHT_SIGNATURE = 'skip_thought_signature_validator'
_FUNCTION_CALL_SIGNATURES_KEY = '__gemini_function_call_thought_signatures__'
# These models ignore custom sampling parameters and reject model prefills.
_FIXED_SAMPLING_MODELS = frozenset({'gemini-3.5-flash-lite', 'gemini-3.6-flash'})
_SAMPLING_PARAMETERS = ('temperature', 'top_k', 'top_p')
# Gateway request params that are not generation settings.
_STREAM_KWARGS = ('stream', 'stream_options')
_SPECIAL_TOOL_KEYS = (
    'google_search_retrieval',
    'google_search',
    'google_maps',
    'code_execution',
    'url_context',
    'computer_use',
)
_DATA_BLOCK_TYPES = ('image', 'video', 'audio', 'text-plain', 'file')
_PROVIDER_RESOLVED_HOSTS = (
    'youtube.com',
    'youtu.be',
    'generativelanguage.googleapis.com',
)
_MAX_TOKENS_PER_BATCH = 20000
_DEFAULT_BATCH_SIZE = 100


class GoogleGenerativeAIError(Exception):
    """A Gemini request failed."""


class ChatGoogleGenerativeAIError(GoogleGenerativeAIError):
    """A Gemini chat request was rejected by the API."""


class OutputParserError(ValueError):
    """A structured reply could not be parsed into its schema."""


def _api_key(params: dict[str, Any]) -> str | None:
    if 'api_key' in params or 'google_api_key' in params:
        return params.get('api_key', params.get('google_api_key'))
    return os.getenv('GOOGLE_API_KEY') or os.getenv('GEMINI_API_KEY')


def _base_url(value: Any) -> str | None:
    if not isinstance(value, dict):
        return value
    keys = list(value)
    if keys == ['api_endpoint']:
        return value['api_endpoint']
    if 'api_endpoint' in keys:
        msg = (
            'When providing base_url as a dict, it can only contain the '
            'api_endpoint key. Extra keys found: '
            f'{[k for k in keys if k != "api_endpoint"]}'
        )
    elif keys:
        msg = 'When providing base_url as a dict, it must only contain the api_endpoint key.'
    else:
        msg = 'base_url must be a string or a dict containing the api_endpoint key.'
    raise ValueError(msg)


def _build_client(
    params: dict[str, Any], http_async_client: httpx.AsyncClient | None
) -> Client:
    api_key = _api_key(params)
    if not api_key:
        msg = (
            'API key required for Gemini Developer API. Provide api_key '
            'parameter or set GOOGLE_API_KEY/GEMINI_API_KEY environment '
            'variable.'
        )
        raise ValueError(msg)
    client_args = params.get('client_args')
    http_options = types.HttpOptions(
        base_url=_base_url(params.get('base_url', params.get('client_options'))),
        api_version=params.get('api_version'),
        headers=params.get('additional_headers'),
        client_args=client_args,
        async_client_args=client_args,
        # Custom client_args (e.g. a proxy) need the SDK's own client.
        httpx_async_client=None if client_args else http_async_client,
    )
    return Client(api_key=api_key, http_options=http_options)


def _param(params: dict[str, Any], name: str, alias: str | None = None, default=None):
    if name in params:
        return params[name]
    if alias is not None and alias in params:
        return params[alias]
    return default


def _is_gemini_3_or_later(model: str | None) -> bool:
    return bool(model) and 'gemini-3' in model.lower().replace('models/', '')


def _is_gemini_25(model: str | None) -> bool:
    return bool(model) and 'gemini-2.5' in model.lower().replace('models/', '')


def _uses_fixed_sampling(model: str) -> bool:
    if not model:
        return False
    normalized = re.sub(r'-\d{3}$', '', model.lower().rsplit('/', 1)[-1])
    return normalized in _FIXED_SAMPLING_MODELS


def build_chat_model(model_name: str, **kwargs: Any) -> 'ChatGoogleGenerativeAI':
    """Build a Gemini chat model from the configured params and credentials."""
    return ChatGoogleGenerativeAI(model_name, **kwargs)


def build_embeddings(model_name: str, **kwargs: Any) -> 'GoogleGenerativeAIEmbeddings':
    """Build a Gemini embedding model from the configured params and credentials."""
    return GoogleGenerativeAIEmbeddings(model_name, **kwargs)


# ── Chat model ────────────────────────────────────────────────────────────────


class ChatGoogleGenerativeAI(ChatModel):
    """A Gemini chat model.

    ``params`` are the model settings and credentials from the gateway config;
    unknown ones are ignored. Call-time kwargs override the generation settings
    and any other kwarg is passed on to ``GenerateContentConfig``.
    """

    def __init__(
        self,
        model: str,
        *,
        http_async_client: httpx.AsyncClient | None = None,
        **params: Any,
    ):
        self.model = model
        self.temperature = _param(params, 'temperature', default=_DEFAULT_TEMPERATURE)
        if 'temperature' not in params and _is_gemini_3_or_later(model):
            self.temperature = None
        self.top_p = params.get('top_p')
        self.top_k = params.get('top_k')
        self.max_output_tokens = _param(params, 'max_output_tokens', 'max_tokens')
        self.n = _param(params, 'n', 'candidate_count', 1)
        self.max_retries = _param(
            params, 'max_retries', 'retries', _DEFAULT_MAX_RETRIES
        )
        self.timeout = _param(params, 'timeout', 'request_timeout')
        self.frequency_penalty = params.get('frequency_penalty')
        self.presence_penalty = params.get('presence_penalty')
        self.seed = params.get('seed')
        self.stop = _param(params, 'stop', 'stop_sequences')
        self.safety_settings = params.get('safety_settings')
        self.response_mime_type = params.get('response_mime_type')
        self.response_schema = params.get('response_schema')
        self.thinking_budget = params.get('thinking_budget')
        self.include_thoughts = params.get('include_thoughts')
        self.reasoning_effort = _param(params, 'reasoning_effort', 'thinking_level')
        thinking_config = params.get('thinking_config')
        if isinstance(thinking_config, types.ThinkingConfig):
            thinking_config = thinking_config.model_dump(exclude_none=True)
        self.thinking_config = thinking_config
        self.cached_content = params.get('cached_content')
        self.labels = params.get('labels')
        self.convert_system_message_to_human = params.get(
            'convert_system_message_to_human', False
        )
        self._validate()
        self._http_async_client = http_async_client
        self._client = _build_client(params, http_async_client)
        self._bound: dict[str, Any] = {}

    _gen_ai_provider = 'gcp.gen_ai'

    def _server_url(self) -> str | None:
        # The SDK resolves it (Gemini API or Vertex AI) but does not expose it.
        return self._client._api_client._http_options.base_url

    def _invocation_params(self, stop: list[str] | None = None, **kwargs: Any) -> dict:
        return {
            'model': self.model,
            'temperature': self.temperature,
            'top_p': self.top_p,
            'max_output_tokens': self.max_output_tokens,
            'stop': stop,
            **self._bound,
            **kwargs,
        }

    def _generation_info(self, message: AIMessage) -> dict | None:
        return {'finish_reason': message.response_metadata.get('finish_reason')}

    def _validate(self) -> None:
        if self.temperature is not None and not 0 <= self.temperature <= 2.0:
            raise ValueError('temperature must be in the range [0.0, 2.0]')
        if self.top_p is not None and not 0 <= self.top_p <= 1:
            raise ValueError('top_p must be in the range [0.0, 1.0]')
        if self.top_k is not None and self.top_k <= 0:
            raise ValueError('top_k must be positive')
        for name in ('frequency_penalty', 'presence_penalty'):
            value = getattr(self, name)
            if value is not None and not -2.0 <= value <= 2.0:
                raise ValueError(f'{name} must be in the range [-2.0, 2.0]')

    def _with(self, **bound: Any) -> 'ChatGoogleGenerativeAI':
        clone = object.__new__(type(self))
        clone.__dict__.update(self.__dict__)
        clone._bound = {**self._bound, **bound}
        return clone

    def bind_tools(
        self, tools: list[dict], tool_choice: Any = None
    ) -> 'ChatGoogleGenerativeAI':
        # Tools are converted per call, so a bad tool fails the call (where
        # fallbacks apply) rather than the bind.
        bound: dict[str, Any] = {'tools': list(tools)}
        if tool_choice:
            bound['tool_choice'] = tool_choice
        return self._with(**bound)

    def with_structured_output(
        self, schema: type[BaseModel], include_raw: bool = False
    ) -> StructuredChatModel:
        return _JsonSchemaStructuredModel(self, schema, include_raw)

    # ── Request ──

    async def _prepare_request(
        self,
        messages: list[BaseMessage],
        *,
        stop: list[str] | None = None,
        tools: Sequence[Any] | None = None,
        functions: Sequence[Any] | None = None,
        safety_settings: dict | None = None,
        tool_config: dict | types.ToolConfig | None = None,
        tool_choice: Any = None,
        generation_config: dict[str, Any] | None = None,
        cached_content: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        for key in _STREAM_KWARGS:
            kwargs.pop(key, None)
        formatted_tools = _format_tools(tools or functions)
        filtered = [
            m for m in messages if not (isinstance(m, HumanMessage) and not m.content)
        ]
        system_instruction, contents = await _convert_messages(
            filtered,
            model=self.model,
            convert_system_message_to_human=self.convert_system_message_to_human,
            http_client=self._http_async_client,
        )
        if (
            _uses_fixed_sampling(self.model)
            and contents
            and contents[-1].role == 'model'
        ):
            msg = (
                f"Model '{self.model}' does not support model prefilling. The final "
                'request turn must be a user message or a function response.'
            )
            raise ValueError(msg)
        formatted_tool_config = _process_tool_config(
            tool_choice, tool_config, formatted_tools
        )
        formatted_safety_settings = _format_safety_settings(
            safety_settings if safety_settings is not None else self.safety_settings
        )

        timeout = kwargs.pop('timeout', None)
        if timeout is not None:
            timeout = int(timeout * 1000)
        elif self.timeout is not None:
            timeout = int(self.timeout * 1000)
        max_retries = kwargs.pop('max_retries', None)
        if max_retries is None:
            max_retries = self.max_retries
        kwargs.pop('strict', None)

        # OpenAI-style response_format maps onto Gemini's JSON schema output.
        response_format = kwargs.pop('response_format', None)
        if isinstance(response_format, dict) and response_format.get('type') in (
            'json_object',
            'json_schema',
        ):
            kwargs.setdefault('response_mime_type', 'application/json')
            schema = response_format.get('json_schema', {}).get('schema')
            if schema and 'response_json_schema' not in kwargs:
                kwargs['response_json_schema'] = schema

        params = self._generation_config(stop, generation_config, **kwargs)
        kwargs.pop('image_config', None)
        labels = kwargs.pop('labels', None)
        if labels is None:
            labels = self.labels
        consumed = {
            'thinking_budget',
            'thinking_level',
            'include_thoughts',
            'reasoning_effort',
            'response_schema',
            'response_json_schema',
            'response_mime_type',
            *params.model_fields_set,
        }
        remaining = {k: v for k, v in kwargs.items() if k not in consumed}

        per_request_http_options = remaining.pop('http_options', None)
        if isinstance(per_request_http_options, dict):
            per_request_http_options = types.HttpOptions(**per_request_http_options)
        retry_options = (
            types.HttpRetryOptions(attempts=max_retries)
            if max_retries is not None
            else None
        )
        http_options = None
        if timeout is not None or retry_options is not None:
            http_options = types.HttpOptions(
                timeout=timeout, retry_options=retry_options
            )
        if per_request_http_options is not None:
            http_options = _merge_http_options(http_options, per_request_http_options)

        request_params = params.model_dump(exclude_unset=True)
        if _uses_fixed_sampling(self.model):
            ignored = [p for p in _SAMPLING_PARAMETERS if p in request_params]
            if ignored:
                warnings.warn(
                    f"Model '{self.model}' uses fixed sampling defaults; the "
                    f'sampling parameter(s) {", ".join(ignored)} will be ignored.',
                    UserWarning,
                    stacklevel=2,
                )
                for p in ignored:
                    request_params.pop(p, None)

        config = types.GenerateContentConfig(
            tools=list(formatted_tools) if formatted_tools else None,
            tool_config=formatted_tool_config,
            safety_settings=formatted_safety_settings,
            cached_content=cached_content or self.cached_content,
            system_instruction=system_instruction,
            http_options=http_options,
            labels=labels,
            **request_params,
            **remaining,
        )
        return {'model': self.model, 'contents': contents, 'config': config}

    def _generation_config(
        self,
        stop: list[str] | None,
        generation_config: dict[str, Any] | None,
        **kwargs: Any,
    ) -> types.GenerationConfig:
        config: dict[str, Any] = {
            'candidate_count': kwargs.get('candidate_count', self.n),
            'temperature': kwargs.get('temperature', self.temperature),
            'stop_sequences': (
                stop if stop is not None else kwargs.get('stop_sequences', self.stop)
            ),
            'max_output_tokens': kwargs.get(
                'max_output_tokens', self.max_output_tokens
            ),
            'top_k': kwargs.get('top_k', self.top_k),
            'top_p': kwargs.get('top_p', self.top_p),
            'frequency_penalty': kwargs.get(
                'frequency_penalty', self.frequency_penalty
            ),
            'presence_penalty': kwargs.get('presence_penalty', self.presence_penalty),
            'seed': kwargs.get('seed', self.seed),
        }
        thinking_config = self._thinking_config(**kwargs)
        if thinking_config is not None:
            config['thinking_config'] = thinking_config
        config = {k: v for k, v in config.items() if v is not None}
        if generation_config:
            config = {**config, **generation_config}

        response_mime_type = kwargs.get('response_mime_type', self.response_mime_type)
        if response_mime_type is not None:
            config['response_mime_type'] = response_mime_type
        response_json_schema = kwargs.get('response_json_schema')
        schema = (
            response_json_schema
            if response_json_schema is not None
            else kwargs.get('response_schema', self.response_schema)
        )
        if schema:
            if response_mime_type != 'application/json':
                msg = (
                    'JSON schema structured output is only supported when '
                    "response_mime_type is set to 'application/json'"
                )
                if response_mime_type == 'text/x.enum':
                    msg += (
                        ". Instead of 'text/x.enum', define enums using your JSON "
                        'schema.'
                    )
                raise ValueError(msg)
            config['response_json_schema'] = schema
        return types.GenerationConfig.model_validate(config)

    def _thinking_config(self, **kwargs: Any) -> types.ThinkingConfig | None:
        raw = kwargs.get('thinking_config', self.thinking_config)
        level = kwargs.get(
            'thinking_level', kwargs.get('reasoning_effort', self.reasoning_effort)
        )
        budget = kwargs.get('thinking_budget', self.thinking_budget)
        include_thoughts = kwargs.get('include_thoughts', self.include_thoughts)
        if (
            raw is None
            and level is None
            and budget is None
            and include_thoughts is None
        ):
            return None
        config: dict[str, Any] = {}
        if raw is not None:
            config.update(
                types.ThinkingConfig.model_validate(raw).model_dump(exclude_none=True)
            )
        if level is not None:
            config['thinking_level'] = level
        if budget is not None:
            config['thinking_budget'] = budget
        if include_thoughts is not None:
            config['include_thoughts'] = include_thoughts
        if 'thinking_level' in config and 'thinking_budget' in config:
            warnings.warn(
                "Both 'thinking_level' and 'thinking_budget' were set after merging "
                "thinking configuration values. 'thinking_level' takes precedence "
                "for Gemini 3+ models; 'thinking_budget' will be ignored.",
                UserWarning,
                stacklevel=2,
            )
            config.pop('thinking_budget')
        return types.ThinkingConfig(**config)

    # ── Calls ──

    async def _agenerate(self, messages: list[BaseMessage], **kwargs: Any) -> AIMessage:
        request = await self._prepare_request(messages, **{**self._bound, **kwargs})
        try:
            response = await self._client.aio.models.generate_content(**request)
        except errors.ClientError as e:
            _raise_client_error(e, request['model'])
        results = _response_to_result(response)
        message, generation_info = results[0]
        message.response_metadata = {**generation_info, **message.response_metadata}
        if len(results) == 1 and response.prompt_feedback:
            message.response_metadata = {
                'prompt_feedback': response.prompt_feedback.model_dump(),
                **message.response_metadata,
            }
        return message

    async def _astream(
        self, messages: list[BaseMessage], **kwargs: Any
    ) -> AsyncIterator[AIMessageChunk]:
        request = await self._prepare_request(messages, **{**self._bound, **kwargs})
        prev_usage: UsageMetadata | None = None
        indexer = _StreamBlockIndexer()
        stream = await self._client.aio.models.generate_content_stream(**request)
        try:
            async for response in stream:
                message, generation_info = _response_to_result(
                    response, stream=True, prev_usage=prev_usage
                )[0]
                message.response_metadata = {
                    **generation_info,
                    **message.response_metadata,
                }
                indexer.assign(message)
                prev_usage = (
                    message.usage_metadata
                    if prev_usage is None
                    else _add_usage(prev_usage, message.usage_metadata)
                )
                yield message
        except errors.ClientError as e:
            _raise_client_error(e, request['model'])


def _raise_client_error(e: errors.ClientError, model: str) -> None:
    text = str(e)
    if (
        'exceeds the maximum number of tokens allowed' in text
        or 'token limit' in text.lower()
    ):
        raise e
    raise ChatGoogleGenerativeAIError(
        f"Error calling model '{model}' ({e.status}): {e}"
    ) from e


def _merge_http_options(
    base: types.HttpOptions | None, override: types.HttpOptions
) -> types.HttpOptions:
    if base is None:
        return override
    merged = base.model_copy(deep=True)
    for field in override.model_fields_set:
        value = getattr(override, field)
        if field == 'headers':
            merged.headers = {**(merged.headers or {}), **(value or {})}
        else:
            setattr(merged, field, value)
    return merged


def _format_safety_settings(safety_settings: Any) -> list[types.SafetySetting]:
    if not safety_settings:
        return []
    if isinstance(safety_settings, dict):
        return [
            types.SafetySetting(category=category, threshold=threshold)
            for category, threshold in safety_settings.items()
        ]
    raise TypeError('safety_settings must be: dict[HarmCategory, HarmBlockThreshold]')


# ── Structured output ─────────────────────────────────────────────────────────


class _JsonSchemaStructuredModel(StructuredChatModel):
    """Structured output through Gemini's native JSON schema mode."""

    def __init__(
        self, model: ChatGoogleGenerativeAI, schema: type[BaseModel], include_raw: bool
    ):
        self.model = model
        self.schema = schema
        self.include_raw = include_raw
        self._json_schema = schema.model_json_schema()

    async def ainvoke(self, input: Sequence[BaseMessage], **kwargs: Any) -> Any:  # noqa: A002
        raw = await self.model.ainvoke(
            input,
            **{
                'response_mime_type': 'application/json',
                'response_json_schema': self._json_schema,
                **kwargs,
            },
        )
        if not self.include_raw:
            return _parse_structured(raw, self.schema)
        try:
            parsed = _parse_structured(raw, self.schema)
        except Exception as e:
            return {'raw': raw, 'parsed': None, 'parsing_error': e}
        return {'raw': raw, 'parsed': parsed, 'parsing_error': None}


_JSON_MARKDOWN = re.compile(r'```(json)?(.*)', re.DOTALL)


def _parse_json_markdown(text: str) -> Any:
    def parse(s: str) -> Any:
        return parse_partial_json(s.strip(' \n\r\t`'))

    try:
        return parse(text)
    except json.JSONDecodeError:
        match = _JSON_MARKDOWN.search(text)
        return parse(text if match is None else match.group(2))


def _parse_structured(message: AIMessage, schema: type[BaseModel]) -> BaseModel:
    text = message.text.strip()
    try:
        obj = _parse_json_markdown(text)
    except json.JSONDecodeError as e:
        raise OutputParserError(f'Invalid json output: {text}') from e
    try:
        return schema.model_validate(obj)
    except ValueError as e:
        dumped = json.dumps(obj, ensure_ascii=False)
        raise OutputParserError(
            f'Failed to parse {schema.__name__} from completion {dumped}. Got: {e}'
        ) from e


# ── Tools ─────────────────────────────────────────────────────────────────────


def _format_tools(tools: Sequence[Any] | None) -> list[types.Tool] | None:
    if not tools:
        return None
    result: list[types.Tool] = []
    declarations: list[types.FunctionDeclaration] = []
    for tool in tools:
        if isinstance(tool, types.Tool):
            result.append(tool)
            continue
        if not isinstance(tool, dict):
            raise ValueError(f'Unsupported tool type {tool}')  # noqa: TRY004
        special = [k for k in _SPECIAL_TOOL_KEYS if tool.get(k) is not None]
        if len(special) > 1:
            msg = (
                'A single tool dict cannot have multiple special tool types. '
                f'Found: {special}. Each special tool type must be in a '
                'separate dict or Tool object.'
            )
            raise ValueError(msg)
        if special:
            result.append(types.Tool.model_validate({special[0]: tool[special[0]]}))
        elif tool.get('function_declarations') is not None:
            declarations.extend(
                _function_declaration(fd) for fd in tool['function_declarations']
            )
        else:
            declarations.append(_function_declaration(tool))
    if declarations:
        result.append(types.Tool(function_declarations=declarations))
    if sum(1 for t in result if t.google_search_retrieval) > 1:
        msg = (
            'Providing multiple google_search_retrieval tools is not supported. '
            'Only one google_search_retrieval tool can be used at a time.'
        )
        raise ValueError(msg)
    return result


def _function_declaration(tool: dict[str, Any]) -> types.FunctionDeclaration:
    if tool.get('type') == 'function' and 'function' in tool:
        function = dict(tool['function'])
    else:
        function = dict(tool)
    parameters = function.get('parameters') or {}
    # Gemini rejects an empty 'properties' field.
    if not parameters.get('properties'):
        parameters = {}
    name = function.get('name') or function.get('title') or 'MISSING_NAME'
    return types.FunctionDeclaration(
        name=str(name),
        description=function.get('description') or None,
        parameters=_dict_to_genai_schema(parameters),
    )


def _tool_names(tools: list[types.Tool]) -> list[str]:
    names: list[str] = []
    for t in tools:
        if t.function_declarations:
            names.extend(f.name for f in t.function_declarations)
    return names


def _process_tool_config(
    tool_choice: Any,
    tool_config: dict | types.ToolConfig | None,
    formatted_tools: list[types.Tool] | None,
) -> types.ToolConfig | None:
    normalized = None
    if tool_config:
        normalized = (
            types.ToolConfig.model_validate(tool_config)
            if isinstance(tool_config, dict)
            else tool_config
        )
    if tool_choice and normalized and normalized.function_calling_config:
        msg = (
            'Cannot specify both tool_choice and tool_config.function_calling_config. '
            f'Received {tool_choice=} and tool_config.function_calling_config='
            f'{normalized.function_calling_config}'
        )
        raise ValueError(msg)
    if not tool_choice:
        return normalized
    if not formatted_tools:
        msg = (
            f'Received {tool_choice=} but no {formatted_tools=}. '
            "'tool_choice' can only be specified if 'tools' is specified."
        )
        raise ValueError(msg)
    names = _tool_names(formatted_tools)
    if not names:
        # Only built-in tools (search, maps, ...): nothing to choose from.
        return normalized
    choice = _tool_choice_to_tool_config(tool_choice, names)
    if normalized:
        return types.ToolConfig(
            function_calling_config=choice.function_calling_config,
            retrieval_config=normalized.retrieval_config,
        )
    return choice


def _tool_choice_to_tool_config(tool_choice: Any, names: list[str]) -> types.ToolConfig:
    allowed: list[str] | None = None
    if tool_choice is True or tool_choice in ('any', 'required'):
        mode = 'ANY'
        allowed = names
    elif tool_choice == 'auto':
        mode = 'AUTO'
    elif tool_choice == 'none':
        mode = 'NONE'
    elif isinstance(tool_choice, str):
        mode = 'ANY'
        allowed = [tool_choice]
    elif isinstance(tool_choice, list):
        mode = 'ANY'
        allowed = tool_choice
    elif isinstance(tool_choice, dict):
        function = tool_choice.get('function')
        if 'mode' in tool_choice:
            mode = tool_choice['mode']
            allowed = tool_choice.get('allowed_function_names')
        elif 'function_calling_config' in tool_choice:
            mode = tool_choice['function_calling_config']['mode']
            allowed = tool_choice['function_calling_config'].get(
                'allowed_function_names'
            )
        elif (
            tool_choice.get('type') == 'function'
            and isinstance(function, dict)
            and function.get('name')
        ):
            # OpenAI-shaped named choice: force that function.
            mode = 'ANY'
            allowed = [function['name']]
        else:
            msg = (
                f'Unrecognized tool choice format:\n\n{tool_choice=}\n\nShould match '
                'Google GenerativeAI ToolConfig or FunctionCallingConfig format.'
            )
            raise ValueError(msg)
    else:
        raise ValueError(f'Unrecognized tool choice format:\n\n{tool_choice=}')
    return types.ToolConfig(
        function_calling_config=types.FunctionCallingConfig(
            mode=types.FunctionCallingConfigMode(mode),
            allowed_function_names=allowed,
        )
    )


# JSON schema -> Gemini schema. Gemini accepts a subset of JSON schema; the
# conversion inlines $refs, keeps the supported keys and maps types to enums.

_ALLOWED_SCHEMA_FIELDS = frozenset(
    {
        'type',
        'type_',
        'description',
        'enum',
        'format',
        'items',
        'properties',
        'required',
        'nullable',
        'anyOf',
        'default',
        'minimum',
        'maximum',
        'minLength',
        'maxLength',
        'pattern',
        'minItems',
        'maxItems',
        'title',
    }
)


def _retrieve_ref(path: str, schema: dict[str, Any]) -> Any:
    components = path.split('/')
    if components[0] != '#':
        msg = (
            'ref paths are expected to be URI fragments, meaning they should start '
            'with #.'
        )
        raise ValueError(msg)
    out: Any = schema
    for component in components[1:]:
        if component in out:
            if isinstance(out, list):
                raise KeyError(f"Reference '{path}' not found.")
            out = out[component]
        elif component.isdigit():
            index = int(component)
            if (isinstance(out, list) and 0 <= index < len(out)) or (
                isinstance(out, dict) and index in out
            ):
                out = out[index]
            else:
                raise KeyError(f"Reference '{path}' not found.")
        else:
            raise KeyError(f"Reference '{path}' not found.")
    return deepcopy(out)


def _dereference(obj: Any, full: dict[str, Any], processing: set[str]) -> Any:
    """Inline ``$ref``s, breaking cycles; ``$defs`` is copied untouched."""

    def props(d: dict[str, Any]) -> dict[str, Any]:
        return {
            k: deepcopy(v)
            if k == '$defs'
            else _dereference(v, full, processing)
            if isinstance(v, dict | list)
            else v
            for k, v in d.items()
        }

    if isinstance(obj, dict) and '$ref' in obj:
        ref = obj['$ref']
        extra = {k: v for k, v in obj.items() if k != '$ref'}
        if ref in processing:
            return props(extra)
        processing.add(ref)
        resolved = _dereference(_retrieve_ref(ref, full), full, processing)
        processing.remove(ref)
        if not extra:
            return resolved
        merged = dict(resolved) if isinstance(resolved, dict) else {}
        merged.update(props(extra))
        return merged
    if isinstance(obj, dict):
        return props(obj)
    if isinstance(obj, list):
        return [_dereference(item, full, processing) for item in obj]
    return obj


def _format_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    converted: dict[str, Any] = {}
    for key, value in schema.items():
        if key == 'definitions':
            continue
        if key == 'items':
            if value is not None:
                converted['items'] = _format_json_schema(value)
        elif key == 'properties':
            converted['properties'] = _properties_from_schema(value)
        elif key == 'allOf':
            if len(value) > 1:
                logger.warning(
                    "Only first value for 'allOf' key is supported. "
                    'Got %d, ignoring other than first value!',
                    len(value),
                )
            return _format_json_schema(value[0])
        elif key in ('type', 'type_'):
            if isinstance(value, dict):
                converted['type'] = value['_value_']
            elif isinstance(value, str):
                converted['type'] = value
            else:
                raise ValueError(f'Invalid type: {value}')
        elif key not in _ALLOWED_SCHEMA_FIELDS:
            logger.warning("Key '%s' is not supported in schema, ignoring", key)
        else:
            converted[key] = value
    return converted


def _dict_to_genai_schema(
    schema: dict[str, Any] | None,
    is_property: bool = False,
    is_any_of_item: bool = False,
) -> types.Schema | None:
    if schema is None:
        return None
    formatted = _format_json_schema(_dereference(schema, schema, set()))
    out: dict[str, Any] = {}
    # Gemini requires anyOf to be the only field set.
    if 'type' in formatted and 'anyOf' not in formatted:
        type_obj = formatted['type']
        if isinstance(type_obj, dict):
            out['type'] = types.Type(type_obj['_value_'])
        elif isinstance(type_obj, str):
            out['type'] = types.Type(type_obj)
        else:
            raise ValueError(f'Invalid type: {type_obj}')
    if 'description' in formatted:
        out['description'] = formatted['description']
    if 'title' in formatted and (not is_property or is_any_of_item):
        out['title'] = formatted['title']
    if 'properties' in formatted:
        out['properties'] = {
            name: _dict_to_genai_schema(prop, is_property=True)
            for name, prop in formatted['properties'].items()
        }
    if formatted.get('required') is not None:
        out['required'] = formatted['required']
    elif not is_property:
        out['required'] = []
    if 'items' in formatted:
        out['items'] = _dict_to_genai_schema(formatted['items'], is_property=True)
    if 'enum' in formatted:
        out['enum'] = formatted['enum']
    if 'nullable' in formatted:
        out['nullable'] = formatted['nullable']
    if 'anyOf' in formatted:
        out['any_of'] = [
            s
            for item in formatted['anyOf']
            if (s := _dict_to_genai_schema(item, is_property=True, is_any_of_item=True))
        ]
    if 'type' not in out and 'any_of' not in out:
        if is_property:
            out['type'] = types.Type.STRING
        elif 'properties' in out:
            out['type'] = types.Type.OBJECT
        else:
            return None
    return types.Schema.model_validate(out)


def _properties_from_schema(schema: Any) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return {}
    properties: dict[str, Any] = {}
    for k, v in schema.items():
        if not isinstance(k, str):
            logger.warning("Key '%s' is not supported in schema, type=%s", k, type(k))
            continue
        if not isinstance(v, dict):
            logger.warning("Value '%s' is not supported in schema, ignoring v=%s", v, v)
            continue
        item: dict[str, Any] = {}
        original_description = v.get('description')
        original_enum = v.get('enum')
        original_items = v.get('items')

        if v.get('anyOf') and all(t.get('type') != 'null' for t in v['anyOf']):
            item['anyOf'] = [_format_json_schema(t) for t in v['anyOf']]
        elif v.get('type') or v.get('anyOf') or v.get('type_'):
            item_type = _type_from_schema(v)
            item['type'] = item_type
            if _is_nullable_schema(v):
                item['nullable'] = True
            any_of = v.get('anyOf')
            if any_of and item_type in (types.Type.ARRAY, types.Type.OBJECT):
                json_type = 'array' if item_type == types.Type.ARRAY else 'object'
                v = [t for t in any_of if t.get('type') == json_type][-1].copy()
            elif any_of:
                non_null = [t for t in any_of if t.get('type') != 'null']
                v = non_null[-1].copy() if non_null else v
            if any_of:
                if original_enum and not v.get('enum'):
                    v['enum'] = original_enum
                if original_items and not v.get('items'):
                    v['items'] = original_items

        if v.get('enum'):
            item['enum'] = v['enum']
        description = v.get('description') or original_description
        if description and isinstance(description, str):
            item['description'] = description
        if item.get('type') == types.Type.ARRAY and v.get('items') is not None:
            item['items'] = _items_from_schema(v['items'])
        if item.get('type') == types.Type.OBJECT:
            if (
                v.get('anyOf')
                and isinstance(v['anyOf'], list)
                and isinstance(v['anyOf'][0], dict)
            ):
                v = v['anyOf'][0]
            v_properties = v.get('properties')
            if v_properties:
                item['properties'] = _properties_from_schema(v_properties)
                if isinstance(v_properties, dict):
                    item['required'] = [
                        name for name, p in v_properties.items() if 'default' not in p
                    ]
            elif not v.get('additionalProperties'):
                # Object without properties: Gemini needs some type.
                item['type'] = types.Type.STRING
        if k == 'title' and 'description' not in item:
            item['description'] = k + ' is ' + str(v)
        properties[k] = item
    return properties


def _items_from_schema(schema: Any) -> dict[str, Any]:
    items: dict[str, Any] = {}
    if isinstance(schema, list):
        for i, v in enumerate(schema):
            items[f'item{i}'] = _properties_from_schema(v)
    elif isinstance(schema, dict):
        items['type'] = _type_from_schema(schema)
        if items['type'] == types.Type.OBJECT and 'properties' in schema:
            items['properties'] = _properties_from_schema(schema['properties'])
        if items['type'] == types.Type.ARRAY and 'items' in schema:
            items['items'] = _format_json_schema(schema['items'])
        if 'title' in schema or 'description' in schema:
            items['description'] = schema.get('description') or schema.get('title')
        if 'enum' in schema:
            items['enum'] = schema['enum']
        if _is_nullable_schema(schema):
            items['nullable'] = True
        if 'required' in schema:
            items['required'] = schema['required']
    elif isinstance(schema, str) and schema:
        items['type'] = _type_from_schema({'type': schema})
        if _is_nullable_schema({'type': schema}):
            items['nullable'] = True
    elif isinstance(schema, str):
        items['type'] = types.Type.STRING
    return items


def _type_from_schema(schema: dict[str, Any]) -> types.Type:
    type_ = _nullable_type_from_schema(schema)
    return type_ if type_ is not None else types.Type.STRING


def _nullable_type_from_schema(schema: dict[str, Any]) -> types.Type | None:
    if 'anyOf' in schema:
        found = [
            t
            for sub in schema['anyOf']
            if (t := _nullable_type_from_schema(sub)) is not None
        ]
        return found[-1] if found else None
    if 'type' in schema or 'type_' in schema:
        type_ = schema['type'] if 'type' in schema else schema['type_']
        if isinstance(type_, types.Type):
            return type_
        if isinstance(type_, int):
            raise ValueError(f'Invalid type, int not supported: {type_}')
        if isinstance(type_, dict):
            return types.Type(type_['_value_'])
        if isinstance(type_, str):
            return None if type_ == 'null' else types.Type(type_)
    return None


def _is_nullable_schema(schema: dict[str, Any]) -> bool:
    if 'anyOf' in schema:
        return any(_nullable_type_from_schema(s) is None for s in schema['anyOf'])
    if 'type' in schema or 'type_' in schema:
        type_ = schema['type'] if 'type' in schema else schema['type_']
        if isinstance(type_, int) and not isinstance(type_, types.Type):
            return type_ == 7
    return False


# ── Messages -> contents ──────────────────────────────────────────────────────


def _decode_signature(sig: Any) -> bytes | None:
    if isinstance(sig, str):
        return base64.b64decode(sig) or None
    if isinstance(sig, bytes):
        return sig or None
    return None


def _block_signature(block: Mapping[str, Any]) -> Any:
    extras = block.get('extras')
    return (
        block.get('thought_signature')
        or block.get('signature')
        or (extras.get('signature') if isinstance(extras, Mapping) else None)
    )


def _extras_signature(block: Mapping[str, Any]) -> bytes | None:
    extras = block.get('extras')
    if not isinstance(extras, dict):
        return None
    sig = extras.get('signature')
    if isinstance(sig, str):
        return base64.b64decode(sig)
    if isinstance(sig, bytes):
        return sig
    return None


def _is_data_block(block: Mapping[str, Any]) -> bool:
    """Tell a multimodal data block, v0 (``source_type``) or v1 shaped."""
    if block.get('type') not in _DATA_BLOCK_TYPES:
        return False
    if any(key in block for key in ('url', 'base64', 'file_id', 'text')):
        return not (block['type'] == 'text' and 'source_type' not in block)
    source_type = block.get('source_type')
    return (
        (source_type == 'url' and 'url' in block)
        or (source_type == 'base64' and 'data' in block)
        or (source_type == 'id' and 'id' in block)
        or (source_type == 'text' and 'url' in block)
    )


def _provider_resolved_uri(block: Mapping[str, Any]) -> str | None:
    """Return a URI Gemini fetches itself, rather than one to download."""
    file_id = block.get('file_id')
    if isinstance(file_id, str) and file_id:
        return file_id
    url = block.get('url')
    if not isinstance(url, str) or not url:
        return None
    if url.startswith('gs://'):
        return url
    host = urlparse(url).hostname or ''
    if any(host == h or host.endswith(f'.{h}') for h in _PROVIDER_RESOLVED_HOSTS):
        return url
    return None


async def _download(url: str, http_client: httpx.AsyncClient | None) -> bytes:
    if http_client is None:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(url)
    else:
        response = await http_client.get(url, follow_redirects=True)
    response.raise_for_status()
    return response.content


def _media_resolution(part: Mapping[str, Any], model: str | None, kwargs: dict) -> None:
    if 'media_resolution' in part:
        if _is_gemini_25(model):
            warnings.warn(
                'Setting per-part media resolution requests to Gemini 2.5 models and '
                'older is not supported. The media_resolution parameter will be '
                'ignored.',
                UserWarning,
                stacklevel=2,
            )
        elif _is_gemini_3_or_later(model):
            kwargs['media_resolution'] = {'level': part['media_resolution']}
    if 'media_processing' in part:
        kwargs['media_processing'] = part['media_processing']


async def _url_part(url: str, http_client: httpx.AsyncClient | None) -> types.Part:
    """Build the part for an ``image_url``: data URL, http(s) URL or gs:// URI."""
    if url.startswith('gs://'):
        mime_type, _ = mimetypes.guess_type(url)
        return types.Part(file_data=types.FileData(file_uri=url, mime_type=mime_type))
    if url.startswith('data:'):
        match = re.search(r'data:([^;]+);base64,(.*)', url)
        if match is None:
            msg = (
                'Invalid base64 data URI format. Expected pattern: '
                'data:([^;]+);base64,(.*)\n'
                'Examples: data:image/jpeg;base64,... or data:application/pdf;base64,...\n'
                f'Got: {url[:100]}...'
            )
            raise ValueError(msg)
        data = base64.b64decode(match.group(2))
    else:
        parsed = urlparse(url)
        if not (parsed.scheme and parsed.netloc):
            msg = (
                'Media string must be one of: valid HTTP/HTTPS URL, base64 encoded '
                'data URI (e.g., data:image/..., data:application/pdf;base64,...), or '
                f"Google Cloud Storage URI (gs://...). Instead got '{url}'."
            )
            raise ValueError(msg)
        data = await _download(url, http_client)
    mime_type, _ = mimetypes.guess_type(url)
    if not mime_type and (kind := filetype.guess(data)):
        mime_type = kind.mime
    return types.Part(inline_data=types.Blob(data=data, mime_type=mime_type))


async def _data_block_part(
    part: Mapping[str, Any], model: str | None, http_client: httpx.AsyncClient | None
) -> types.Part:
    resolved_uri = None if 'source_type' in part else _provider_resolved_uri(part)
    kwargs: dict[str, Any] = {}
    data = b''
    if resolved_uri is not None:
        kwargs['file_data'] = types.FileData(
            file_uri=resolved_uri, mime_type=part.get('mime_type')
        )
    elif 'source_type' in part:
        if part['source_type'] == 'url':
            data = await _download(part['url'], http_client)
        elif part['source_type'] == 'base64':
            data = base64.b64decode(part['data'])
        else:
            raise ValueError('source_type must be url or base64.')
    elif 'url' in part:
        data = await _download(part['url'], http_client)
    elif 'base64' in part:
        data = base64.b64decode(part['base64'])
    else:
        raise ValueError(
            "Data content block must contain 'url', 'base64', or 'data' field."
        )
    if resolved_uri is None:
        mime_type = part.get('mime_type')
        if not mime_type:
            source = part.get('url') or part.get('base64') or part.get('data')
            mime_type, _ = mimetypes.guess_type(source)
            if not mime_type and (kind := filetype.guess(data)):
                mime_type = kind.mime
        blob: dict[str, Any] = {'data': data}
        if mime_type:
            blob['mime_type'] = mime_type
        kwargs['inline_data'] = types.Blob(**blob)
    _media_resolution(part, model, kwargs)
    return types.Part(**kwargs)


def _media_part(part: Mapping[str, Any], model: str | None) -> types.Part:
    mime_type = part.get('mime_type')
    kwargs: dict[str, Any] = {}
    if 'data' in part:
        if not mime_type:
            raise ValueError(f'Missing mime_type in media part: {part}')
        data = part['data']
        if isinstance(data, str):
            clean = re.sub(r'\s+', '', data)
            invalid = 'Data should be valid base64'
            if not re.match(r'^[A-Za-z0-9+/]*={0,2}$', clean) or len(clean) % 4 != 0:
                raise ValueError(invalid)
            try:
                data = base64.b64decode(clean)
            except Exception as e:
                raise ValueError(invalid) from e
        kwargs['inline_data'] = types.Blob(data=data, mime_type=mime_type)
    elif 'file_uri' in part:
        kwargs['file_data'] = types.FileData(
            file_uri=part['file_uri'], mime_type=mime_type
        )
    else:
        raise ValueError(f'Media part must have either data or file_uri: {part}')
    if 'video_metadata' in part:
        kwargs['video_metadata'] = types.VideoMetadata.model_validate(
            part['video_metadata']
        )
    _media_resolution(part, model, kwargs)
    if (sig := _extras_signature(part)) is not None:
        kwargs['thought_signature'] = sig
    return types.Part(**kwargs)


async def _convert_to_parts(
    raw_content: str | Sequence[Any],
    model: str | None,
    http_client: httpx.AsyncClient | None,
) -> list[types.Part]:
    content = [raw_content] if isinstance(raw_content, str) else raw_content
    parts: list[types.Part] = []
    for part in content:
        if isinstance(part, str):
            parts.append(types.Part(text=part))
            continue
        if not isinstance(part, Mapping):
            raise ChatGoogleGenerativeAIError(
                'Unknown error occurred while converting message content to parts.'
            )
        if 'type' not in part:
            logger.warning(
                'Unrecognized message part format. Assuming it is a text part.'
            )
            parts.append(types.Part(text=str(part)))
            continue
        part_type = part['type']
        if part_type == 'text':
            parts.append(
                types.Part(
                    text=part['text'],
                    thought_signature=_decode_signature(_block_signature(part)),
                )
            )
        elif part_type == 'file' and 'file_id' in part:
            kwargs: dict[str, Any] = {
                'file_data': types.FileData(
                    file_uri=part['file_id'],
                    mime_type=part.get('mime_type', 'application/octet-stream'),
                )
            }
            if 'media_processing' in part:
                kwargs['media_processing'] = part['media_processing']
            parts.append(types.Part(**kwargs))
        elif _is_data_block(part):
            parts.append(await _data_block_part(part, model, http_client))
        elif part_type == 'image_url':
            image_url = part['image_url']
            if isinstance(image_url, dict):
                if 'url' not in image_url:
                    raise ValueError(f'Unrecognized message image format: {image_url}')
                image_url = image_url['url']
            image_part = await _url_part(image_url, http_client)
            if (sig := _extras_signature(part)) is not None:
                image_part.thought_signature = sig
            parts.append(image_part)
        elif part_type == 'media':
            parts.append(_media_part(part, model))
        elif part_type == 'thinking':
            parts.append(
                types.Part(
                    text=part['thinking'],
                    thought=True,
                    thought_signature=_decode_signature(_block_signature(part)),
                )
            )
        elif part_type == 'reasoning':
            text = part.get('reasoning')
            if text is None:
                summary = part.get('summary')
                if isinstance(summary, list):
                    text = ' '.join(
                        t.strip()
                        for item in summary
                        if isinstance(item, dict)
                        and isinstance((t := item.get('text')), str)
                        and t.strip()
                    )
                if not text:
                    continue
            parts.append(
                types.Part(
                    text=text,
                    thought=True,
                    thought_signature=_decode_signature(_block_signature(part)),
                )
            )
        else:
            raise ValueError(f'Unrecognized message part type: {part_type}.')
    return parts


async def _convert_to_parts_lenient(
    content: list[Any], model: str | None, http_client: httpx.AsyncClient | None
) -> list[types.Part]:
    """Convert block by block, dropping the blocks Gemini cannot represent."""
    parts: list[types.Part] = []
    for block in content:
        try:
            parts.extend(await _convert_to_parts([block], model, http_client))
        except (ValueError, ChatGoogleGenerativeAIError) as exc:
            logger.warning(
                'Dropping content block that cannot be represented as a Gemini '
                'part (type: %s): %s',
                block.get('type') if isinstance(block, Mapping) else type(block),
                exc,
            )
    return parts


def _file_uri(block: Any) -> Any:
    if not isinstance(block, Mapping):
        return None
    file_data = block.get('file_data')
    if isinstance(file_data, Mapping):
        return file_data.get('file_uri')
    block_type = block.get('type')
    if block_type in ('file_data', 'media'):
        return block.get('file_uri')
    if block_type == 'file':
        return block.get('file_id') or block.get('url')
    if block_type == 'image':
        return block.get('url')
    if block_type == 'image_url':
        image_url = block.get('image_url')
        return image_url.get('url') if isinstance(image_url, Mapping) else image_url
    return None


def _ai_content(message: AIMessage, *, exclude_function_calls: bool) -> list[Any]:
    content = message.content
    if not exclude_function_calls:
        content = [content] if isinstance(content, str) else content
    elif not isinstance(content, list):
        content = [content] if content else []
    else:
        filtered: list[Any] = []
        for block in content:
            if not isinstance(block, dict):
                if not (isinstance(block, str) and not block):
                    filtered.append(block)
                continue
            block_type = block.get('type')
            if block_type in (
                'tool_call',
                'tool_call_chunk',
                'invalid_tool_call',
                'function_call_signature',
                'function_call',
            ):
                continue
            if block_type == 'file_data' and 'file_uri' in block:
                filtered.append(
                    {
                        'type': 'media',
                        'file_uri': block['file_uri'],
                        'mime_type': block.get('mime_type', 'application/octet-stream'),
                    }
                )
                continue
            has_payload = (
                block.get('text')
                or block.get('thinking')
                or block.get('reasoning')
                or block.get('summary')
            )
            if (
                block_type in ('text', 'thinking', 'reasoning')
                and not has_payload
                and not _block_signature(block)
            ):
                continue
            filtered.append(block)
        content = filtered
    # The Gemini Developer API does not accept gs:// references.
    kept = []
    for block in content:
        uri = _file_uri(block)
        if isinstance(uri, str) and uri.startswith('gs://'):
            logger.warning(
                'Dropping Google Cloud Storage file URI from chat history because '
                'the target Gemini Developer API does not support gs:// references.'
            )
            continue
        kept.append(block)
    return kept


async def _ai_parts(
    message: AIMessage,
    model: str | None,
    http_client: httpx.AsyncClient | None,
    *,
    exclude_function_calls: bool,
) -> list[types.Part]:
    content = _ai_content(message, exclude_function_calls=exclude_function_calls)
    if message.response_metadata.get('model_provider') in _NATIVE_PROVIDERS:
        return await _convert_to_parts(content, model, http_client)
    return await _convert_to_parts_lenient(content, model, http_client)


def _function_call_signatures(message: AIMessage) -> dict[int, Any]:
    """Legacy function-call signature blocks, indexed by tool call."""
    provider = message.response_metadata.get('model_provider')
    if (provider is not None and provider not in _NATIVE_PROVIDERS) or not isinstance(
        message.content, list
    ):
        return {}
    signatures: dict[int, Any] = {}
    ordinal = 0
    for block in message.content:
        if (
            not isinstance(block, Mapping)
            or block.get('type') != 'function_call_signature'
        ):
            continue
        signature = block.get('signature')
        if not isinstance(signature, str | bytes) or not signature:
            continue
        index = block.get('index', ordinal)
        ordinal += 1
        if isinstance(index, int):
            signatures[index] = signature
    return signatures


async def _tool_message_parts(
    message: ToolMessage | FunctionMessage,
    name: str | None,
    model: str | None,
    http_client: httpx.AsyncClient | None,
) -> list[types.Part]:
    name = message.name or name or message.additional_kwargs.get('name')
    parts: list[types.Part] = []
    response: Any
    if isinstance(message.content, list):
        media = [
            b
            for b in message.content
            if isinstance(b, dict)
            and (_is_data_block(b) or b.get('type') == 'image_url')
        ]
        parts.extend(await _convert_to_parts(media, model, http_client))
        response = [b for b in message.content if not any(b is m for m in media)]
    else:
        try:
            response = json.loads(message.content)
        except json.JSONDecodeError:
            response = message.content
    parts.append(
        types.Part(
            function_response=types.FunctionResponse(
                name=name,
                response=response
                if isinstance(response, dict)
                else {'output': response},
            )
        )
    )
    return parts


async def _convert_messages(
    messages: Sequence[BaseMessage],
    *,
    model: str,
    convert_system_message_to_human: bool = False,
    http_client: httpx.AsyncClient | None = None,
) -> tuple[types.Content | None, list[types.Content]]:
    """Split messages into the system instruction and the ``contents``.

    Only a leading system message starts the system instruction; later ones are
    appended to it, or dropped when there is none. Tool results follow the
    assistant turn that called them, as one user turn of function responses.
    """
    contents: list[types.Content] = []
    system_instruction: types.Content | None = None
    others = [m for m in messages if not isinstance(m, ToolMessage)]
    tool_messages = [m for m in messages if isinstance(m, ToolMessage)]
    for i, message in enumerate(others):
        if isinstance(message, SystemMessage):
            system_parts = await _convert_to_parts(message.content, model, http_client)
            if i == 0:
                system_instruction = types.Content(parts=system_parts)
            elif system_instruction is not None:
                if system_instruction.parts is None:
                    system_instruction.parts = system_parts
                else:
                    system_instruction.parts.extend(system_parts)
            continue
        if isinstance(message, AIMessage):
            role = 'model'
            if message.tool_calls:
                parts = await _ai_parts(
                    message, model, http_client, exclude_function_calls=True
                )
                signatures = message.additional_kwargs.get(
                    _FUNCTION_CALL_SIGNATURES_KEY, {}
                )
                indexed_signatures = _function_call_signatures(message)
                for index, call in enumerate(message.tool_calls):
                    function_call = types.FunctionCall(
                        name=call['name'], args=call['args']
                    )
                    sig = signatures.get(call.get('id')) or indexed_signatures.get(
                        index
                    )
                    if sig:
                        parts.append(
                            types.Part(
                                function_call=function_call,
                                thought_signature=_decode_signature(sig),
                            )
                        )
                    else:
                        parts.append(types.Part(function_call=function_call))
                pending = {call['id']: call for call in message.tool_calls}
                response_parts: list[types.Part] = []
                for tool_message in tool_messages:
                    if not pending:
                        break
                    if tool_message.tool_call_id in pending:
                        call = pending.pop(tool_message.tool_call_id)
                        response_parts.extend(
                            await _tool_message_parts(
                                tool_message, call.get('name'), model, http_client
                            )
                        )
                contents.append(types.Content(role=role, parts=parts))
                # Gemini rejects a content with no parts.
                if response_parts:
                    contents.append(types.Content(role='user', parts=response_parts))
                continue
            if raw_function_call := message.additional_kwargs.get('function_call'):
                parts = [
                    types.Part(
                        function_call=types.FunctionCall(
                            name=raw_function_call['name'],
                            args=json.loads(raw_function_call['arguments']),
                        )
                    )
                ]
            else:
                parts = await _ai_parts(
                    message, model, http_client, exclude_function_calls=False
                )
        elif isinstance(message, HumanMessage):
            role = 'user'
            parts = await _convert_to_parts(message.content, model, http_client)
            if i == 1 and convert_system_message_to_human and system_instruction:
                parts = list(system_instruction.parts or []) + parts
                system_instruction = None
        elif isinstance(message, FunctionMessage):
            role = 'user'
            parts = await _tool_message_parts(message, None, model, http_client)
        else:
            msg = f'Unexpected message with type {type(message)} at the position {i}.'
            raise ValueError(msg)  # noqa: TRY004
        if role == 'model' and not parts:
            logger.warning(
                'AI message at index %d converted to no Gemini parts; using an empty '
                'text part.',
                i,
            )
            parts = [types.Part(text='')]
        contents.append(types.Content(role=role, parts=parts))

    if _is_gemini_3_or_later(model):
        _patch_missing_thought_signatures(contents)
    return system_instruction, contents


def _patch_missing_thought_signatures(contents: list[types.Content]) -> None:
    """Gemini 3+ wants a thought signature on the first function call of each
    model turn of the active loop; put the bypass placeholder where none is.
    """
    start = 0
    for i in range(len(contents) - 1, -1, -1):
        content = contents[i]
        if content.role != 'user':
            continue
        parts = content.parts or []
        has_response = any(p.function_response for p in parts)
        has_standard = any(p.text or p.inline_data for p in parts)
        if has_standard and not has_response:
            start = i + 1
            break
    for content in contents[start:]:
        if content.role != 'model':
            continue
        for part in content.parts or []:
            if part.function_call:
                if not part.thought_signature:
                    # Assigned after construction so it stays a str: the SDK
                    # would base64-encode bytes and hide the placeholder.
                    part.thought_signature = _SKIP_THOUGHT_SIGNATURE  # type: ignore[assignment]
                break


# ── Response -> messages ──────────────────────────────────────────────────────


def _append(content: str | list[Any] | None, item: Any) -> str | list[Any]:
    if content is None and isinstance(item, str):
        return item
    if content is None:
        return [item]
    if isinstance(content, str):
        return [content, item]
    content.append(item)
    return content


def _integer_like_floats(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _integer_like_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_integer_like_floats(v) for v in obj]
    if isinstance(obj, float) and obj.is_integer():
        return int(obj)
    return obj


def _server_tool_name(tool_type: Any) -> str:
    if tool_type is None:
        return 'media_processing'
    return str(getattr(tool_type, 'value', tool_type)).lower()


def _parse_candidate(
    candidate: types.Candidate,
    *,
    streaming: bool,
    model_name: str | None,
    content_model: str | None,
) -> AIMessage:
    content: str | list[Any] | None = None
    additional_kwargs: dict[str, Any] = {}
    response_metadata: dict[str, Any] = {'model_provider': 'google_genai'}
    if model_name:
        response_metadata['model_name'] = model_name
    tool_calls = []
    tool_call_chunks = []
    content_model = content_model or model_name
    gemini_3 = _is_gemini_3_or_later(content_model or '')

    parts = (candidate.content.parts or []) if candidate.content else []
    for part in parts:
        text = part.text
        if text is not None and not streaming:
            text = text.rstrip('\n')
        thought_sig = (
            base64.b64encode(part.thought_signature).decode('ascii') or None
            if isinstance(part.thought_signature, bytes) and part.thought_signature
            else None
        )

        if part.thought:
            thinking: dict[str, Any] = {'type': 'thinking', 'thinking': part.text}
            if thought_sig:
                thinking['signature'] = thought_sig
            content = _append(content, thinking)
        elif text or (part.text is not None and thought_sig):
            block: dict[str, Any] = {'type': 'text', 'text': text or ''}
            if thought_sig:
                block['extras'] = {'signature': thought_sig}
            if (
                thought_sig
                or gemini_3
                or (
                    isinstance(content, list)
                    and any(
                        isinstance(item, dict) and item.get('type') == 'thinking'
                        for item in content
                    )
                )
            ):
                content = _append(content, block)
            else:
                content = _append(content, text or '')

        code = part.executable_code
        if code is not None and code.code and code.language:
            content = _append(
                content,
                {
                    'type': 'executable_code',
                    'executable_code': code.code,
                    'language': code.language,
                    'id': str(uuid.uuid4()),
                },
            )
        result = part.code_execution_result
        if result is not None and result.output:
            outcome = 1 if result.outcome in (None, types.Outcome.OUTCOME_OK) else 2
            content = _append(
                content,
                {
                    'type': 'code_execution_result',
                    'code_execution_result': result.output,
                    'outcome': outcome,
                    'tool_call_id': '',
                },
            )

        media_call = getattr(part, 'tool_call', None)
        if media_call is not None:
            call_block: dict[str, Any] = {
                'type': 'server_tool_call',
                'name': _server_tool_name(media_call.tool_type),
                'id': media_call.id or str(uuid.uuid4()),
                'args': dict(media_call.args or {}),
            }
            if thought_sig:
                call_block['extras'] = {'signature': thought_sig}
            content = _append(content, call_block)
        media_result = getattr(part, 'tool_response', None)
        if media_result is not None:
            result_block: dict[str, Any] = {
                'type': 'server_tool_result',
                'tool_call_id': media_result.id or '',
                'status': 'success',
                'output': dict(media_result.response or {}),
                'extras': {'block_type': _server_tool_name(media_result.tool_type)},
            }
            if thought_sig:
                result_block['extras']['signature'] = thought_sig
            content = _append(content, result_block)

        inline = part.inline_data
        if inline and inline.data and inline.mime_type:
            if inline.mime_type.startswith('audio/'):
                buffer = io.BytesIO()
                with wave.open(buffer, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(24000)
                    wf.writeframes(inline.data)
                additional_kwargs['audio'] = buffer.getvalue()
            if inline.mime_type.startswith('image/'):
                encoded = base64.b64encode(inline.data).decode('ascii')
                image: dict[str, Any] = {
                    'type': 'image_url',
                    'image_url': {
                        'url': f'data:image/{inline.mime_type[6:]};base64,{encoded}'
                    },
                }
                if thought_sig:
                    image['extras'] = {'signature': thought_sig}
                content = _append(content, image)

        if part.function_call:
            args = _integer_like_floats(
                dict(part.function_call.args) if part.function_call.args else {}
            )
            arguments = json.dumps(args)
            additional_kwargs['function_call'] = {
                'name': part.function_call.name,
                'arguments': arguments,
            }
            raw_id = part.function_call.id
            call_id = str(raw_id) if raw_id else str(uuid.uuid4())
            if streaming:
                tool_call_chunks.append(
                    tool_call_chunk(
                        name=part.function_call.name, args=arguments, id=call_id
                    )
                )
            else:
                # The arguments were serialized from a dict, so they parse.
                tool_calls.append(
                    tool_call(
                        name=part.function_call.name or '',
                        args=json.loads(arguments, strict=False),
                        id=call_id,
                    )
                )
            if thought_sig:
                additional_kwargs.setdefault(_FUNCTION_CALL_SIGNATURES_KEY, {})[
                    call_id
                ] = thought_sig

    if content is None:
        content = [] if gemini_3 else ''
    if streaming:
        return AIMessageChunk(
            content=content,
            additional_kwargs=additional_kwargs,
            response_metadata=response_metadata,
            tool_call_chunks=tool_call_chunks,
        )
    return AIMessage(
        content=content,
        additional_kwargs=additional_kwargs,
        response_metadata=response_metadata,
        tool_calls=tool_calls,
    )


def _usage_op(left: dict[str, Any], right: dict[str, Any], op) -> dict[str, Any]:
    combined: dict[str, Any] = {}
    for k in [*left, *(k for k in right if k not in left)]:
        lv, rv = left.get(k, 0), right.get(k, 0)
        if isinstance(lv, int) and isinstance(rv, int):
            combined[k] = op(lv, rv)
        elif isinstance(left.get(k, {}), dict) and isinstance(right.get(k, {}), dict):
            combined[k] = _usage_op(left.get(k, {}), right.get(k, {}), op)
        else:
            types_ = [type(d[k]) for d in (left, right) if k in d]
            msg = f'Unknown value types: {types_}. Only dict and int values are supported.'
            raise ValueError(msg)  # noqa: TRY004
    return combined


def _add_usage(
    left: UsageMetadata | None, right: UsageMetadata | None
) -> UsageMetadata:
    if not (left or right):
        return UsageMetadata(input_tokens=0, output_tokens=0, total_tokens=0)
    if not (left and right):
        return left or right  # type: ignore[return-value]
    return UsageMetadata(**_usage_op(left, right, lambda a, b: a + b))  # type: ignore[typeddict-item]


def _subtract_usage(
    left: UsageMetadata | None, right: UsageMetadata | None
) -> UsageMetadata:
    if not (left or right):
        return UsageMetadata(input_tokens=0, output_tokens=0, total_tokens=0)
    if not (left and right):
        return left or right  # type: ignore[return-value]
    return UsageMetadata(**_usage_op(left, right, lambda a, b: max(a - b, 0)))  # type: ignore[typeddict-item]


def _usage(
    response: types.GenerateContentResponse, prev_usage: UsageMetadata | None
) -> UsageMetadata | None:
    """Return the reply's usage; streams report running totals, chunks get deltas."""
    meta = response.usage_metadata
    if meta is None:
        return None
    # Server-side tool prompt tokens are input tokens too.
    input_tokens = (meta.prompt_token_count or 0) + (
        meta.tool_use_prompt_token_count or 0
    )
    thought_tokens = meta.thoughts_token_count or 0
    output_tokens = (meta.candidates_token_count or 0) + thought_tokens
    total_tokens = meta.total_token_count or 0
    cache_read = meta.cached_content_token_count or 0
    if input_tokens + output_tokens + cache_read + total_tokens <= 0:
        return None
    cumulative = UsageMetadata(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        input_token_details={'cache_read': cache_read},
    )
    if thought_tokens > 0:
        cumulative['output_token_details'] = {'reasoning': thought_tokens}
    usage = _subtract_usage(cumulative, prev_usage)
    if prev_usage and input_tokens < prev_usage.get('input_tokens', 0):
        # A lower final prompt count is the ground truth; compensate here
        # since the subtraction floors at zero.
        usage['input_tokens'] = input_tokens - prev_usage.get('input_tokens', 0)
    return usage


def _response_to_result(
    response: types.GenerateContentResponse,
    stream: bool = False,
    prev_usage: UsageMetadata | None = None,
) -> list[tuple[AIMessage, dict[str, Any]]]:
    """One ``(message, generation_info)`` per candidate."""
    usage = _usage(response, prev_usage)
    results: list[tuple[AIMessage, dict[str, Any]]] = []
    for candidate in response.candidates or []:
        generation_info: dict[str, Any] = {}
        model_name = None
        if candidate.finish_reason:
            if hasattr(candidate.finish_reason, 'name'):
                generation_info['finish_reason'] = candidate.finish_reason.name
            elif isinstance(candidate.finish_reason, int):
                generation_info['finish_reason'] = f'UNKNOWN_{candidate.finish_reason}'
            generation_info['model_name'] = response.model_version or ''
            # Only the last chunk names the model.
            model_name = response.model_version
        generation_info['safety_ratings'] = [
            rating.model_dump() for rating in candidate.safety_ratings or []
        ]
        message = _parse_candidate(
            candidate,
            streaming=stream,
            model_name=model_name,
            content_model=response.model_version,
        )
        if candidate.grounding_metadata:
            grounding = candidate.grounding_metadata.model_dump()
            for key in (
                'grounding_supports',
                'grounding_chunks',
                'web_search_queries',
                'image_search_queries',
            ):
                if key in grounding and grounding[key] is None:
                    grounding[key] = []
            generation_info['grounding_metadata'] = grounding
            message.response_metadata['grounding_metadata'] = grounding
        message.usage_metadata = usage
        results.append((message, generation_info))
    if not response.candidates:
        # Likely a prompt feedback block: answer empty, like other providers.
        logger.warning(
            'Gemini produced an empty response. Continuing with empty message\n'
            'Feedback: %s',
            response.prompt_feedback,
        )
        if stream:
            metadata = (
                {'prompt_feedback': response.prompt_feedback.model_dump()}
                if response.prompt_feedback
                else {}
            )
            return [(AIMessageChunk(content='', response_metadata=metadata), {})]
        return [(AIMessage(content=''), {})]
    return results


class _StreamBlockIndexer:
    """Assigns streaming ``index`` values to content blocks and tool calls."""

    def __init__(self) -> None:
        self._next = 0
        self._open_type: str | None = None
        self._open_index = -1

    def _allocate(self, block_type: str | None) -> int:
        index = self._next
        self._next += 1
        self._open_type = block_type
        self._open_index = index
        return index

    def assign(self, message: AIMessageChunk) -> None:
        if isinstance(message.content, list):
            for block in message.content:
                if not isinstance(block, dict) or 'type' not in block:
                    continue
                block_type = block['type']
                # Text and thinking deltas keep merging into the open block.
                if block_type == self._open_type and block_type in ('text', 'thinking'):
                    index = self._open_index
                else:
                    index = self._allocate(block_type)
                block.setdefault('index', index)
        for chunk in message.tool_call_chunks:
            # Gemini sends each function call whole, so each is its own call.
            if chunk.get('index') is None:
                chunk['index'] = self._allocate(None)


# ── Embeddings ────────────────────────────────────────────────────────────────


def _split_by_punctuation(text: str) -> list[str]:
    split_by = string.punctuation + '\t\n '
    return [s for s in re.split(f'([{split_by}])', text) if s]


def _prepare_batches(texts: list[str], batch_size: int) -> list[list[str]]:
    """Split texts into batches of at most ``batch_size`` texts and roughly
    ``_MAX_TOKENS_PER_BATCH`` tokens; an oversized text gets a batch of its own.
    """
    batches: list[list[str]] = []
    current: list[str] = []
    current_tokens = 0
    index = 0
    while index < len(texts):
        text = texts[index]
        tokens = len(_split_by_punctuation(text)) * 2
        end_of_batch = False
        if tokens > _MAX_TOKENS_PER_BATCH:
            if current:
                batches.append(current)
            current = [text]
            index += 1
            end_of_batch = True
        elif (
            current_tokens + tokens > _MAX_TOKENS_PER_BATCH
            or len(current) == batch_size
        ):
            end_of_batch = True
        else:
            if index == len(texts) - 1:
                end_of_batch = True
            current_tokens += tokens
            current.append(text)
            index += 1
        if end_of_batch:
            batches.append(current)
            current = []
            current_tokens = 0
    return batches


class GoogleGenerativeAIEmbeddings(Embeddings):
    """Gemini embeddings: documents embed as ``RETRIEVAL_DOCUMENT`` and a query
    as ``RETRIEVAL_QUERY`` unless ``task_type`` is configured.
    """

    def __init__(
        self,
        model: str,
        *,
        http_async_client: httpx.AsyncClient | None = None,
        **params: Any,
    ):
        self.model = model
        self.task_type = params.get('task_type')
        self.output_dimensionality = params.get('output_dimensionality')
        self._client = _build_client(params, http_async_client)

    def _config(self, task_type: str) -> types.EmbedContentConfig:
        return types.EmbedContentConfig(
            task_type=task_type.upper(),
            output_dimensionality=self.output_dimensionality,
        )

    def _batches(self, texts: list[str]):
        config = self._config(self.task_type or 'RETRIEVAL_DOCUMENT')
        for batch in _prepare_batches(texts, _DEFAULT_BATCH_SIZE):
            yield [{'parts': [{'text': text}]} for text in batch], config

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for contents, config in self._batches(texts):
            with _embedding_errors():
                result = self._client.models.embed_content(
                    model=self.model, contents=contents, config=config
                )
            embeddings.extend(list(e.values) for e in result.embeddings)
        return embeddings

    def embed_query(self, text: str) -> list[float]:
        with _embedding_errors():
            result = self._client.models.embed_content(
                model=self.model,
                contents=text,
                config=self._config(self.task_type or 'RETRIEVAL_QUERY'),
            )
        return list(result.embeddings[0].values)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for contents, config in self._batches(texts):
            with _embedding_errors():
                result = await self._client.aio.models.embed_content(
                    model=self.model, contents=contents, config=config
                )
            embeddings.extend(list(e.values) for e in result.embeddings)
        return embeddings

    async def aembed_query(self, text: str) -> list[float]:
        with _embedding_errors():
            result = await self._client.aio.models.embed_content(
                model=self.model,
                contents=text,
                config=self._config(self.task_type or 'RETRIEVAL_QUERY'),
            )
        return list(result.embeddings[0].values)


@contextmanager
def _embedding_errors() -> Iterator[None]:
    """Wrap any embedding failure in a ``GoogleGenerativeAIError``."""
    try:
        yield
    except errors.ClientError as e:
        raise GoogleGenerativeAIError(
            f'Error embedding content ({e.status}): {e}'
        ) from e
    except Exception as e:
        raise GoogleGenerativeAIError(f'Error embedding content: {e}') from e
