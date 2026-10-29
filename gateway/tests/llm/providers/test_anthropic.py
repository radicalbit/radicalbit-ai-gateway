"""Tests for the native Anthropic chat model."""

from unittest.mock import Mock

import anthropic
from pydantic import BaseModel, ValidationError
import pytest

from tests.common import provider_responses as canned
from tests.common.provider_recorder import CannedResponse, ProviderRecorder

from radicalbit_ai_gateway.llm.factory import init_chat_model
from radicalbit_ai_gateway.llm.messages import (
    AIMessage,
    FunctionMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from radicalbit_ai_gateway.llm.providers import anthropic as anthropic_provider
from radicalbit_ai_gateway.llm.providers.anthropic import (
    ChatAnthropic,
    OutputParserError,
    _default_http_client,
    _normalize_tool_call_id,
)

URL = 'https://api.anthropic.com/v1/messages'
MESSAGES = [HumanMessage('Hi')]
WEATHER_TOOL = {
    'type': 'function',
    'function': {
        'name': 'get_weather',
        'description': 'Get the weather.',
        'parameters': {'type': 'object', 'properties': {'city': {'type': 'string'}}},
    },
}
WEATHER_USE = canned.ANTHROPIC_WEATHER_TOOL_USE


def model(name: str = 'claude-sonnet-4-5', **kwargs) -> ChatAnthropic:
    return init_chat_model(f'anthropic:{name}', api_key='sk', **kwargs)


async def invoke(chat_model, responses, messages=MESSAGES, **kwargs):
    with ProviderRecorder(responses) as recorder:
        result = await chat_model.ainvoke(messages, **kwargs)
    return result, recorder.requests


async def stream(chat_model, responses, messages=MESSAGES, **kwargs):
    with ProviderRecorder(responses) as recorder:
        chunks = [c async for c in chat_model.astream(messages, **kwargs)]
    return chunks, recorder.requests


class Judgement(BaseModel):
    """A verdict."""

    ok: bool
    why: str | None = None


def stream_events(*blocks, stop_reason='end_turn', usage=None):
    events = [
        {
            'type': 'message_start',
            'message': {
                'id': 'msg_1',
                'type': 'message',
                'role': 'assistant',
                'model': 'claude-x',
                'content': [],
                'stop_reason': None,
                'stop_sequence': None,
                'usage': {'input_tokens': 9, 'output_tokens': 1},
            },
        },
        *blocks,
        {
            'type': 'message_delta',
            'delta': {'stop_reason': stop_reason, 'stop_sequence': None},
            'usage': usage or {'output_tokens': 4},
        },
        {'type': 'message_stop'},
    ]
    return CannedResponse(sse_events=events, sse_format='anthropic')


# ── construction ─────────────────────────────────────────────────────────────


def test_factory_builds_native_model():
    assert isinstance(model(), ChatAnthropic)


@pytest.mark.parametrize(
    ('name', 'max_tokens'),
    [
        ('claude-sonnet-4-5', 64000),
        ('claude-haiku-4-5-20251001', 64000),
        ('claude-opus-4-7', 128000),
        ('claude-3-5-sonnet-latest', 4096),
    ],
)
async def test_default_max_tokens_follows_model_profile(name, max_tokens):
    _, requests = await invoke(model(name), [canned.anthropic_message()])
    assert requests[0]['body']['max_tokens'] == max_tokens


async def test_configured_params_reach_the_body():
    chat_model = model(temperature=0.2, top_k=3, max_tokens=128, stop=['END'])
    _, requests = await invoke(chat_model, [canned.anthropic_message()])
    request = requests[0]
    assert request['url'] == URL
    assert request['headers']['x-api-key'] == 'sk'
    assert request['body'] == {
        'model': 'claude-sonnet-4-5',
        'max_tokens': 128,
        'messages': [{'role': 'user', 'content': 'Hi'}],
        'stop_sequences': ['END'],
        'temperature': 0.2,
        'top_k': 3,
    }


async def test_unknown_params_are_sent_as_is():
    _, requests = await invoke(model(service_tier='auto'), [canned.anthropic_message()])
    assert requests[0]['body']['service_tier'] == 'auto'


async def test_unknown_param_the_sdk_rejects_raises_type_error():
    with pytest.raises(TypeError):
        await invoke(model(api_version='2024'), [canned.anthropic_message()])


async def test_base_url_and_betas():
    chat_model = model(base_url='http://proxy.local:9000', betas=['b-1'])
    _, requests = await invoke(chat_model, [canned.anthropic_message()])
    assert requests[0]['url'] == 'http://proxy.local:9000/v1/messages'
    assert requests[0]['query'] == [('beta', 'true')]
    assert requests[0]['headers']['anthropic-beta'] == 'b-1'


def test_http_client_has_no_timeout_and_is_shared():
    first, second = model().client, model().client
    assert first.timeout is None
    assert first.max_retries == 2
    assert first._client is second._client
    assert first._client is _default_http_client(
        base_url='https://api.anthropic.com', timeout=None
    )


# ── request payload ─────────────────────────────────────────────────────────


async def test_call_kwargs_override_and_stop_maps_to_stop_sequences():
    _, requests = await invoke(
        model(temperature=0.2),
        [canned.anthropic_message()],
        temperature=0.5,
        max_tokens=10,
        stop=['X'],
    )
    body = requests[0]['body']
    assert body['temperature'] == 0.5
    assert body['max_tokens'] == 10
    assert body['stop_sequences'] == ['X']


async def test_system_blocks_keep_cache_control():
    messages = [
        SystemMessage(
            content=[
                {'type': 'text', 'text': 'Cached.', 'cache_control': {'type': 'x'}}
            ]
        ),
        HumanMessage('Hi'),
    ]
    _, requests = await invoke(model(), [canned.anthropic_message()], messages)
    assert requests[0]['body']['system'] == [
        {'type': 'text', 'text': 'Cached.', 'cache_control': {'type': 'x'}}
    ]


def test_non_consecutive_system_messages_are_rejected():
    with pytest.raises(ValueError, match='non-consecutive system'):
        model()._request_payload(
            [SystemMessage('a'), HumanMessage('b'), SystemMessage('c')]
        )


def test_function_messages_have_no_anthropic_role():
    with pytest.raises(KeyError):
        model()._request_payload([FunctionMessage('x', name='f')])


def test_tool_round_trip_is_merged_into_user_turns():
    payload = model()._request_payload(
        [
            HumanMessage('Weather?'),
            AIMessage(
                'Checking.  ',
                tool_calls=[{'name': 'get_weather', 'args': {'c': 1}, 'id': 'a:b.c'}],
            ),
            ToolMessage('sunny', tool_call_id='a:b.c'),
            ToolMessage('rainy', tool_call_id='toolu_2'),
            AIMessage('Done.  '),
        ]
    )
    normalized = _normalize_tool_call_id('a:b.c')
    assert normalized.startswith('toolu_')
    assert payload['messages'] == [
        {'role': 'user', 'content': 'Weather?'},
        {
            'role': 'assistant',
            'content': [
                {'type': 'text', 'text': 'Checking.  '},
                {
                    'type': 'tool_use',
                    'name': 'get_weather',
                    'input': {'c': 1},
                    'id': normalized,
                },
            ],
        },
        {
            'role': 'user',
            'content': [
                {
                    'type': 'tool_result',
                    'content': 'sunny',
                    'tool_use_id': normalized,
                    'is_error': False,
                },
                {
                    'type': 'tool_result',
                    'content': 'rainy',
                    'tool_use_id': 'toolu_2',
                    'is_error': False,
                },
            ],
        },
        {'role': 'assistant', 'content': 'Done.'},
    ]


def test_multimodal_blocks():
    payload = model()._request_payload(
        [
            HumanMessage(
                content=[
                    {'type': 'text', 'text': 'Look'},
                    {'type': 'text', 'text': '  '},
                    {
                        'type': 'image',
                        'source_type': 'base64',
                        'data': 'AAA',
                        'mime_type': 'image/png',
                    },
                    {'type': 'image_url', 'image_url': {'url': 'https://x.test/a.png'}},
                    {
                        'type': 'file',
                        'source_type': 'base64',
                        'data': 'PDF',
                        'mime_type': 'application/pdf',
                        'filename': 'a.pdf',
                    },
                ]
            )
        ]
    )
    assert payload['messages'][0]['content'] == [
        {'type': 'text', 'text': 'Look'},
        {
            'type': 'image',
            'source': {'type': 'base64', 'media_type': 'image/png', 'data': 'AAA'},
        },
        {'type': 'image', 'source': {'type': 'url', 'url': 'https://x.test/a.png'}},
        {
            'type': 'document',
            'source': {
                'type': 'base64',
                'media_type': 'application/pdf',
                'data': 'PDF',
            },
        },
    ]


def test_response_format_becomes_output_config_format():
    payload = model()._request_payload(
        MESSAGES,
        response_format={
            'type': 'json_schema',
            'json_schema': {
                'name': 'g',
                'schema': {'type': 'object', 'properties': {'g': {'type': 'string'}}},
            },
        },
    )
    assert 'response_format' not in payload
    assert payload['output_config']['format']['type'] == 'json_schema'


@pytest.mark.parametrize(
    ('name', 'thinking'),
    [
        ('claude-sonnet-4-5', None),
        ('claude-opus-4-7', {'type': 'adaptive', 'display': 'summarized'}),
    ],
)
def test_reasoning_effort(name, thinking):
    payload = model(name)._request_payload(MESSAGES, reasoning_effort='low')
    assert payload['output_config'] == {'effort': 'low'}
    assert payload.get('thinking') == thinking
    assert 'reasoning_effort' not in payload


# ── tools ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ('tool_choice', 'expected'),
    [
        ('auto', {'type': 'auto'}),
        ('any', {'type': 'any'}),
        # Any other string names a tool, OpenAI's 'required' included.
        ('required', {'type': 'tool', 'name': 'required'}),
        (
            {'type': 'function', 'function': {'name': 'get_weather'}},
            {'type': 'function', 'function': {'name': 'get_weather'}},
        ),
    ],
)
def test_bind_tools(tool_choice, expected):
    payload = (
        model()
        .bind_tools([WEATHER_TOOL], tool_choice=tool_choice)
        ._request_payload(MESSAGES)
    )
    assert payload['tools'] == [
        {
            'name': 'get_weather',
            'input_schema': WEATHER_TOOL['function']['parameters'],
            'description': 'Get the weather.',
        }
    ]
    assert payload['tool_choice'] == expected


