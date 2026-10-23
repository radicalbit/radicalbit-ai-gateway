"""Mistral AI chat and embedding models over the plain HTTP API.

The request and response handling reproduces the ``langchain-mistralai``
integration the gateway used before, so the wire format is unchanged: the
injected sampling defaults, the 9-character tool-call ids Mistral requires,
the retry policy and the error messages.
"""

import asyncio
from collections.abc import AsyncIterator, Iterator, Sequence
import copy
import hashlib
import json
import logging
import os
import re
import ssl
import time
from typing import Any
import uuid

import certifi
import httpx
from pydantic import BaseModel

from radicalbit_ai_gateway.llm.chat_model import ChatModel, StructuredChatModel
from radicalbit_ai_gateway.llm.embeddings import Embeddings
from radicalbit_ai_gateway.llm.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    invalid_tool_call,
    tool_call,
    tool_call_chunk,
)

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = 'https://api.mistral.ai/v1'
DEFAULT_EMBEDDINGS_ENDPOINT = 'https://api.mistral.ai/v1/'

# Same as httpx's default ``verify=True``, built once.
_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

# Settings consumed by the model itself; every other configured parameter is
# sent in the request body.
_SETTINGS = frozenset(
    {
        'api_key',
        'mistral_api_key',
        'base_url',
        'endpoint',
        'max_retries',
        'timeout',
        'max_concurrent_requests',
        'model',
        'model_name',
        'temperature',
        'max_tokens',
        'stop',
        'top_p',
        'random_seed',
        'safe_mode',
        'streaming',
        'model_kwargs',
        'client',
        'async_client',
        'http_async_client',
        # Generic chat-model options with no effect on the request.
        'cache',
        'callbacks',
        'custom_get_token_ids',
        'disable_streaming',
        'metadata',
        'name',
        'output_version',
        'profile',
        'rate_limiter',
        'tags',
        'verbose',
    }
)

# Transport failures are retried with exponential backoff (4s, 4s, 4s, 8s,
# then 10s); HTTP error statuses are not.
_RETRY_MIN_WAIT = 4
_RETRY_MAX_WAIT = 10

_TOOL_CALL_ID = re.compile(r'^[a-zA-Z0-9]{9}$')
_BASE62 = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'

_DATA_BLOCK_TYPES = ('image', 'video', 'audio', 'text-plain', 'file')


def build_chat_model(model_name: str, **kwargs: Any) -> 'ChatMistralAI':
    """Build the chat model from the configured credentials and params."""
    return ChatMistralAI(model_name, **kwargs)


def build_embeddings(model_name: str, **kwargs: Any) -> 'MistralEmbeddings':
    """Build the embedding model from the configured credentials and params."""
    return MistralEmbeddings(model_name, **kwargs)


# ── Chat ─────────────────────────────────────────────────────────────────────


