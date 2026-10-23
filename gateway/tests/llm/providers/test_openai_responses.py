"""Tests for the OpenAI Responses API path of the native OpenAI chat model."""

import json

from httpx_aiohttp import HttpxAiohttpClient
from pydantic import BaseModel
import pytest

# Loads the scenario registry before the OpenAI scenarios module it imports.
from tests.common import provider_responses as canned
from tests.common.provider_recorder import CannedResponse, ProviderRecorder
from tests.common.provider_responses import (
    _response_body,
    openai_response,
    openai_response_stream,
)

from radicalbit_ai_gateway.llm.factory import init_chat_model
from radicalbit_ai_gateway.llm.messages import (
    AIMessage,
    FunctionMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from radicalbit_ai_gateway.llm.providers._openai_responses import (
    model_prefers_responses_api,
)
from radicalbit_ai_gateway.llm.providers.openai import ChatOpenAI

URL = 'https://api.openai.com/v1/responses'
MESSAGES = [HumanMessage('Hi')]
WEATHER_TOOL = {
    'type': 'function',
    'function': {
        'name': 'get_weather',
        'parameters': {'type': 'object', 'properties': {'city': {'type': 'string'}}},
    },
    'strict': True,
}


def model(name='gpt-4o-mini', **kwargs) -> ChatOpenAI:
    kwargs.setdefault('http_async_client', HttpxAiohttpClient())
    kwargs.setdefault('use_responses_api', True)
    return init_chat_model(f'openai:{name}', api_key='sk', **kwargs)


def build(messages, chat_model=None, **kwargs) -> dict:
    chat_model = chat_model or model()
    return chat_model._get_request_payload(messages, **chat_model._call_kwargs(kwargs))


async def invoke(chat_model, responses, messages=MESSAGES, **kwargs):
    with ProviderRecorder(responses) as recorder:
        result = await chat_model.ainvoke(messages, **kwargs)
    return result, recorder.requests


async def stream(chat_model, responses, messages=MESSAGES, **kwargs):
    with ProviderRecorder(responses) as recorder:
        chunks = [c async for c in chat_model.astream(messages, **kwargs)]
    return chunks, recorder.requests


def response(output, **overrides) -> CannedResponse:
    body = _response_body(output, 'gpt-4o-mini')
    body.update(overrides)
    return CannedResponse(json_body=body)


def events_stream(*events, final_output=(), final_type='response.completed'):
    body = _response_body([], 'gpt-4o-mini', status='in_progress')
    final = _response_body(list(final_output), 'gpt-4o-mini')
    if final_type == 'response.incomplete':
        final['status'] = 'incomplete'
        final['incomplete_details'] = {'reason': 'max_output_tokens'}
    all_events = [
        {'type': 'response.created', 'response': body},
        *events,
        {'type': final_type, 'response': final},
    ]
    for i, event in enumerate(all_events):
        event['sequence_number'] = i
    return CannedResponse(sse_events=all_events)


class Judgement(BaseModel):
    """A verdict."""

    ok: bool


# ── Routing ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ('name', 'expected'),
    [
        (None, False),
        ('gpt-4o', False),
        ('gpt-5-pro', True),
        ('gpt-5.1-codex-mini', True),
    ],
)
def test_models_that_prefer_the_responses_api(name, expected):
    assert model_prefers_responses_api(name) is expected


@pytest.mark.parametrize(
    'settings',
    [
        {'include': ['reasoning.encrypted_content']},
        {'truncation': 'auto'},
        {'reasoning': {'effort': 'low'}},
        {'context_management': [{'type': 'compaction'}]},
        {'output_version': 'responses/v1'},
    ],
)
async def test_responses_only_settings_switch_the_api(settings):
    chat_model = model(use_responses_api=None, **settings)
    _, requests = await invoke(chat_model, [openai_response()])
    assert requests[0]['url'] == URL


