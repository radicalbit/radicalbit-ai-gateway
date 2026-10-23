"""Canned provider responses in each provider's native wire format."""

import json

from tests.common.provider_recorder import CannedResponse

# ── OpenAI-compatible (openai, azure-openai, deepseek, mistralai, ollama) ─────


def openai_completion(
    content: str | None = 'Hello from the model',
    *,
    model: str = 'gpt-4o-mini-2024-07-18',
    tool_calls: list[dict] | None = None,
    finish_reason: str = 'stop',
    prompt_tokens: int = 21,
    completion_tokens: int = 7,
    cached_tokens: int = 0,
    extra_message: dict | None = None,
) -> CannedResponse:
    message = {'role': 'assistant', 'content': content, 'refusal': None}
    if tool_calls:
        message['tool_calls'] = tool_calls
    message.update(extra_message or {})
    return CannedResponse(
        json_body={
            'id': 'chatcmpl-provider-1',
            'object': 'chat.completion',
            'created': 1730000000,
            'model': model,
            'system_fingerprint': 'fp_golden',
            'choices': [
                {
                    'index': 0,
                    'message': message,
                    'logprobs': None,
                    'finish_reason': finish_reason,
                }
            ],
            'usage': {
                'prompt_tokens': prompt_tokens,
                'completion_tokens': completion_tokens,
                'total_tokens': prompt_tokens + completion_tokens,
                'prompt_tokens_details': {
                    'cached_tokens': cached_tokens,
                    'audio_tokens': 0,
                },
                'completion_tokens_details': {
                    'reasoning_tokens': 0,
                    'audio_tokens': 0,
                    'accepted_prediction_tokens': 0,
                    'rejected_prediction_tokens': 0,
                },
            },
        }
    )


def _openai_chunk(delta: dict, finish_reason=None, model='gpt-4o-mini-2024-07-18'):
    return {
        'id': 'chatcmpl-provider-1',
        'object': 'chat.completion.chunk',
        'created': 1730000000,
        'model': model,
        'system_fingerprint': 'fp_golden',
        'choices': [
            {
                'index': 0,
                'delta': delta,
                'logprobs': None,
                'finish_reason': finish_reason,
            }
        ],
    }


def openai_stream(
    parts: list[str] = ('Hello', ' from', ' the model'),
    *,
    model: str = 'gpt-4o-mini-2024-07-18',
    tool_calls: list[dict] | None = None,
    prompt_tokens: int = 21,
    completion_tokens: int = 7,
    cached_tokens: int = 0,
    include_usage: bool = True,
    extra_first_delta: dict | None = None,
) -> CannedResponse:
    events = [
        _openai_chunk(
            {
                'role': 'assistant',
                'content': '',
                'refusal': None,
                **(extra_first_delta or {}),
            },
            model=model,
        )
    ]
    events += [_openai_chunk({'content': p}, model=model) for p in parts]
    for i, tc in enumerate(tool_calls or []):
        events.append(
            _openai_chunk(
                {
                    'tool_calls': [
                        {
                            'index': i,
                            'id': tc['id'],
                            'type': 'function',
                            'function': {
                                'name': tc['function']['name'],
                                'arguments': '',
                            },
                        }
                    ]
                },
                model=model,
            )
        )
        args = tc['function']['arguments']
        half = len(args) // 2
        for piece in (args[:half], args[half:]):
            events.append(
                _openai_chunk(
                    {'tool_calls': [{'index': i, 'function': {'arguments': piece}}]},
                    model=model,
                )
            )
    events.append(
        _openai_chunk(
            {}, finish_reason='tool_calls' if tool_calls else 'stop', model=model
        )
    )
    if include_usage:
        events.append(
            {
                'id': 'chatcmpl-provider-1',
                'object': 'chat.completion.chunk',
                'created': 1730000000,
                'model': model,
                'system_fingerprint': 'fp_golden',
                'choices': [],
                'usage': {
                    'prompt_tokens': prompt_tokens,
                    'completion_tokens': completion_tokens,
                    'total_tokens': prompt_tokens + completion_tokens,
                    'prompt_tokens_details': {
                        'cached_tokens': cached_tokens,
                        'audio_tokens': 0,
                    },
                    'completion_tokens_details': {
                        'reasoning_tokens': 0,
                        'audio_tokens': 0,
                        'accepted_prediction_tokens': 0,
                        'rejected_prediction_tokens': 0,
                    },
                },
            }
        )
    events.append('[DONE]')
    return CannedResponse(sse_events=events)