class ChatMistralAI(ChatModel):
    _gen_ai_provider = 'mistral_ai'

    def __init__(
        self,
        model_name: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        max_retries: int = 5,
        timeout: float = 120,
        temperature: float | None = 0.7,
        max_tokens: int | None = None,
        stop: list[str] | None = None,
        top_p: float | None = 1,
        random_seed: int | None = None,
        safe_mode: bool | None = None,
        model_kwargs: dict[str, Any] | None = None,
        **kwargs: Any,
    ):
        api_key = kwargs.pop('mistral_api_key', api_key)
        base_url = kwargs.pop('endpoint', base_url)
        self.model_name = kwargs.pop('model', None) or model_name
        if api_key is None:
            api_key = os.environ.get('MISTRAL_API_KEY')
        self.base_url = (
            base_url or os.environ.get('MISTRAL_BASE_URL') or DEFAULT_BASE_URL
        )
        self.max_retries = max_retries
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.stop = stop
        self.top_p = top_p
        self.random_seed = random_seed
        self.safe_mode = safe_mode
        self.model_kwargs = {
            **(model_kwargs or {}),
            **{k: v for k, v in kwargs.items() if k not in _SETTINGS},
        }
        if temperature is not None and not 0 <= temperature <= 1:
            raise ValueError('temperature must be in the range [0.0, 1.0]')
        if top_p is not None and not 0 <= top_p <= 1:
            raise ValueError('top_p must be in the range [0.0, 1.0]')
        # Request kwargs added by bind_tools, sent on every call.
        self.bound: dict[str, Any] = {}
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'Authorization': f'Bearer {api_key}',
            },
            timeout=timeout,
            verify=_SSL_CONTEXT,
        )

    def _default_params(self) -> dict[str, Any]:
        params = {
            'model': self.model_name,
            'temperature': self.temperature,
            'max_tokens': self.max_tokens,
            'top_p': self.top_p,
            'random_seed': self.random_seed,
            'safe_prompt': self.safe_mode,
            **self.model_kwargs,
        }
        return {k: v for k, v in params.items() if v is not None}

    def _invocation_params(self, stop: list[str] | None = None, **kwargs: Any) -> dict:
        return {**self._default_params(), 'stop': stop, **self.bound, **kwargs}

    def _llm_output(self, message: AIMessage) -> dict | None:
        metadata = message.response_metadata
        return {
            'model_name': metadata.get('model_name'),
            'token_usage': metadata.get('token_usage'),
        }

    def _generation_info(self, message: AIMessage) -> dict | None:
        # Stream chunks carried none.
        if isinstance(message, AIMessageChunk):
            return None
        return {'finish_reason': message.response_metadata.get('finish_reason')}

    def _request_body(
        self, messages: list[BaseMessage], kwargs: dict[str, Any]
    ) -> dict[str, Any]:
        kwargs = {**self.bound, **kwargs}
        stop = kwargs.pop('stop', None)
        params = self._default_params()
        stop = stop if stop is not None else self.stop
        if stop:
            params['stop'] = stop
        return {
            'messages': [_to_mistral_message(m) for m in messages],
            **params,
            **kwargs,
        }

    async def _agenerate(self, messages: list[BaseMessage], **kwargs: Any) -> AIMessage:
        # A caller-supplied ``stream`` never switches this call to streaming.
        kwargs.pop('stream', None)
        body = self._request_body(messages, kwargs)
        body['stream'] = False
        response = await self._post_with_retry(body)
        return self._to_ai_message(response)

    async def _post_with_retry(self, body: dict[str, Any]) -> dict[str, Any]:
        attempt = 1
        while True:
            try:
                response = await self.client.post(url='/chat/completions', json=body)
                await _raise_on_error(response)
                return response.json()
            except (httpx.RequestError, httpx.StreamError) as e:
                if attempt >= self.max_retries:
                    raise
                wait = max(_RETRY_MIN_WAIT, min(2 ** (attempt - 1), _RETRY_MAX_WAIT))
                logger.warning(
                    'Retrying Mistral request in %s seconds as it raised %s: %s.',
                    wait,
                    type(e).__name__,
                    e,
                )
                await asyncio.sleep(wait)
                attempt += 1

    def _to_ai_message(self, response: dict[str, Any]) -> AIMessage:
        token_usage = response.get('usage', {})
        choice = response['choices'][0]
        message = _from_mistral_message(choice['message'])
        if token_usage:
            message.usage_metadata = {
                'input_tokens': token_usage.get('prompt_tokens', 0),
                'output_tokens': token_usage.get('completion_tokens', 0),
                'total_tokens': token_usage.get('total_tokens', 0),
            }
        message.response_metadata = {
            'token_usage': token_usage,
            'model_name': self.model_name,
            'model': self.model_name,
            'finish_reason': choice.get('finish_reason'),
            **message.response_metadata,
        }
        return message

    async def _astream(
        self, messages: list[BaseMessage], **kwargs: Any
    ) -> AsyncIterator[AIMessageChunk]:
        body = {**self._request_body(messages, kwargs), 'stream': True}
        index = -1
        index_type = ''
        async with self.client.stream(
            'POST',
            '/chat/completions',
            json=body,
            headers={'Accept': 'text/event-stream', 'Cache-Control': 'no-store'},
        ) as response:
            await _raise_on_error(response)
            async for event in _aiter_sse_data(response):
                if event == '[DONE]':
                    return
                data = json.loads(event)
                if len(data.get('choices', [])) == 0:
                    continue
                chunk, index, index_type = _to_message_chunk(data, index, index_type)
                yield chunk

    def bind_tools(self, tools: list[dict], tool_choice: Any = None) -> 'ChatMistralAI':
        bound = copy.copy(self)
        bound.bound = {**self.bound, **_tool_kwargs(tools, tool_choice)}
        return bound

    def with_structured_output(
        self, schema: type[BaseModel], include_raw: bool = False
    ) -> '_MistralStructuredModel':
        # Mistral's default structured-output method: a forced function call.
        bound = self.bind_tools([_pydantic_to_tool(schema)], tool_choice='any')
        return _MistralStructuredModel(bound, schema, include_raw)


