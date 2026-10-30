"""OpenAI Responses API requests and replies.

LangChain's OpenAI integration switches a chat model to the Responses API for
some models (``codex``, ``*-pro``) and parameters (``reasoning``, ``text``,
``include``...). The gateway keeps that routing, so this module builds the same
payloads and returns replies in the same content-block format (a list of
blocks rather than a string).
"""

from collections.abc import AsyncIterator
import json
from typing import Any, Literal

from openai.types.responses import Response
from pydantic import BaseModel, ValidationError

from radicalbit_ai_gateway.llm.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    ToolMessage,
)
from radicalbit_ai_gateway.llm.providers._openai_common import (
    message_to_dict,
    to_response_format,
    usage_metadata,
)

_RESPONSES_ONLY_PREFIXES = (
    'gpt-5-pro',
    'gpt-5.2-pro',
    'gpt-5.4-pro',
    'gpt-5.5-pro',
    'gpt-5.6-sol',
)
_RESPONSES_ONLY_ARGS = (
    'context_management',
    'include',
    'previous_response_id',
    'reasoning',
    'text',
    'truncation',
)
# Output items kept verbatim as content blocks.
_PASSTHROUGH_ITEMS = (
    'compaction',
    'web_search_call',
    'file_search_call',
    'computer_call',
    'code_interpreter_call',
    'mcp_call',
    'mcp_list_tools',
    'mcp_approval_request',
    'image_generation_call',
    'tool_search_call',
    'tool_search_output',
    'apply_patch_call',
    'apply_patch_call_output',
)
# Content-block ids generated client side; the API rejects them.
_AUTO_ID_PREFIX = 'lc_'


def model_prefers_responses_api(model_name: str | None) -> bool:
    if not model_name:
        return False
    return model_name.startswith(_RESPONSES_ONLY_PREFIXES) or 'codex' in model_name


def payload_uses_responses_api(payload: dict) -> bool:
    builtin_tools = 'tools' in payload and any(
        'type' in tool and tool['type'] != 'function' for tool in payload['tools']
    )
    return bool(builtin_tools or set(_RESPONSES_ONLY_ARGS).intersection(payload))


def is_pydantic_class(obj: Any) -> bool:
    return isinstance(obj, type) and issubclass(obj, BaseModel)


# ── Request ──────────────────────────────────────────────────────────────────


def _chat_block_to_responses(block: dict) -> dict:
    if block['type'] == 'text':
        new_block = {'type': 'input_text', 'text': block['text']}
    elif block['type'] == 'image_url':
        new_block = {'type': 'input_image', 'image_url': block['image_url']['url']}
        if block['image_url'].get('detail'):
            new_block['detail'] = block['image_url']['detail']
    elif block['type'] == 'file':
        new_block = {'type': 'input_file', **block['file']}
    else:
        return block
    if 'prompt_cache_breakpoint' in block:
        new_block['prompt_cache_breakpoint'] = block['prompt_cache_breakpoint']
    return new_block


def _tool_output(content: Any) -> Any:
    if isinstance(content, str):
        return content
    if isinstance(content, list) and all(
        isinstance(block, dict)
        and block.get('type')
        in ('input_text', 'input_image', 'input_file', 'text', 'image_url', 'file')
        for block in content
    ):
        return [_chat_block_to_responses(block) for block in content]
    try:
        return json.dumps(content, ensure_ascii=False)
    except Exception:
        return str(content)


def _computer_call_output(message: ToolMessage) -> dict | None:
    output: dict | None = None
    if isinstance(message.content, list):
        for block in message.content:
            if (
                message.additional_kwargs.get('type') == 'computer_call_output'
                and isinstance(block, dict)
                and block.get('type') == 'input_image'
            ):
                output = {
                    'call_id': message.tool_call_id,
                    'type': 'computer_call_output',
                    'output': block,
                }
                break
            if (
                isinstance(block, dict)
                and block.get('type') == 'non_standard'
                and block.get('value', {}).get('type') == 'computer_call_output'
            ):
                output = block['value']
                break
    elif message.additional_kwargs.get('type') == 'computer_call_output':
        output = {
            'call_id': message.tool_call_id,
            'type': 'computer_call_output',
            'output': {'type': 'input_image', 'image_url': message.content},
        }
    if output is not None and 'acknowledged_safety_checks' in message.additional_kwargs:
        output['acknowledged_safety_checks'] = message.additional_kwargs[
            'acknowledged_safety_checks'
        ]
    return output