def error(status: int = 500, message: str = 'upstream exploded') -> CannedResponse:
    return CannedResponse(
        status=status,
        json_body={'error': {'message': message, 'type': 'server_error', 'code': None}},
    )


WEATHER_TOOL_CALL = {
    'id': 'call_weather_1',
    'type': 'function',
    'function': {'name': 'get_weather', 'arguments': '{"city": "Paris", "unit": "c"}'},
}


# ── Anthropic Messages API ────────────────────────────────────────────────────

_ANTHROPIC_MODEL = 'claude-sonnet-4-5-20250929'


def _anthropic_usage(input_tokens, output_tokens, cache_read, cache_5m, cache_1h):
    return {
        'input_tokens': input_tokens,
        'output_tokens': output_tokens,
        'cache_creation_input_tokens': cache_5m + cache_1h,
        'cache_read_input_tokens': cache_read,
        'cache_creation': {
            'ephemeral_5m_input_tokens': cache_5m,
            'ephemeral_1h_input_tokens': cache_1h,
        },
        'service_tier': 'standard',
    }


def anthropic_message(
    text: str | None = 'Hello from the model',
    *,
    tool_use: list[dict] | None = None,
    input_tokens: int = 21,
    output_tokens: int = 7,
    cache_read: int = 0,
    cache_5m: int = 0,
    cache_1h: int = 0,
) -> CannedResponse:
    content = []
    if text is not None:
        content.append({'type': 'text', 'text': text})
    content.extend({'type': 'tool_use', **tu} for tu in tool_use or [])
    return CannedResponse(
        json_body={
            'id': 'msg_provider_1',
            'type': 'message',
            'role': 'assistant',
            'model': _ANTHROPIC_MODEL,
            'content': content,
            'stop_reason': 'tool_use' if tool_use else 'end_turn',
            'stop_sequence': None,
            'usage': _anthropic_usage(
                input_tokens, output_tokens, cache_read, cache_5m, cache_1h
            ),
        }
    )


def anthropic_stream(
    parts: list[str] = ('Hello', ' from', ' the model'),
    *,
    tool_use: list[dict] | None = None,
    input_tokens: int = 21,
    output_tokens: int = 7,
    cache_read: int = 0,
    cache_5m: int = 0,
    cache_1h: int = 0,
) -> CannedResponse:
    start_usage = _anthropic_usage(input_tokens, 1, cache_read, cache_5m, cache_1h)
    events = [
        {
            'type': 'message_start',
            'message': {
                'id': 'msg_provider_1',
                'type': 'message',
                'role': 'assistant',
                'model': _ANTHROPIC_MODEL,
                'content': [],
                'stop_reason': None,
                'stop_sequence': None,
                'usage': start_usage,
            },
        }
    ]
    index = 0
    if parts:
        events.append(
            {
                'type': 'content_block_start',
                'index': index,
                'content_block': {'type': 'text', 'text': ''},
            }
        )
        events += [
            {
                'type': 'content_block_delta',
                'index': index,
                'delta': {'type': 'text_delta', 'text': p},
            }
            for p in parts
        ]
        events.append({'type': 'content_block_stop', 'index': index})
        index += 1
    for tu in tool_use or []:
        events.append(
            {
                'type': 'content_block_start',
                'index': index,
                'content_block': {
                    'type': 'tool_use',
                    'id': tu['id'],
                    'name': tu['name'],
                    'input': {},
                },
            }
        )
        raw = json.dumps(tu['input'])
        half = len(raw) // 2
        for piece in (raw[:half], raw[half:]):
            events.append(
                {
                    'type': 'content_block_delta',
                    'index': index,
                    'delta': {'type': 'input_json_delta', 'partial_json': piece},
                }
            )
        events.append({'type': 'content_block_stop', 'index': index})
        index += 1
    events.append(
        {
            'type': 'message_delta',
            'delta': {
                'stop_reason': 'tool_use' if tool_use else 'end_turn',
                'stop_sequence': None,
            },
            'usage': {'output_tokens': output_tokens},
        }
    )
    events.append({'type': 'message_stop'})
    return CannedResponse(sse_events=events, sse_format='anthropic')


