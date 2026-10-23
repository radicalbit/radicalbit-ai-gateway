"""Tests for the native OpenAI and Azure OpenAI chat and embedding models."""

import asyncio
import json

from httpx_aiohttp import HttpxAiohttpClient
import openai
from pydantic import BaseModel
import pytest

# Loads the scenario registry before the OpenAI scenarios module it imports.
from tests.common import provider_responses as canned
from tests.common.provider_recorder import CannedResponse, ProviderRecorder
from tests.common.provider_responses import openai_response, openai_response_stream

from radicalbit_ai_gateway.llm.factory import init_chat_model, init_embeddings
from radicalbit_ai_gateway.llm.messages import (
    AIMessage,
    BaseMessage,
    FunctionMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from radicalbit_ai_gateway.llm.providers._openai_common import (
    OutputParserError,
    StreamChunkTimeoutError,
    to_openai_function,
    to_response_format,
    tool_choice_kwarg,
    with_chunk_timeout,
)
from radicalbit_ai_gateway.llm.providers.openai import (
    AzureChatOpenAI,
    AzureOpenAIEmbeddings,
    ChatOpenAI,
    OpenAIEmbeddings,
    OpenAIRefusalError,
)

MESSAGES = [SystemMessage('Be terse.'), HumanMessage('Hi')]
WEATHER_TOOL = {
    'type': 'function',
    'function': {
        'name': 'get_weather',
        'parameters': {'type': 'object', 'properties': {'city': {'type': 'string'}}},
    },
}
AZURE = {
    'api_key': 'sk',
    'api_version': '2024-10-21',
    'azure_endpoint': 'https://res.openai.azure.com',
}


def model(name='gpt-4o-mini', **kwargs) -> ChatOpenAI:
    kwargs.setdefault('http_async_client', HttpxAiohttpClient())
    return init_chat_model(f'openai:{name}', api_key='sk', **kwargs)


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


# ── Construction ─────────────────────────────────────────────────────────────


def test_factory_builds_native_models():
    assert isinstance(model(), ChatOpenAI)
    assert isinstance(init_chat_model('azure_openai:dep', **AZURE), AzureChatOpenAI)
    assert isinstance(init_chat_model('azure:dep', **AZURE), AzureChatOpenAI)
    assert isinstance(
        init_embeddings('text-embedding-3-small', provider='openai', api_key='sk'),
        OpenAIEmbeddings,
    )
    assert isinstance(
        init_embeddings('emb', provider='azure_openai', **AZURE),
        AzureOpenAIEmbeddings,
    )


def test_unknown_settings_become_request_parameters():
    chat_model = model(prompt_cache_key='k', temperature=1)
    assert chat_model.model_kwargs == {'prompt_cache_key': 'k'}
    assert chat_model.temperature == 1.0


def test_gpt5_drops_non_default_temperature_and_o1_defaults_it():
    assert model('gpt-5-mini', temperature=0.2).temperature is None
    assert model('gpt-5-chat-latest', temperature=0.2).temperature == 0.2
    assert model('o1').temperature == 1


def test_stream_usage_defaults_on_only_for_the_official_endpoint():
    assert ChatOpenAI(model='gpt-4o', api_key='sk').stream_usage is True
    assert model().stream_usage is None
    assert (
        ChatOpenAI(model='gpt-4o', api_key='sk', base_url='http://x/v1').stream_usage
        is None
    )


# ── Chat Completions requests ────────────────────────────────────────────────


async def test_request_payload_and_reply_metadata():
    chat_model = model(max_tokens=10, seed=3, service_tier='flex')
    response = canned.openai_completion(prompt_tokens=30, cached_tokens=8)
    response.json_body['service_tier'] = 'flex'
    result, requests = await invoke(chat_model, [response], stop=['END'])

    assert requests[0]['url'] == 'https://api.openai.com/v1/chat/completions'
    assert requests[0]['body'] == {
        'model': 'gpt-4o-mini',
        'stream': False,
        'seed': 3,
        'service_tier': 'flex',
        'max_completion_tokens': 10,
        'stop': ['END'],
        'messages': [
            {'content': 'Be terse.', 'role': 'system'},
            {'content': 'Hi', 'role': 'user'},
        ],
    }
    assert result.content == 'Hello from the model'
    assert result.additional_kwargs == {'refusal': None}
    assert result.usage_metadata == {
        'input_tokens': 30,
        'output_tokens': 7,
        'total_tokens': 37,
        'input_token_details': {'audio': 0, 'flex_cache_read': 8, 'flex': 22},
        'output_token_details': {'audio': 0, 'flex_reasoning': 0, 'flex': 7},
    }
    metadata = result.response_metadata
    assert metadata['finish_reason'] == 'stop'
    assert metadata['model_name'] == 'gpt-4o-mini-2024-07-18'
    assert metadata['model_provider'] == 'openai'
    assert metadata['token_usage']['prompt_tokens_details']['cached_tokens'] == 8
    assert result.id.startswith('run-')


async def test_o_series_system_prompt_is_a_developer_message():
    _, requests = await invoke(model('o3-mini'), [canned.openai_completion()])
    assert requests[0]['body']['messages'][0]['role'] == 'developer'


async def test_tool_round_trip_messages_and_tool_calls():
    bad_call = {
        'id': 'call_bad',
        'type': 'function',
        'function': {'name': 'get_weather', 'arguments': '{"city": '},
    }
    messages = [
        HumanMessage('Weather?'),
        AIMessage(
            'None',
            tool_calls=[{'name': 'get_weather', 'args': {'city': 'Pé'}, 'id': 'c1'}],
        ),
        ToolMessage('sunny', tool_call_id='c1'),
    ]
    chat_model = model().bind_tools([WEATHER_TOOL], tool_choice='get_weather')
    result, requests = await invoke(
        chat_model,
        [
            canned.openai_completion(
                None,
                tool_calls=[canned.WEATHER_TOOL_CALL, bad_call],
                finish_reason='tool_calls',
            )
        ],
        messages,
    )

    body = requests[0]['body']
    assert body['tools'] == [WEATHER_TOOL]
    assert body['tool_choice'] == {
        'type': 'function',
        'function': {'name': 'get_weather'},
    }
    assert body['messages'][1] == {
        'content': 'None',
        'role': 'assistant',
        'tool_calls': [
            {
                'type': 'function',
                'id': 'c1',
                'function': {'name': 'get_weather', 'arguments': '{"city": "Pé"}'},
            }
        ],
    }
    assert body['messages'][2] == {
        'content': 'sunny',
        'role': 'tool',
        'tool_call_id': 'c1',
    }
    assert result.content == ''
    assert result.tool_calls == [
        {
            'name': 'get_weather',
            'args': {'city': 'Paris', 'unit': 'c'},
            'id': 'call_weather_1',
            'type': 'tool_call',
        }
    ]
    assert result.invalid_tool_calls[0]['id'] == 'call_bad'
    assert 'are not valid JSON' in result.invalid_tool_calls[0]['error']


@pytest.mark.parametrize(
    ('tool_choice', 'expected'),
    [('any', 'required'), (True, 'required'), ('auto', 'auto'), ('none', 'none')],
)
async def test_tool_choice_normalization(tool_choice, expected):
    chat_model = model().bind_tools([WEATHER_TOOL], tool_choice=tool_choice)
    _, requests = await invoke(chat_model, [canned.openai_completion()])
    assert requests[0]['body']['tool_choice'] == expected


async def test_multimodal_user_content():
    content = [
        {'type': 'text', 'text': 'look'},
        {
            'type': 'image',
            'source_type': 'base64',
            'data': 'AAAA',
            'mime_type': 'image/png',
        },
        {
            'type': 'file',
            'source_type': 'base64',
            'data': 'JVBE',
            'mime_type': 'application/pdf',
        },
    ]
    _, requests = await invoke(
        model(), [canned.openai_completion()], [HumanMessage(content)]
    )
    assert requests[0]['body']['messages'][0]['content'] == [
        {'type': 'text', 'text': 'look'},
        {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AAAA'}},
        {
            'type': 'file',
            'file': {
                'file_data': 'data:application/pdf;base64,JVBE',
                'filename': 'LC_AUTOGENERATED',
            },
        },
    ]


async def test_provider_errors_propagate():
    with pytest.raises(openai.BadRequestError):
        await invoke(model(), [canned.error(400, 'bad request')])
    with pytest.raises(openai.BadRequestError):
        await stream(model(), [canned.error(400, 'bad request')])


async def test_null_choices_is_an_error():
    with pytest.raises(TypeError, match="null value for 'choices'"):
        await invoke(model(), [CannedResponse(json_body={'choices': None})])


# ── Streaming ────────────────────────────────────────────────────────────────


async def test_stream_chunks_usage_and_tool_calls():
    chunks, requests = await stream(
        model().bind_tools([WEATHER_TOOL], tool_choice='auto'),
        [canned.openai_stream(['Hi'], tool_calls=[canned.WEATHER_TOOL_CALL])],
        stream_options={'include_usage': True},
    )

    body = requests[0]['body']
    assert body['stream'] is True
    assert body['stream_options'] == {'include_usage': True}
    assert [c.content for c in chunks[:2]] == ['', 'Hi']
    assert chunks[2].tool_call_chunks[0]['name'] == 'get_weather'
    finish = next(c for c in chunks if c.response_metadata.get('finish_reason'))
    assert finish.response_metadata == {
        'finish_reason': 'tool_calls',
        'model_name': 'gpt-4o-mini-2024-07-18',
        'system_fingerprint': 'fp_golden',
        'model_provider': 'openai',
    }
    usage_chunk = chunks[-2]
    assert usage_chunk.usage_metadata['input_tokens'] == 21
    assert usage_chunk.response_metadata == {}
    assert chunks[-1].chunk_position == 'last'
    assert len({c.id for c in chunks}) == 1


async def test_stream_without_usage_option_omits_stream_options():
    _, requests = await stream(model(), [canned.openai_stream()])
    assert 'stream_options' not in requests[0]['body']


async def test_stream_with_response_format_ends_with_the_final_completion():
    response_format = {
        'type': 'json_schema',
        'json_schema': {'name': 'x', 'schema': {'type': 'object'}},
    }
    chunks, requests = await stream(
        model(),
        [canned.openai_stream(['{}'])],
        response_format=response_format,
        stream_options={'include_usage': True},
    )
    assert requests[0]['body']['response_format'] == response_format
    final = chunks[-2]
    assert final.usage_metadata['total_tokens'] == 28
    assert final.response_metadata['token_usage']['total_tokens'] == 28
    assert final.additional_kwargs == {'parsed': None, 'refusal': None}


# ── Structured output ────────────────────────────────────────────────────────


async def test_structured_output_uses_strict_json_schema():
    structured = model().with_structured_output(Judgement, include_raw=True)
    result, requests = await invoke(
        structured, [canned.openai_completion(json.dumps({'ok': True, 'why': 'x'}))]
    )

    response_format = requests[0]['body']['response_format']
    assert response_format['type'] == 'json_schema'
    assert response_format['json_schema']['strict'] is True
    assert response_format['json_schema']['name'] == 'Judgement'
    assert requests[0]['body']['stream'] is False
    assert result['parsed'] == Judgement(ok=True, why='x')
    assert result['parsing_error'] is None
    assert isinstance(result['raw'], AIMessage)


async def test_structured_output_refusal_is_a_parsing_error():
    structured = model().with_structured_output(Judgement, include_raw=True)
    result, _ = await invoke(
        structured,
        [canned.openai_completion(None, extra_message={'refusal': 'no'})],
    )
    assert result['parsed'] is None
    assert isinstance(result['parsing_error'], OpenAIRefusalError)

    with pytest.raises(OpenAIRefusalError):
        await invoke(
            model().with_structured_output(Judgement),
            [canned.openai_completion(None, extra_message={'refusal': 'no'})],
        )


async def test_structured_output_on_older_models_uses_function_calling():
    structured = model('gpt-4').with_structured_output(Judgement)
    tool_call = {
        'id': 'c',
        'type': 'function',
        'function': {'name': 'Judgement', 'arguments': '{"ok": false}'},
    }
    result, requests = await invoke(
        structured, [canned.openai_completion(None, tool_calls=[tool_call])]
    )
    body = requests[0]['body']
    assert body['tool_choice'] == {
        'type': 'function',
        'function': {'name': 'Judgement'},
    }
    assert body['parallel_tool_calls'] is False
    assert body['tools'][0]['function'] == {
        'name': 'Judgement',
        'description': 'A verdict.',
        'parameters': {
            'properties': {
                'ok': {'type': 'boolean'},
                'why': {
                    'anyOf': [{'type': 'string'}, {'type': 'null'}],
                    'default': None,
                },
            },
            'required': ['ok'],
            'type': 'object',
        },
    }
    assert result == Judgement(ok=False)


# ── Responses API ────────────────────────────────────────────────────────────


async def test_codex_models_use_the_responses_api():
    result, requests = await invoke(
        model('gpt-5-codex'), [openai_response()], max_completion_tokens=20
    )
    assert requests[0]['url'] == 'https://api.openai.com/v1/responses'
    assert requests[0]['body'] == {
        'model': 'gpt-5-codex',
        'stream': False,
        'max_output_tokens': 20,
        'input': [
            {'content': 'Be terse.', 'role': 'system', 'type': 'message'},
            {'content': 'Hi', 'role': 'user', 'type': 'message'},
        ],
    }
    assert result.content == [
        {
            'id': 'rs_golden_1',
            'summary': [{'text': 'Thinking.', 'type': 'summary_text'}],
            'type': 'reasoning',
        },
        {
            'type': 'text',
            'text': 'Hello from the model',
            'annotations': [],
            'id': 'msg_golden_1',
        },
    ]
    assert result.id == 'resp_golden_1'
    assert result.usage_metadata['input_token_details'] == {'cache_read': 4}


async def test_reasoning_kwarg_switches_to_the_responses_api_stream():
    chunks, requests = await stream(
        model(),
        [openai_response_stream(tool_calls=[canned.WEATHER_TOOL_CALL])],
        reasoning={'effort': 'low'},
    )
    assert requests[0]['url'] == 'https://api.openai.com/v1/responses'
    assert requests[0]['body']['reasoning'] == {'effort': 'low'}
    assert chunks[0].id == 'resp_golden_1'
    text = [b['text'] for c in chunks for b in c.content if b.get('type') == 'text']
    assert ''.join(text) == 'Hello from the model'
    args = ''.join(
        tc['args'] or '' for c in chunks for tc in c.tool_call_chunks if tc['args']
    )
    assert json.loads(args) == {'city': 'Paris', 'unit': 'c'}
    assert chunks[-1].chunk_position == 'last'
    assert chunks[-1].usage_metadata['total_tokens'] == 28


# ── Azure OpenAI ─────────────────────────────────────────────────────────────


async def test_azure_deployment_url_and_content_filter():
    chat_model = init_chat_model('azure_openai:dep', max_tokens=5, **AZURE)
    result, requests = await invoke(chat_model, [canned.openai_completion()])
    assert (
        requests[0]['url']
        == 'https://res.openai.azure.com/openai/deployments/dep/chat/completions'
    )
    assert requests[0]['query'] == [('api-version', '2024-10-21')]
    assert requests[0]['headers']['api-key'] == 'sk'
    assert requests[0]['body']['max_completion_tokens'] == 5
    assert result.response_metadata['content_filter_results'] == {}

    with pytest.raises(ValueError, match='content filter'):
        await invoke(
            chat_model, [canned.openai_completion(None, finish_reason='content_filter')]
        )


async def test_azure_function_calling_drops_parallel_tool_calls():
    structured = init_chat_model('azure_openai:gpt-4', **AZURE).with_structured_output(
        Judgement
    )
    tool_call = {
        'id': 'c',
        'type': 'function',
        'function': {'name': 'Judgement', 'arguments': '{"ok": true}'},
    }
    _, requests = await invoke(
        structured, [canned.openai_completion(None, tool_calls=[tool_call])]
    )
    assert 'parallel_tool_calls' not in requests[0]['body']


def test_azure_base_url_must_point_to_openai_path():
    with pytest.raises(ValueError, match='azure_endpoint'):
        AzureChatOpenAI(
            model='dep', api_key='sk', api_version='v', base_url='https://res.com'
        )


# ── Embeddings ───────────────────────────────────────────────────────────────


async def test_embeddings_send_token_ids_and_average_long_inputs():
    embeddings = init_embeddings(
        'text-embedding-3-small', provider='openai', api_key='sk'
    )
    long_text = 'word ' * 9000
    with ProviderRecorder([canned.openai_embeddings(count=3)]) as recorder:
        vectors = await embeddings.aembed_documents([long_text, 'short'])

    body = recorder.requests[0]['body']
    assert body['model'] == 'text-embedding-3-small'
    assert body['encoding_format'] == 'base64'
    assert [len(tokens) for tokens in body['input']] == [8191, 810, 1]
    assert all(isinstance(t, int) for t in body['input'][2])
    first = vectors[0]
    assert sum(v * v for v in first) == pytest.approx(1.0)
    assert vectors[1] == [0.3, 0.31, 0.32, 0.33]


async def test_embeddings_empty_text_uses_the_empty_string_embedding():
    embeddings = init_embeddings(
        'text-embedding-3-small', provider='openai', api_key='sk'
    )
    with ProviderRecorder(
        [canned.openai_embeddings(count=1), canned.openai_embeddings(count=1)]
    ) as recorder:
        vectors = await embeddings.aembed_documents(['', 'x'])
    assert recorder.requests[1]['body']['input'] == ''
    assert vectors[0] == vectors[1]


async def test_embeddings_without_ctx_check_send_raw_text():
    embeddings = init_embeddings(
        'nomic',
        provider='openai',
        api_key='sk',
        check_embedding_ctx_length=False,
        dimensions=4,
    )
    with ProviderRecorder([canned.openai_embeddings(count=1)]) as recorder:
        vector = await embeddings.aembed_query('hello')
    assert recorder.requests[0]['body']['input'] == ['hello']
    assert recorder.requests[0]['body']['dimensions'] == 4
    assert vector == [0.1, 0.11, 0.12, 0.13]


# ── Chat Completions message conversion ──────────────────────────────────────


def payload(messages, chat_model=None, **kwargs):
    return (chat_model or model())._get_request_payload(messages, **kwargs)


def test_assistant_history_variants_on_the_wire():
    raw_call = {
        'id': 'c9',
        'type': 'function',
        'function': {'name': 'f', 'arguments': '{}'},
        'index': 0,
    }
    messages = [
        HumanMessage('Hi', name='alice'),
        AIMessage('', additional_kwargs={'tool_calls': [raw_call]}),
        AIMessage(
            '',
            additional_kwargs={'function_call': {'name': 'f', 'arguments': '{}'}},
        ),
        AIMessage(
            '',
            invalid_tool_calls=[
                {'name': 'f', 'args': '{"x', 'id': 'c8', 'error': 'bad'}
            ],
        ),
        AIMessage(
            [
                {'type': 'text', 'text': 'Said', 'id': 'lc_1'},
                {'type': 'reasoning', 'reasoning': 'hm'},
                {'type': 'thinking', 'thinking': 'hm'},
                {'type': 'tool_use', 'id': 't', 'name': 'f', 'input': {}},
                {'type': 'function_call', 'name': 'f', 'arguments': '{}'},
                {'type': 'audio', 'id': 'audio_1'},
            ]
        ),
        AIMessage('Heard', additional_kwargs={'audio': {'id': 'audio_2', 'data': 'x'}}),
        AIMessage('Raw', additional_kwargs={'audio': {'data': 'x'}}),
        SystemMessage('Be nice.', additional_kwargs={'__openai_role__': 'developer'}),
        FunctionMessage('42', name='f'),
    ]
    assert payload(messages)['messages'] == [
        {'content': 'Hi', 'name': 'alice', 'role': 'user'},
        {
            'content': None,
            'role': 'assistant',
            'tool_calls': [
                {
                    'id': 'c9',
                    'type': 'function',
                    'function': {'name': 'f', 'arguments': '{}'},
                }
            ],
        },
        {
            'content': None,
            'role': 'assistant',
            'function_call': {'name': 'f', 'arguments': '{}'},
        },
        {
            'content': None,
            'role': 'assistant',
            'tool_calls': [
                {
                    'type': 'function',
                    'id': 'c8',
                    'function': {'name': 'f', 'arguments': '{"x'},
                }
            ],
        },
        {
            'content': [
                {'type': 'text', 'text': 'Said'},
                {'type': 'audio', 'id': 'audio_1'},
            ],
            'role': 'assistant',
            'audio': {'id': 'audio_1'},
        },
        {'content': 'Heard', 'role': 'assistant', 'audio': {'id': 'audio_2'}},
        {'content': 'Raw', 'role': 'assistant', 'audio': {'data': 'x'}},
        {'content': 'Be nice.', 'role': 'developer'},
        {'content': '42', 'name': 'f', 'role': 'function'},
    ]


def test_tool_message_content_is_sanitized():
    message = ToolMessage(
        [
            {'type': 'text', 'text': 'a', 'id': 'x', 'prompt_cache_breakpoint': True},
            {'type': 'text', 'text': 'b', 'annotations': []},
            {'type': 'image_url', 'image_url': {'url': 'https://x/i.png'}},
        ],
        tool_call_id='c1',
        name='f',
        artifact={'kept': 'locally'},
    )
    assert payload([message])['messages'] == [
        {
            'content': [
                {'type': 'text', 'text': 'a', 'prompt_cache_breakpoint': True},
                {'type': 'text', 'text': 'b'},
                {'type': 'image_url', 'image_url': {'url': 'https://x/i.png'}},
            ],
            'role': 'tool',
            'tool_call_id': 'c1',
        }
    ]


def test_unknown_message_types_are_rejected():
    class OtherMessage(BaseMessage):
        type: str = 'other'

    with pytest.raises(TypeError, match='Got unknown type'):
        payload([OtherMessage('x')])


def test_user_content_blocks_and_cache_breakpoints():
    content = [
        {'type': 'text', 'text': 'a', 'extras': {'prompt_cache_breakpoint': 'x'}},
        {'type': 'image', 'url': 'https://x/i.png', 'prompt_cache_breakpoint': 'y'},
        {
            'type': 'image',
            'base64': 'AAAA',
            'mime_type': 'image/png',
            'extras': {'prompt_cache_breakpoint': 'z'},
        },
        {
            'type': 'image',
            'source': {'type': 'base64', 'media_type': 'image/gif', 'data': 'R0lG'},
        },
        {'type': 'image', 'source': {'type': 'url', 'url': 'https://x/j.png'}},
        {'type': 'image', 'source': {'type': 'base64'}},
        {'type': 'audio', 'base64': 'UklG', 'mime_type': 'audio/wav'},
        {
            'type': 'audio',
            'source_type': 'base64',
            'data': 'SUQz',
            'mime_type': 'a/mp3',
        },
        {'type': 'file', 'file_id': 'file-1'},
        {'type': 'file', 'source_type': 'id', 'id': 'file-2'},
        {
            'type': 'file',
            'base64': 'JVBE',
            'mime_type': 'application/pdf',
            'filename': 'a.pdf',
        },
        {
            'type': 'file',
            'base64': 'JVBE',
            'mime_type': 'application/pdf',
            'extras': {'filename': 'b.pdf'},
        },
        {
            'type': 'file',
            'base64': 'JVBE',
            'mime_type': 'application/pdf',
            'metadata': {'filename': 'c.pdf'},
        },
        {'type': 'video', 'note': 'not a data block'},
    ]
    assert payload([HumanMessage(content)])['messages'][0]['content'] == [
        {'type': 'text', 'text': 'a', 'prompt_cache_breakpoint': 'x'},
        {
            'type': 'image_url',
            'image_url': {'url': 'https://x/i.png'},
            'prompt_cache_breakpoint': 'y',
        },
        {
            'type': 'image_url',
            'image_url': {'url': 'data:image/png;base64,AAAA'},
            'prompt_cache_breakpoint': 'z',
        },
        {'type': 'image_url', 'image_url': {'url': 'data:image/gif;base64,R0lG'}},
        {'type': 'image_url', 'image_url': {'url': 'https://x/j.png'}},
        {'type': 'input_audio', 'input_audio': {'data': 'UklG', 'format': 'wav'}},
        {'type': 'input_audio', 'input_audio': {'data': 'SUQz', 'format': 'mp3'}},
        {'type': 'file', 'file': {'file_id': 'file-1'}},
        {'type': 'file', 'file': {'file_id': 'file-2'}},
        {
            'type': 'file',
            'file': {
                'file_data': 'data:application/pdf;base64,JVBE',
                'filename': 'a.pdf',
            },
        },
        {
            'type': 'file',
            'file': {
                'file_data': 'data:application/pdf;base64,JVBE',
                'filename': 'b.pdf',
            },
        },
        {
            'type': 'file',
            'file': {
                'file_data': 'data:application/pdf;base64,JVBE',
                'filename': 'c.pdf',
            },
        },
        {'type': 'video', 'note': 'not a data block'},
    ]


@pytest.mark.parametrize(
    ('block', 'error'),
    [
        ({'type': 'image', 'base64': 'AA'}, 'mime_type key is required'),
        ({'type': 'image', 'file_id': 'f'}, 'Unsupported source type'),
        ({'type': 'file', 'url': 'https://x/a.pdf'}, 'does not support file URLs'),
        ({'type': 'file', 'text': 'plain'}, 'Keys base64, url, or file_id'),
        ({'type': 'audio', 'url': 'https://x/a.wav'}, 'Key base64 is required'),
        ({'type': 'video', 'url': 'https://x/a.mp4'}, 'video is not supported'),
    ],
)
def test_unsupported_data_blocks_are_rejected(block, error):
    with pytest.raises(ValueError, match=error):
        payload([HumanMessage([block])])


@pytest.mark.parametrize(
    ('block', 'expected'),
    [
        (
            {'type': 'image', 'source_type': 'url', 'url': 'https://x/i.png'},
            {'type': 'input_image', 'image_url': 'https://x/i.png'},
        ),
        (
            {'type': 'file', 'url': 'https://x/a.pdf'},
            {'type': 'input_file', 'file_url': 'https://x/a.pdf'},
        ),
        (
            {'type': 'file', 'source_type': 'id', 'id': 'file-1'},
            {'type': 'input_file', 'file_id': 'file-1'},
        ),
        (
            {'type': 'file', 'source_type': 'text', 'url': 'https://x/a.txt'},
            {'type': 'input_file', 'file_url': 'https://x/a.txt'},
        ),
    ],
)
def test_responses_api_data_blocks(block, expected):
    body = payload([HumanMessage([block])], model(use_responses_api=True))
    assert body['input'] == [{'content': [expected], 'role': 'user', 'type': 'message'}]


# ── Tool definitions ─────────────────────────────────────────────────────────


class Address(BaseModel):
    """Where."""

    city: str


class Person(BaseModel):
    """Someone."""

    title: str
    home: Address


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
        {'name': 'plain', 'parameters': {'type': 'object'}, 'extra': 'dropped'},
        {
            'title': 'schema',
            'description': 'S.',
            'type': 'object',
            'properties': {'q': {'type': 'string'}},
        },
        {'title': 'bare'},
        Person,
        {'type': 'web_search_preview_2025_03_11'},
        {'type': 'file_search', 'vector_store_ids': ['vs']},
    ]
    functions = [
        tool.get('function', tool) for tool in model().bind_tools(tools)._bound['tools']
    ]
    assert functions == [
        {'name': 'anth', 'parameters': {'type': 'object'}, 'description': 'A.'},
        {'name': 'anth_nodesc', 'parameters': {'type': 'object'}},
        {'name': 'bedrock', 'parameters': {'type': 'object'}, 'description': 'B.'},
        {'name': 'bedrock_nodesc', 'parameters': {}},
        {'name': 'plain', 'parameters': {'type': 'object'}},
        {
            'name': 'schema',
            'description': 'S.',
            'parameters': {'type': 'object', 'properties': {'q': {'type': 'string'}}},
        },
        {'name': 'bare'},
        {
            'name': 'Person',
            'description': 'Someone.',
            'parameters': {
                'properties': {
                    'title': {'type': 'string'},
                    'home': {
                        'description': 'Where.',
                        'properties': {'city': {'type': 'string'}},
                        'required': ['city'],
                        'type': 'object',
                    },
                },
                'required': ['title', 'home'],
                'type': 'object',
            },
        },
        {'type': 'web_search_preview_2025_03_11'},
        {'type': 'file_search', 'vector_store_ids': ['vs']},
    ]


def test_unsupported_tool_definition_is_rejected():
    with pytest.raises(ValueError, match='Unsupported function'):
        model().bind_tools([{'description': 'no name'}])


def test_strict_functions_close_every_object_schema():
    function = to_openai_function(
        {
            'name': 'f',
            'parameters': {
                'type': 'object',
                'properties': {
                    'a': {'anyOf': [{'type': 'object', 'properties': {}}]},
                    'b': {
                        'type': 'array',
                        'items': {'type': 'object', 'properties': {}},
                    },
                },
            },
        },
        strict=True,
    )
    assert function['strict'] is True
    assert function['parameters'] == {
        'type': 'object',
        'properties': {
            'a': {
                'anyOf': [
                    {'type': 'object', 'properties': {}, 'additionalProperties': False}
                ]
            },
            'b': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {},
                    'additionalProperties': False,
                },
            },
        },
        'required': ['a', 'b'],
        'additionalProperties': False,
    }

    with pytest.raises(ValueError, match="already has a 'strict' key"):
        to_openai_function({'name': 'f', 'parameters': {}, 'strict': False}, True)