def _custom_tool_output(message: ToolMessage) -> dict | None:
    for block in message.content:
        if isinstance(block, dict) and block.get('type') == 'custom_tool_call_output':
            return {
                'type': 'custom_tool_call_output',
                'call_id': message.tool_call_id,
                'output': block.get('output') or '',
            }
        if (
            isinstance(block, dict)
            and block.get('type') == 'non_standard'
            and block.get('value', {}).get('type') == 'custom_tool_call_output'
        ):
            return block['value']
    return None


def _without_index(block: dict) -> dict:
    new_block = {k: v for k, v in block.items() if k != 'index'}
    if isinstance(new_block.get('summary'), list):
        new_block['summary'] = [
            {k: v for k, v in sub.items() if k != 'index'}
            for sub in new_block['summary']
        ]
    return new_block


def _annotation_from_block(annotation: dict) -> dict:
    if annotation.get('type') == 'file_citation' and 'file_index' in annotation:
        annotation = annotation.copy()
        annotation['index'] = annotation.pop('file_index')
    return annotation


def _annotation_to_block(annotation: dict) -> dict:
    # ``index`` is reserved for stream aggregation in content blocks.
    if annotation.get('type') == 'file_citation' and 'index' in annotation:
        annotation = annotation.copy()
        annotation['file_index'] = annotation.pop('index')
    return annotation


def _assistant_items(items: list, msg: dict, store: bool | None) -> None:
    content = msg.get('content')
    if isinstance(content, list):
        for block in content:
            if not (isinstance(block, dict) and (block_type := block.get('type'))):
                continue
            if block_type in ('text', 'output_text', 'refusal'):
                msg_id = block.get('id')
                phase = block.get('phase')
                if block_type == 'refusal':
                    new_block = {'type': 'refusal', 'refusal': block['refusal']}
                else:
                    if block.get('text') is None:
                        continue
                    new_block = {
                        'type': 'output_text',
                        'text': block['text'],
                        'annotations': [
                            _annotation_from_block(annotation)
                            for annotation in block.get('annotations') or []
                        ],
                    }
                for item in items:
                    if (item_id := item.get('id')) and item_id == msg_id:
                        item.setdefault('content', []).append(new_block)
                        if phase is not None:
                            item['phase'] = phase
                        break
                else:
                    new_item: dict = {
                        'type': 'message',
                        'content': [new_block],
                        'role': 'assistant',
                    }
                    if (
                        store is not False
                        and msg_id
                        and not msg_id.startswith(_AUTO_ID_PREFIX)
                    ):
                        new_item['id'] = msg_id
                    if phase is not None:
                        new_item['phase'] = phase
                    items.append(new_item)
            elif block_type == 'reasoning':
                if store is not False or block.get('encrypted_content'):
                    items.append(_without_index(block))
            elif block_type in (
                *_PASSTHROUGH_ITEMS,
                'function_call',
                'custom_tool_call',
            ):
                if block_type == 'image_generation_call':
                    if store is not False:
                        items.append(
                            {'type': 'image_generation_call', 'id': block['id']}
                        )
                    elif set(call := _without_index(block)) - {'type', 'id'}:
                        items.append(call)
                else:
                    items.append(_without_index(block))
    elif isinstance(content, str):
        items.append(
            {
                'type': 'message',
                'role': 'assistant',
                'content': [
                    {'type': 'output_text', 'text': content, 'annotations': []}
                ],
            }
        )

    if tool_calls := msg.pop('tool_calls', None):
        known_call_ids = {
            item['call_id']
            for item in items
            if item.get('type') in ('function_call', 'custom_tool_call')
            and 'call_id' in item
        }
        items.extend(
            {
                'type': 'function_call',
                'name': tc['function']['name'],
                'arguments': tc['function']['arguments'],
                'call_id': tc['id'],
            }
            for tc in tool_calls
            if tc['id'] not in known_call_ids
        )


