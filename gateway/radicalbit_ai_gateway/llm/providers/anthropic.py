"""Anthropic chat model on the official ``anthropic`` SDK.

The request payload, the parsed replies and the defaults (``max_tokens`` from
the model's profile, no client timeout, 2 SDK retries) follow what the
LangChain integration this replaces produced, so the wire traffic is unchanged.
Streamed chunks carry plain-text content only: tool-use and other non-text
blocks reach the caller as ``tool_call_chunks`` (or not at all), never as a
list of raw blocks.
"""

from collections.abc import AsyncIterator, Mapping, Sequence
import copy
import datetime
from functools import cache, lru_cache
import hashlib
import inspect
import json
import logging
import os
import re
from typing import Any
import warnings

import anthropic
from pydantic import BaseModel

from radicalbit_ai_gateway.llm.chat_model import ChatModel, StructuredChatModel
from radicalbit_ai_gateway.llm.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolCall,
    ToolMessage,
    tool_call,
    tool_call_chunk,
)

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = 'https://api.anthropic.com'
_FALLBACK_MAX_OUTPUT_TOKENS = 4096

# Model name -> (default max_tokens, accepts the adaptive+summarized thinking
# shape). Profiles match the exact model name; any other model gets 4096.
_MODEL_PROFILES: dict[str, tuple[int, bool]] = {
    'claude-fable-5': (128000, True),
    'claude-fable-5-1': (128000, True),
    'claude-haiku-4-5': (64000, False),
    'claude-haiku-4-5-20251001': (64000, False),
    'claude-opus-4-5': (64000, False),
    'claude-opus-4-5-20251101': (64000, False),
    'claude-opus-4-6': (128000, False),
    'claude-opus-4-7': (128000, True),
    'claude-opus-4-8': (128000, True),
    'claude-opus-5': (128000, True),
    'claude-sonnet-4-5': (64000, False),
    'claude-sonnet-4-5-20250929': (64000, False),
    'claude-sonnet-4-6': (128000, False),
    'claude-sonnet-5': (128000, True),
}

# Model settings accepted by the builder, by name and alias.
_ALIASES = {
    'model_name': 'model',
    'max_tokens_to_sample': 'max_tokens',
    'timeout': 'default_request_timeout',
    'stop': 'stop_sequences',
    'base_url': 'anthropic_api_url',
    'api_key': 'anthropic_api_key',
    'effort': 'reasoning_effort',
}
_FIELDS = {
    'model',
    'max_tokens',
    'temperature',
    'top_k',
    'top_p',
    'default_request_timeout',
    'max_retries',
    'stop_sequences',
    'anthropic_api_url',
    'anthropic_api_key',
    'anthropic_proxy',
    'default_headers',
    'betas',
    'model_kwargs',
    'stream_usage',
    'thinking',
    'output_config',
    'reasoning_effort',
    'mcp_servers',
    'context_management',
    'container',
    'reuse_last_container',
    'inference_geo',
    'user_profile_id',
}
# Settings of the former LangChain base class: consumed, never sent upstream.
_IGNORED_FIELDS = {
    'cache',
    'callbacks',
    'custom_get_token_ids',
    'disable_streaming',
    'metadata',
    'name',
    'output_version',
    'profile',
    'rate_limiter',
    'streaming',
    'tags',
    'verbose',
}

_ROLES = {
    'human': 'user',
    'ai': 'assistant',
    'AIMessageChunk': 'assistant',
}

_BUILTIN_TOOL_PREFIXES = (
    'text_editor_',
    'computer_',
    'bash_',
    'web_search_',
    'web_fetch_',
    'code_execution_',
    'mcp_toolset',
    'memory_',
    'tool_search_',
    'advisor_',
)
_TOOL_TYPE_TO_BETA = {
    'web_fetch_20250910': 'web-fetch-2025-09-10',
    'code_execution_20250522': 'code-execution-2025-05-22',
    'mcp_toolset': 'mcp-client-2025-11-20',
    'memory_20250818': 'context-management-2025-06-27',
    'computer_20250124': 'computer-use-2025-01-24',
    'computer_20251124': 'computer-use-2025-11-24',
    'tool_search_tool_regex_20251119': 'advanced-tool-use-2025-11-20',
    'tool_search_tool_bm25_20251119': 'advanced-tool-use-2025-11-20',
    'advisor_20260301': 'advisor-tool-2026-03-01',
}
# OpenAI tool types passed through untouched by the OpenAI tool conversion.
_OPENAI_TOOL_TYPES = (
    'function',
    'file_search',
    'computer',
    'computer_use_preview',
    'code_interpreter',
    'mcp',
    'image_generation',
    'web_search_preview',
    'web_search',
    'tool_search',
)
_TOP_LEVEL_COMPOSITION_KEYS = ('oneOf', 'anyOf')
_SAMPLING_PARAMS = ('temperature', 'top_p', 'top_k')
_DATA_BLOCK_TYPES = ('image', 'video', 'audio', 'text-plain', 'file')

# Content blocks copied with only these fields.
_FILTERED_BLOCK_FIELDS = {
    'server_tool_use': ('type', 'id', 'input', 'name', 'server_name', 'cache_control'),
    'mcp_tool_use': ('type', 'id', 'input', 'name', 'server_name', 'cache_control'),
    'redacted_thinking': ('type', 'cache_control', 'data'),
}
_TOOL_RESULT_FIELDS = ('type', 'content', 'tool_use_id', 'cache_control')
_SERVER_TOOL_RESULT_FIELDS = (
    'type',
    'content',
    'tool_use_id',
    'is_error',
    'cache_control',
    'retrieved_at',
)
_SERVER_TOOL_RESULT_TYPES = (
    'code_execution_tool_result',
    'bash_code_execution_tool_result',
    'text_editor_code_execution_tool_result',
    'mcp_tool_result',
    'web_search_tool_result',
    'web_fetch_tool_result',
)

_TOOL_CALL_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')

_MAX_TOKENS_ERROR = (
    'Output parser received a `max_tokens` stop reason. '
    'The output is likely incomplete—please increase `max_tokens` '
    'or shorten your prompt.'
)
_THINKING_ADMONITION = (
    'You are attempting to use structured output via forced tool calling, '
    'which is not guaranteed when `thinking` is enabled. This method will '
    'raise an OutputParserException if tool calls are not generated. Consider '
    'disabling `thinking` or adjust your prompt to ensure the tool is called.'
)


class OutputParserError(ValueError):
    """A structured reply could not be parsed into its schema."""