@pytest.mark.parametrize(
    ('tool_choice', 'expected'),
    [
        ('file_search', {'type': 'file_search'}),
        ('ns', {'type': 'function', 'function': {'name': 'ns'}}),
        ('whatever', 'whatever'),
        ({'type': 'function', 'name': 'x'}, {'type': 'function', 'name': 'x'}),
    ],
)
def test_tool_choice_against_builtin_and_named_tools(tool_choice, expected):
    tools = [{'type': 'namespace', 'name': 'ns'}]
    assert tool_choice_kwarg(tool_choice, tools) == expected


def test_unrecognized_tool_choice_is_rejected():
    with pytest.raises(ValueError, match='Unrecognized tool_choice'):
        model().bind_tools([WEATHER_TOOL], tool_choice=1)


@pytest.mark.parametrize(
    ('schema', 'strict', 'expected'),
    [
        (
            {'type': 'json_schema', 'json_schema': {'name': 'a', 'schema': {}}},
            None,
            {'type': 'json_schema', 'json_schema': {'name': 'a', 'schema': {}}},
        ),
        (
            {'name': 'a', 'schema': {}},
            None,
            {'type': 'json_schema', 'json_schema': {'name': 'a', 'schema': {}}},
        ),
        (
            {'title': 'a', 'type': 'object', 'properties': {}, 'strict': True},
            None,
            {
                'type': 'json_schema',
                'json_schema': {
                    'name': 'a',
                    'strict': True,
                    'schema': {
                        'type': 'object',
                        'properties': {},
                        'strict': True,
                        'additionalProperties': False,
                    },
                },
            },
        ),
        (
            {'title': 'a', 'type': 'object', 'properties': {}},
            None,
            {
                'type': 'json_schema',
                'json_schema': {
                    'name': 'a',
                    'strict': False,
                    'schema': {'type': 'object', 'properties': {}},
                },
            },
        ),
    ],
)
def test_response_format_from_dict_schemas(schema, strict, expected):
    assert to_response_format(schema, strict=strict) == expected