def test_builtin_tools_pass_through_and_composition_tools_are_dropped():
    builtin = {'type': 'web_fetch_20250910', 'name': 'web_fetch'}
    any_of = {
        'type': 'function',
        'function': {'name': 'bad', 'parameters': {'anyOf': [{'type': 'object'}]}},
    }
    with pytest.warns(UserWarning, match='Dropping tool'):
        bound = model().bind_tools([WEATHER_TOOL, builtin, any_of], tool_choice='auto')
    payload = bound._request_payload(MESSAGES)
    assert [t['name'] for t in payload['tools']] == ['get_weather', 'web_fetch']
    assert payload['betas'] == ['web-fetch-2025-09-10']


# ── replies ─────────────────────────────────────────────────────────────────


async def test_text_reply():
    result, _ = await invoke(model(), [canned.anthropic_message('Hello')])
    assert result.content == 'Hello'
    assert result.id.startswith('run-')
    assert result.tool_calls == []
    assert result.response_metadata['stop_reason'] == 'end_turn'
    assert result.response_metadata['model_name'] == 'claude-sonnet-4-5-20250929'
    assert result.response_metadata['model_provider'] == 'anthropic'
    assert result.response_metadata['usage']['input_tokens'] == 21


async def test_text_and_tool_use_reply():
    result, _ = await invoke(
        model(), [canned.anthropic_message('Let me check.', tool_use=[WEATHER_USE])]
    )
    assert [block['type'] for block in result.content] == ['text', 'tool_use']
    assert result.tool_calls == [
        {
            'name': 'get_weather',
            'args': {'city': 'Paris', 'unit': 'c'},
            'id': 'toolu_weather_1',
            'type': 'tool_call',
        }
    ]