def build_input(messages: list[BaseMessage], store: bool | None = None) -> list:
    """Translate the conversation into Responses API input items."""
    items: list = []
    for message in messages:
        msg = message_to_dict(message, api='responses')
        if not isinstance(message, AIMessage) and isinstance(msg['content'], list):
            for i, block in enumerate(msg['content']):
                if isinstance(block, dict) and block.get('type') == 'non_standard':
                    msg['content'][i] = block['value']
        msg.pop('name', None)
        if msg['role'] == 'tool':
            computer_output = _computer_call_output(message)
            custom_output = _custom_tool_output(message)
            if computer_output:
                items.append(computer_output)
            elif custom_output:
                items.append(custom_output)
            else:
                items.append(
                    {
                        'type': 'function_call_output',
                        'output': _tool_output(msg['content']),
                        'call_id': msg['tool_call_id'],
                    }
                )
        elif msg['role'] == 'assistant':
            _assistant_items(items, msg, store)
        elif msg['role'] in ('user', 'system', 'developer'):
            if isinstance(msg['content'], list):
                new_blocks = []
                for block in msg['content']:
                    if block['type'] in ('text', 'image_url', 'file'):
                        new_blocks.append(_chat_block_to_responses(block))
                    elif block['type'] in ('input_text', 'input_image', 'input_file'):
                        new_blocks.append(block)
                    elif block['type'] in (
                        'mcp_approval_response',
                        'tool_search_output',
                        'apply_patch_call_output',
                        'configuration_update',
                    ):
                        items.append(block)
                msg['content'] = new_blocks
                if msg['content']:
                    msg['type'] = 'message'
                    items.append(msg)
            else:
                msg['type'] = 'message'
                items.append(msg)
        else:
            items.append(msg)
    return items


def build_payload(messages: list[BaseMessage], payload: dict) -> dict:
    """Rewrite a Chat Completions payload into a Responses API one."""
    for legacy in ('max_tokens', 'max_completion_tokens'):
        if legacy in payload:
            payload['max_output_tokens'] = payload.pop(legacy)
    if 'reasoning_effort' in payload and 'reasoning' not in payload:
        payload['reasoning'] = {'effort': payload.pop('reasoning_effort')}
    # The Responses API has no stop sequences.
    payload.pop('stop', None)

    model = payload.get('model') or ''
    if (
        model.startswith('gpt-5')
        and 'chat' not in model
        and (payload.get('reasoning') or {}).get('effort') != 'none'
    ):
        payload.pop('temperature', None)

    payload['input'] = build_input(messages, store=payload.get('store'))
    if tools := payload.pop('tools', None):
        new_tools: list = []
        for tool in tools:
            if tool['type'] == 'function' and 'function' in tool:
                extra = {k: v for k, v in tool.items() if k not in ('type', 'function')}
                new_tools.append({'type': 'function', **tool['function'], **extra})
            else:
                if tool['type'] == 'image_generation':
                    if 'partial_images' in tool:
                        raise NotImplementedError(
                            'Partial image generation is not yet supported. Please '
                            "drop the 'partial_images' key from the image_generation "
                            'tool.'
                        )
                    if payload.get('stream'):
                        # Required by OpenAI when streaming; partials are ignored.
                        tool = {**tool, 'partial_images': 1}
                new_tools.append(tool)
        payload['tools'] = new_tools
    if tool_choice := payload.pop('tool_choice', None):
        if (
            isinstance(tool_choice, dict)
            and tool_choice['type'] == 'function'
            and 'function' in tool_choice
        ):
            payload['tool_choice'] = {'type': 'function', **tool_choice['function']}
        else:
            payload['tool_choice'] = tool_choice

    if isinstance(payload.get('text'), dict):
        payload['text'] = payload['text'].copy()

    if schema := payload.pop('response_format', None):
        strict = payload.pop('strict', None)
        if not payload.get('stream') and is_pydantic_class(schema):
            payload['text_format'] = schema
        else:
            if is_pydantic_class(schema):
                schema_dict = schema.model_json_schema()
                strict = True
            else:
                schema_dict = schema
            if schema_dict == {'type': 'json_object'}:
                text_format: dict | None = {'type': 'json_object'}
            elif (
                isinstance(
                    response_format := to_response_format(schema_dict, strict=strict),
                    dict,
                )
                and response_format['type'] == 'json_schema'
            ):
                text_format = {'type': 'json_schema', **response_format['json_schema']}
            else:
                text_format = None
            if text_format is not None:
                if isinstance(payload.get('text'), dict):
                    payload['text']['format'] = text_format
                else:
                    payload['text'] = {'format': text_format}

    verbosity = payload.pop('verbosity', None)
    if verbosity is not None:
        if isinstance(payload.get('text'), dict):
            payload['text']['verbosity'] = verbosity
        else:
            payload['text'] = {'verbosity': verbosity}
    return payload