def test_response_format_with_conflicting_strict_is_rejected():
    schema = {
        'type': 'json_schema',
        'json_schema': {'name': 'a', 'schema': {}, 'strict': False},
    }
    with pytest.raises(ValueError, match="already has 'strict' value"):
        to_response_format(schema, strict=True)


# ── Chat Completions replies ─────────────────────────────────────────────────


async def test_reply_with_function_call_audio_and_name():
    result, _ = await invoke(
        model(),
        [
            canned.openai_completion(
                None,
                extra_message={
                    'function_call': {'name': 'f', 'arguments': '{}'},
                    'audio': {
                        'id': 'audio_1',
                        'data': 'UklG',
                        'expires_at': 1,
                        'transcript': 'hi',
                    },
                    'name': 'bot',
                },
            )
        ],
    )
    assert result.content == ''
    assert result.name == 'bot'
    assert result.additional_kwargs['function_call'] == {'name': 'f', 'arguments': '{}'}
    assert result.additional_kwargs['audio']['id'] == 'audio_1'


async def test_priority_tier_usage_splits_cache_and_reasoning():
    response = canned.openai_completion(prompt_tokens=30, cached_tokens=10)
    response.json_body['service_tier'] = 'priority'
    usage = response.json_body['usage']
    usage['completion_tokens_details']['reasoning_tokens'] = 3
    usage['prompt_tokens_details']['cache_write_tokens'] = 5
    del usage['total_tokens']
    result, _ = await invoke(model(), [response])
    assert result.usage_metadata == {
        'input_tokens': 30,
        'output_tokens': 7,
        'total_tokens': 37,
        'input_token_details': {
            'audio': 0,
            'priority_cache_read': 10,
            'priority_cache_creation': 5,
            'priority': 20,
        },
        'output_token_details': {'audio': 0, 'priority_reasoning': 3, 'priority': 4},
    }
    assert result.response_metadata['service_tier'] == 'priority'


