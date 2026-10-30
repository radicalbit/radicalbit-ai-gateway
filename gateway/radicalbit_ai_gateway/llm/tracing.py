"""Telemetry of chat model calls.

Every ``ChatModel.ainvoke``/``astream`` call gets a CLIENT span named
``<model class>.chat``, a child of the current span, with ``gen_ai.*``
attributes, and records the ``gen_ai.client.operation.duration`` and
``gen_ai.client.token.usage`` histograms on the global meter provider (the
gateway exposes them on its Prometheus endpoint).

The spans and metrics are the ones Traceloop's LangChain instrumentation
emitted when the providers were LangChain integrations, attribute for
attribute, except that each model reports its own provider
(``ChatModel._gen_ai_provider``) and LangChain's own association properties
(``ls_*``, ``lc_versions``) are gone. What LangChain derived from its
internals the providers supply through the ``ChatModel`` hooks
``_invocation_params``, ``_serialized_kwargs``, ``_llm_output``,
``_generation_info`` and ``_error_type``. Some values keep LangChain's
quirks: a streamed reply is reported as LangChain merged it (role
``unknown``, the request model as response model), and the request params are
read first from the call and then from the model's constructor params, the
latter winning.

Traceloop itself must instrument nothing (``TRACELOOP_INSTRUMENTS``): model
calls are traced here, and the SDKs the providers use must not be traced twice.
"""

from collections.abc import Callable, Sequence
import contextlib
import dataclasses
import datetime
import functools
import json
import logging
import operator
import os
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from opentelemetry import context as context_api, metrics, trace
from opentelemetry.semconv._incubating.attributes import (
    gen_ai_attributes as GenAIAttributes,
)
from opentelemetry.semconv.attributes.error_attributes import ERROR_TYPE
from opentelemetry.semconv.attributes.server_attributes import (
    SERVER_ADDRESS,
    SERVER_PORT,
)
from opentelemetry.semconv_ai import Meters, SpanAttributes
from opentelemetry.trace import Span, SpanKind, Status, StatusCode
from pydantic import BaseModel
from traceloop.sdk.instruments import Instruments

from radicalbit_ai_gateway.llm.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    tool_call_chunk,
)
from radicalbit_ai_gateway.llm.providers._openai_common import (
    _image_block,
    is_data_content_block,
)

if TYPE_CHECKING:
    from radicalbit_ai_gateway.llm.chat_model import ChatModel

logger = logging.getLogger(__name__)

# Passed to ``Traceloop.init``: no instrumentation (``None`` would mean all).
TRACELOOP_INSTRUMENTS: frozenset[Instruments] = frozenset()

_tracer = trace.get_tracer(__name__)
_meter = metrics.get_meter(__name__)
_duration_histogram = _meter.create_histogram(
    name=Meters.LLM_OPERATION_DURATION,
    unit='s',
    description='GenAI operation duration',
)
_token_histogram = _meter.create_histogram(
    name=Meters.LLM_TOKEN_USAGE,
    unit='token',
    description='Measures number of input and output tokens used',
)

# Semantic convention attributes the installed package does not define yet.
_RESPONSE_TIME_TO_FIRST_CHUNK = 'gen_ai.response.time_to_first_chunk'
_REQUEST_PREVIOUS_RESPONSE_ID = 'gen_ai.request.previous_response.id'
_REQUEST_REASONING_LEVEL = 'gen_ai.request.reasoning.level'
_DEFAULT_PORTS = {'https': 443, 'http': 80}

_FINISH_REASONS = {
    'stop': 'stop',
    'length': 'length',
    'tool_calls': 'tool_call',
    'function_call': 'tool_call',
    'content_filter': 'content_filter',
    'end_turn': 'stop',
    'stop_sequence': 'stop',
    'tool_use': 'tool_call',
    'max_tokens': 'length',
}
_ROLES = {
    'human': 'user',
    'system': 'system',
    'ai': 'assistant',
    'tool': 'tool',
    'function': 'tool',
}


def _dont_throw(func: Callable) -> Callable:
    """Tracing never fails a model call: errors are logged and swallowed."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except Exception:
            logger.debug('Failed to trace %s', func.__name__, exc_info=True)
            return None

    return wrapper


def _should_send_prompts() -> bool:
    """Traceloop's content-tracing switch (``TRACELOOP_TRACE_CONTENT``)."""
    return (os.getenv('TRACELOOP_TRACE_CONTENT') or 'true').lower() == 'true' or bool(
        context_api.get_value('override_enable_content_tracing')
    )


class _JSONEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)  # type: ignore[arg-type]
        if hasattr(o, 'to_json'):
            return o.to_json()
        if isinstance(o, BaseModel):
            return o.model_dump()
        if isinstance(o, datetime.datetime):
            return o.isoformat()
        try:
            return str(o)
        except Exception:
            return ''