# ── Reply ────────────────────────────────────────────────────────────────────


def _output_text(response: Any) -> str:
    return ''.join(
        content.text
        for output in response.output
        if output.type == 'message'
        for content in output.content
        if content.type == 'output_text'
    )


def response_to_message(
    response: Any, schema: Any = None, metadata: dict | None = None
) -> AIMessage:
    """Build the assistant message of a Responses API reply."""
    if response.error:
        raise ValueError(response.error)

    response_metadata = {
        k: v
        for k, v in response.model_dump(
            exclude_none=True, mode='json', warnings=False
        ).items()
        if k
        in (
            'created_at',
            'id',
            'incomplete_details',
            'metadata',
            'object',
            'status',
            'user',
            'model',
            'service_tier',
        )
    }
    if metadata:
        response_metadata.update(metadata)
    response_metadata['model_provider'] = 'openai'
    response_metadata['model_name'] = response_metadata.get('model')
    usage = (
        usage_metadata(
            response.usage.model_dump(), response.service_tier, responses_api=True
        )
        if response.usage
        else None
    )

    content: list = []
    tool_calls = []
    invalid_tool_calls = []
    additional_kwargs: dict = {}
    for output in response.output:
        if output.type == 'message':
            phase = getattr(output, 'phase', None)
            for part in output.content:
                if part.type == 'output_text':
                    block = {
                        'type': 'text',
                        'text': part.text,
                        'annotations': [
                            _annotation_to_block(annotation.model_dump())
                            for annotation in part.annotations
                        ]
                        if isinstance(part.annotations, list)
                        else [],
                        'id': output.id,
                    }
                    if phase is not None:
                        block['phase'] = phase
                    content.append(block)
                    if hasattr(part, 'parsed'):
                        additional_kwargs['parsed'] = part.parsed
                if part.type == 'refusal':
                    block = {
                        'type': 'refusal',
                        'refusal': part.refusal,
                        'id': output.id,
                    }
                    if phase is not None:
                        block['phase'] = phase
                    content.append(block)
        elif output.type == 'function_call':
            block = output.model_dump(exclude_none=True, mode='json')
            # Content blocks carry the wire name of the reserved word.
            if 'async_' in block:
                block['async'] = block.pop('async_')
            content.append(block)
            try:
                args = json.loads(output.arguments, strict=False)
                error = None
            except json.JSONDecodeError as e:
                args = output.arguments
                error = str(e)
            if error is None:
                tool_calls.append(
                    {
                        'type': 'tool_call',
                        'name': output.name,
                        'args': args,
                        'id': output.call_id,
                    }
                )
            else:
                invalid_tool_calls.append(
                    {
                        'type': 'invalid_tool_call',
                        'name': output.name,
                        'args': args,
                        'id': output.call_id,
                        'error': error,
                    }
                )
        elif output.type == 'custom_tool_call':
            content.append(output.model_dump(exclude_none=True, mode='json'))
            tool_calls.append(
                {
                    'type': 'tool_call',
                    'name': output.name,
                    'args': {'__arg1': output.input},
                    'id': output.call_id,
                }
            )
        elif output.type in ('reasoning', *_PASSTHROUGH_ITEMS):
            content.append(output.model_dump(exclude_none=True, mode='json'))

    output_text = _output_text(response)
    if (
        schema is not None
        and 'parsed' not in additional_kwargs
        and output_text
        and response.text
        and (text_config := response.text.model_dump())
        and (text_config.get('format', {}).get('type') == 'json_schema')
    ):
        try:
            parsed = json.loads(output_text)
            additional_kwargs['parsed'] = (
                schema(**parsed) if is_pydantic_class(schema) else parsed
            )
        except json.JSONDecodeError:
            pass

    return AIMessage(
        content=content,
        id=response.id,
        usage_metadata=usage,
        response_metadata=response_metadata,
        additional_kwargs=additional_kwargs,
        tool_calls=tool_calls,
        invalid_tool_calls=invalid_tool_calls,
    )