class _MistralStructuredModel(StructuredChatModel):
    def __init__(
        self, model: 'ChatMistralAI', schema: type[BaseModel], include_raw: bool
    ):
        self.model = model
        self.schema = schema
        self.include_raw = include_raw

    async def ainvoke(self, input: Sequence[BaseMessage], **kwargs: Any) -> Any:  # noqa: A002
        raw = await self.model.ainvoke(input, **kwargs)
        if not self.include_raw:
            return _parse_first_tool_call(raw, self.schema)
        try:
            parsed = _parse_first_tool_call(raw, self.schema)
        except Exception as e:
            return {'raw': raw, 'parsed': None, 'parsing_error': e}
        return {'raw': raw, 'parsed': parsed, 'parsing_error': None}


class OutputParserError(ValueError):
    """The model's reply could not be parsed into the requested schema."""


def _parse_first_tool_call(message: AIMessage, schema: type[BaseModel]) -> Any:
    if message.tool_calls:
        calls = [{'type': tc['name'], 'args': tc['args']} for tc in message.tool_calls]
    elif 'tool_calls' in message.additional_kwargs:
        # Every tool call was invalid: re-parse them to surface the error.
        calls = []
        errors = []
        for raw in message.additional_kwargs['tool_calls']:
            try:
                parsed = _parse_tool_call(raw)
            except OutputParserError as e:
                errors.append(str(e))
                continue
            if parsed is not None:
                calls.append({'type': parsed['name'], 'args': parsed['args']})
        if errors:
            raise OutputParserError('\n\n'.join(errors))
    else:
        return None
    if not calls:
        return None
    first = calls[0]
    if not isinstance(first['args'], dict):
        raise ValueError(  # noqa: TRY004
            f'Tool arguments must be specified as a dict, received: {first["args"]}'
        )
    name = schema.model_config.get('title') or schema.__name__
    if first['type'] != name:
        raise OutputParserError(
            f'Unknown tool type: {first["type"]!r}. Available tools: {name}'
        )
    return schema(**first['args'])