def build_chat_model(model_name: str, **kwargs: Any) -> 'ChatAnthropic':
    """Build a ``ChatAnthropic`` from the gateway's configured kwargs."""
    settings: dict[str, Any] = {'model': model_name}
    model_kwargs = dict(kwargs.pop('model_kwargs', None) or {})
    for key, value in kwargs.items():
        field = _ALIASES.get(key, key)
        if field in _FIELDS:
            if value is not None or field not in settings:
                settings[field] = value
        elif key not in _IGNORED_FIELDS:
            warnings.warn(
                f'WARNING! {key} is not default parameter.\n'
                f'{key} was transferred to model_kwargs.\n'
                f'Please confirm that {key} is what you intended.',
                stacklevel=2,
            )
            model_kwargs[key] = value
    return ChatAnthropic(model_kwargs=model_kwargs, **settings)


class ChatAnthropic(ChatModel):
    """Claude models through the Anthropic Messages API."""

    _gen_ai_provider = 'anthropic'

    def __init__(
        self,
        model: str,
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_k: int | None = None,
        top_p: float | None = None,
        default_request_timeout: float | None = None,
        max_retries: int = 2,
        stop_sequences: list[str] | None = None,
        anthropic_api_url: str | None = None,
        anthropic_api_key: str | None = None,
        anthropic_proxy: str | None = None,
        default_headers: Mapping[str, str] | None = None,
        betas: list[str] | None = None,
        model_kwargs: dict[str, Any] | None = None,
        stream_usage: bool = True,
        thinking: dict[str, Any] | None = None,
        output_config: dict[str, Any] | None = None,
        reasoning_effort: str | None = None,
        mcp_servers: list[dict[str, Any]] | None = None,
        context_management: dict[str, Any] | None = None,
        container: dict[str, Any] | str | None = None,
        reuse_last_container: bool | None = None,
        inference_geo: str | None = None,
        user_profile_id: str | None = None,
    ):
        self.model = model
        profile = _MODEL_PROFILES.get(model)
        if max_tokens is None:
            max_tokens = profile[0] if profile else _FALLBACK_MAX_OUTPUT_TOKENS
        self.max_tokens = max_tokens
        self.supports_xhigh = bool(profile and profile[1])
        self.temperature = temperature
        self.top_k = top_k
        self.top_p = top_p
        self.default_request_timeout = default_request_timeout
        self.max_retries = max_retries
        self.stop_sequences = stop_sequences
        self.anthropic_api_url = (
            anthropic_api_url
            or _first_env('ANTHROPIC_API_URL', 'ANTHROPIC_BASE_URL')
            or _DEFAULT_BASE_URL
        )
        if anthropic_api_key is None:
            anthropic_api_key = os.getenv('ANTHROPIC_API_KEY') or ''
        self.anthropic_api_key = anthropic_api_key
        self.anthropic_proxy = (
            anthropic_proxy
            if anthropic_proxy is not None
            else os.getenv('ANTHROPIC_PROXY')
        )
        self.default_headers = default_headers
        self.betas = betas
        self.model_kwargs = model_kwargs or {}
        self.stream_usage = stream_usage
        self.thinking = thinking
        self.output_config = output_config
        self.reasoning_effort = reasoning_effort
        self.mcp_servers = mcp_servers
        self.context_management = context_management
        self.container = container
        self.reuse_last_container = reuse_last_container
        self.inference_geo = inference_geo
        self.user_profile_id = user_profile_id
        self._bound: dict[str, Any] = {}
        self._client: anthropic.AsyncAnthropic | None = None

    # ── client ──────────────────────────────────────────────────────────────

    @property
    def client(self) -> anthropic.AsyncAnthropic:
        """The SDK client, built on first use like the integration did."""
        if self._client is None:
            params: dict[str, Any] = {
                'api_key': self.anthropic_api_key,
                'base_url': self.anthropic_api_url,
                'max_retries': self.max_retries,
                'default_headers': dict(self.default_headers or {}),
            }
            http_params: dict[str, Any] = {'base_url': self.anthropic_api_url}
            # A timeout <= 0 means "SDK default"; None means no timeout at all.
            if self.default_request_timeout is None or self.default_request_timeout > 0:
                params['timeout'] = self.default_request_timeout
                http_params['timeout'] = self.default_request_timeout
            if self.anthropic_proxy:
                http_params['proxy'] = self.anthropic_proxy
            params['http_client'] = _default_http_client(**http_params)
            self._client = anthropic.AsyncAnthropic(**params)
        return self._client

    # ── tools and structured output ─────────────────────────────────────────

    def bind_tools(self, tools: list[dict], tool_choice: Any = None) -> 'ChatAnthropic':
        formatted = [
            tool if _is_builtin_tool(tool) else _convert_tool(tool) for tool in tools
        ]
        formatted, dropped = _drop_unsupported_root_composition_tools(formatted)
        if tools and not formatted:
            raise ValueError(
                f'All {len(tools)} bound tool(s) use a top-level '
                f'{"/".join(_TOP_LEVEL_COMPOSITION_KEYS)} in their input_schema, '
                f'which the Anthropic API rejects: {sorted(dropped)}.'
            )
        bound: dict[str, Any] = {}
        if tool_choice and dropped:
            self._check_dropped_tool_choice(tool_choice, dropped)
        if not tool_choice:
            pass
        elif isinstance(tool_choice, dict):
            bound['tool_choice'] = tool_choice.copy()
        elif isinstance(tool_choice, str) and tool_choice in ('any', 'auto'):
            bound['tool_choice'] = {'type': tool_choice}
        elif isinstance(tool_choice, str):
            # Any other string names a tool, including OpenAI's 'required' and
            # 'none'.
            bound['tool_choice'] = {'type': 'tool', 'name': tool_choice}
        else:
            raise ValueError(
                f"Unrecognized 'tool_choice' type {tool_choice=}. Expected dict, "
                f'str, or None.'
            )
        # The API rejects forced tool use while thinking is enabled.
        if (
            self._thinking_enabled()
            and 'tool_choice' in bound
            and bound['tool_choice'].get('type') in ('any', 'tool')
        ):
            warnings.warn(
                'tool_choice is forced but thinking is enabled. The Anthropic '
                'API does not support forced tool use with thinking. '
                'Dropping tool_choice to avoid an API error.',
                stacklevel=2,
            )
            del bound['tool_choice']
        return self._bind(tools=formatted, **bound)

    def _check_dropped_tool_choice(self, tool_choice: Any, dropped: set[str]) -> None:
        choice_type = choice_name = None
        if isinstance(tool_choice, dict):
            choice_type = tool_choice.get('type')
            choice_name = tool_choice.get('name')
        elif isinstance(tool_choice, str):
            if tool_choice in ('any', 'auto'):
                choice_type = tool_choice
            else:
                choice_type, choice_name = 'tool', tool_choice
        if self._thinking_enabled() and choice_type in ('any', 'tool'):
            return
        if choice_type == 'tool' and choice_name in dropped:
            raise ValueError(
                f'tool_choice forces {choice_name!r}, but that tool was dropped '
                'because its input_schema uses a top-level '
                f'{"/".join(_TOP_LEVEL_COMPOSITION_KEYS)}, which the Anthropic '
                'API rejects.'
            )
        if choice_type == 'any':
            raise ValueError(
                "tool_choice='any' forces the model to call a tool, but "
                f'{sorted(dropped)} were dropped because their input_schema uses '
                f'a top-level {"/".join(_TOP_LEVEL_COMPOSITION_KEYS)}, which the '
                'Anthropic API rejects.'
            )

    def _bind(self, **kwargs: Any) -> 'ChatAnthropic':
        bound = copy.copy(self)
        bound._bound = {**self._bound, **kwargs}
        return bound

    def _thinking_enabled(self) -> bool:
        return self.thinking is not None and self.thinking.get('type') in (
            'enabled',
            'adaptive',
        )

    def with_structured_output(
        self, schema: type[BaseModel], include_raw: bool = False
    ) -> StructuredChatModel:
        """Force a tool named after ``schema`` and parse its call into it."""
        tool = _convert_tool(schema)
        if self._thinking_enabled():
            # Forcing a tool is rejected with thinking: offer it and require it.
            warnings.warn(_THINKING_ADMONITION, stacklevel=2)
            model = self.bind_tools([schema])
            return _StructuredAnthropic(model, schema, include_raw, require_tool=True)
        model = self.bind_tools([schema], tool_choice=tool['name'])
        return _StructuredAnthropic(model, schema, include_raw, require_tool=False)

    # ── tracing ─────────────────────────────────────────────────────────────

    def _invocation_params(self, stop: list[str] | None = None, **kwargs: Any) -> dict:
        return {
            'model': self.model,
            'max_tokens': self.max_tokens,
            'temperature': self.temperature,
            'top_k': self.top_k,
            'top_p': self.top_p,
            'stop': stop,
            **self._bound,
            **kwargs,
        }

    def _llm_output(self, message: AIMessage) -> dict | None:
        metadata = message.response_metadata
        return {
            'model_name': metadata.get('model_name'),
            'id': metadata.get('id'),
            'usage': metadata.get('usage'),
        }

    # ── invocation ──────────────────────────────────────────────────────────

    async def _agenerate(self, messages: list[BaseMessage], **kwargs: Any) -> AIMessage:
        stop = kwargs.pop('stop', None)
        payload = self._request_payload(messages, stop=stop, **kwargs)
        data = await (await self._create(payload)).parse()
        return _format_output(data)

    async def _astream(
        self, messages: list[BaseMessage], **kwargs: Any
    ) -> AsyncIterator[AIMessageChunk]:
        stop = kwargs.pop('stop', None)
        stream_usage = kwargs.pop('stream_usage', None)
        if stream_usage is None:
            stream_usage = self.stream_usage
        kwargs['stream'] = True
        payload = self._request_payload(messages, stop=stop, **kwargs)
        stream = await (await self._create(payload)).parse()
        block_start = None
        async for event in stream:
            chunk, block_start = _chunk_from_event(
                event, stream_usage=stream_usage, block_start=block_start
            )
            if chunk is not None:
                yield chunk

    async def _create(self, payload: dict[str, Any]) -> Any:
        client = self.client
        messages_api = client.beta.messages if 'betas' in payload else client.messages
        try:
            return await messages_api.with_raw_response.create(**payload)
        except TypeError as e:
            if 'Could not resolve authentication method' in str(e):
                raise TypeError(
                    'Anthropic authentication failed: no API key or authorization '
                    'credentials were provided. Set the ANTHROPIC_API_KEY '
                    'environment variable or configure an api_key credential.'
                ) from e
            raise

    # ── request payload ─────────────────────────────────────────────────────

    def _request_payload(
        self,
        messages: Sequence[BaseMessage],
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        kwargs = {**self._bound, **kwargs}
        self._validate_configuration(kwargs)
        system, formatted_messages = _format_messages(messages)
        payload: dict[str, Any] = {
            'model': self.model,
            'max_tokens': self.max_tokens,
            'messages': formatted_messages,
            'temperature': self.temperature,
            'top_k': self.top_k,
            'top_p': self.top_p,
            'stop_sequences': stop or self.stop_sequences,
            'betas': self.betas,
            'context_management': self.context_management,
            'mcp_servers': self.mcp_servers,
            'container': self.container,
            'user_profile_id': self.user_profile_id,
            'system': system,
            **self.model_kwargs,
            **kwargs,
        }
        # A call-time `thinking` counts as explicitly set too.
        thinking_explicitly_set = 'thinking' in payload or self.thinking is not None
        if self.thinking is not None:
            payload['thinking'] = self.thinking
        if self.inference_geo is not None:
            payload['inference_geo'] = self.inference_geo
        if self.model.startswith('claude-fable-5'):
            for key in _SAMPLING_PARAMS:
                payload.pop(key, None)

        self._apply_output_config(payload, thinking_explicitly_set)
        self._apply_container(payload, messages)
        _apply_required_betas(payload)
        return _route_unsupported_sampling_params(
            {k: v for k, v in payload.items() if v is not None}
        )

    def _apply_output_config(
        self, payload: dict[str, Any], thinking_explicitly_set: bool
    ) -> None:
        # Priority: call-time effort/reasoning_effort > call-time output_config
        # > configured reasoning_effort > configured output_config.
        output_config: dict[str, Any] = dict(self.output_config or {})
        effort_applied = False
        if self.reasoning_effort:
            output_config['effort'] = self.reasoning_effort
            effort_applied = True
        if isinstance(payload_config := payload.get('output_config'), dict):
            output_config.update(payload_config)
        # Neither is an API field.
        effort = payload.pop('effort', None)
        reasoning_effort = payload.pop('reasoning_effort', None)
        effort = effort if effort is not None else reasoning_effort
        if effort:
            output_config['effort'] = effort
            effort_applied = True
        if output_config:
            payload['output_config'] = output_config
        # Only models accepting `xhigh` take the adaptive+summarized shape.
        if effort_applied and not thinking_explicitly_set and self.supports_xhigh:
            payload['thinking'] = {'type': 'adaptive', 'display': 'summarized'}

        if 'response_format' in payload:
            response_format = payload.pop('response_format')
            if (
                isinstance(response_format, dict)
                and response_format.get('type') == 'json_schema'
                and 'schema' in response_format.get('json_schema', {})
            ):
                response_format = response_format['json_schema']['schema']
            payload.setdefault('output_config', {})['format'] = {
                'type': 'json_schema',
                'schema': anthropic.transform_schema(response_format),
            }
        if 'output_format' in payload:
            payload.setdefault('output_config', {})['format'] = payload.pop(
                'output_format'
            )

    def _apply_container(
        self, payload: dict[str, Any], messages: Sequence[BaseMessage]
    ) -> None:
        container = payload.get('container')
        if not self.reuse_last_container or _container_id(container):
            return
        # Reuse the container of the most recent reply (code execution).
        for message in reversed(messages):
            if (
                isinstance(message, AIMessage)
                and isinstance(last := message.response_metadata.get('container'), dict)
                and (container_id := last.get('id'))
            ):
                payload['container'] = (
                    {**container, 'id': container_id}
                    if isinstance(container, dict)
                    else container_id
                )
                return

    def _validate_configuration(self, kwargs: Mapping[str, Any]) -> None:
        """Reject settings the target model is known not to accept."""
        config = {**self.model_kwargs, **kwargs}
        thinking = (
            self.thinking if self.thinking is not None else config.get('thinking')
        )
        output_config = dict(self.output_config or {})
        if self.reasoning_effort:
            output_config['effort'] = self.reasoning_effort
        if isinstance(config.get('output_config'), dict):
            output_config.update(config['output_config'])
        effort = config.get('effort')
        if effort is None:
            effort = config.get('reasoning_effort')
        if effort:
            output_config['effort'] = effort
        thinking_type = thinking.get('type') if isinstance(thinking, Mapping) else None

        is_fable = self.model.startswith('claude-fable-5')
        if is_fable:
            if config.get('top_k', self.top_k) is not None:
                raise ValueError(f'`top_k` is not supported for {self.model}.')
            if config.get('top_p', self.top_p) not in (None, 1):
                raise ValueError(
                    f'`top_p` is not supported for {self.model} at non-default values.'
                )
            if config.get('temperature', self.temperature) not in (None, 1):
                raise ValueError(
                    f'`temperature` is not supported for {self.model} at '
                    'non-default values.'
                )
            if thinking_type == 'disabled':
                raise ValueError(
                    '`thinking={"type": "disabled"}` is not supported for '
                    f'{self.model}; omit `thinking` to use adaptive thinking.'
                )
        if (
            self.model.startswith('claude-opus-5') or is_fable
        ) and thinking_type == 'enabled':
            raise ValueError(
                '`thinking={"type": "enabled", "budget_tokens": ...}` is not '
                f'supported for {self.model}; use adaptive thinking and '
                '`output_config.effort` instead.'
            )
        if (
            self.model.startswith('claude-opus-5')
            and thinking_type == 'disabled'
            and output_config.get('effort') in {'xhigh', 'max'}
        ):
            raise ValueError(
                '`thinking={"type": "disabled"}` is not supported for '
                f'{self.model} with '
                f'`output_config.effort={output_config["effort"]!r}`; use adaptive '
                'thinking, omit `thinking`, or set effort to `high` or below.'
            )


class _StructuredAnthropic(StructuredChatModel):
    def __init__(
        self,
        model: ChatAnthropic,
        schema: type[BaseModel],
        include_raw: bool,
        require_tool: bool,
    ):
        self.model = model
        self.schema = schema
        self.include_raw = include_raw
        self.require_tool = require_tool

    async def ainvoke(self, input: Sequence[BaseMessage], **kwargs: Any) -> Any:  # noqa: A002
        raw = await self.model.ainvoke(input, **kwargs)
        if self.require_tool and not raw.tool_calls:
            raise OutputParserError(_THINKING_ADMONITION)
        if not self.include_raw:
            return _parse_tool_call(raw, self.schema)
        try:
            parsed = _parse_tool_call(raw, self.schema)
        except Exception as e:
            return {'raw': raw, 'parsed': None, 'parsing_error': e}
        return {'raw': raw, 'parsed': parsed, 'parsing_error': None}


def _parse_tool_call(message: AIMessage, schema: type[BaseModel]) -> BaseModel | None:
    """Parse the first tool call of ``message`` into ``schema``."""
    if not message.tool_calls:
        return None
    first = message.tool_calls[0]
    args = first['args']
    if not isinstance(args, dict):
        raise ValueError(  # noqa: TRY004
            f'Tool arguments must be specified as a dict, received: {args}'
        )
    name = schema.model_config.get('title') or schema.__name__
    if first['name'] != name:
        raise OutputParserError(
            f'Unknown tool type: {first["name"]!r}. Available tools: {name}'
        )
    try:
        return schema(**args)
    except ValueError:
        if message.response_metadata.get('stop_reason') == 'max_tokens':
            logger.exception(_MAX_TOKENS_ERROR)
        raise


# ── HTTP client ─────────────────────────────────────────────────────────────

_NOT_GIVEN: Any = object()


@lru_cache
def _default_http_client(
    *,
    base_url: str | None,
    timeout: Any = _NOT_GIVEN,
    proxy: str | None = None,
) -> anthropic.DefaultAsyncHttpxClient:
    """One shared connection pool per base URL, timeout and proxy."""
    kwargs: dict[str, Any] = {
        'base_url': base_url or os.getenv('ANTHROPIC_BASE_URL') or _DEFAULT_BASE_URL
    }
    if timeout is not _NOT_GIVEN:
        kwargs['timeout'] = timeout
    if proxy is not None:
        kwargs['proxy'] = proxy
    return anthropic.DefaultAsyncHttpxClient(**kwargs)


def _first_env(*names: str) -> str | None:
    for name in names:
        if value := os.getenv(name):
            return value
    return None


# ── payload helpers ─────────────────────────────────────────────────────────


@cache
def _unsupported_sampling_params() -> frozenset[str]:
    """Return the sampling params the installed SDK's ``create`` rejects."""
    accepted = inspect.signature(
        anthropic.resources.messages.Messages.create
    ).parameters
    return frozenset(p for p in _SAMPLING_PARAMS if p not in accepted)


def _route_unsupported_sampling_params(payload: dict[str, Any]) -> dict[str, Any]:
    """Move sampling params the SDK rejects as arguments into ``extra_body``.

    The API still honours them; values already in ``extra_body`` win.
    """
    extra_body = payload.get('extra_body')
    if extra_body is not None and not isinstance(extra_body, Mapping):
        return payload
    relocated = {
        k: payload.pop(k) for k in _unsupported_sampling_params() if k in payload
    }
    if relocated:
        payload['extra_body'] = {**relocated, **(extra_body or {})}
    return payload


def _add_beta(payload: dict[str, Any], beta: str) -> None:
    if payload.get('betas'):
        if beta not in payload['betas']:
            payload['betas'] = [*payload['betas'], beta]
    else:
        payload['betas'] = [beta]


def _apply_required_betas(payload: dict[str, Any]) -> None:
    """Add the beta headers some tools and settings require."""
    if isinstance(payload.get('tools'), list):
        has_input_examples = False
        for tool in payload['tools']:
            if isinstance(tool, dict):
                if (tool_type := tool.get('type')) in _TOOL_TYPE_TO_BETA:
                    _add_beta(payload, _TOOL_TYPE_TO_BETA[tool_type])
                if tool.get('input_examples'):
                    has_input_examples = True
        if has_input_examples:
            _add_beta(payload, 'advanced-tool-use-2025-11-20')
    if payload.get('mcp_servers'):
        _add_beta(payload, 'mcp-client-2025-11-20')
    output_config = payload.get('output_config')
    if isinstance(output_config, dict) and output_config.get('task_budget'):
        _add_beta(payload, 'task-budgets-2026-03-13')
    thinking = payload.get('thinking')
    if isinstance(thinking, dict) and thinking.get('display') == 'updates':
        _add_beta(payload, 'thinking-display-updates-2026-08-18')
    if payload.get('user_profile_id'):
        _add_beta(payload, 'user-profiles-2026-03-24')


def _container_id(container: Any) -> str | None:
    if isinstance(container, str):
        return container
    if isinstance(container, dict):
        return container.get('id')
    return None


# ── tools ───────────────────────────────────────────────────────────────────


def _is_builtin_tool(tool: Any) -> bool:
    """Whether ``tool`` is a server-side Anthropic tool, sent as is."""
    if not isinstance(tool, dict):
        return False
    tool_type = tool.get('type')
    return isinstance(tool_type, str) and tool_type.startswith(_BUILTIN_TOOL_PREFIXES)


def _convert_tool(tool: Mapping[str, Any] | type[BaseModel]) -> dict[str, Any]:
    """Convert an OpenAI-format tool (or a pydantic model) to Anthropic format."""
    if isinstance(tool, dict) and all(
        k in tool for k in ('name', 'description', 'input_schema')
    ):
        return dict(tool)
    function = _openai_function(tool)
    formatted = {'name': function['name'], 'input_schema': function['parameters']}
    if 'description' in function:
        formatted['description'] = function['description']
    return formatted


def _openai_function(tool: Mapping[str, Any] | type[BaseModel]) -> dict[str, Any]:
    if isinstance(tool, dict):
        tool_type = tool.get('type') or ''
        if tool_type in _OPENAI_TOOL_TYPES or tool_type.startswith(
            'web_search_preview'
        ):
            return tool['function']
        if 'name' in tool and 'input_schema' in tool:
            function = {'name': tool['name'], 'parameters': tool['input_schema']}
            if 'description' in tool:
                function['description'] = tool['description']
            return function
        if 'toolSpec' in tool:
            spec = tool['toolSpec']
            function = {'name': spec['name'], 'parameters': spec['inputSchema']['json']}
            if 'description' in spec:
                function['description'] = spec['description']
            return function
        if 'name' in tool:
            return {
                k: v
                for k, v in tool.items()
                if k in {'name', 'description', 'parameters', 'strict'}
            }
        if 'title' in tool:
            rest = dict(tool)
            function = {'name': rest.pop('title')}
            if 'description' in rest:
                function['description'] = rest.pop('description')
            if rest and 'properties' in rest:
                function['parameters'] = rest
            return function
        raise ValueError(f'Unsupported function\n\n{tool}')
    if isinstance(tool, type) and issubclass(tool, BaseModel):
        schema = _dereference(tool.model_json_schema())
        schema.pop('$defs', None)
        name = schema.pop('title', '')
        description = schema.pop('description', '')
        return {
            'name': name,
            'description': description,
            'parameters': _rm_titles(schema),
        }
    raise ValueError(f'Unsupported function\n\n{tool}')


def _dereference(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline the local ``$ref``s of a JSON schema."""

    def resolve(node: Any, seen: tuple[str, ...]) -> Any:
        if isinstance(node, list):
            return [resolve(item, seen) for item in node]
        if not isinstance(node, dict):
            return node
        ref = node.get('$ref')
        if isinstance(ref, str) and ref.startswith('#/') and ref not in seen:
            target: Any = schema
            for part in ref[2:].split('/'):
                target = target[part]
            siblings = {k: v for k, v in node.items() if k != '$ref'}
            return {**resolve(target, (*seen, ref)), **resolve(siblings, seen)}
        return {k: resolve(v, seen) for k, v in node.items()}

    return resolve(copy.deepcopy(schema), ())


def _rm_titles(kv: dict[str, Any], prev_key: str = '') -> dict[str, Any]:
    """Drop JSON-schema ``title``s, keeping properties that are named title."""
    new_kv = {}
    for k, v in kv.items():
        if k == 'title':
            if isinstance(v, dict) and prev_key == 'properties':
                new_kv[k] = _rm_titles(v, k)
        elif isinstance(v, dict):
            new_kv[k] = _rm_titles(v, k)
        else:
            new_kv[k] = v
    return new_kv


def _drop_unsupported_root_composition_tools(
    tools: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], set[str]]:
    """Drop tools whose input_schema has a top-level oneOf/anyOf (rejected)."""
    kept: list[dict[str, Any]] = []
    dropped: set[str] = set()
    for tool in tools:
        input_schema = tool.get('input_schema')
        offending = (
            [k for k in _TOP_LEVEL_COMPOSITION_KEYS if k in input_schema]
            if isinstance(input_schema, Mapping)
            else []
        )
        if not offending:
            kept.append(tool)
            continue
        name = tool.get('name')
        if isinstance(name, str):
            dropped.add(name)
        described = repr(name) if isinstance(name, str) else 'with no name'
        warnings.warn(
            f'Dropping tool {described}: its input_schema has a top-level '
            f'{"/".join(offending)}, which the Anthropic API does not support.',
            stacklevel=3,
        )
    return kept, dropped


# ── messages ────────────────────────────────────────────────────────────────


def _normalize_tool_call_id(tool_call_id: str | None) -> str | None:
    """Map an id other providers minted to one Anthropic accepts, deterministically."""
    if not tool_call_id or _TOOL_CALL_ID_PATTERN.match(tool_call_id):
        return tool_call_id
    digest = hashlib.sha256(tool_call_id.encode()).hexdigest()
    return f'toolu_{digest[:24]}'


def _normalize_block_tool_use_id(block: dict) -> dict:
    if 'tool_use_id' in block:
        return {**block, 'tool_use_id': _normalize_tool_call_id(block['tool_use_id'])}
    return block


def _tool_use_blocks(tool_calls: list[ToolCall]) -> list[dict[str, Any]]:
    return [
        {
            'type': 'tool_use',
            'name': tc['name'],
            'input': tc['args'],
            'id': _normalize_tool_call_id(tc['id']),
        }
        for tc in tool_calls
    ]


def _merge_messages(messages: Sequence[BaseMessage]) -> list[BaseMessage]:
    """Turn tool results into user messages and merge runs of user/system ones."""
    merged: list[BaseMessage] = []
    for curr in messages:
        if isinstance(curr, ToolMessage):
            curr = HumanMessage(_tool_result_content(curr))
        last = merged[-1] if merged else None
        if last is not None and any(
            isinstance(curr, c) and isinstance(last, c)
            for c in (SystemMessage, HumanMessage)
        ):
            if isinstance(last.content, str):
                new_content: list = [{'type': 'text', 'text': last.content}]
            else:
                new_content = copy.copy(last.content)
            if isinstance(curr.content, str):
                new_content.append({'type': 'text', 'text': curr.content})
            else:
                new_content.extend(curr.content)
            merged[-1] = curr.model_copy(update={'content': new_content})
        else:
            merged.append(curr)
    return merged


def _tool_result_content(message: ToolMessage) -> list:
    content = message.content
    if (
        isinstance(content, list)
        and content
        and all(
            isinstance(block, dict) and block.get('type') == 'tool_result'
            for block in content
        )
    ):
        return content
    cache_control = None
    if isinstance(content, list):
        # cache_control is only accepted on the tool_result itself.
        cleaned = []
        for block in content:
            if isinstance(block, dict) and 'cache_control' in block:
                cache_control = block['cache_control']
                block = {k: v for k, v in block.items() if k != 'cache_control'}
            cleaned.append(block)
        content = cleaned
    tool_result: dict[str, Any] = {
        'type': 'tool_result',
        'content': content,
        'tool_use_id': _normalize_tool_call_id(message.tool_call_id),
        'is_error': message.status == 'error',
    }
    if cache_control:
        tool_result['cache_control'] = cache_control
    return [tool_result]


def _format_messages(
    messages: Sequence[BaseMessage],
) -> tuple[str | list[dict] | None, list[dict]]:
    """Split ``messages`` into Anthropic's system prompt and message list."""
    system: str | list[dict] | None = None
    formatted: list[dict] = []
    merged = _merge_messages(messages)
    for i, message in enumerate(merged):
        if message.type == 'system':
            if system is not None:
                raise ValueError('Received multiple non-consecutive system messages.')
            if isinstance(message.content, list):
                system = [
                    (
                        _format_text_block(block)
                        if block.get('type') == 'text'
                        else block
                    )
                    if isinstance(block, dict)
                    else {'type': 'text', 'text': block}
                    for block in message.content
                ]
            else:
                system = message.content
            continue

        role = _ROLES[message.type]
        content: str | list
        if isinstance(message.content, str):
            content = message.content
        elif isinstance(message.content, list):
            content = []
            for block in message.content:
                content.extend(_format_block(block, message))
        else:
            raise ValueError(  # noqa: TRY004
                'Anthropic message content must be str or list of dicts'
            )

        # Every tool call needs a tool_use block.
        if isinstance(message, AIMessage) and message.tool_calls:
            content = content or []
            if isinstance(content, str):
                content = [{'type': 'text', 'text': content}]
            tool_use_ids = [b['id'] for b in content if b['type'] == 'tool_use']
            content.extend(
                _tool_use_blocks(
                    [
                        tc
                        for tc in message.tool_calls
                        if _normalize_tool_call_id(tc['id']) not in tool_use_ids
                    ]
                )
            )

        is_last = i == len(merged) - 1
        if role == 'assistant' and is_last:
            if isinstance(content, str):
                content = content.rstrip()
            elif (
                content
                and isinstance(content[-1], dict)
                and content[-1].get('type') == 'text'
            ):
                content[-1]['text'] = content[-1]['text'].rstrip()
        # Only the final assistant message may be empty.
        if not content and role == 'assistant' and not is_last:
            continue
        formatted.append({'role': role, 'content': content})
    return system, formatted


def _format_block(block: Any, message: BaseMessage) -> list[dict]:
    """Format one content block of a user or assistant message."""
    if isinstance(block, str):
        return [{'type': 'text', 'text': block}]
    if not isinstance(block, dict):
        raise ValueError(  # noqa: TRY004
            f'Content blocks must be str or dict, instead was: {type(block)}'
        )
    if 'type' not in block:
        raise ValueError('Dict content block must have a type key')
    block_type = block['type']
    if block_type in ('reasoning', 'function_call') and (
        not isinstance(message, AIMessage)
        or message.response_metadata.get('model_provider') != 'anthropic'
    ):
        return []
    if block_type == 'image_url':
        return [{'type': 'image', 'source': _format_image(block['image_url']['url'])}]
    if _is_data_content_block(block):
        return [_format_data_content_block(block)]
    if block_type == 'tool_use':
        return [_format_tool_use(block, message)]
    if block_type in ('server_tool_use', 'mcp_tool_use'):
        formatted = {
            k: v for k, v in block.items() if k in _FILTERED_BLOCK_FIELDS[block_type]
        }
        # Streamed blocks carry their input as partial JSON.
        if block.get('input') == {} and 'partial_json' in block:
            try:
                if parsed := json.loads(block['partial_json']):
                    formatted['input'] = parsed
            except json.JSONDecodeError:
                pass
        return [formatted]
    if block_type == 'text':
        # Empty text blocks are rejected.
        return [_format_text_block(block)] if block.get('text', '').strip() else []
    if block_type == 'thinking':
        formatted = {
            k: v
            for k, v in block.items()
            if k in ('type', 'thinking', 'cache_control', 'signature')
        }
        if 'signature' in formatted:
            formatted.setdefault('thinking', '')
        return [formatted]
    if block_type == 'redacted_thinking':
        return [
            {k: v for k, v in block.items() if k in _FILTERED_BLOCK_FIELDS[block_type]}
        ]
    if block_type == 'tool_search_tool_result' or (
        block_type == 'tool_result'
        and isinstance(block.get('content'), list)
        and any(
            isinstance(item, dict) and item.get('type') == 'tool_reference'
            for item in block['content']
        )
    ):
        return [
            _normalize_block_tool_use_id(
                {k: v for k, v in block.items() if k in _TOOL_RESULT_FIELDS}
            )
        ]
    if block_type == 'tool_result':
        tool_content = _format_messages([HumanMessage(block['content'])])[1][0][
            'content'
        ]
        return [_normalize_block_tool_use_id({**block, 'content': tool_content})]
    if block_type in _SERVER_TOOL_RESULT_TYPES:
        return [
            _normalize_block_tool_use_id(
                {k: v for k, v in block.items() if k in _SERVER_TOOL_RESULT_FIELDS}
            )
        ]
    return [block]


def _format_tool_use(block: dict, message: BaseMessage) -> dict:
    # A tool call with the same id is preferred over the block.
    if (
        isinstance(message, AIMessage)
        and block['id'] in [tc['id'] for tc in message.tool_calls]
        and not block.get('caller')
    ):
        overlapping = [tc for tc in message.tool_calls if tc['id'] == block['id']]
        return _tool_use_blocks(overlapping)[0]
    if tool_input := block.get('input'):
        args = tool_input
    elif 'partial_json' in block:
        try:
            args = json.loads(block['partial_json'] or '{}')
        except json.JSONDecodeError:
            args = {}
    else:
        args = {}
    tool_use = {
        'type': 'tool_use',
        'name': block['name'],
        'input': args,
        'id': _normalize_tool_call_id(block['id']),
    }
    if caller := block.get('caller'):
        tool_use['caller'] = caller
    return tool_use


def _format_text_block(block: dict) -> dict:
    """Keep only the text-block fields the API accepts."""
    formatted = {
        k: v
        for k, v in block.items()
        if k in ('type', 'text', 'cache_control', 'citations')
    }
    if formatted.get('citations'):
        formatted['citations'] = [
            {k: v for k, v in citation.items() if not (k == 'file_id' and v is None)}
            for citation in formatted['citations']
        ]
    return formatted


def _format_image(url: str) -> dict:
    """Convert an OpenAI image URL (http or data URI) to an Anthropic source."""
    if match := re.match(r'^data:(?P<media_type>image/.+);base64,(?P<data>.+)$', url):
        return {
            'type': 'base64',
            'media_type': match.group('media_type'),
            'data': match.group('data'),
        }
    if re.match(r'^https?://.*$', url):
        return {'type': 'url', 'url': url}
    raise ValueError(
        'Malformed url parameter.'
        ' Must be either an image URL (https://example.com/image.jpg)'
        " or base64 encoded string (data:image/png;base64,'/9j/4AAQSk'...)"
    )


def _is_data_content_block(block: dict) -> bool:
    """Whether ``block`` is a multimodal data block (image, file, ...)."""
    if block.get('type') not in _DATA_BLOCK_TYPES:
        return False
    if any(key in block for key in ('url', 'base64', 'file_id', 'text')):
        return True
    source_type = block.get('source_type')
    return (
        (source_type == 'url' and 'url' in block)
        or (source_type == 'base64' and 'data' in block)
        or (source_type == 'id' and 'id' in block)
        or (source_type == 'text' and 'url' in block)
    )


def _data_source(block: dict, default_mime: str | None) -> dict | None:
    if 'url' in block:
        return None
    if 'base64' in block or block.get('source_type') == 'base64':
        # Images require a mime type; documents default to PDF.
        media_type = (
            block['mime_type']
            if default_mime is None
            else block.get('mime_type') or default_mime
        )
        return {
            'type': 'base64',
            'media_type': media_type,
            'data': block.get('base64') or block.get('data', ''),
        }
    if 'file_id' in block:
        return {'type': 'file', 'file_id': block['file_id']}
    if block.get('source_type') == 'id':
        return {'type': 'file', 'file_id': block['id']}
    return None


def _format_data_content_block(block: dict) -> dict:
    """Format an image or file block as an Anthropic image or document block."""
    block_type = block['type']
    if block_type == 'image':
        if 'url' in block:
            source = (
                _format_image(block['url'])
                if block['url'].startswith('data:')
                else {'type': 'url', 'url': block['url']}
            )
        elif (source := _data_source(block, None)) is None:
            raise ValueError(
                "Anthropic only supports 'url', 'base64', or 'id' keys for image "
                'content blocks.'
            )
        formatted: dict[str, Any] = {'type': 'image', 'source': source}
    elif block_type == 'file':
        if 'url' in block:
            source = {'type': 'url', 'url': block['url']}
        elif 'base64' in block or block.get('source_type') == 'base64':
            source = _data_source(block, 'application/pdf')
        elif block.get('source_type') == 'text':
            source = {
                'type': 'text',
                'media_type': block.get('mime_type') or 'text/plain',
                'data': block['text'],
            }
        elif (source := _data_source(block, None)) is None:
            raise ValueError(
                "Anthropic only supports 'url', 'base64', or 'id' keys for file "
                'content blocks.'
            )
        formatted = {'type': 'document', 'source': source}
    elif block_type == 'text-plain':
        formatted = {
            'type': 'document',
            'source': {
                'type': 'text',
                'media_type': block.get('mime_type') or 'text/plain',
                'data': block['text'],
            },
        }
    else:
        raise ValueError(f'Block of type {block_type} is not supported.')

    for key in ('cache_control', 'citations', 'title', 'context'):
        if key in block:
            formatted[key] = block[key]
        elif (extras := block.get('extras')) and key in extras:
            formatted[key] = extras[key]
        elif (metadata := block.get('metadata')) and key in metadata:
            formatted[key] = metadata[key]
    return formatted


# ── replies ─────────────────────────────────────────────────────────────────


def _format_output(data: Any) -> AIMessage:
    """Build the reply message from an SDK ``Message``."""
    data_dict = data.model_dump()
    content = data_dict['content']
    for block in content:
        if isinstance(block, dict):
            for key in ('citations', 'caller', 'encrypted_content'):
                if key in block and block[key] is None:
                    block.pop(key)
            if block.get('type') == 'thinking' and block.get('text', 0) is None:
                block.pop('text')

    llm_output = {
        k: v for k, v in data_dict.items() if k not in ('content', 'role', 'type')
    }
    if isinstance(container := llm_output.get('container'), dict) and isinstance(
        expires_at := container.get('expires_at'), datetime.datetime
    ):
        container['expires_at'] = expires_at.isoformat()
    if 'model' in llm_output and 'model_name' not in llm_output:
        llm_output['model_name'] = llm_output['model']
    response_metadata = {**llm_output, 'model_provider': 'anthropic'}

    if (
        len(content) == 1
        and content[0]['type'] == 'text'
        and not content[0].get('citations')
    ):
        message = AIMessage(
            content=content[0]['text'], response_metadata=response_metadata
        )
    elif any(block['type'] == 'tool_use' for block in content):
        message = AIMessage(
            content=content,
            tool_calls=[
                tool_call(name=block['name'], args=block['input'], id=block['id'])
                for block in content
                if block['type'] == 'tool_use'
            ],
            response_metadata=response_metadata,
        )
    else:
        message = AIMessage(content=content, response_metadata=response_metadata)
    message.usage_metadata = _usage_metadata(data.usage)
    return message


def _chunk_from_event(
    event: Any, *, stream_usage: bool, block_start: Any
) -> tuple[AIMessageChunk | None, Any]:
    """Convert a stream event into a chunk (or None) and the open block's start.

    Content is always a string: text deltas carry their text, every other
    block contributes no content (tool use is reported as tool_call_chunks).
    """
    chunk: AIMessageChunk | None = None
    if event.type == 'message_start' and stream_usage:
        # Usage is reported once, complete, by message_delta.
        response_metadata = (
            {'model_name': event.message.model}
            if hasattr(event.message, 'model')
            else {}
        )
        chunk = AIMessageChunk(content='', response_metadata=response_metadata)
    elif event.type == 'content_block_start' and event.content_block is not None:
        block = event.content_block
        if any(
            kind in block.type
            for kind in ('tool_result', 'tool_use', 'document', 'redacted_thinking')
        ):
            chunks = []
            if block.type == 'tool_use':
                # Arguments may arrive whole on the start event.
                parsed_args = getattr(block, 'input', None)
                args = (
                    json.dumps(parsed_args)
                    if parsed_args and isinstance(parsed_args, dict)
                    else ''
                )
                chunks = [
                    tool_call_chunk(
                        index=event.index, id=block.id, name=block.name, args=args
                    )
                ]
            chunk = AIMessageChunk(content='', tool_call_chunks=chunks)
            block_start = event
        elif block.type in ('text', 'thinking'):
            # The opening text may sit on the start event itself.
            block_start = event
            if block.type == 'text':
                if text := getattr(block, 'text', '') or '':
                    chunk = AIMessageChunk(content=text)
            elif (getattr(block, 'thinking', '') or '') or (
                getattr(block, 'signature', '') or ''
            ):
                chunk = AIMessageChunk(content='')
    elif event.type == 'content_block_delta':
        delta_type = event.delta.type
        if delta_type == 'text_delta':
            chunk = AIMessageChunk(content=event.delta.text)
        elif delta_type == 'input_json_delta':
            start_block = getattr(block_start, 'content_block', None)
            chunks = []
            if getattr(start_block, 'type', None) == 'tool_use':
                chunks = [
                    tool_call_chunk(index=event.index, args=event.delta.partial_json)
                ]
            chunk = AIMessageChunk(content='', tool_call_chunks=chunks)
        elif delta_type in (
            'citations_delta',
            'thinking_delta',
            'signature_delta',
            'compaction_delta',
        ):
            chunk = AIMessageChunk(content='')
    elif event.type == 'message_delta' and stream_usage:
        response_metadata = {
            'stop_reason': event.delta.stop_reason,
            'stop_sequence': event.delta.stop_sequence,
        }
        if context_management := getattr(event, 'context_management', None):
            response_metadata['context_management'] = context_management.model_dump()
        if container := getattr(event.delta, 'container', None):
            response_metadata['container'] = container.model_dump(mode='json')
        chunk = AIMessageChunk(
            content='',
            usage_metadata=_usage_metadata(event.usage),
            response_metadata=response_metadata,
        )
        if response_metadata['stop_reason']:
            chunk.chunk_position = 'last'

    if chunk is not None:
        chunk.response_metadata['model_provider'] = 'anthropic'
    return chunk, block_start


def _usage_metadata(usage: Any) -> dict[str, Any]:
    """Usage in gateway terms: input_tokens includes cache reads and writes."""
    input_token_details: dict[str, Any] = {
        'cache_read': getattr(usage, 'cache_read_input_tokens', None),
        'cache_creation': getattr(usage, 'cache_creation_input_tokens', None),
    }
    cache_creation = getattr(usage, 'cache_creation', None)
    specific_cache_creation = 0
    if cache_creation:
        if isinstance(cache_creation, BaseModel):
            cache_creation = cache_creation.model_dump()
        for key in ('ephemeral_5m_input_tokens', 'ephemeral_1h_input_tokens'):
            specific_cache_creation += cache_creation.get(key, 0)
            input_token_details[key] = cache_creation.get(key)
        if not isinstance(specific_cache_creation, int):
            specific_cache_creation = 0
        if specific_cache_creation > 0:
            # The TTL breakdown replaces the total, so it is not counted twice.
            input_token_details['cache_creation'] = 0

    # Anthropic's input_tokens excludes the cached ones.
    input_tokens = (
        (getattr(usage, 'input_tokens', 0) or 0)
        + (input_token_details['cache_read'] or 0)
        + (specific_cache_creation or input_token_details['cache_creation'] or 0)
    )
    output_tokens = getattr(usage, 'output_tokens', 0) or 0
    usage_metadata: dict[str, Any] = {
        'input_tokens': input_tokens,
        'output_tokens': output_tokens,
        'total_tokens': input_tokens + output_tokens,
        'input_token_details': {
            k: v for k, v in input_token_details.items() if v is not None
        },
    }
    reasoning = getattr(
        getattr(usage, 'output_tokens_details', None), 'thinking_tokens', None
    )
    if reasoning is not None:
        usage_metadata['output_token_details'] = {'reasoning': reasoning}
    return usage_metadata