async def iter_sse_events(lines: AsyncIterator[str]) -> AsyncIterator[tuple[str, str]]:
    """Parse server-sent event lines into ``(event, data)`` pairs.

    An event without an ``event:`` field takes its name from the data's
    ``type``, as every Responses API stream event carries one. A ``[DONE]``
    terminator, which OpenAI does not send but compatible servers may, is
    skipped.
    """
    event = ''
    data: list[str] = []
    async for line in lines:
        if line.startswith('event:'):
            event = line[6:].strip()
        elif line.startswith('data:'):
            data.append(line[5:].removeprefix(' '))
        elif not line and data:
            payload = '\n'.join(data)
            if payload != '[DONE]':
                yield event or json.loads(payload).get('type', ''), payload
            event, data = '', []
    if data and data != ['[DONE]']:
        payload = '\n'.join(data)
        yield event or json.loads(payload).get('type', ''), payload


def _coerce_response(response: Any) -> Any:
    if isinstance(response, dict):
        try:
            return Response.model_validate(response)
        except ValidationError:
            return Response.model_construct(**response)
    return response


class StreamState:
    """Position of the current content block while a reply streams."""

    def __init__(self):
        self.index = -1
        self.output_index = -1
        self.sub_index = -1

    def advance(self, output_index: int, sub_index: int | None = None) -> None:
        if sub_index is None:
            if self.output_index != output_index:
                self.index += 1
        else:
            if self.output_index != output_index or self.sub_index != sub_index:
                self.index += 1
            self.sub_index = sub_index
        self.output_index = output_index