def _dumps(value: Any) -> str:
    return json.dumps(value, cls=_JSONEncoder)


def _set(span: Span, key: str, value: Any) -> None:
    if value is not None:
        span.set_attribute(key, value)


# ── Messages ─────────────────────────────────────────────────────────────────


def _format_for_tracing(message: BaseMessage) -> BaseMessage:
    """Return the message as LangChain handed it to tracing.

    Base64 data blocks become OpenAI image blocks and single-key blocks get a
    ``type``.
    """
    if not isinstance(message.content, list):
        return message
    content = list(message.content)
    for idx, block in enumerate(content):
        if not isinstance(block, dict):
            continue
        if (
            block.get('type') == 'image'
            and is_data_content_block(block)
            and not ('file_id' in block or block.get('source_type') == 'id')
        ):
            content[idx] = _image_block(block)
        elif (
            block.get('type') == 'file'
            and is_data_content_block(block)
            and 'base64' in block
        ):
            content[idx] = {
                **{k: v for k, v in block.items() if k != 'base64'},
                'data': block['base64'],
                'source_type': 'base64',
            }
        elif len(block) == 1 and 'type' not in block:
            key = next(iter(block))
            content[idx] = {'type': key, key: block[key]}
    if content == message.content:
        return message
    return message.model_copy(update={'content': content})


def _content_to_parts(content: Any) -> list[dict]:
    if isinstance(content, str):
        return [{'type': 'text', 'content': content}] if content else []
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                if block:
                    parts.append({'type': 'text', 'content': block})
            elif isinstance(block, dict):
                block_type = block.get('type', '')
                if block_type == 'text':
                    if text := block.get('text', ''):
                        parts.append({'type': 'text', 'content': text})
                elif block_type == 'image_url':
                    if url := (block.get('image_url') or {}).get('url', ''):
                        parts.append({'type': 'uri', 'modality': 'image', 'uri': url})
                elif block_type == 'image':
                    parts.append(
                        {
                            'type': 'blob',
                            'modality': 'image',
                            'mime_type': block.get(
                                'media_type', block.get('mime_type', '')
                            ),
                            'content': block.get('data', ''),
                        }
                    )
                else:
                    parts.append({'type': 'text', 'content': _dumps(block)})
            else:
                parts.append({'type': 'text', 'content': str(block)})
        return parts
    return [{'type': 'text', 'content': str(content)}] if content else []


def _tool_calls_to_parts(tool_calls: Sequence[Any]) -> list[dict]:
    parts = []
    for tc in tool_calls or []:
        tc_dict = dict(tc)
        function = tc_dict.get('function', {})
        args = tc_dict.get('args', function.get('arguments'))
        if isinstance(args, str):
            with contextlib.suppress(json.JSONDecodeError, TypeError):
                args = json.loads(args)
        part = {
            'type': 'tool_call',
            'id': tc_dict.get('id', ''),
            'name': tc_dict.get('name', function.get('name', '')),
        }
        if args is not None:
            part['arguments'] = args
        parts.append(part)
    return parts


def _input_attributes(messages: Sequence[BaseMessage]) -> dict[str, str]:
    input_messages = []
    system_instructions: list[dict] = []
    for message in map(_format_for_tracing, messages):
        role = _ROLES.get(message.type, 'unknown')
        if role == 'system':
            system_instructions.extend(_content_to_parts(message.content))
            continue
        if role == 'tool' and hasattr(message, 'tool_call_id'):
            content = message.content
            parts = [
                {
                    'type': 'tool_call_response',
                    'id': message.tool_call_id,
                    'response': content
                    if isinstance(content, str)
                    else _dumps(content),
                }
            ]
        else:
            parts = _content_to_parts(message.content)
            tool_calls = (
                message.tool_calls
                if hasattr(message, 'tool_calls')
                else message.additional_kwargs.get('tool_calls')
            )
            if tool_calls:
                parts.extend(_tool_calls_to_parts(tool_calls))
        input_messages.append({'role': role, 'parts': parts})
    attributes = {}
    if system_instructions:
        attributes[GenAIAttributes.GEN_AI_SYSTEM_INSTRUCTIONS] = _dumps(
            system_instructions
        )
    if input_messages:
        attributes[GenAIAttributes.GEN_AI_INPUT_MESSAGES] = _dumps(input_messages)
    return attributes