async def test_usage_counts_cache_reads_and_writes_as_input():
    result, _ = await invoke(
        model(),
        [canned.anthropic_message(input_tokens=30, cache_read=1000, cache_5m=200)],
    )
    assert result.usage_metadata == {
        'input_tokens': 1230,
        'output_tokens': 7,
        'total_tokens': 1237,
        'input_token_details': {
            'cache_read': 1000,
            'cache_creation': 0,
            'ephemeral_5m_input_tokens': 200,
            'ephemeral_1h_input_tokens': 0,
        },
    }


async def test_errors_propagate():
    with pytest.raises(anthropic.BadRequestError):
        await invoke(model(), [canned.error(400, 'bad request')])


# ── streaming ───────────────────────────────────────────────────────────────


async def test_text_stream():
    chunks, requests = await stream(model(), [canned.anthropic_stream()])
    assert requests[0]['body']['stream'] is True
    assert [c.content for c in chunks] == ['', 'Hello', ' from', ' the model', '']
    assert chunks[0].response_metadata == {
        'model_name': 'claude-sonnet-4-5-20250929',
        'model_provider': 'anthropic',
    }
    last = chunks[-1]
    assert last.chunk_position == 'last'
    assert last.response_metadata['stop_reason'] == 'end_turn'
    assert last.usage_metadata['output_tokens'] == 7
    assert len({c.id for c in chunks}) == 1


async def test_tool_stream_carries_tool_call_chunks_and_no_content():
    chunks, _ = await stream(
        model().bind_tools([WEATHER_TOOL], tool_choice='auto'),
        [canned.anthropic_stream(['Let me'], tool_use=[WEATHER_USE])],
    )
    assert [c.content for c in chunks] == ['', 'Let me', '', '', '', '']
    tool_chunks = [tc for c in chunks for tc in c.tool_call_chunks]
    assert tool_chunks[0] == {
        'name': 'get_weather',
        'args': '',
        'id': 'toolu_weather_1',
        'index': 1,
        'type': 'tool_call_chunk',
    }
    assert ''.join(tc['args'] for tc in tool_chunks) == (
        '{"city": "Paris", "unit": "c"}'
    )


async def test_thinking_and_tool_input_on_start_event():
    events = stream_events(
        {
            'type': 'content_block_start',
            'index': 0,
            'content_block': {'type': 'thinking', 'thinking': '', 'signature': ''},
        },
        {
            'type': 'content_block_delta',
            'index': 0,
            'delta': {'type': 'thinking_delta', 'thinking': 'hmm'},
        },
        {
            'type': 'content_block_start',
            'index': 1,
            'content_block': {'type': 'text', 'text': 'Hi'},
        },
        {
            'type': 'content_block_start',
            'index': 2,
            'content_block': {
                'type': 'tool_use',
                'id': 'toolu_2',
                'name': 'f',
                'input': {'a': 1},
            },
        },
        usage={'output_tokens': 4, 'cache_read_input_tokens': 2},
    )
    chunks, _ = await stream(model(), [events])
    assert [c.content for c in chunks] == ['', '', 'Hi', '', '']
    assert chunks[3].tool_call_chunks[0]['args'] == '{"a": 1}'
    assert chunks[-1].usage_metadata['input_tokens'] == 2


async def test_stream_without_usage():
    chunks, _ = await stream(model(stream_usage=False), [canned.anthropic_stream()])
    assert [c.content for c in chunks] == ['Hello', ' from', ' the model', '']
    assert all(c.usage_metadata is None for c in chunks)


async def test_stream_errors_propagate():
    with pytest.raises(anthropic.BadRequestError):
        await stream(model(), [canned.error(400)])


# ── structured output ───────────────────────────────────────────────────────


def judgement(args, name='Judgement'):
    return canned.anthropic_message(
        None, tool_use=[{'id': 'toolu_j', 'name': name, 'input': args}]
    )


async def test_structured_output_forces_the_schema_tool():
    structured = model().with_structured_output(Judgement, include_raw=True)
    with ProviderRecorder([judgement({'ok': True})]) as recorder:
        result = await structured.ainvoke(MESSAGES)
    body = recorder.requests[0]['body']
    assert body['tool_choice'] == {'type': 'tool', 'name': 'Judgement'}
    assert body['tools'] == [
        {
            'name': 'Judgement',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'ok': {'type': 'boolean'},
                    'why': {
                        'anyOf': [{'type': 'string'}, {'type': 'null'}],
                        'default': None,
                    },
                },
                'required': ['ok'],
            },
            'description': 'A verdict.',
        }
    ]
    assert result['parsed'] == Judgement(ok=True)
    assert result['parsing_error'] is None
    assert isinstance(result['raw'], AIMessage)


async def test_structured_output_parsing_errors():
    structured = model().with_structured_output(Judgement, include_raw=True)
    with ProviderRecorder([judgement({'why': 'x'})]):
        result = await structured.ainvoke(MESSAGES)
    assert result['parsed'] is None
    assert isinstance(result['parsing_error'], ValidationError)

    with ProviderRecorder([judgement({'ok': True}, name='Other')]):
        result = await structured.ainvoke(MESSAGES)
    assert isinstance(result['parsing_error'], OutputParserError)

    with ProviderRecorder([canned.anthropic_message('no tool')]):
        result = await structured.ainvoke(MESSAGES)
    assert result['parsed'] is None
    assert result['parsing_error'] is None


async def test_structured_output_without_raw():
    structured = model().with_structured_output(Judgement)
    with ProviderRecorder([judgement({'ok': False})]):
        assert await structured.ainvoke(MESSAGES) == Judgement(ok=False)
    with ProviderRecorder([judgement({})]), pytest.raises(ValidationError):
        await structured.ainvoke(MESSAGES)