async def test_builtin_tools_switch_the_api():
    chat_model = model(use_responses_api=None).bind_tools([{'type': 'web_search'}])
    _, requests = await invoke(chat_model, [openai_response()])
    assert requests[0]['url'] == URL
    assert requests[0]['body']['tools'] == [{'type': 'web_search'}]


# ── Request payload ──────────────────────────────────────────────────────────


def test_parameters_are_rewritten_for_the_responses_api():
    body = build(
        MESSAGES,
        model('gpt-5', temperature=1, reasoning_effort='low', verbosity='low'),
        max_tokens=10,
        stop=['END'],
        text={'format': {'type': 'text'}},
    )
    assert body == {
        'model': 'gpt-5',
        'stream': False,
        'max_output_tokens': 10,
        'reasoning': {'effort': 'low'},
        'text': {'format': {'type': 'text'}, 'verbosity': 'low'},
        'input': [{'content': 'Hi', 'role': 'user', 'type': 'message'}],
    }


def test_gpt5_keeps_temperature_without_reasoning():
    body = build(MESSAGES, model('gpt-5', reasoning={'effort': 'none'}, temperature=1))
    assert body['temperature'] == 1
    assert build(MESSAGES, model('gpt-5', verbosity='high'))['text'] == {
        'verbosity': 'high'
    }


def test_tools_and_tool_choice_are_flattened():
    chat_model = model().bind_tools(
        [WEATHER_TOOL, {'type': 'image_generation', 'quality': 'low'}],
        tool_choice='get_weather',
    )
    body = build(MESSAGES, chat_model)
    assert body['tools'] == [
        {
            'type': 'function',
            'name': 'get_weather',
            'parameters': {
                'type': 'object',
                'properties': {'city': {'type': 'string'}},
            },
            'strict': True,
        },
        {'type': 'image_generation', 'quality': 'low'},
    ]
    assert body['tool_choice'] == {'type': 'function', 'name': 'get_weather'}

    streamed = build(MESSAGES, chat_model, stream=True)
    assert streamed['tools'][1] == {
        'type': 'image_generation',
        'quality': 'low',
        'partial_images': 1,
    }
    assert build(MESSAGES, model().bind_tools([WEATHER_TOOL], tool_choice='auto'))[
        'tool_choice'
    ] == ('auto')


def test_partial_image_generation_is_rejected():
    chat_model = model().bind_tools([{'type': 'image_generation', 'partial_images': 2}])
    with pytest.raises(NotImplementedError, match='Partial image generation'):
        build(MESSAGES, chat_model)


@pytest.mark.parametrize(
    ('response_format', 'stream', 'text'),
    [
        ({'type': 'json_object'}, False, {'format': {'type': 'json_object'}}),
        (
            {'type': 'json_schema', 'json_schema': {'name': 'a', 'schema': {}}},
            False,
            {'format': {'type': 'json_schema', 'name': 'a', 'schema': {}}},
        ),
        (
            Judgement,
            True,
            {
                'format': {
                    'type': 'json_schema',
                    'name': 'Judgement',
                    'description': 'A verdict.',
                    'strict': True,
                    'schema': {
                        'type': 'object',
                        # Property titles survive the JSON-schema round trip.
                        'properties': {'ok': {'title': 'Ok', 'type': 'boolean'}},
                        'required': ['ok'],
                        'additionalProperties': False,
                    },
                }
            },
        ),
    ],
)
def test_response_format_becomes_text_format(response_format, stream, text):
    body = build(MESSAGES, response_format=response_format, stream=stream)
    assert 'response_format' not in body
    assert body['text'] == text


def test_response_format_merges_into_text_settings():
    body = build(
        MESSAGES,
        model(verbosity='low'),
        text={'verbosity': 'high'},
        response_format={'type': 'json_object'},
    )
    assert body['text'] == {'verbosity': 'low', 'format': {'type': 'json_object'}}