def _generation_text(message: AIMessage) -> str:
    """Return the ``text`` LangChain's ``ChatGeneration`` derived from the reply."""
    content = message.content
    if isinstance(content, str):
        return content
    if any(
        isinstance(b, dict) and 'text' in b and b.get('type') is None for b in content
    ):
        # Legacy blocks: a ``text`` key without a ``type``.
        return ''.join(
            b if isinstance(b, str) else b.get('text', '')
            for b in content
            if isinstance(b, str)
            or (
                isinstance(b, dict)
                and (b.get('type') == 'text' or (b.get('type') is None and 'text' in b))
            )
        )
    return message.text


# ── Stream merging (LangChain's AIMessageChunk addition) ─────────────────────


def _merge_dicts(left: dict[str, Any], *others: dict[str, Any]) -> dict[str, Any]:
    merged = left.copy()
    for right in others:
        for key, value in right.items():
            if key not in merged or (value is not None and merged[key] is None):
                merged[key] = value
            elif value is None:
                continue
            elif type(merged[key]) is not type(value):
                raise TypeError(f'Cannot merge {key!r}: different types')
            elif isinstance(merged[key], str):
                if (key == 'index' and merged[key].startswith('lc_')) or (
                    key in {'id', 'output_version', 'model_provider'}
                    and merged[key] == value
                ):
                    continue
                merged[key] += value
            elif isinstance(merged[key], dict):
                merged[key] = _merge_dicts(merged[key], value)
            elif isinstance(merged[key], list):
                merged[key] = _merge_lists(merged[key], value)
            elif merged[key] == value:
                continue
            elif isinstance(merged[key], int) and not isinstance(merged[key], bool):
                if key in {'index', 'created', 'timestamp'}:
                    merged[key] = value
                else:
                    merged[key] += value
            else:
                raise TypeError(f'Cannot merge {key!r}: unsupported type')
    return merged


def _merge_lists(left: list | None, *others: list | None) -> list | None:
    merged = left.copy() if left is not None else None
    for other in others:
        if other is None:
            continue
        if merged is None:
            merged = other.copy()
            continue
        for e in other:
            index = e.get('index') if isinstance(e, dict) else None
            if not (
                isinstance(index, int)
                or (isinstance(index, str) and index.startswith('lc_'))
            ):
                merged.append(e)
                continue
            to_merge = [
                i
                for i, e_left in enumerate(merged)
                if isinstance(e_left, dict)
                and 'index' in e_left
                and e_left['index'] == index
                and (
                    e_left.get('id') in {None, ''}
                    or e.get('id') in {None, ''}
                    or e_left.get('id') == e.get('id')
                )
            ]
            if not to_merge:
                merged.append(e)
                continue
            target = merged[to_merge[0]]
            if target.get('type') and e.get('type') == 'non_standard' and 'value' in e:
                value = {k: v for k, v in e['value'].items() if k != 'type'}
                if target['type'] != 'non_standard':
                    new_e: dict[str, Any] = {'extras': value}
                else:
                    new_e = {'value': value, 'index': index}
            else:
                new_e = {k: v for k, v in e.items() if k != 'type'}
            merged[to_merge[0]] = _merge_dicts(target, new_e)
    return merged


def _merge_content(first: Any, *contents: Any) -> Any:
    merged = '' if first is None else first
    for content in contents:
        if isinstance(merged, str):
            merged = (
                merged + content if isinstance(content, str) else [merged, *content]
            )
        elif isinstance(content, list):
            merged = _merge_lists(merged, content)
        elif merged and isinstance(merged[-1], str):
            merged[-1] += content
        elif content == '':
            pass
        elif merged:
            merged.append(content)
    return merged