async def test_structured_output_with_thinking_offers_the_tool_unforced():
    chat_model = model(thinking={'type': 'enabled', 'budget_tokens': 1024})
    with pytest.warns(UserWarning, match='not guaranteed'):
        structured = chat_model.with_structured_output(Judgement, include_raw=True)
    with (
        ProviderRecorder([canned.anthropic_message('no')]) as recorder,
        pytest.raises(OutputParserError),
    ):
        await structured.ainvoke(MESSAGES)
    assert 'tool_choice' not in recorder.requests[0]['body']


# ── client configuration ────────────────────────────────────────────────────


def test_api_key_and_proxy_come_from_the_environment(monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'env-key')
    monkeypatch.setenv('ANTHROPIC_PROXY', 'http://proxy.local:3128')
    monkeypatch.setenv('ANTHROPIC_BASE_URL', 'http://gw.local')
    chat_model = ChatAnthropic('claude-sonnet-4-5', default_request_timeout=5)
    assert chat_model.anthropic_api_key == 'env-key'
    assert chat_model.anthropic_api_url == 'http://gw.local'
    client = chat_model.client
    assert client.api_key == 'env-key'
    assert client.timeout == 5
    assert client._client is _default_http_client(
        base_url='http://gw.local', timeout=5, proxy='http://proxy.local:3128'
    )


def test_default_http_client_falls_back_to_the_default_base_url(monkeypatch):
    monkeypatch.delenv('ANTHROPIC_BASE_URL', raising=False)
    client = _default_http_client(base_url=None)
    assert str(client.base_url) == 'https://api.anthropic.com'


async def test_missing_credentials_raise_a_clear_error(monkeypatch):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.delenv('ANTHROPIC_AUTH_TOKEN', raising=False)
    chat_model = ChatAnthropic('claude-sonnet-4-5')
    chat_model.anthropic_api_key = None
    with pytest.raises(TypeError, match='Anthropic authentication failed'):
        await invoke(chat_model, [canned.anthropic_message()])


def test_tracing_params_and_llm_output():
    bound = model(temperature=0.1).bind_tools([WEATHER_TOOL])
    params = bound._invocation_params(stop=['X'], foo=1)
    assert params['model'] == 'claude-sonnet-4-5'
    assert params['temperature'] == 0.1
    assert params['stop'] == ['X']
    assert params['foo'] == 1
    assert params['tools'][0]['name'] == 'get_weather'
    message = AIMessage(
        'x', response_metadata={'model_name': 'm', 'id': 'i', 'usage': {'a': 1}}
    )
    assert bound._llm_output(message) == {
        'model_name': 'm',
        'id': 'i',
        'usage': {'a': 1},
    }


# ── request payload: settings ───────────────────────────────────────────────


def test_inference_geo_container_and_user_profile_betas():
    payload = model(
        inference_geo='eu',
        mcp_servers=[{'type': 'url', 'url': 'https://mcp', 'name': 'm'}],
        user_profile_id='up_1',
        betas=['b-1'],
    )._request_payload(
        MESSAGES,
        output_config={'task_budget': 10},
        thinking={'type': 'enabled', 'budget_tokens': 10, 'display': 'updates'},
    )
    assert payload['inference_geo'] == 'eu'
    assert payload['betas'] == [
        'b-1',
        'mcp-client-2025-11-20',
        'task-budgets-2026-03-13',
        'thinking-display-updates-2026-08-18',
        'user-profiles-2026-03-24',
    ]


def test_tool_betas_are_added_once():
    tools = [
        {'type': 'mcp_toolset', 'mcp_server_name': 'm'},
        {**WEATHER_TOOL['function'], 'input_examples': [{'city': 'Rome'}]},
        {
            'name': 'x',
            'description': 'Kept as is.',
            'input_schema': {'type': 'object'},
            'input_examples': [{}],
        },
    ]
    payload = model(betas=['mcp-client-2025-11-20']).bind_tools(tools)
    payload = payload._request_payload(MESSAGES)
    assert payload['betas'] == [
        'mcp-client-2025-11-20',
        'advanced-tool-use-2025-11-20',
    ]


def test_output_config_priority_and_output_format():
    chat_model = model(
        output_config={'effort': 'low', 'other': 1}, reasoning_effort='medium'
    )
    payload = chat_model._request_payload(
        MESSAGES,
        output_config={'effort': 'high'},
        output_format={'type': 'json_schema', 'schema': {'type': 'object'}},
    )
    assert payload['output_config'] == {
        'effort': 'high',
        'other': 1,
        'format': {'type': 'json_schema', 'schema': {'type': 'object'}},
    }
    payload = chat_model._request_payload(MESSAGES, effort='max')
    assert payload['output_config'] == {'effort': 'max', 'other': 1}


def test_explicit_thinking_is_kept_with_effort():
    payload = model(
        'claude-opus-4-7', thinking={'type': 'enabled', 'budget_tokens': 64}
    )._request_payload(MESSAGES, reasoning_effort='high')
    assert payload['thinking'] == {'type': 'enabled', 'budget_tokens': 64}


def test_fable_drops_sampling_params():
    payload = ChatAnthropic('claude-fable-5', temperature=1, top_p=1)._request_payload(
        MESSAGES
    )
    assert not {'temperature', 'top_p', 'top_k'} & set(payload)


@pytest.mark.parametrize(
    ('name', 'settings', 'error'),
    [
        ('claude-fable-5', {'top_k': 3}, '`top_k` is not supported'),
        ('claude-fable-5', {'top_p': 0.5}, '`top_p` is not supported'),
        ('claude-fable-5', {'temperature': 0.5}, '`temperature` is not supported'),
        (
            'claude-fable-5',
            {'thinking': {'type': 'disabled'}},
            'omit `thinking` to use adaptive',
        ),
        (
            'claude-opus-5',
            {'thinking': {'type': 'enabled', 'budget_tokens': 10}},
            'use adaptive thinking',
        ),
        (
            'claude-opus-5',
            {'thinking': {'type': 'disabled'}, 'reasoning_effort': 'xhigh'},
            "effort='xhigh'",
        ),
    ],
)
def test_settings_rejected_by_the_model(name, settings, error):
    with pytest.raises(ValueError, match=error):
        ChatAnthropic(name)._request_payload(MESSAGES, **settings)