def test_user_and_system_content_blocks():
    content = [
        {'type': 'text', 'text': 'look', 'prompt_cache_breakpoint': True},
        {
            'type': 'image_url',
            'image_url': {'url': 'https://x/i.png', 'detail': 'high'},
        },
        {'type': 'file', 'file': {'file_id': 'file-1'}},
        {'type': 'input_text', 'text': 'raw'},
        {'type': 'mcp_approval_response', 'approval_request_id': 'r', 'approve': True},
        {'type': 'non_standard', 'value': {'type': 'input_text', 'text': 'ns'}},
        {'type': 'unknown_block'},
    ]
    messages = [
        SystemMessage([{'type': 'text', 'text': 'Be terse.'}]),
        HumanMessage(content, name='alice'),
        HumanMessage([{'type': 'unknown_block'}]),
        FunctionMessage('42', name='f'),
    ]
    assert build(messages)['input'] == [
        {
            'content': [{'type': 'input_text', 'text': 'Be terse.'}],
            'role': 'system',
            'type': 'message',
        },
        {'type': 'mcp_approval_response', 'approval_request_id': 'r', 'approve': True},
        {
            'content': [
                {'type': 'input_text', 'text': 'look', 'prompt_cache_breakpoint': True},
                {
                    'type': 'input_image',
                    'image_url': 'https://x/i.png',
                    'detail': 'high',
                },
                {'type': 'input_file', 'file_id': 'file-1'},
                {'type': 'input_text', 'text': 'raw'},
                {'type': 'input_text', 'text': 'ns'},
            ],
            'role': 'user',
            'type': 'message',
        },
        {'content': '42', 'role': 'function'},
    ]


def test_assistant_history_becomes_output_items():
    reasoning = {
        'type': 'reasoning',
        'id': 'rs_1',
        'summary': [{'type': 'summary_text', 'text': 'hm', 'index': 0}],
        'index': 0,
    }
    history = AIMessage(
        [
            reasoning,
            {
                'type': 'text',
                'text': 'See',
                'id': 'msg_1',
                'phase': 'final',
                'annotations': [{'type': 'file_citation', 'file_index': 3}],
            },
            {'type': 'text', 'text': ' this.', 'id': 'msg_1'},
            {'type': 'refusal', 'refusal': 'No.', 'id': 'msg_2', 'phase': 'final'},
            {'type': 'text', 'text': None, 'id': 'msg_3'},
            {'type': 'output_text', 'text': 'auto id', 'id': 'lc_abc'},
            {
                'type': 'web_search_call',
                'id': 'ws_1',
                'status': 'completed',
                'index': 4,
            },
            {'type': 'image_generation_call', 'id': 'ig_1', 'result': 'AAAA'},
            {
                'type': 'function_call',
                'call_id': 'call_1',
                'name': 'f',
                'arguments': '{}',
            },
            'bare string',
        ],
        tool_calls=[
            {'name': 'f', 'args': {}, 'id': 'call_1'},
            {'name': 'g', 'args': {'x': 1}, 'id': 'call_2'},
        ],
    )
    assert build([history])['input'] == [
        {
            'type': 'reasoning',
            'id': 'rs_1',
            'summary': [{'type': 'summary_text', 'text': 'hm'}],
        },
        {
            'type': 'message',
            'content': [
                {
                    'type': 'output_text',
                    'text': 'See',
                    'annotations': [{'type': 'file_citation', 'index': 3}],
                },
                {'type': 'output_text', 'text': ' this.', 'annotations': []},
            ],
            'role': 'assistant',
            'id': 'msg_1',
            'phase': 'final',
        },
        {
            'type': 'message',
            'content': [{'type': 'refusal', 'refusal': 'No.'}],
            'role': 'assistant',
            'id': 'msg_2',
            'phase': 'final',
        },
        {
            'type': 'message',
            'content': [{'type': 'output_text', 'text': 'auto id', 'annotations': []}],
            'role': 'assistant',
        },
        {'type': 'web_search_call', 'id': 'ws_1', 'status': 'completed'},
        {'type': 'image_generation_call', 'id': 'ig_1'},
        {'type': 'function_call', 'call_id': 'call_1', 'name': 'f', 'arguments': '{}'},
        {
            'type': 'function_call',
            'name': 'g',
            'arguments': '{"x": 1}',
            'call_id': 'call_2',
        },
    ]