ANTHROPIC_WEATHER_TOOL_USE = {
    'id': 'toolu_weather_1',
    'name': 'get_weather',
    'input': {'city': 'Paris', 'unit': 'c'},
}


# ── Google Gemini (generateContent) ───────────────────────────────────────────


def _gemini_payload(parts, finish_reason, usage):
    payload = {
        'candidates': [
            {
                'content': {'parts': parts, 'role': 'model'},
                'index': 0,
            }
        ],
        'modelVersion': 'gemini-2.5-flash',
        'responseId': 'gemini-provider-1',
    }
    if finish_reason:
        payload['candidates'][0]['finishReason'] = finish_reason
    if usage:
        payload['usageMetadata'] = usage
    return payload


def _gemini_usage(prompt_tokens, output_tokens, cached_tokens):
    usage = {
        'promptTokenCount': prompt_tokens,
        'candidatesTokenCount': output_tokens,
        'totalTokenCount': prompt_tokens + output_tokens,
        'promptTokensDetails': [{'modality': 'TEXT', 'tokenCount': prompt_tokens}],
    }
    if cached_tokens:
        usage['cachedContentTokenCount'] = cached_tokens
    return usage


def gemini_response(
    text: str | None = 'Hello from the model',
    *,
    function_calls: list[dict] | None = None,
    prompt_tokens: int = 21,
    output_tokens: int = 7,
    cached_tokens: int = 0,
) -> CannedResponse:
    parts = []
    if text is not None:
        parts.append({'text': text})
    parts += [{'functionCall': fc} for fc in function_calls or []]
    return CannedResponse(
        json_body=_gemini_payload(
            parts, 'STOP', _gemini_usage(prompt_tokens, output_tokens, cached_tokens)
        )
    )


def gemini_stream(
    parts: list[str] = ('Hello', ' from', ' the model'),
    *,
    function_calls: list[dict] | None = None,
    prompt_tokens: int = 21,
    output_tokens: int = 7,
    cached_tokens: int = 0,
) -> CannedResponse:
    events = [
        _gemini_payload(
            [{'text': p}],
            None,
            _gemini_usage(prompt_tokens, i + 1, cached_tokens),
        )
        for i, p in enumerate(parts)
    ]
    if function_calls:
        events.append(
            _gemini_payload(
                [{'functionCall': fc} for fc in function_calls],
                None,
                _gemini_usage(prompt_tokens, output_tokens - 1, cached_tokens),
            )
        )
    events.append(
        _gemini_payload(
            [{'text': ''}],
            'STOP',
            _gemini_usage(prompt_tokens, output_tokens, cached_tokens),
        )
    )
    return CannedResponse(sse_events=events)


GEMINI_WEATHER_CALL = {'name': 'get_weather', 'args': {'city': 'Paris', 'unit': 'c'}}


# ── Mistral ───────────────────────────────────────────────────────────────────

MISTRAL_WEATHER_TOOL_CALL = {
    'id': 'Wx1Abc2De',
    'type': 'function',
    'function': {'name': 'get_weather', 'arguments': '{"city": "Paris", "unit": "c"}'},
}


def mistral_completion(
    content: str | None = 'Hello from the model',
    *,
    tool_calls: list[dict] | None = None,
    prompt_tokens: int = 21,
    completion_tokens: int = 7,
) -> CannedResponse:
    return CannedResponse(
        json_body={
            'id': 'mistral-provider-1',
            'object': 'chat.completion',
            'created': 1730000000,
            'model': 'mistral-small-latest',
            'choices': [
                {
                    'index': 0,
                    'message': {
                        'role': 'assistant',
                        'content': content or '',
                        'tool_calls': tool_calls,
                    },
                    'finish_reason': 'tool_calls' if tool_calls else 'stop',
                }
            ],
            'usage': {
                'prompt_tokens': prompt_tokens,
                'completion_tokens': completion_tokens,
                'total_tokens': prompt_tokens + completion_tokens,
            },
        }
    )