def event_to_chunk(
    event: Any, state: StreamState, schema: Any = None, metadata: dict | None = None
) -> AIMessageChunk | None:
    """Translate one Responses API stream event into a message chunk."""
    content: list = []
    tool_call_chunks: list = []
    additional_kwargs: dict = {}
    response_metadata = metadata or {}
    response_metadata['model_provider'] = 'openai'
    usage = None
    chunk_position: Literal['last'] | None = None
    chunk_id = None
    item = getattr(event, 'item', None)
    if event.type == 'response.output_text.delta':
        state.advance(event.output_index, event.content_index)
        content.append({'type': 'text', 'text': event.delta, 'index': state.index})
    elif event.type == 'response.output_text.annotation.added':
        state.advance(event.output_index, event.content_index)
        annotation = (
            event.annotation
            if isinstance(event.annotation, dict)
            else event.annotation.model_dump(exclude_none=True, mode='json')
        )
        content.append(
            {
                'type': 'text',
                'annotations': [_annotation_to_block(annotation)],
                'index': state.index,
            }
        )
    elif event.type == 'response.output_text.done':
        state.advance(event.output_index, event.content_index)
        content.append(
            {'type': 'text', 'text': '', 'id': event.item_id, 'index': state.index}
        )
    elif event.type == 'response.created':
        response = _coerce_response(event.response)
        chunk_id = response.id
        response_metadata['id'] = response.id
    elif event.type in ('response.completed', 'response.incomplete'):
        message = response_to_message(_coerce_response(event.response), schema=schema)
        if parsed := message.additional_kwargs.get('parsed'):
            additional_kwargs['parsed'] = parsed
        usage = message.usage_metadata
        response_metadata = {
            k: v for k, v in message.response_metadata.items() if k != 'id'
        }
        chunk_position = 'last'
    elif event.type == 'response.output_item.added' and item.type == 'message':
        if phase := getattr(item, 'phase', None):
            state.advance(event.output_index, 0)
            content.append(
                {'type': 'text', 'text': '', 'phase': phase, 'index': state.index}
            )
    elif event.type == 'response.output_item.added' and item.type == 'function_call':
        state.advance(event.output_index)
        tool_call_chunks.append(
            {
                'type': 'tool_call_chunk',
                'name': item.name,
                'args': item.arguments,
                'id': item.call_id,
                'index': state.index,
            }
        )
        block: dict = {
            'type': 'function_call',
            'name': item.name,
            'arguments': item.arguments,
            'call_id': item.call_id,
            'id': item.id,
            'index': state.index,
        }
        if getattr(item, 'namespace', None) is not None:
            block['namespace'] = item.namespace
        async_flag = getattr(item, 'async_', None)
        if async_flag is None:
            async_flag = getattr(item, 'async', None)
        if async_flag is not None:
            block['async'] = async_flag
        content.append(block)
    elif event.type == 'response.output_item.done' and item.type in _PASSTHROUGH_ITEMS:
        state.advance(event.output_index)
        block = item.model_dump(exclude_none=True, mode='json')
        block['index'] = state.index
        content.append(block)
    elif event.type == 'response.output_item.done' and item.type == 'custom_tool_call':
        state.advance(event.output_index)
        block = item.model_dump(exclude_none=True, mode='json')
        block['index'] = state.index
        content.append(block)
        tool_call_chunks.append(
            {
                'type': 'tool_call_chunk',
                'name': item.name,
                'args': json.dumps({'__arg1': item.input}),
                'id': item.call_id,
                'index': state.index,
            }
        )
    elif event.type == 'response.function_call_arguments.delta':
        state.advance(event.output_index)
        tool_call_chunks.append(
            {'type': 'tool_call_chunk', 'args': event.delta, 'index': state.index}
        )
        content.append(
            {'type': 'function_call', 'arguments': event.delta, 'index': state.index}
        )
    elif event.type == 'response.refusal.done':
        content.append({'type': 'refusal', 'refusal': event.refusal})
    elif event.type == 'response.output_item.added' and item.type == 'reasoning':
        state.advance(event.output_index)
        state.sub_index = 0
        reasoning = item.model_dump(exclude_none=True, mode='json')
        # The encrypted content is complete only on the ``done`` event.
        reasoning.pop('encrypted_content', None)
        reasoning['index'] = state.index
        content.append(reasoning)
    elif (
        event.type == 'response.output_item.done'
        and item.type == 'reasoning'
        and item.encrypted_content
    ):
        state.advance(event.output_index)
        content.append(
            {
                'type': 'reasoning',
                'id': item.id,
                'summary': [],
                'encrypted_content': item.encrypted_content,
                'index': state.index,
            }
        )
    elif event.type == 'response.reasoning_summary_part.added':
        state.advance(event.output_index)
        content.append(
            {
                'summary': [
                    {'index': event.summary_index, 'type': 'summary_text', 'text': ''}
                ],
                'index': state.index,
                'type': 'reasoning',
                'id': event.item_id,
            }
        )
    elif event.type == 'response.reasoning_summary_text.delta':
        state.advance(event.output_index)
        content.append(
            {
                'summary': [
                    {
                        'index': event.summary_index,
                        'type': 'summary_text',
                        'text': event.delta,
                    }
                ],
                'index': state.index,
                'type': 'reasoning',
            }
        )
    else:
        return None

    return AIMessageChunk(
        content=content,
        tool_call_chunks=tool_call_chunks,
        usage_metadata=usage,
        response_metadata=response_metadata,
        additional_kwargs=additional_kwargs,
        id=chunk_id,
        chunk_position=chunk_position,
    )