def test_assistant_history_without_store():
    history = AIMessage(
        [
            {'type': 'reasoning', 'id': 'rs_1', 'summary': []},
            {
                'type': 'reasoning',
                'id': 'rs_2',
                'summary': [],
                'encrypted_content': 'E',
            },
            {'type': 'text', 'text': 'Hi', 'id': 'msg_1'},
            {'type': 'image_generation_call', 'id': 'ig_1'},
            {'type': 'image_generation_call', 'id': 'ig_2', 'result': 'AAAA'},
        ]
    )
    assert build([history], model(store=False))['input'] == [
        {'type': 'reasoning', 'id': 'rs_2', 'summary': [], 'encrypted_content': 'E'},
        {
            'type': 'message',
            'content': [{'type': 'output_text', 'text': 'Hi', 'annotations': []}],
            'role': 'assistant',
        },
        {'type': 'image_generation_call', 'id': 'ig_2', 'result': 'AAAA'},
    ]


def test_plain_assistant_text_history():
    assert build([AIMessage('Hello')])['input'] == [
        {
            'type': 'message',
            'role': 'assistant',
            'content': [{'type': 'output_text', 'text': 'Hello', 'annotations': []}],
        }
    ]


def test_tool_results_become_output_items():
    messages = [
        ToolMessage('sunny', tool_call_id='c1'),
        ToolMessage(
            [
                {'type': 'text', 'text': 'see'},
                {'type': 'image_url', 'image_url': {'url': 'https://x/i.png'}},
            ],
            tool_call_id='c2',
        ),
        ToolMessage([{'type': 'json', 'json': {'a': 1}}], tool_call_id='c3'),
        ToolMessage(
            'https://x/screen.png',
            tool_call_id='c4',
            additional_kwargs={
                'type': 'computer_call_output',
                'acknowledged_safety_checks': [{'id': 's'}],
            },
        ),
        ToolMessage(
            [{'type': 'input_image', 'image_url': 'https://x/s.png'}],
            tool_call_id='c5',
            additional_kwargs={'type': 'computer_call_output'},
        ),
        ToolMessage(
            [
                {
                    'type': 'non_standard',
                    'value': {'type': 'computer_call_output', 'call_id': 'c6'},
                }
            ],
            tool_call_id='c6',
        ),
        ToolMessage(
            [{'type': 'custom_tool_call_output', 'output': 'done'}], tool_call_id='c7'
        ),
        ToolMessage(
            [
                {
                    'type': 'non_standard',
                    'value': {'type': 'custom_tool_call_output', 'call_id': 'c8'},
                }
            ],
            tool_call_id='c8',
        ),
    ]
    assert build(messages)['input'] == [
        {'type': 'function_call_output', 'output': 'sunny', 'call_id': 'c1'},
        {
            'type': 'function_call_output',
            'output': [
                {'type': 'input_text', 'text': 'see'},
                {'type': 'input_image', 'image_url': 'https://x/i.png'},
            ],
            'call_id': 'c2',
        },
        {
            'type': 'function_call_output',
            'output': '[{"type": "json", "json": {"a": 1}}]',
            'call_id': 'c3',
        },
        {
            'call_id': 'c4',
            'type': 'computer_call_output',
            'output': {'type': 'input_image', 'image_url': 'https://x/screen.png'},
            'acknowledged_safety_checks': [{'id': 's'}],
        },
        {
            'call_id': 'c5',
            'type': 'computer_call_output',
            'output': {'type': 'input_image', 'image_url': 'https://x/s.png'},
        },
        {'type': 'computer_call_output', 'call_id': 'c6'},
        {'type': 'custom_tool_call_output', 'call_id': 'c7', 'output': 'done'},
        {'type': 'custom_tool_call_output', 'call_id': 'c8'},
    ]