def test_opus5_validation_reads_configured_effort():
    chat_model = ChatAnthropic(
        'claude-opus-5', thinking={'type': 'disabled'}, reasoning_effort='max'
    )
    with pytest.raises(ValueError, match="effort='max'"):
        chat_model._request_payload(MESSAGES)
    chat_model = ChatAnthropic(
        'claude-opus-5',
        thinking={'type': 'disabled'},
        output_config={'effort': 'low'},
    )
    payload = chat_model._request_payload(MESSAGES, output_config={'effort': 'high'})
    assert payload['output_config'] == {'effort': 'high'}


@pytest.mark.parametrize(
    ('container', 'expected'),
    [
        (None, 'cntr_1'),
        ({'skills': ['x']}, {'skills': ['x'], 'id': 'cntr_1'}),
        ('cntr_explicit', 'cntr_explicit'),
    ],
)
def test_reuse_last_container(container, expected):
    messages = [
        HumanMessage('Run it'),
        AIMessage('ok', response_metadata={'container': {'id': 'cntr_1'}}),
        AIMessage('again', response_metadata={}),
        HumanMessage('Again'),
    ]
    payload = model(reuse_last_container=True, container=container)._request_payload(
        messages
    )
    assert payload['container'] == expected


def test_reuse_last_container_without_a_previous_one():
    payload = model(reuse_last_container=True)._request_payload(MESSAGES)
    assert 'container' not in payload


def test_non_mapping_extra_body_is_left_alone(monkeypatch):
    monkeypatch.setattr(
        'radicalbit_ai_gateway.llm.providers.anthropic._unsupported_sampling_params',
        lambda: frozenset({'top_k'}),
    )
    assert model(top_k=3)._request_payload(MESSAGES, extra_body={'a': 1})[
        'extra_body'
    ] == {'top_k': 3, 'a': 1}
    payload = model(top_k=3)._request_payload(MESSAGES, extra_body='raw')
    assert payload['top_k'] == 3
    assert payload['extra_body'] == 'raw'


# ── tools ───────────────────────────────────────────────────────────────────


class Node(BaseModel):
    """A tree node."""

    title: str
    child: 'Leaf'


class Leaf(BaseModel):
    value: int


Node.model_rebuild()


def test_tool_definitions_in_every_supported_format():
    tools = [
        {'name': 'anth', 'description': 'A.', 'input_schema': {'type': 'object'}},
        {'name': 'anth_nodesc', 'input_schema': {'type': 'object'}},
        {
            'toolSpec': {
                'name': 'bedrock',
                'description': 'B.',
                'inputSchema': {'json': {'type': 'object'}},
            }
        },
        {'toolSpec': {'name': 'bedrock_nodesc', 'inputSchema': {'json': {}}}},
        {'name': 'plain', 'description': 'P.', 'parameters': {}, 'extra': 'x'},
        {
            'title': 'schema',
            'description': 'S.',
            'type': 'object',
            'properties': {'q': {'type': 'string'}},
        },
        Node,
    ]
    assert model().bind_tools(tools)._bound['tools'] == [
        {'name': 'anth', 'description': 'A.', 'input_schema': {'type': 'object'}},
        {'name': 'anth_nodesc', 'input_schema': {'type': 'object'}},
        {'name': 'bedrock', 'input_schema': {'type': 'object'}, 'description': 'B.'},
        {'name': 'bedrock_nodesc', 'input_schema': {}},
        {'name': 'plain', 'input_schema': {}, 'description': 'P.'},
        {
            'name': 'schema',
            'input_schema': {'type': 'object', 'properties': {'q': {'type': 'string'}}},
            'description': 'S.',
        },
        {
            'name': 'Node',
            'input_schema': {
                'properties': {
                    'title': {'type': 'string'},
                    'child': {
                        'properties': {'value': {'type': 'integer'}},
                        'required': ['value'],
                        'type': 'object',
                    },
                },
                'required': ['title', 'child'],
                'type': 'object',
            },
            'description': 'A tree node.',
        },
    ]


@pytest.mark.parametrize('tool', [{'description': 'no name'}, 'not a tool'])
def test_unsupported_tool_definitions_are_rejected(tool):
    with pytest.raises(ValueError, match='Unsupported function'):
        model().bind_tools([tool])


def test_unrecognized_tool_choice_is_rejected():
    with pytest.raises(ValueError, match="Unrecognized 'tool_choice'"):
        model().bind_tools([WEATHER_TOOL], tool_choice=1)


def test_forced_tool_choice_is_dropped_with_thinking():
    chat_model = model(thinking={'type': 'adaptive'})
    with pytest.warns(UserWarning, match='Dropping tool_choice'):
        bound = chat_model.bind_tools([WEATHER_TOOL], tool_choice='any')
    assert 'tool_choice' not in bound._bound


ANY_OF = {
    'type': 'function',
    'function': {'name': 'bad', 'parameters': {'anyOf': [{'type': 'object'}]}},
}


def test_all_tools_dropped_is_an_error():
    with (
        pytest.warns(UserWarning, match="Dropping tool 'bad'"),
        pytest.raises(ValueError, match=r'All 1 bound tool\(s\)'),
    ):
        model().bind_tools([ANY_OF])


@pytest.mark.parametrize(
    'tool_choice',
    ['bad', {'type': 'tool', 'name': 'bad'}, 'any'],
)
def test_tool_choice_on_a_dropped_tool_is_an_error(tool_choice):
    with (
        pytest.warns(UserWarning, match='Dropping tool'),
        pytest.raises(ValueError, match='dropped'),
    ):
        model().bind_tools([WEATHER_TOOL, ANY_OF], tool_choice=tool_choice)