def _tool_kwargs(tools: list[dict], tool_choice: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {'tools': tools}
    if tool_choice:
        names = [
            name
            for tool in tools
            if ('function' in tool and (name := tool['function'].get('name')))
            or (name := tool.get('name'))
        ]
        if tool_choice in names:
            kwargs['tool_choice'] = {
                'type': 'function',
                'function': {'name': tool_choice},
            }
        else:
            kwargs['tool_choice'] = tool_choice
    return kwargs


def _pydantic_to_tool(schema: type[BaseModel]) -> dict[str, Any]:
    """Describe a pydantic model as an OpenAI-format function tool."""
    json_schema = _dereference(schema.model_json_schema())
    json_schema.pop('$defs', None)
    name = json_schema.pop('title', '')
    description = json_schema.pop('description', '')
    return {
        'type': 'function',
        'function': {
            'name': name,
            'description': description,
            'parameters': _rm_titles(json_schema),
        },
    }


def _dereference(schema: dict[str, Any]) -> dict[str, Any]:
    defs = schema.get('$defs', {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            ref = node.get('$ref')
            if isinstance(ref, str) and ref.startswith('#/$defs/'):
                target = resolve(defs[ref.removeprefix('#/$defs/')])
                rest = {k: resolve(v) for k, v in node.items() if k != '$ref'}
                return {**target, **rest}
            return {k: resolve(v) for k, v in node.items()}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return {k: (v if k == '$defs' else resolve(v)) for k, v in schema.items()}


def _rm_titles(kv: dict[str, Any], prev_key: str = '') -> dict[str, Any]:
    # Drop schema titles, but keep properties that are themselves named title.
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


# ── Request conversion ───────────────────────────────────────────────────────


def _mistral_tool_call_id(tool_call_id: str) -> str:
    """Map any tool-call id onto Mistral's 9-character alphanumeric format."""
    if _TOOL_CALL_ID.match(tool_call_id):
        return tool_call_id
    num = int.from_bytes(hashlib.sha256(tool_call_id.encode()).digest(), 'big')
    encoded = []
    while num:
        num, rem = divmod(num, len(_BASE62))
        encoded.append(_BASE62[rem])
    base62 = ''.join(reversed(encoded)) or _BASE62[0]
    return base62[:9] if len(base62) >= 9 else base62.rjust(9, '0')


def _is_data_block(block: dict) -> bool:
    if block.get('type') not in _DATA_BLOCK_TYPES:
        return False
    if any(key in block for key in ('url', 'base64', 'file_id', 'text')):
        return not (block['type'] == 'text' and 'source_type' not in block)
    if 'source_type' in block:
        source_type = block['source_type']
        return (
            (source_type == 'url' and 'url' in block)
            or (source_type == 'base64' and 'data' in block)
            or (source_type == 'id' and 'id' in block)
            or (source_type == 'text' and 'url' in block)
        )
    return False


def _to_chat_completions_block(block: dict) -> dict:
    """Translate a standard data block into the chat-completions shape."""
    block_type = block['type']
    if block_type == 'image':
        if 'url' in block:
            return {'type': 'image_url', 'image_url': {'url': block['url']}}
        if 'base64' in block or block.get('source_type') == 'base64':
            if 'mime_type' not in block:
                raise ValueError('mime_type key is required for base64 data.')
            data = block['data'] if 'data' in block else block['base64']
            return {
                'type': 'image_url',
                'image_url': {'url': f'data:{block["mime_type"]};base64,{data}'},
            }
        raise ValueError(
            "Unsupported source type. Only 'url' and 'base64' are supported."
        )
    if block_type == 'file':
        if block.get('source_type') == 'base64' or 'base64' in block:
            data = block['data'] if 'source_type' in block else block['base64']
            file = {'file_data': f'data:{block["mime_type"]};base64,{data}'}
            if filename := block.get('filename'):
                file['filename'] = filename
            elif 'filename' in (extras := block.get('extras') or {}) or (
                'filename' in (extras := block.get('metadata') or {})
            ):
                file['filename'] = extras['filename']
            else:
                file['filename'] = 'LC_AUTOGENERATED'
            return {'type': 'file', 'file': file}
        if block.get('source_type') == 'id' or 'file_id' in block:
            file_id = block['id'] if 'source_type' in block else block['file_id']
            return {'type': 'file', 'file': {'file_id': file_id}}
        if 'url' in block:
            raise ValueError('OpenAI Chat Completions does not support file URLs.')
        raise ValueError('Keys base64, url, or file_id required for file blocks.')
    if block_type == 'audio':
        if 'base64' in block or block.get('source_type') == 'base64':
            data = block['data'] if 'source_type' in block else block['base64']
            return {
                'type': 'input_audio',
                'input_audio': {
                    'data': data,
                    'format': block['mime_type'].split('/')[-1],
                },
            }
        raise ValueError('Key base64 is required for audio blocks.')
    raise ValueError(f'Block of type {block_type} is not supported.')


def _format_user_content(content: Any) -> Any:
    if not isinstance(content, list):
        return content
    return [
        _to_chat_completions_block(block)
        if isinstance(block, dict) and _is_data_block(block)
        else block
        for block in content
    ]


def _clean_block(block: dict) -> dict:
    # Drop keys added while parsing a reply (e.g. the stream ``index``).
    if block.get('type') == 'text' and 'text' in block:
        return {'type': 'text', 'text': block['text']}
    new_block = {k: v for k, v in block.items() if k != 'index'}
    if block.get('type') == 'thinking' and isinstance(block.get('thinking'), list):
        new_block['thinking'] = [
            {k: v for k, v in sb.items() if k != 'index'}
            if isinstance(sb, dict) and 'index' in sb
            else sb
            for sb in block['thinking']
        ]
    return new_block


def _legacy_tool_calls(message: AIMessage) -> tuple[list, list]:
    """Tool calls of ``message``, parsed from ``additional_kwargs`` if needed.

    A message carrying only raw ``additional_kwargs['tool_calls']`` is treated
    as if its tool calls had been parsed from them, as LangChain messages do.
    """
    if message.tool_calls or message.invalid_tool_calls:
        return message.tool_calls, message.invalid_tool_calls
    raw_tool_calls = message.additional_kwargs.get('tool_calls')
    if not raw_tool_calls:
        return [], []
    tool_calls = []
    invalid_tool_calls = []
    try:
        for raw in raw_tool_calls:
            if 'function' not in raw:
                continue
            name = raw['function']['name']
            try:
                args = json.loads(raw['function']['arguments'])
                tool_calls.append(
                    tool_call(name=name or '', args=args or {}, id=raw.get('id'))
                )
            except json.JSONDecodeError:
                invalid_tool_calls.append(
                    invalid_tool_call(
                        name=name, args=raw['function']['arguments'], id=raw.get('id')
                    )
                )
    except Exception:
        return [], []
    return tool_calls, invalid_tool_calls


def _assistant_message(message: AIMessage) -> dict[str, Any]:
    result: dict[str, Any] = {'role': 'assistant'}
    tool_calls: list[dict] = []
    parsed_calls, invalid_calls = _legacy_tool_calls(message)
    if parsed_calls or invalid_calls:
        for tc in parsed_calls:
            call = {
                'function': {
                    'name': tc['name'],
                    'arguments': json.dumps(tc['args'], ensure_ascii=False),
                }
            }
            if tc_id := tc.get('id'):
                call['id'] = _mistral_tool_call_id(tc_id)
            tool_calls.append(call)
        for tc in invalid_calls:
            call = {'function': {'name': tc['name'], 'arguments': tc['args']}}
            if tc_id := tc.get('id'):
                call['id'] = _mistral_tool_call_id(tc_id)
            tool_calls.append(call)
    elif 'tool_calls' in message.additional_kwargs:
        for tc in message.additional_kwargs['tool_calls']:
            call = {
                'function': {
                    'name': tc['function']['name'],
                    'arguments': tc['function']['arguments'],
                }
            }
            if tc_id := tc.get('id'):
                call['id'] = tc_id
            tool_calls.append(call)
    if tool_calls:
        result['tool_calls'] = tool_calls

    content = message.content
    if tool_calls and content:
        # Mistral rejects an assistant message with both content and tool calls.
        content = ''
    elif isinstance(content, list):
        content = [_clean_block(b) if isinstance(b, dict) else b for b in content]
    if any(isinstance(block, dict) for block in content):
        content = [
            block if isinstance(block, dict) else {'type': 'text', 'text': block}
            for block in content
        ]
    result['content'] = content

    if 'prefix' in message.additional_kwargs:
        result['prefix'] = message.additional_kwargs['prefix']
    return result


def _tool_message_content(content: Any) -> Any:
    # Mistral rejects unknown keys on text blocks of tool messages.
    if not isinstance(content, list):
        return content
    return [
        {'type': 'text', 'text': block['text']}
        if isinstance(block, dict) and block.get('type') == 'text' and 'text' in block
        else block
        for block in content
    ]


def _to_mistral_message(message: BaseMessage) -> dict[str, Any]:
    if isinstance(message, HumanMessage):
        return {'role': 'user', 'content': _format_user_content(message.content)}
    if isinstance(message, AIMessage):
        return _assistant_message(message)
    if isinstance(message, SystemMessage):
        return {'role': 'system', 'content': message.content}
    if isinstance(message, ToolMessage):
        return {
            'role': 'tool',
            'content': _tool_message_content(message.content),
            'name': message.name,
            'tool_call_id': _mistral_tool_call_id(message.tool_call_id),
        }
    raise ValueError(f'Got unknown type {message}')


# ── Response conversion ──────────────────────────────────────────────────────


def _normalize_content(content: Any) -> str | list:
    """Turn ``reference`` (citation) blocks into text blocks keeping the citation."""
    if not isinstance(content, list):
        return content or ''
    has_reference = False
    blocks: list = []
    for block in content:
        if isinstance(block, dict) and block.get('type') == 'reference':
            has_reference = True
            new_block = {
                'type': 'text',
                'text': block.get('text', ''),
                'reference': {
                    k: v for k, v in block.items() if k not in ('type', 'text')
                },
            }
            if 'index' in block:
                new_block['index'] = block['index']
            blocks.append(new_block)
        else:
            blocks.append(block)
    return blocks if has_reference else content


def _parse_tool_call(raw: dict[str, Any]) -> dict[str, Any] | None:
    if 'function' not in raw:
        return None
    arguments = raw['function']['arguments']
    if not arguments:
        args = {}
    elif isinstance(arguments, dict):
        args = arguments
    else:
        try:
            args = json.loads(arguments, strict=False)
        except json.JSONDecodeError as e:
            raise OutputParserError(
                f'Function {raw["function"]["name"]} arguments:\n\n{arguments}'
                f'\n\nare not valid JSON. Received JSONDecodeError {e}'
            ) from e
    return {
        'name': raw['function']['name'] or '',
        'args': args or {},
        'id': raw.get('id'),
    }


def _from_mistral_message(message: dict[str, Any]) -> AIMessage:
    role = message['role']
    if role != 'assistant':
        raise ValueError(f"Expected role to be 'assistant', got {role}")
    content = _normalize_content(message.get('content', ''))
    additional_kwargs: dict[str, Any] = {}
    tool_calls = []
    invalid_tool_calls = []
    if raw_tool_calls := message.get('tool_calls'):
        additional_kwargs['tool_calls'] = raw_tool_calls
        for raw in raw_tool_calls:
            try:
                parsed = _parse_tool_call(raw)
                if not parsed['id']:
                    parsed['id'] = uuid.uuid4().hex
                tool_calls.append(tool_call(**parsed))
            except Exception as e:
                invalid_tool_calls.append(
                    invalid_tool_call(
                        name=raw['function']['name'],
                        args=raw['function']['arguments'],
                        id=raw.get('id'),
                        error=str(e),
                    )
                )
    return AIMessage(
        content=content,
        additional_kwargs=additional_kwargs,
        tool_calls=tool_calls,
        invalid_tool_calls=invalid_tool_calls,
        response_metadata={'model_provider': 'mistralai'},
    )


def _to_message_chunk(
    data: dict[str, Any], index: int, index_type: str
) -> tuple[AIMessageChunk, int, str]:
    choice = data['choices'][0]
    delta = choice['delta']
    content = _normalize_content(delta.get('content') or '')
    if isinstance(content, list):
        # Number the blocks so consecutive pieces of one block merge.
        for block in content:
            if isinstance(block, dict):
                block_type = 'reference' if 'reference' in block else block.get('type')
                if block_type is not None and block_type != index_type:
                    index_type = block_type
                    index += 1
                if 'index' not in block:
                    block['index'] = index
                if block.get('type') == 'thinking' and isinstance(
                    block.get('thinking'), list
                ):
                    for sub_block in block['thinking']:
                        if isinstance(sub_block, dict) and 'index' not in sub_block:
                            sub_block['index'] = 0
    additional_kwargs: dict[str, Any] = {}
    tool_call_chunks = []
    if raw_tool_calls := delta.get('tool_calls'):
        additional_kwargs['tool_calls'] = raw_tool_calls
        try:
            for raw in raw_tool_calls:
                if not raw.get('index') and not raw.get('id'):
                    call_id = uuid.uuid4().hex
                else:
                    call_id = raw.get('id')
                tool_call_chunks.append(
                    tool_call_chunk(
                        name=raw['function'].get('name'),
                        args=raw['function'].get('arguments'),
                        id=call_id,
                        index=raw.get('index'),
                    )
                )
        except KeyError:
            pass
    usage_metadata = None
    if token_usage := data.get('usage'):
        usage_metadata = {
            'input_tokens': token_usage.get('prompt_tokens', 0),
            'output_tokens': token_usage.get('completion_tokens', 0),
            'total_tokens': token_usage.get('total_tokens', 0),
        }
    response_metadata: dict[str, Any] = {'model_provider': 'mistralai'}
    if choice.get('finish_reason') is not None and isinstance(data.get('model'), str):
        response_metadata['model_name'] = data['model']
        response_metadata['finish_reason'] = choice['finish_reason']
    chunk = AIMessageChunk(
        content=content,
        additional_kwargs=additional_kwargs,
        tool_call_chunks=tool_call_chunks,
        usage_metadata=usage_metadata,
        response_metadata=response_metadata,
    )
    return chunk, index, index_type


# ── HTTP helpers ─────────────────────────────────────────────────────────────


async def _raise_on_error(response: httpx.Response) -> None:
    if httpx.codes.is_error(response.status_code):
        error_message = (await response.aread()).decode('utf-8')
        raise httpx.HTTPStatusError(
            f'Error response {response.status_code} '
            f'while fetching {response.url}: {error_message}',
            request=response.request,
            response=response,
        )


class SSEError(httpx.TransportError):
    """A streaming reply is not a server-sent event stream."""


_SSE_LINE_BREAK = re.compile(r'\r\n|\r|\n')


async def _aiter_sse_data(response: httpx.Response) -> AsyncIterator[str]:
    """Yield the ``data`` of each server-sent event of ``response``."""
    content_type = response.headers.get('content-type', '').partition(';')[0]
    if 'text/event-stream' not in content_type:
        raise SSEError(
            "Expected response header Content-Type to contain 'text/event-stream', "
            f'got {content_type!r}'
        )
    buffer = ''
    data: list[str] = []
    dispatch = False
    async for text in response.aiter_text():
        buffer += text
        # A trailing '\r' may be the first half of '\r\n': keep it buffered.
        held = '\r' if buffer.endswith('\r') else ''
        lines = _SSE_LINE_BREAK.split(buffer.removesuffix(held))
        buffer = lines.pop() + held
        for line in lines:
            if not line:
                if dispatch:
                    yield '\n'.join(data)
                data = []
                dispatch = False
                continue
            if line.startswith(':'):
                continue
            field, _, value = line.partition(':')
            value = value.removeprefix(' ')
            if field == 'data':
                data.append(value)
                dispatch = True
            elif field in ('event', 'id', 'retry'):
                dispatch = True


# ── Embeddings ───────────────────────────────────────────────────────────────

# Most tokens sent in one embeddings request, across all its inputs.
EMBEDDINGS_MAX_BATCH_TOKENS = 16_000

_EMBEDDING_SETTINGS = frozenset(
    {
        'api_key',
        'mistral_api_key',
        'endpoint',
        'base_url',
        'max_retries',
        'timeout',
        'wait_time',
        'max_concurrent_requests',
        'model',
        'http_async_client',
    }
)


def _is_retryable(e: BaseException) -> bool:
    if isinstance(e, httpx.TimeoutException):
        return True
    if isinstance(e, httpx.HTTPStatusError):
        return e.response.status_code == 429 or e.response.status_code >= 500
    return False


class MistralEmbeddings(Embeddings):
    """Mistral embeddings via ``POST {endpoint}/embeddings``.

    Inputs are sent in batches of at most ``EMBEDDINGS_MAX_BATCH_TOKENS``,
    counting one token per character; the batches are sent concurrently.
    Timeouts, 429 and 5xx responses are retried after ``wait_time`` seconds,
    up to ``max_retries`` attempts.
    """

    def __init__(
        self,
        model_name: str,
        *,
        api_key: str | None = None,
        endpoint: str | None = None,
        max_retries: int | None = 5,
        timeout: float = 120,
        wait_time: float | None = 30,
        http_async_client: httpx.AsyncClient | None = None,
        **kwargs: Any,
    ):
        unknown = set(kwargs) - _EMBEDDING_SETTINGS
        if unknown:
            raise ValueError(
                f'Unsupported Mistral embeddings parameters: {sorted(unknown)}'
            )
        api_key = kwargs.get('mistral_api_key', api_key)
        if api_key is None:
            api_key = os.environ.get('MISTRAL_API_KEY', '')
        self.model_name = kwargs.get('model') or model_name
        self.endpoint = (
            endpoint or kwargs.get('base_url') or DEFAULT_EMBEDDINGS_ENDPOINT
        )
        self.max_retries = max_retries
        self.wait_time = wait_time
        self.timeout = timeout
        self.headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': f'Bearer {api_key}',
        }
        self.url = self.endpoint.rstrip('/') + '/embeddings'
        self.async_client = http_async_client
        self._sync_client: httpx.Client | None = None

    def _batches(self, texts: list[str]) -> Iterator[list[str]]:
        batch: list[str] = []
        batch_tokens = 0
        for text in texts:
            text_tokens = len(text)
            if batch_tokens + text_tokens > EMBEDDINGS_MAX_BATCH_TOKENS:
                if batch:
                    yield batch
                batch = [text]
                batch_tokens = text_tokens
            else:
                batch.append(text)
                batch_tokens += text_tokens
        if batch:
            yield batch

    def _attempts(self) -> int:
        if self.max_retries is None or self.wait_time is None:
            return 1
        return max(self.max_retries, 1)

    async def _aembed_batch(self, client: httpx.AsyncClient, batch: list[str]):
        attempt = 1
        while True:
            try:
                response = await client.post(
                    self.url,
                    json={'model': self.model_name, 'input': batch},
                    headers=self.headers,
                    timeout=self.timeout,
                )
                response.raise_for_status()
            except Exception as e:
                if attempt >= self._attempts() or not _is_retryable(e):
                    raise
                await asyncio.sleep(self.wait_time)
                attempt += 1
            else:
                return response

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        try:
            if self.async_client is not None:
                responses = await asyncio.gather(
                    *(
                        self._aembed_batch(self.async_client, b)
                        for b in self._batches(texts)
                    )
                )
            else:
                async with httpx.AsyncClient() as client:
                    responses = await asyncio.gather(
                        *(self._aembed_batch(client, b) for b in self._batches(texts))
                    )
            return _vectors(responses)
        except Exception:
            logger.exception('An error occurred with MistralAI')
            raise

    async def aembed_query(self, text: str) -> list[float]:
        return (await self.aembed_documents([text]))[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self._sync_client is None:
            self._sync_client = httpx.Client()
        try:
            responses = []
            for batch in self._batches(texts):
                attempt = 1
                while True:
                    try:
                        response = self._sync_client.post(
                            self.url,
                            json={'model': self.model_name, 'input': batch},
                            headers=self.headers,
                            timeout=self.timeout,
                        )
                        response.raise_for_status()
                        break
                    except Exception as e:
                        if attempt >= self._attempts() or not _is_retryable(e):
                            raise
                        time.sleep(self.wait_time)
                        attempt += 1
                responses.append(response)
            return _vectors(responses)
        except Exception:
            logger.exception('An error occurred with MistralAI')
            raise

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def _vectors(responses: list[httpx.Response]) -> list[list[float]]:
    return [
        list(map(float, item['embedding']))
        for response in responses
        for item in response.json()['data']
    ]