def test_previous_response_id_trims_the_history():
    messages = [
        HumanMessage('Hi'),
        AIMessage('Hello', response_metadata={'id': 'resp_1'}),
        HumanMessage('Again'),
    ]
    body = build(messages, model(use_previous_response_id=True))
    assert body['previous_response_id'] == 'resp_1'
    assert body['input'] == [{'content': 'Again', 'role': 'user', 'type': 'message'}]


# ── Replies ──────────────────────────────────────────────────────────────────


async def test_reply_output_items():
    output = [
        {
            'type': 'message',
            'id': 'msg_1',
            'status': 'completed',
            'role': 'assistant',
            'phase': 'final_answer',
            'content': [
                {
                    'type': 'output_text',
                    'text': 'See',
                    'annotations': [
                        {
                            'type': 'file_citation',
                            'file_id': 'f',
                            'filename': 'a.pdf',
                            'index': 2,
                        }
                    ],
                },
                {'type': 'refusal', 'refusal': 'No.'},
            ],
        },
        {
            'type': 'function_call',
            'id': 'fc_1',
            'call_id': 'call_bad',
            'name': 'f',
            'arguments': '{"x": ',
            'status': 'completed',
        },
        {
            'type': 'custom_tool_call',
            'id': 'ct_1',
            'call_id': 'call_custom',
            'name': 'grammar',
            'input': 'a+b',
        },
        {
            'type': 'web_search_call',
            'id': 'ws_1',
            'status': 'completed',
            'action': {'type': 'search', 'query': 'q'},
        },
    ]
    result, _ = await invoke(
        model(include_response_headers=True), [response(output)], MESSAGES
    )
    assert result.content == [
        {
            'type': 'text',
            'text': 'See',
            'annotations': [
                {
                    'type': 'file_citation',
                    'file_id': 'f',
                    'filename': 'a.pdf',
                    'file_index': 2,
                }
            ],
            'id': 'msg_1',
            'phase': 'final_answer',
        },
        {'type': 'refusal', 'refusal': 'No.', 'id': 'msg_1', 'phase': 'final_answer'},
        {
            'arguments': '{"x": ',
            'call_id': 'call_bad',
            'name': 'f',
            'type': 'function_call',
            'id': 'fc_1',
            'status': 'completed',
        },
        {
            'call_id': 'call_custom',
            'input': 'a+b',
            'name': 'grammar',
            'type': 'custom_tool_call',
            'id': 'ct_1',
        },
        {
            'id': 'ws_1',
            'action': {'query': 'q', 'type': 'search'},
            'status': 'completed',
            'type': 'web_search_call',
        },
    ]
    assert result.tool_calls == [
        {
            'name': 'grammar',
            'args': {'__arg1': 'a+b'},
            'id': 'call_custom',
            'type': 'tool_call',
        }
    ]
    assert result.invalid_tool_calls[0]['id'] == 'call_bad'
    assert result.invalid_tool_calls[0]['args'] == '{"x": '
    assert result.response_metadata['headers']['content-type'] == 'application/json'
    assert result.response_metadata['model_provider'] == 'openai'
    assert result.response_metadata['model_name'] == 'gpt-4o-mini'


async def test_reply_usage_with_service_tier_and_without_usage():
    result, _ = await invoke(model(), [response([], service_tier='priority')], MESSAGES)
    assert result.usage_metadata == {
        'input_tokens': 21,
        'output_tokens': 7,
        'total_tokens': 28,
        'input_token_details': {'priority_cache_read': 4, 'priority': 17},
        'output_token_details': {'priority_reasoning': 3, 'priority': 4},
    }
    result, _ = await invoke(model(), [response([], usage=None)], MESSAGES)
    assert result.usage_metadata is None