def mistral_stream(
    parts: list[str] = ('Hello', ' from', ' the model'),
    *,
    tool_calls: list[dict] | None = None,
    prompt_tokens: int = 21,
    completion_tokens: int = 7,
) -> CannedResponse:
    def chunk(delta, finish_reason=None, usage=None):
        body = {
            'id': 'mistral-provider-1',
            'object': 'chat.completion.chunk',
            'created': 1730000000,
            'model': 'mistral-small-latest',
            'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish_reason}],
        }
        if usage:
            body['usage'] = usage
        return body

    events = [chunk({'role': 'assistant', 'content': ''})]
    events += [chunk({'content': p}) for p in parts]
    if tool_calls:
        events.append(chunk({'tool_calls': tool_calls}))
    events.append(
        chunk(
            {'content': ''},
            finish_reason='tool_calls' if tool_calls else 'stop',
            usage={
                'prompt_tokens': prompt_tokens,
                'completion_tokens': completion_tokens,
                'total_tokens': prompt_tokens + completion_tokens,
            },
        )
    )
    events.append('[DONE]')
    return CannedResponse(sse_events=events)


# ── Embeddings ────────────────────────────────────────────────────────────────


def openai_embeddings(count: int = 2, dims: int = 4, prompt_tokens: int = 8):
    return CannedResponse(
        json_body={
            'object': 'list',
            'data': [
                {
                    'object': 'embedding',
                    'index': i,
                    'embedding': [
                        round(0.1 * (i + 1) + 0.01 * d, 4) for d in range(dims)
                    ],
                }
                for i in range(count)
            ],
            'model': 'text-embedding-3-small',
            'usage': {'prompt_tokens': prompt_tokens, 'total_tokens': prompt_tokens},
        }
    )


def gemini_embeddings(count: int = 2, dims: int = 4):
    return CannedResponse(
        json_body={
            'embeddings': [
                {'values': [round(0.1 * (i + 1) + 0.01 * d, 4) for d in range(dims)]}
                for i in range(count)
            ]
        }
    )


# ── Responses API wire format ─────────────────────────────────────────────────

_RESPONSE_ID = 'resp_golden_1'
_MESSAGE_ITEM_ID = 'msg_golden_1'
_REASONING_ITEM_ID = 'rs_golden_1'
_FUNCTION_ITEM_ID = 'fc_golden_1'


def _message_item(text: str) -> dict:
    return {
        'type': 'message',
        'id': _MESSAGE_ITEM_ID,
        'status': 'completed',
        'role': 'assistant',
        'content': [{'type': 'output_text', 'text': text, 'annotations': []}],
    }


def _reasoning_item(summary: str) -> dict:
    return {
        'type': 'reasoning',
        'id': _REASONING_ITEM_ID,
        'summary': [{'type': 'summary_text', 'text': summary}],
    }


def _function_call_item(tool_call: dict) -> dict:
    return {
        'type': 'function_call',
        'id': _FUNCTION_ITEM_ID,
        'call_id': tool_call['id'],
        'name': tool_call['function']['name'],
        'arguments': tool_call['function']['arguments'],
        'status': 'completed',
    }


def _response_body(output: list[dict], model: str, status: str = 'completed'):
    return {
        'id': _RESPONSE_ID,
        'object': 'response',
        'created_at': 1730000000,
        'status': status,
        'model': model,
        'output': output,
        'error': None,
        'incomplete_details': None,
        'instructions': None,
        'metadata': {},
        'parallel_tool_calls': True,
        'temperature': 1.0,
        'top_p': 1.0,
        'tool_choice': 'auto',
        'tools': [],
        'text': {'format': {'type': 'text'}},
        'usage': {
            'input_tokens': 21,
            'input_tokens_details': {'cached_tokens': 4},
            'output_tokens': 7,
            'output_tokens_details': {'reasoning_tokens': 3},
            'total_tokens': 28,
        }
        if status == 'completed'
        else None,
    }


def _response_output(
    text: str | None, reasoning: str | None, tool_calls: list[dict] | None
) -> list[dict]:
    output = []
    if reasoning is not None:
        output.append(_reasoning_item(reasoning))
    if text is not None:
        output.append(_message_item(text))
    output += [_function_call_item(tc) for tc in tool_calls or []]
    return output