def test_forced_choice_on_a_dropped_tool_is_ignored_with_thinking():
    chat_model = model(thinking={'type': 'enabled', 'budget_tokens': 10})
    with pytest.warns(UserWarning, match='Dropping tool'):
        bound = chat_model.bind_tools([WEATHER_TOOL, ANY_OF], tool_choice='bad')
    assert 'tool_choice' not in bound._bound
    with pytest.warns(UserWarning, match='Dropping tool'):
        bound = model().bind_tools([WEATHER_TOOL, ANY_OF], tool_choice='auto')
    assert bound._bound['tool_choice'] == {'type': 'auto'}


def test_dropped_tool_without_name():
    with pytest.warns(UserWarning, match='Dropping tool with no name'):
        bound = model().bind_tools(
            [WEATHER_TOOL, {'type': 'bash_20250124', 'input_schema': {'oneOf': []}}]
        )
    assert [t['name'] for t in bound._bound['tools']] == ['get_weather']


# ── request payload: messages ───────────────────────────────────────────────


def test_consecutive_user_turns_are_merged():
    payload = model()._request_payload(
        [
            HumanMessage([{'type': 'text', 'text': 'a'}]),
            HumanMessage('b'),
            HumanMessage([{'type': 'text', 'text': 'c'}]),
            SystemMessage('late system'),
        ]
    )
    assert payload['messages'] == [
        {
            'role': 'user',
            'content': [
                {'type': 'text', 'text': 'a'},
                {'type': 'text', 'text': 'b'},
                {'type': 'text', 'text': 'c'},
            ],
        }
    ]
    assert payload['system'] == 'late system'


def test_system_content_list_of_strings_and_blocks():
    payload = model()._request_payload(
        [
            SystemMessage(
                [
                    'plain',
                    {'type': 'text', 'text': 'cited', 'id': 'drop', 'citations': None},
                    {'type': 'image_url', 'image_url': {'url': 'https://x/i.png'}},
                ]
            ),
            HumanMessage('Hi'),
        ]
    )
    assert payload['system'] == [
        {'type': 'text', 'text': 'plain'},
        {'type': 'text', 'text': 'cited', 'citations': None},
        {'type': 'image_url', 'image_url': {'url': 'https://x/i.png'}},
    ]


def test_tool_results_with_cache_control_and_errors():
    payload = model()._request_payload(
        [
            ToolMessage(
                [
                    {'type': 'text', 'text': 'sunny', 'cache_control': {'type': 'x'}},
                    'raw',
                ],
                tool_call_id='c1',
                status='error',
            ),
            ToolMessage(
                [
                    {
                        'type': 'tool_result',
                        'tool_use_id': 'c.2',
                        'content': [{'type': 'tool_reference', 'tool_name': 't'}],
                        'extra': 'dropped',
                    }
                ],
                tool_call_id='c.2',
            ),
        ]
    )
    assert payload['messages'] == [
        {
            'role': 'user',
            'content': [
                {
                    'type': 'tool_result',
                    'content': [
                        {'type': 'text', 'text': 'sunny'},
                        {'type': 'text', 'text': 'raw'},
                    ],
                    'tool_use_id': 'c1',
                    'is_error': True,
                    'cache_control': {'type': 'x'},
                },
                {
                    'type': 'tool_result',
                    'content': [{'type': 'tool_reference', 'tool_name': 't'}],
                    'tool_use_id': _normalize_tool_call_id('c.2'),
                },
            ],
        }
    ]


def test_assistant_blocks_round_trip():
    history = AIMessage(
        [
            {'type': 'thinking', 'thinking': 'hm', 'signature': 'sig', 'extra': 1},
            {'type': 'thinking', 'signature': 'sig2'},
            {'type': 'redacted_thinking', 'data': 'R', 'extra': 1},
            {'type': 'reasoning', 'reasoning': 'other provider'},
            {
                'type': 'server_tool_use',
                'id': 'srv_1',
                'name': 'web_search',
                'input': {},
                'partial_json': '{"query": "q"}',
                'extra': 1,
            },
            {
                'type': 'mcp_tool_use',
                'id': 'mcp_1',
                'name': 'm',
                'server_name': 's',
                'input': {},
                'partial_json': '{"bad',
            },
            {
                'type': 'web_search_tool_result',
                'tool_use_id': 'srv.1',
                'content': [],
                'extra': 1,
            },
            {'type': 'tool_search_tool_result', 'tool_use_id': 't1', 'content': {}},
            {
                'type': 'text',
                'text': 'Answer',
                'citations': [{'type': 'char_location', 'file_id': None, 'x': 1}],
            },
            {'type': 'tool_use', 'id': 'tu_1', 'name': 'f', 'input': {'a': 1}},
            {'type': 'tool_use', 'id': 'tu_2', 'name': 'f', 'partial_json': '{"b": 2}'},
            {'type': 'tool_use', 'id': 'tu_3', 'name': 'f', 'partial_json': '{"b'},
            {'type': 'tool_use', 'id': 'tu_4', 'name': 'f', 'caller': {'type': 'x'}},
            {'type': 'tool_use', 'id': 'tu_5', 'name': 'f', 'input': {'stale': 1}},
            {'type': 'custom_block', 'x': 1},
            'trailing   ',
        ],
        tool_calls=[
            {'name': 'f', 'args': {'fresh': 1}, 'id': 'tu_5'},
            {'name': 'g', 'args': {}, 'id': 'tu_6'},
        ],
    )
    content = model()._request_payload([HumanMessage('Hi'), history])['messages'][1][
        'content'
    ]
    assert content == [
        {'type': 'thinking', 'thinking': 'hm', 'signature': 'sig'},
        {'type': 'thinking', 'signature': 'sig2', 'thinking': ''},
        {'type': 'redacted_thinking', 'data': 'R'},
        {
            'type': 'server_tool_use',
            'id': 'srv_1',
            'name': 'web_search',
            'input': {'query': 'q'},
        },
        {
            'type': 'mcp_tool_use',
            'id': 'mcp_1',
            'name': 'm',
            'server_name': 's',
            'input': {},
        },
        {
            'type': 'web_search_tool_result',
            'tool_use_id': _normalize_tool_call_id('srv.1'),
            'content': [],
        },
        {'type': 'tool_search_tool_result', 'tool_use_id': 't1', 'content': {}},
        {
            'type': 'text',
            'text': 'Answer',
            'citations': [{'type': 'char_location', 'x': 1}],
        },
        {'type': 'tool_use', 'name': 'f', 'input': {'a': 1}, 'id': 'tu_1'},
        {'type': 'tool_use', 'name': 'f', 'input': {'b': 2}, 'id': 'tu_2'},
        {'type': 'tool_use', 'name': 'f', 'input': {}, 'id': 'tu_3'},
        {
            'type': 'tool_use',
            'name': 'f',
            'input': {},
            'id': 'tu_4',
            'caller': {'type': 'x'},
        },
        {'type': 'tool_use', 'name': 'f', 'input': {'fresh': 1}, 'id': 'tu_5'},
        {'type': 'custom_block', 'x': 1},
        # Not the last block, so not stripped.
        {'type': 'text', 'text': 'trailing   '},
        {'type': 'tool_use', 'name': 'g', 'input': {}, 'id': 'tu_6'},
    ]