async def test_reply_error_is_raised():
    error = {'code': 'server_error', 'message': 'boom'}
    with pytest.raises(ValueError, match='boom'):
        await invoke(model(), [response([], error=error)], MESSAGES)


async def test_structured_output_is_parsed_by_the_sdk():
    structured = model().with_structured_output(Judgement)
    message = {
        'type': 'message',
        'id': 'msg_1',
        'status': 'completed',
        'role': 'assistant',
        'content': [{'type': 'output_text', 'text': '{"ok": true}', 'annotations': []}],
    }
    result, requests = await invoke(structured, [response([message])])
    assert result == Judgement(ok=True)
    assert requests[0]['body']['text']['format']['name'] == 'Judgement'


async def test_structured_output_refusal_raises():
    structured = model().with_structured_output(Judgement, include_raw=True)
    message = {
        'type': 'message',
        'id': 'msg_1',
        'status': 'completed',
        'role': 'assistant',
        'content': [{'type': 'refusal', 'refusal': 'No.'}],
    }
    result, _ = await invoke(structured, [response([message])])
    assert result['parsed'] is None
    assert 'Structured Output response' in str(result['parsing_error'])


async def test_json_schema_reply_is_parsed_into_a_dict():
    schema = {'type': 'json_schema', 'json_schema': {'name': 'a', 'schema': {}}}
    text = {'format': {'type': 'json_schema', 'name': 'a', 'schema': {}}}
    good = response(canned_message('{"a": 1}'), text=text)
    bad = response(canned_message('not json'), text=text)
    result, _ = await invoke(model(), [good], response_format=schema)
    assert result.additional_kwargs == {'parsed': {'a': 1}}
    result, _ = await invoke(model(), [bad], response_format=schema)
    assert result.additional_kwargs == {}


def canned_message(text):
    return [
        {
            'type': 'message',
            'id': 'msg_1',
            'status': 'completed',
            'role': 'assistant',
            'content': [{'type': 'output_text', 'text': text, 'annotations': []}],
        }
    ]


# ── Streaming ────────────────────────────────────────────────────────────────


def blocks(chunks, block_type):
    return [
        {k: v for k, v in block.items() if k != 'index'}
        for chunk in chunks
        for block in chunk.content
        if isinstance(block, dict) and block.get('type') == block_type
    ]


async def test_stream_text_reasoning_and_tool_calls():
    chunks, requests = await stream(
        model(include_response_headers=True),
        [openai_response_stream(tool_calls=[canned.WEATHER_TOOL_CALL])],
    )
    assert requests[0]['body']['stream'] is True
    assert chunks[0].id == 'resp_golden_1'
    assert chunks[0].response_metadata['headers']['content-type'] == (
        'text/event-stream'
    )
    assert 'headers' not in chunks[1].response_metadata
    assert blocks(chunks, 'reasoning') == [
        {'type': 'reasoning', 'id': 'rs_golden_1', 'summary': []},
        {
            'summary': [{'index': 0, 'type': 'summary_text', 'text': ''}],
            'type': 'reasoning',
            'id': 'rs_golden_1',
        },
        {
            'summary': [{'index': 0, 'type': 'summary_text', 'text': 'Thinking.'}],
            'type': 'reasoning',
        },
    ]
    assert [b['text'] for b in blocks(chunks, 'text')] == [
        'Hello',
        ' from',
        ' the model',
        '',
    ]
    calls = blocks(chunks, 'function_call')
    assert calls[0] == {
        'type': 'function_call',
        'name': 'get_weather',
        'arguments': '',
        'call_id': 'call_weather_1',
        'id': 'fc_golden_1',
    }
    assert (
        ''.join(c['arguments'] for c in calls)
        == canned.WEATHER_TOOL_CALL['function']['arguments']
    )
    last = chunks[-1]
    assert last.chunk_position == 'last'
    assert last.usage_metadata['input_token_details'] == {'cache_read': 4}
    assert last.response_metadata['status'] == 'completed'