def openai_response(
    text: str | None = 'Hello from the model',
    *,
    model: str = 'gpt-5-codex',
    reasoning: str | None = 'Thinking.',
    tool_calls: list[dict] | None = None,
) -> CannedResponse:
    return CannedResponse(
        json_body=_response_body(_response_output(text, reasoning, tool_calls), model)
    )


def openai_response_stream(
    parts: list[str] | None = ('Hello', ' from', ' the model'),
    *,
    model: str = 'gpt-5-codex',
    reasoning: str | None = 'Thinking.',
    tool_calls: list[dict] | None = None,
) -> CannedResponse:
    text = ''.join(parts) if parts is not None else None
    final = _response_body(_response_output(text, reasoning, tool_calls), model)
    events: list[dict] = [
        {
            'type': 'response.created',
            'response': _response_body([], model, status='in_progress'),
        },
        {
            'type': 'response.in_progress',
            'response': _response_body([], model, status='in_progress'),
        },
    ]
    index = 0
    if reasoning is not None:
        item = {'type': 'reasoning', 'id': _REASONING_ITEM_ID, 'summary': []}
        events += [
            {'type': 'response.output_item.added', 'output_index': index, 'item': item},
            {
                'type': 'response.reasoning_summary_part.added',
                'item_id': _REASONING_ITEM_ID,
                'output_index': index,
                'summary_index': 0,
                'part': {'type': 'summary_text', 'text': ''},
            },
            {
                'type': 'response.reasoning_summary_text.delta',
                'item_id': _REASONING_ITEM_ID,
                'output_index': index,
                'summary_index': 0,
                'delta': reasoning,
            },
            {
                'type': 'response.reasoning_summary_text.done',
                'item_id': _REASONING_ITEM_ID,
                'output_index': index,
                'summary_index': 0,
                'text': reasoning,
            },
            {
                'type': 'response.output_item.done',
                'output_index': index,
                'item': _reasoning_item(reasoning),
            },
        ]
        index += 1
    if parts is not None:
        item = {
            'type': 'message',
            'id': _MESSAGE_ITEM_ID,
            'status': 'in_progress',
            'role': 'assistant',
            'content': [],
        }
        events += [
            {'type': 'response.output_item.added', 'output_index': index, 'item': item},
            {
                'type': 'response.content_part.added',
                'item_id': _MESSAGE_ITEM_ID,
                'output_index': index,
                'content_index': 0,
                'part': {'type': 'output_text', 'text': '', 'annotations': []},
            },
            *(
                {
                    'type': 'response.output_text.delta',
                    'item_id': _MESSAGE_ITEM_ID,
                    'output_index': index,
                    'content_index': 0,
                    'delta': part,
                }
                for part in parts
            ),
            {
                'type': 'response.output_text.done',
                'item_id': _MESSAGE_ITEM_ID,
                'output_index': index,
                'content_index': 0,
                'text': text,
            },
            {
                'type': 'response.content_part.done',
                'item_id': _MESSAGE_ITEM_ID,
                'output_index': index,
                'content_index': 0,
                'part': {'type': 'output_text', 'text': text, 'annotations': []},
            },
            {
                'type': 'response.output_item.done',
                'output_index': index,
                'item': _message_item(text),
            },
        ]
        index += 1
    for tc in tool_calls or []:
        done = _function_call_item(tc)
        args = done['arguments']
        half = len(args) // 2
        events += [
            {
                'type': 'response.output_item.added',
                'output_index': index,
                'item': {**done, 'arguments': '', 'status': 'in_progress'},
            },
            *(
                {
                    'type': 'response.function_call_arguments.delta',
                    'item_id': _FUNCTION_ITEM_ID,
                    'output_index': index,
                    'delta': piece,
                }
                for piece in (args[:half], args[half:])
            ),
            {
                'type': 'response.function_call_arguments.done',
                'item_id': _FUNCTION_ITEM_ID,
                'output_index': index,
                'arguments': args,
            },
            {'type': 'response.output_item.done', 'output_index': index, 'item': done},
        ]
        index += 1
    events.append({'type': 'response.completed', 'response': final})
    for i, event in enumerate(events):
        event['sequence_number'] = i
    return CannedResponse(sse_events=events)


def openai_completion_with(**json_overrides) -> CannedResponse:
    """Build a chat completion with some top-level JSON fields overridden."""
    response = openai_completion()
    response.json_body.update(json_overrides)
    return response