def test_reasoning_blocks_from_anthropic_replies_are_sent_back():
    history = AIMessage(
        [{'type': 'reasoning', 'reasoning': 'x'}],
        response_metadata={'model_provider': 'anthropic'},
    )
    payload = model()._request_payload([HumanMessage('Hi'), history])
    assert payload['messages'][1]['content'] == [
        {'type': 'reasoning', 'reasoning': 'x'}
    ]


def test_trailing_assistant_text_is_stripped_and_empty_turns_dropped():
    payload = model()._request_payload(
        [
            HumanMessage('Hi'),
            AIMessage([{'type': 'text', 'text': ' '}]),
            HumanMessage('Again'),
            AIMessage([{'type': 'text', 'text': 'Prefill  '}]),
        ]
    )
    assert payload['messages'] == [
        {'role': 'user', 'content': 'Hi'},
        {'role': 'user', 'content': 'Again'},
        {'role': 'assistant', 'content': [{'type': 'text', 'text': 'Prefill'}]},
    ]


def test_tool_result_block_content_is_formatted():
    payload = model()._request_payload(
        [
            HumanMessage(
                [
                    {
                        'type': 'tool_result',
                        'tool_use_id': 'a.b',
                        'content': [
                            {'type': 'text', 'text': 'x'},
                            {
                                'type': 'image_url',
                                'image_url': {'url': 'data:image/png;base64,AAA'},
                            },
                        ],
                    }
                ]
            )
        ]
    )
    assert payload['messages'][0]['content'] == [
        {
            'type': 'tool_result',
            'tool_use_id': _normalize_tool_call_id('a.b'),
            'content': [
                {'type': 'text', 'text': 'x'},
                {
                    'type': 'image',
                    'source': {
                        'type': 'base64',
                        'media_type': 'image/png',
                        'data': 'AAA',
                    },
                },
            ],
        }
    ]


def test_data_blocks_become_images_and_documents():
    content = [
        {'type': 'image', 'url': 'https://x/i.png', 'cache_control': {'type': 'x'}},
        {'type': 'image', 'url': 'data:image/jpeg;base64,/9j/'},
        {'type': 'image', 'file_id': 'file_1'},
        {'type': 'image', 'base64': 'AAA', 'mime_type': 'image/png'},
        {'type': 'file', 'url': 'https://x/a.pdf', 'extras': {'title': 'A'}},
        {'type': 'file', 'base64': 'PDF', 'metadata': {'citations': {'enabled': True}}},
        {'type': 'file', 'source_type': 'text', 'text': 'body'},
        {'type': 'file', 'source_type': 'id', 'id': 'file_2', 'context': 'ctx'},
        {'type': 'text-plain', 'text': 'notes', 'mime_type': 'text/markdown'},
    ]
    payload = model()._request_payload([HumanMessage(content)])
    assert payload['messages'][0]['content'] == [
        {
            'type': 'image',
            'source': {'type': 'url', 'url': 'https://x/i.png'},
            'cache_control': {'type': 'x'},
        },
        {
            'type': 'image',
            'source': {'type': 'base64', 'media_type': 'image/jpeg', 'data': '/9j/'},
        },
        {'type': 'image', 'source': {'type': 'file', 'file_id': 'file_1'}},
        {
            'type': 'image',
            'source': {'type': 'base64', 'media_type': 'image/png', 'data': 'AAA'},
        },
        {
            'type': 'document',
            'source': {'type': 'url', 'url': 'https://x/a.pdf'},
            'title': 'A',
        },
        {
            'type': 'document',
            'source': {
                'type': 'base64',
                'media_type': 'application/pdf',
                'data': 'PDF',
            },
            'citations': {'enabled': True},
        },
        {
            'type': 'document',
            'source': {'type': 'text', 'media_type': 'text/plain', 'data': 'body'},
        },
        {
            'type': 'document',
            'source': {'type': 'file', 'file_id': 'file_2'},
            'context': 'ctx',
        },
        {
            'type': 'document',
            'source': {'type': 'text', 'media_type': 'text/markdown', 'data': 'notes'},
        },
    ]


@pytest.mark.parametrize(
    ('block', 'error'),
    [
        ('not a block', None),
        (1, 'must be str or dict'),
        ({'text': 'no type'}, 'must have a type key'),
        ({'type': 'image_url', 'image_url': {'url': 'ftp://x'}}, 'Malformed url'),
        ({'type': 'image', 'text': 'x'}, 'for image content'),
        ({'type': 'file', 'source_type': 'url', 'url': 'u', 'x': 1}, None),
        ({'type': 'audio', 'base64': 'AAA'}, 'audio is not supported'),
    ],
)
def test_content_block_validation(block, error):
    message = HumanMessage([block]) if not isinstance(block, int) else None
    if message is None:
        message = HumanMessage.model_construct(content=[block], type='human')
    if error is None:
        model()._request_payload([message])
        return
    with pytest.raises(ValueError, match=error):
        model()._request_payload([message])