async def test_function_calling_structured_output_parsing_errors():
    structured = model('gpt-4').with_structured_output(Judgement, include_raw=True)

    def reply(name, arguments):
        call = {
            'id': 'c',
            'type': 'function',
            'function': {'name': name, 'arguments': arguments},
        }
        return canned.openai_completion(None, tool_calls=[call])

    result, _ = await invoke(structured, [reply('Other', '{"ok": true}')])
    assert result['parsed'] is None
    assert isinstance(result['parsing_error'], OutputParserError)
    assert "Unknown tool type: 'Other'" in str(result['parsing_error'])

    # Unparseable arguments leave no tool call to parse.
    result, _ = await invoke(structured, [reply('Judgement', '{"ok": ')])
    assert result['parsed'] is None
    assert result['parsing_error'] is None
    assert result['raw'].invalid_tool_calls[0]['name'] == 'Judgement'

    result, _ = await invoke(structured, [canned.openai_completion('no tool')])
    assert result == {'raw': result['raw'], 'parsed': None, 'parsing_error': None}


# ── Chat Completions streaming ───────────────────────────────────────────────


def sse(*deltas, usage=None):
    events = [
        {
            'id': 'chatcmpl-1',
            'object': 'chat.completion.chunk',
            'created': 1,
            'model': 'gpt-4o-mini',
            'choices': [
                {'index': 0, 'delta': delta, 'finish_reason': finish}
                for delta, finish in [d if isinstance(d, tuple) else (d, None)]
            ],
        }
        for d in deltas
    ]
    if usage:
        events.append(
            {
                'id': 'chatcmpl-1',
                'object': 'chat.completion.chunk',
                'created': 1,
                'model': 'gpt-4o-mini',
                'service_tier': 'flex',
                'choices': [],
                'usage': usage,
            }
        )
    return CannedResponse(sse_events=[*events, '[DONE]'])