def _add_ints(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    combined: dict[str, Any] = {}
    for key in set(left).union(right):
        lv, rv = left.get(key, 0), right.get(key, 0)
        if isinstance(lv, int) and isinstance(rv, int):
            combined[key] = operator.add(lv, rv)
        elif isinstance(left.get(key, {}), dict) and isinstance(
            right.get(key, {}), dict
        ):
            combined[key] = _add_ints(left.get(key, {}), right.get(key, {}))
        else:
            raise ValueError(f'Cannot add usage {key!r}')  # noqa: TRY004
    return combined


def _add_usage(left: dict | None, right: dict | None) -> dict:
    if not (left or right):
        return {'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0}
    if not (left and right):
        return left or right  # type: ignore[return-value]
    return _add_ints(left, right)


def _merge_chunks(chunks: list[AIMessageChunk]) -> AIMessageChunk:
    first, *others = chunks
    if not others:
        return first
    raw_tool_calls = _merge_lists(
        list(first.tool_call_chunks), *(list(o.tool_call_chunks) for o in others)
    )
    usage = None
    if first.usage_metadata or any(o.usage_metadata is not None for o in others):
        usage = first.usage_metadata
        for other in others:
            usage = _add_usage(usage, other.usage_metadata)
    return AIMessageChunk(
        content=_merge_content(first.content, *(o.content for o in others)),
        additional_kwargs=_merge_dicts(
            first.additional_kwargs, *(o.additional_kwargs for o in others)
        ),
        response_metadata=_merge_dicts(
            first.response_metadata, *(o.response_metadata for o in others)
        ),
        tool_call_chunks=[
            tool_call_chunk(
                name=rtc.get('name'),
                args=rtc.get('args'),
                index=rtc.get('index'),
                id=rtc.get('id'),
            )
            for rtc in raw_tool_calls or []
        ],
        usage_metadata=usage,
    )


# ── Spans ────────────────────────────────────────────────────────────────────


class ChatTrace:
    """The span of one chat model call, from the request to its reply or error.

    Create it with ``start``; it is ``None`` when tracing failed to start.
    """

    def __init__(
        self,
        model: 'ChatModel',
        messages: Sequence[BaseMessage],
        kwargs: dict,
        stream: bool = False,
    ):
        kwargs = dict(kwargs)
        stop = kwargs.pop('stop', None)
        self._model = model
        self._provider = model._gen_ai_provider
        self._start_time = time.time()
        self._request_model: str | None = None
        self._chunk_infos: list[dict | None] = []
        self.span = _start_span(model, stream)
        span = self.span
        if not span.is_recording():
            return
        invocation_params = model._invocation_params(stop=stop, **kwargs)
        self._set_request_params(invocation_params, invocation_params)
        self._set_request_params(model._serialized_kwargs(), None)
        if _should_send_prompts():
            if functions := invocation_params.get('functions'):
                span.set_attribute(
                    GenAIAttributes.GEN_AI_TOOL_DEFINITIONS,
                    _dumps([_tool_definition(f) for f in functions]),
                )
            for key, value in _input_attributes(messages).items():
                span.set_attribute(key, value)

    @classmethod
    @_dont_throw
    def start(
        cls,
        model: 'ChatModel',
        messages: Sequence[BaseMessage],
        kwargs: dict,
        stream: bool = False,
    ) -> 'ChatTrace':
        return cls(model, messages, kwargs, stream)

    def _set_request_params(
        self, params: dict[str, Any], invocation_params: dict[str, Any] | None
    ) -> None:
        """Set the request attributes from ``params``, overriding earlier ones.

        LangChain read the call's invocation params first and the model's
        constructor params next, so the latter win where both have a value.
        """
        span = self.span
        for key in ('model', 'model_id', 'model_name'):
            if (model := params.get(key)) is not None:
                self._request_model = model
                break
        else:
            model = 'unknown'
        span.set_attribute(GenAIAttributes.GEN_AI_REQUEST_MODEL, model)
        # Replaced by the reply's model, when the provider reports one.
        span.set_attribute(GenAIAttributes.GEN_AI_RESPONSE_MODEL, model)
        params = params.get('params') or params
        _set(
            span,
            GenAIAttributes.GEN_AI_REQUEST_MAX_TOKENS,
            params.get('max_tokens') or params.get('max_new_tokens'),
        )
        _set(
            span, GenAIAttributes.GEN_AI_REQUEST_TEMPERATURE, params.get('temperature')
        )
        _set(span, GenAIAttributes.GEN_AI_REQUEST_TOP_P, params.get('top_p'))
        if invocation_params and (tools := invocation_params.get('tools')):
            span.set_attribute(
                GenAIAttributes.GEN_AI_TOOL_DEFINITIONS,
                _dumps([_tool_definition(t.get('function', t), t) for t in tools]),
            )

    @_dont_throw
    def add_chunk(self, chunk: AIMessageChunk) -> None:
        """Record a streamed chunk's generation info, merged at the end."""
        if not self._chunk_infos:
            _set_time_to_first_chunk(self.span, self._start_time)
        self._chunk_infos.append(self._model._generation_info(chunk))

    @_dont_throw
    def end_stream(self, chunks: list[AIMessageChunk]) -> None:
        if not self.span.is_recording():
            self.span.end()
            return
        infos = [info for info in self._chunk_infos[1:] if info]
        generation_info = (
            _merge_dicts(self._chunk_infos[0] or {}, *infos) or None
            if len(chunks) > 1
            else self._chunk_infos[0]
        )
        merged = _merge_chunks(
            [
                c.model_copy(
                    update={
                        'response_metadata': {**(info or {}), **c.response_metadata}
                    }
                )
                for c, info in zip(chunks, self._chunk_infos, strict=True)
            ]
        )
        self._end(merged, generation_info, None)

    @_dont_throw
    def end(self, message: AIMessage) -> None:
        if not self.span.is_recording():
            self.span.end()
            return
        self._end(
            message,
            self._model._generation_info(message),
            self._model._llm_output(message),
        )

    def _end(
        self,
        message: AIMessage,
        generation_info: dict | None,
        llm_output: dict | None,
    ) -> None:
        span = self.span
        model_name = None
        if llm_output is not None:
            model_name = llm_output.get('model_name') or llm_output.get('model_id')
            if model_name is not None:
                span.set_attribute(GenAIAttributes.GEN_AI_RESPONSE_MODEL, model_name)
                if self._request_model is None:
                    span.set_attribute(GenAIAttributes.GEN_AI_REQUEST_MODEL, model_name)
            if response_id := llm_output.get('id'):
                span.set_attribute(GenAIAttributes.GEN_AI_RESPONSE_ID, response_id)
        if model_name is None:
            model_name = message.response_metadata.get('model_name') or None
        if model_name is None:
            model_name = self._request_model or 'unknown'

        token_usage = (llm_output or {}).get('token_usage') or (llm_output or {}).get(
            'usage'
        )
        if token_usage is not None:
            # The provider's raw usage, as reported in LangChain's llm_output.
            prompt_tokens = (
                token_usage.get('prompt_tokens')
                or token_usage.get('input_token_count')
                or token_usage.get('input_tokens')
            )
            completion_tokens = (
                token_usage.get('completion_tokens')
                or token_usage.get('generated_token_count')
                or token_usage.get('output_tokens')
            )
            total_tokens = token_usage.get('total_tokens') or (
                prompt_tokens + completion_tokens
            )
            _set(span, GenAIAttributes.GEN_AI_USAGE_INPUT_TOKENS, prompt_tokens)
            _set(span, GenAIAttributes.GEN_AI_USAGE_OUTPUT_TOKENS, completion_tokens)
            _set(span, SpanAttributes.GEN_AI_USAGE_TOTAL_TOKENS, total_tokens)
            self._record_tokens(prompt_tokens, completion_tokens, model_name)
        self._set_usage(message, token_usage is None, model_name)
        self._set_output(message, generation_info)
        _duration_histogram.record(
            time.time() - self._start_time,
            attributes={
                GenAIAttributes.GEN_AI_PROVIDER_NAME: self._provider,
                GenAIAttributes.GEN_AI_RESPONSE_MODEL: model_name,
            },
        )
        span.end()

    def _record_tokens(self, input_tokens: int, output_tokens: int, model: str) -> None:
        _record_tokens(self._provider, input_tokens, output_tokens, model)

    def _set_usage(self, message: AIMessage, record: bool, model_name: str) -> None:
        """Usage from the reply's ``usage_metadata`` (token totals and cache)."""
        input_tokens = output_tokens = total_tokens = 0
        cache_read = cache_creation = None
        if (usage := message.usage_metadata) is not None:
            input_tokens = usage.get('input_tokens') or usage.get('prompt_tokens') or 0
            output_tokens = (
                usage.get('output_tokens') or usage.get('completion_tokens') or 0
            )
            total_tokens = input_tokens + output_tokens
            if details := usage.get('input_token_details'):
                if isinstance(value := details.get('cache_read'), int | float):
                    cache_read = value
                if isinstance(value := details.get('cache_creation'), int | float):
                    cache_creation = value
        if not (
            input_tokens > 0
            or output_tokens > 0
            or total_tokens > 0
            or cache_read is not None
            or cache_creation is not None
        ):
            return
        span = self.span
        span.set_attribute(GenAIAttributes.GEN_AI_USAGE_INPUT_TOKENS, input_tokens)
        span.set_attribute(GenAIAttributes.GEN_AI_USAGE_OUTPUT_TOKENS, output_tokens)
        span.set_attribute(SpanAttributes.GEN_AI_USAGE_TOTAL_TOKENS, total_tokens)
        _set(span, GenAIAttributes.GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS, cache_read)
        _set(
            span,
            GenAIAttributes.GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS,
            cache_creation,
        )
        if record:
            self._record_tokens(input_tokens, output_tokens, model_name)

    def _set_output(self, message: AIMessage, generation_info: dict | None) -> None:
        span = self.span
        finish_reason = None
        if generation_info and (raw := generation_info.get('finish_reason')):
            finish_reason = _FINISH_REASONS.get(raw, raw)
            span.set_attribute(
                GenAIAttributes.GEN_AI_RESPONSE_FINISH_REASONS, [finish_reason]
            )
        if not _should_send_prompts():
            return
        parts = []
        if text := _generation_text(message):
            parts.append({'type': 'text', 'content': text})
        elif message.content:
            parts.extend(_content_to_parts(message.content))
        if function_call := message.additional_kwargs.get('function_call'):
            args = function_call.get('arguments')
            if isinstance(args, str):
                with contextlib.suppress(json.JSONDecodeError, TypeError):
                    args = json.loads(args)
            parts.append(
                {
                    'type': 'tool_call',
                    'id': '',
                    'name': function_call.get('name'),
                    'arguments': args,
                }
            )
        if message.tool_calls:
            parts.extend(_tool_calls_to_parts(message.tool_calls))
        output = {
            # A merged stream chunk is not an ``ai`` message: role ``unknown``.
            'role': _ROLES.get(message.type, 'unknown'),
            'parts': parts,
            'finish_reason': finish_reason or '',
        }
        span.set_attribute(GenAIAttributes.GEN_AI_OUTPUT_MESSAGES, _dumps([output]))

    @_dont_throw
    def fail(self, error: BaseException) -> None:
        _fail(self.span, self._model._error_type(error), str(error), error)


def _start_span(model: 'ChatModel', stream: bool) -> Span:
    """Start the CLIENT span of a model call, with the attributes every call has."""
    span = _tracer.start_span(f'{type(model).__name__}.chat', kind=SpanKind.CLIENT)
    if not span.is_recording():
        return span
    # The gateway's own task context does not describe this span.
    span.set_attribute(SpanAttributes.TRACELOOP_WORKFLOW_NAME, '')
    span.set_attribute(SpanAttributes.TRACELOOP_ENTITY_PATH, '')
    span.set_attribute(GenAIAttributes.GEN_AI_PROVIDER_NAME, model._gen_ai_provider)
    span.set_attribute(GenAIAttributes.GEN_AI_OPERATION_NAME, 'chat')
    if stream:
        span.set_attribute(GenAIAttributes.GEN_AI_REQUEST_STREAM, True)
    try:
        url = urlparse(model._server_url() or '')
        if url.hostname:
            span.set_attribute(SERVER_ADDRESS, url.hostname)
            _set(span, SERVER_PORT, url.port or _DEFAULT_PORTS.get(url.scheme))
    except Exception:
        logger.debug('Failed to read the server of %s', type(model).__name__)
    return span


def _set_time_to_first_chunk(span: Span, start_time: float) -> None:
    if span.is_recording():
        span.set_attribute(_RESPONSE_TIME_TO_FIRST_CHUNK, time.time() - start_time)


def _record_tokens(
    provider: str, input_tokens: int, output_tokens: int, model: str
) -> None:
    for token_type, count in (('input', input_tokens), ('output', output_tokens)):
        if count > 0:
            _token_histogram.record(
                count,
                attributes={
                    GenAIAttributes.GEN_AI_PROVIDER_NAME: provider,
                    GenAIAttributes.GEN_AI_TOKEN_TYPE: token_type,
                    GenAIAttributes.GEN_AI_RESPONSE_MODEL: model,
                },
            )


def _fail(
    span: Span, error_type: str, message: str, error: BaseException | None = None
) -> None:
    span.set_attribute(SpanAttributes.GEN_AI_TASK_STATUS, 'failure')
    span.set_attribute(ERROR_TYPE, error_type)
    span.set_status(Status(StatusCode.ERROR, message))
    if error is not None:
        span.record_exception(error)
    span.end()


# ── Responses API ────────────────────────────────────────────────────────────

# Stream events whose payload carries the final response object.
_RESPONSES_FINAL_EVENTS = frozenset(
    {'response.completed', 'response.incomplete', 'response.failed'}
)
_RESPONSES_ROLES = {'developer': 'system'}
_RESPONSES_INCOMPLETE_REASONS = {
    'max_output_tokens': 'length',
    'content_filter': 'content_filter',
}


def _responses_content_parts(content: Any) -> list[dict]:
    """Return the parts of a Responses message's ``content``, a string or blocks."""
    if not isinstance(content, list):
        return _content_to_parts(content)
    parts = []
    for block in content:
        block_type = block.get('type') if isinstance(block, dict) else None
        if block_type in ('input_text', 'output_text'):
            if text := block.get('text'):
                parts.append({'type': 'text', 'content': text})
        elif block_type == 'input_image' and (url := block.get('image_url')):
            parts.append({'type': 'uri', 'modality': 'image', 'uri': url})
        else:
            parts.extend(_content_to_parts([block]))
    return parts


def _responses_item(item: dict) -> tuple[str, list[dict]]:
    """Return the role and the parts of a Responses input or output item."""
    item_type = item.get('type', 'message')
    if item_type == 'message':
        role = item.get('role', 'user')
        parts = _responses_content_parts(item.get('content'))
        return _RESPONSES_ROLES.get(role, role), parts
    if item_type == 'function_call':
        call = {
            'id': item.get('call_id', ''),
            'name': item.get('name', ''),
            'args': item.get('arguments'),
        }
        return 'assistant', _tool_calls_to_parts([call])
    if item_type == 'function_call_output':
        output = item.get('output')
        part = {
            'type': 'tool_call_response',
            'id': item.get('call_id', ''),
            'response': output if isinstance(output, str) else _dumps(output),
        }
        return 'tool', [part]
    if item_type == 'reasoning':
        # Encrypted reasoning is not reported, only its summary.
        summary = ''.join(s.get('text', '') for s in item.get('summary') or [])
        return 'assistant', [
            {'type': 'reasoning', 'content': summary}
        ] if summary else []
    # A built-in tool call (web search...) or another item: a generic part.
    return 'assistant', [item]


def _responses_input_attributes(body: dict) -> dict[str, str]:
    """Return the system instructions and input messages of a Responses request.

    Consecutive items of a role are one message, as a chat message carries
    both its text and its tool calls.
    """
    items = body.get('input')
    if isinstance(items, str):
        items = [{'role': 'user', 'content': items}]
    system_instructions = _responses_content_parts(body.get('instructions'))
    input_messages: list[dict] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        role, parts = _responses_item(item)
        if role == 'system':
            system_instructions.extend(parts)
        elif input_messages and input_messages[-1]['role'] == role:
            input_messages[-1]['parts'].extend(parts)
        else:
            input_messages.append({'role': role, 'parts': parts})
    attributes = {}
    if system_instructions:
        attributes[GenAIAttributes.GEN_AI_SYSTEM_INSTRUCTIONS] = _dumps(
            system_instructions
        )
    if input_messages:
        attributes[GenAIAttributes.GEN_AI_INPUT_MESSAGES] = _dumps(input_messages)
    return attributes


def _responses_finish_reason(response: dict) -> str | None:
    status = response.get('status')
    if status == 'incomplete':
        reason = (response.get('incomplete_details') or {}).get('reason')
        return _RESPONSES_INCOMPLETE_REASONS.get(reason, reason)
    if status == 'completed':
        output = response.get('output') or []
        if any(item.get('type') == 'function_call' for item in output):
            return 'tool_call'
        return 'stop'
    return None


class ResponsesTrace:
    """The span of one native Responses API call, from the request to its reply.

    It is the span of a chat call (``ChatTrace``), with the same name,
    attributes and metrics, read from the client's request body and the
    upstream's response object rather than from messages. The request params
    are the client's, falling back to the model's settings, as the provider
    merges them. Create it with ``start``; it is ``None`` when tracing failed
    to start.
    """

    def __init__(self, model: 'ChatModel', body: dict, stream: bool = False):
        self._model = model
        self._provider = model._gen_ai_provider
        self._start_time = time.time()
        # A stream's final response object, or its error event.
        self._response: dict | None = None
        self._error: dict | None = None
        self._first_event = True
        settings = model._serialized_kwargs()
        self._request_model = (
            settings.get('model') or settings.get('model_name') or 'unknown'
        )
        self.span = _start_span(model, stream)
        span = self.span
        if not span.is_recording():
            return
        span.set_attribute(GenAIAttributes.GEN_AI_REQUEST_MODEL, self._request_model)
        # Replaced by the response's model.
        span.set_attribute(GenAIAttributes.GEN_AI_RESPONSE_MODEL, self._request_model)
        for attribute, key, setting in (
            (
                GenAIAttributes.GEN_AI_REQUEST_MAX_TOKENS,
                'max_output_tokens',
                'max_tokens',
            ),
            (GenAIAttributes.GEN_AI_REQUEST_TEMPERATURE, 'temperature', 'temperature'),
            (GenAIAttributes.GEN_AI_REQUEST_TOP_P, 'top_p', 'top_p'),
        ):
            value = body.get(key)
            _set(span, attribute, settings.get(setting) if value is None else value)
        reasoning = getattr(model, 'reasoning', None) or {}
        _set(
            span,
            _REQUEST_REASONING_LEVEL,
            (body.get('reasoning') or {}).get('effort')
            or reasoning.get('effort')
            or getattr(model, 'reasoning_effort', None),
        )
        _set(span, _REQUEST_PREVIOUS_RESPONSE_ID, body.get('previous_response_id'))
        conversation = body.get('conversation')
        if isinstance(conversation, dict):
            conversation = conversation.get('id')
        _set(span, GenAIAttributes.GEN_AI_CONVERSATION_ID, conversation)
        if tools := body.get('tools'):
            # Built-in tools (web search...) have a type and no name.
            definitions = [
                _tool_definition({**tool, 'name': tool.get('name') or tool.get('type')})
                for tool in tools
            ]
            span.set_attribute(
                GenAIAttributes.GEN_AI_TOOL_DEFINITIONS, _dumps(definitions)
            )
        if _should_send_prompts():
            for key, value in _responses_input_attributes(body).items():
                span.set_attribute(key, value)

    @classmethod
    @_dont_throw
    def start(
        cls, model: 'ChatModel', body: dict, stream: bool = False
    ) -> 'ResponsesTrace':
        return cls(model, body, stream)

    @_dont_throw
    def add_event(self, event: str, data: str) -> None:
        """Keep the final response object, or the error, of a stream event."""
        if self._first_event:
            self._first_event = False
            _set_time_to_first_chunk(self.span, self._start_time)
        if event in _RESPONSES_FINAL_EVENTS:
            self._response = json.loads(data).get('response')
        elif event == 'error':
            self._error = json.loads(data)

    @_dont_throw
    def end_stream(self) -> None:
        if self._response is None and self._error is not None:
            _fail(
                self.span,
                self._error.get('code') or 'error',
                self._error.get('message') or '',
            )
            return
        self.end(self._response)

    @_dont_throw
    def end(self, response: dict | None) -> None:
        span = self.span
        if not span.is_recording() or response is None:
            span.end()
            return
        model_name = response.get('model') or self._request_model
        span.set_attribute(GenAIAttributes.GEN_AI_RESPONSE_MODEL, model_name)
        _set(span, GenAIAttributes.GEN_AI_RESPONSE_ID, response.get('id'))
        self._set_usage(response.get('usage'), model_name)
        finish_reason = _responses_finish_reason(response)
        if finish_reason:
            span.set_attribute(
                GenAIAttributes.GEN_AI_RESPONSE_FINISH_REASONS, [finish_reason]
            )
        if _should_send_prompts():
            parts = []
            for item in response.get('output') or []:
                parts.extend(_responses_item(item)[1])
            output = {
                'role': 'assistant',
                'parts': parts,
                'finish_reason': finish_reason or '',
            }
            span.set_attribute(GenAIAttributes.GEN_AI_OUTPUT_MESSAGES, _dumps([output]))
        _duration_histogram.record(
            time.time() - self._start_time,
            attributes={
                GenAIAttributes.GEN_AI_PROVIDER_NAME: self._provider,
                GenAIAttributes.GEN_AI_RESPONSE_MODEL: model_name,
            },
        )
        if response.get('status') == 'failed':
            error = response.get('error') or {}
            _fail(
                span,
                error.get('code') or 'response.failed',
                error.get('message') or '',
            )
            return
        span.end()

    def _set_usage(self, usage: dict | None, model_name: str) -> None:
        if not usage:
            return
        span = self.span
        input_tokens = usage.get('input_tokens') or 0
        output_tokens = usage.get('output_tokens') or 0
        span.set_attribute(GenAIAttributes.GEN_AI_USAGE_INPUT_TOKENS, input_tokens)
        span.set_attribute(GenAIAttributes.GEN_AI_USAGE_OUTPUT_TOKENS, output_tokens)
        span.set_attribute(
            SpanAttributes.GEN_AI_USAGE_TOTAL_TOKENS,
            usage.get('total_tokens') or input_tokens + output_tokens,
        )
        # Each set when non-zero, as the semantic conventions recommend.
        input_details = usage.get('input_tokens_details') or {}
        output_details = usage.get('output_tokens_details') or {}
        for attribute, count in (
            (
                GenAIAttributes.GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS,
                input_details.get('cached_tokens'),
            ),
            (
                GenAIAttributes.GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS,
                input_details.get('cache_write_tokens'),
            ),
            (
                GenAIAttributes.GEN_AI_USAGE_REASONING_OUTPUT_TOKENS,
                output_details.get('reasoning_tokens'),
            ),
        ):
            if count:
                span.set_attribute(attribute, count)
        _record_tokens(self._provider, input_tokens, output_tokens, model_name)

    @_dont_throw
    def fail(self, error: BaseException) -> None:
        if self._response is not None:
            # The stream already carried its final response: the call is
            # done, whatever stops the stream after it. A client that closes
            # the connection once it has ``response.completed`` (opencode
            # does) cancels the stream while it waits for the upstream to
            # close.
            self.end(self._response)
            return
        _fail(self.span, self._model._error_type(error), str(error), error)


def _tool_definition(function: dict, tool: dict | None = None) -> dict:
    definition = {'name': function.get('name')}
    if function.get('description'):
        definition['description'] = function.get('description')
    parameters = function.get(
        'parameters', tool.get('input_schema') if tool is not None else None
    )
    if parameters:
        definition['parameters'] = parameters
    return definition