async def test_stream_annotations_refusal_and_passthrough_items():
    web_search = {
        'type': 'web_search_call',
        'id': 'ws_1',
        'status': 'completed',
        'action': {'type': 'search', 'query': 'q'},
    }
    custom = {
        'type': 'custom_tool_call',
        'id': 'ct_1',
        'call_id': 'call_custom',
        'name': 'grammar',
        'input': 'a+b',
    }
    reasoning = {
        'type': 'reasoning',
        'id': 'rs_1',
        'summary': [],
        'encrypted_content': 'ENC',
    }
    events = events_stream(
        {
            'type': 'response.output_item.added',
            'output_index': 0,
            'item': {
                'type': 'message',
                'id': 'msg_1',
                'status': 'in_progress',
                'role': 'assistant',
                'phase': 'commentary',
                'content': [],
            },
        },
        {
            'type': 'response.output_text.annotation.added',
            'item_id': 'msg_1',
            'output_index': 0,
            'content_index': 0,
            'annotation_index': 0,
            'annotation': {
                'type': 'file_citation',
                'file_id': 'f',
                'filename': 'a.pdf',
                'index': 1,
            },
        },
        {
            'type': 'response.refusal.done',
            'item_id': 'msg_1',
            'output_index': 0,
            'content_index': 1,
            'refusal': 'No.',
        },
        {'type': 'response.output_item.done', 'output_index': 1, 'item': web_search},
        {'type': 'response.output_item.done', 'output_index': 2, 'item': custom},
        {'type': 'response.output_item.done', 'output_index': 3, 'item': reasoning},
        {'type': 'response.in_progress', 'response': {}},
        final_output=[custom],
        final_type='response.incomplete',
    )
    chunks, _ = await stream(model(), [events])
    content = [block for chunk in chunks for block in chunk.content]
    assert content == [
        {'type': 'text', 'text': '', 'phase': 'commentary', 'index': 0},
        {
            'type': 'text',
            'annotations': [
                {
                    'type': 'file_citation',
                    'file_id': 'f',
                    'filename': 'a.pdf',
                    'file_index': 1,
                }
            ],
            'index': 0,
        },
        {'type': 'refusal', 'refusal': 'No.'},
        {**web_search, 'index': 1},
        {**custom, 'index': 2},
        {**reasoning, 'index': 3},
    ]
    tool_chunk = next(c for c in chunks if c.tool_call_chunks).tool_call_chunks[0]
    assert tool_chunk == {
        'name': 'grammar',
        'args': '{"__arg1": "a+b"}',
        'id': 'call_custom',
        'index': 2,
        'type': 'tool_call_chunk',
    }
    last = chunks[-1]
    assert last.chunk_position == 'last'
    assert last.response_metadata['incomplete_details'] == {
        'reason': 'max_output_tokens'
    }


async def test_stream_structured_output_is_parsed_on_completion():
    text = {
        'format': {
            'type': 'json_schema',
            'name': 'Judgement',
            'schema': {'type': 'object'},
            'strict': True,
        }
    }
    events = events_stream(final_output=canned_message('{"ok": false}'))
    events.sse_events[-1]['response']['text'] = text
    chunks, requests = await stream(model(), [events], response_format=Judgement)
    assert requests[0]['body']['text']['format']['strict'] is True
    assert chunks[-1].additional_kwargs == {'parsed': Judgement(ok=False)}


async def test_stream_reasoning_kwarg_routes_to_the_responses_api():
    chunks, requests = await stream(
        model(use_responses_api=None),
        [openai_response_stream(parts=None, reasoning=None)],
        reasoning={'effort': 'low'},
    )
    assert requests[0]['url'] == URL
    assert json.dumps(requests[0]['body']['reasoning']) == '{"effort": "low"}'
    assert chunks[-1].chunk_position == 'last'