def test_file_block_without_a_supported_source_is_rejected():
    with pytest.raises(ValueError, match='for file content'):
        model()._request_payload([HumanMessage([{'type': 'file', 'text': 'x'}])])


# ── replies (extra) ─────────────────────────────────────────────────────────


def message_body(content, **overrides):
    body = canned.anthropic_message().json_body
    body['content'] = content
    body.update(overrides)
    return CannedResponse(json_body=body)


async def test_thinking_and_citation_replies_keep_their_blocks():
    content = [
        {'type': 'thinking', 'thinking': 'hm', 'signature': 'sig'},
        {
            'type': 'text',
            'text': 'Cited',
            'citations': [
                {
                    'type': 'char_location',
                    'cited_text': 'c',
                    'document_index': 0,
                    'document_title': None,
                    'start_char_index': 0,
                    'end_char_index': 1,
                }
            ],
        },
    ]
    usage = {
        'input_tokens': 5,
        'output_tokens': 3,
        'cache_creation_input_tokens': 4,
        'cache_read_input_tokens': None,
        'cache_creation': None,
        'output_tokens_details': {'thinking_tokens': 2},
    }
    container = {'id': 'cntr_1', 'expires_at': '2026-01-01T00:00:00Z'}
    result, _ = await invoke(
        model(), [message_body(content, usage=usage, container=container)]
    )
    assert [b['type'] for b in result.content] == ['thinking', 'text']
    assert result.content[0] == {
        'signature': 'sig',
        'thinking': 'hm',
        'type': 'thinking',
    }
    assert result.content[1]['citations'][0]['cited_text'] == 'c'
    assert result.tool_calls == []
    container = result.response_metadata['container']
    assert container['expires_at'] == '2026-01-01T00:00:00+00:00'
    assert result.usage_metadata == {
        'input_tokens': 9,
        'output_tokens': 3,
        'total_tokens': 12,
        'input_token_details': {'cache_creation': 4},
        'output_token_details': {'reasoning': 2},
    }


async def test_usage_with_non_integer_cache_creation_breakdown():
    usage = {
        'input_tokens': 5,
        'output_tokens': 3,
        'cache_creation_input_tokens': 4,
        'cache_read_input_tokens': 1,
        'cache_creation': {
            'ephemeral_5m_input_tokens': 2.5,
            'ephemeral_1h_input_tokens': 0,
        },
    }
    result, _ = await invoke(
        model(), [message_body([{'type': 'text', 'text': 'x'}], usage=usage)]
    )
    assert result.usage_metadata['input_tokens'] == 10
    assert result.usage_metadata['input_token_details']['cache_creation'] == 4


async def test_structured_output_logs_truncated_replies(monkeypatch):
    logger = Mock()
    monkeypatch.setattr(anthropic_provider, 'logger', logger)
    structured = model().with_structured_output(Judgement)
    reply = judgement({})
    reply.json_body['stop_reason'] = 'max_tokens'
    with ProviderRecorder([reply]), pytest.raises(ValidationError):
        await structured.ainvoke(MESSAGES)
    assert 'max_tokens' in logger.exception.call_args.args[0]


# ── streaming (extra) ───────────────────────────────────────────────────────


async def test_stream_block_events():
    events = stream_events(
        {
            'type': 'content_block_start',
            'index': 0,
            'content_block': {'type': 'thinking', 'thinking': 'pre', 'signature': ''},
        },
        {
            'type': 'content_block_delta',
            'index': 0,
            'delta': {'type': 'signature_delta', 'signature': 'sig'},
        },
        {
            'type': 'content_block_start',
            'index': 1,
            'content_block': {
                'type': 'server_tool_use',
                'id': 'srv_1',
                'name': 'web_search',
                'input': {},
            },
        },
        {
            'type': 'content_block_delta',
            'index': 1,
            'delta': {'type': 'input_json_delta', 'partial_json': '{"q":'},
        },
        {
            'type': 'content_block_start',
            'index': 2,
            'content_block': {
                'type': 'web_search_tool_result',
                'tool_use_id': 'srv_1',
                'content': [],
            },
        },
        {
            'type': 'content_block_start',
            'index': 3,
            'content_block': {'type': 'text', 'text': ''},
        },
        {
            'type': 'content_block_delta',
            'index': 3,
            'delta': {
                'type': 'citations_delta',
                'citation': {
                    'type': 'char_location',
                    'cited_text': 'c',
                    'document_index': 0,
                    'document_title': None,
                    'start_char_index': 0,
                    'end_char_index': 1,
                },
            },
        },
        {'type': 'content_block_stop', 'index': 3},
    )
    events.sse_events[-2] = {
        'type': 'message_delta',
        'delta': {
            'stop_reason': 'end_turn',
            'stop_sequence': None,
            'container': {'id': 'cntr_1', 'expires_at': '2026-01-01T00:00:00Z'},
        },
        'usage': {'output_tokens': 4},
        'context_management': {'applied_edits': []},
    }
    chat_model = model(betas=['context-management-2025-06-27'])
    chunks, _ = await stream(chat_model, [events])
    # message_start, thinking start, signature, server tool start, its json
    # delta, tool result start, citation, message_delta: none carries content
    # and server-side tool input is not a client tool call.
    assert [c.content for c in chunks] == [''] * 8
    assert all(c.tool_call_chunks == [] for c in chunks)
    last = chunks[-1]
    assert last.response_metadata['container']['id'] == 'cntr_1'
    assert last.response_metadata['container']['expires_at'] == ('2026-01-01T00:00:00Z')
    assert last.response_metadata['context_management'] == {'applied_edits': []}