async def test_stream_function_call_deltas_and_flex_usage():
    chunks, _ = await stream(
        model(),
        [
            sse(
                {'role': 'assistant', 'function_call': {'name': None, 'arguments': ''}},
                {'function_call': {'arguments': '{}'}},
                ({}, 'function_call'),
                usage={
                    'prompt_tokens': 5,
                    'completion_tokens': 2,
                    'total_tokens': 7,
                    'completion_tokens_details': {'reasoning_tokens': 1},
                },
            )
        ],
        stream_usage=True,
    )
    assert chunks[0].additional_kwargs == {
        'function_call': {'name': '', 'arguments': ''}
    }
    assert chunks[1].additional_kwargs == {
        'function_call': {'arguments': '{}', 'name': ''}
    }
    assert chunks[2].response_metadata['finish_reason'] == 'function_call'
    assert chunks[3].usage_metadata == {
        'input_tokens': 5,
        'output_tokens': 2,
        'total_tokens': 7,
        'input_token_details': {'flex': 5},
        'output_token_details': {'flex_reasoning': 1, 'flex': 1},
    }


async def test_stream_without_chunk_timeout():
    chunks, _ = await stream(model(stream_chunk_timeout=0), [canned.openai_stream()])
    assert ''.join(c.content for c in chunks) == 'Hello from the model'


async def test_stalled_stream_raises_chunk_timeout():
    class Stalled:
        closed = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            await asyncio.sleep(1)

        async def aclose(self):
            self.closed = True
            raise RuntimeError('already closed')

    source = Stalled()
    with pytest.raises(StreamChunkTimeoutError, match="model 'm' after 0 chunk"):
        async for _ in with_chunk_timeout(source, 0.01, 'm'):
            pass
    assert source.closed
