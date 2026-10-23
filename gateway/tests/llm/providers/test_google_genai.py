"""Tests for the native Gemini chat and embedding models."""

import base64

from google.genai import errors, types
import httpx
from pydantic import BaseModel
import pytest

from tests.common import provider_responses as canned
from tests.common.provider_recorder import CannedResponse, ProviderRecorder

from radicalbit_ai_gateway.llm.factory import init_chat_model, init_embeddings
from radicalbit_ai_gateway.llm.messages import (
    AIMessage,
    BaseMessage,
    FunctionMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from radicalbit_ai_gateway.llm.providers.google_genai import (
    ChatGoogleGenerativeAI,
    ChatGoogleGenerativeAIError,
    GoogleGenerativeAIEmbeddings,
    GoogleGenerativeAIError,
    OutputParserError,
    _prepare_batches,
)

BASE = 'https://generativelanguage.googleapis.com/v1beta/models'
MESSAGES = [SystemMessage('Be terse.'), HumanMessage('Hi')]
WEATHER_TOOL = {
    'type': 'function',
    'function': {
        'name': 'get_weather',
        'description': 'Get the weather.',
        'parameters': {
            'type': 'object',
            'properties': {
                'city': {'type': 'string'},
                'unit': {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
                'place': {'$ref': '#/$defs/Place'},
            },
            'required': ['city'],
            '$defs': {
                'Place': {
                    'type': 'object',
                    'properties': {'lat': {'type': 'number'}},
                }
            },
        },
    },
}
PNG = (
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9Q'
    'DwADhgGAWjR9awAAAABJRU5ErkJggg=='
)


def model(name: str = 'gemini-2.5-flash', **kwargs) -> ChatGoogleGenerativeAI:
    return init_chat_model(f'google-genai:{name}', api_key='sk', **kwargs)


async def invoke(chat_model, responses, messages=MESSAGES, **kwargs):
    with ProviderRecorder(responses) as recorder:
        result = await chat_model.ainvoke(messages, **kwargs)
    return result, recorder.requests


async def stream(chat_model, responses, messages=MESSAGES, **kwargs):
    with ProviderRecorder(responses) as recorder:
        chunks = [c async for c in chat_model.astream(messages, **kwargs)]
    return chunks, recorder.requests


def gemini_error(status: int, message: str, code: str) -> CannedResponse:
    return CannedResponse(
        status=status,
        json_body={'error': {'code': status, 'message': message, 'status': code}},
    )


class Judgement(BaseModel):
    """A verdict."""

    ok: bool
    why: str | None = None


# ── Construction ─────────────────────────────────────────────────────────────


def test_factory_builds_native_model():
    chat_model = model()
    assert type(chat_model).__name__ == 'ChatGoogleGenerativeAI'
    assert chat_model.model == 'gemini-2.5-flash'


def test_missing_api_key_is_rejected(monkeypatch):
    monkeypatch.delenv('GOOGLE_API_KEY', raising=False)
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    with pytest.raises(ValueError, match='API key required'):
        init_chat_model('google_genai:gemini-2.5-flash')


def test_api_key_falls_back_to_environment(monkeypatch):
    monkeypatch.setenv('GOOGLE_API_KEY', 'env-key')
    assert init_chat_model('google_genai:gemini-2.5-flash') is not None


@pytest.mark.parametrize(
    'params',
    [{'temperature': 2.5}, {'top_p': 1.5}, {'top_k': 0}, {'presence_penalty': 3}],
)
def test_out_of_range_params_are_rejected(params):
    with pytest.raises(ValueError, match='must be'):
        model(**params)


# ── Request ──────────────────────────────────────────────────────────────────


async def test_basic_request_body():
    _, requests = await invoke(model(), [canned.gemini_response()])
    assert requests[0]['url'] == f'{BASE}/gemini-2.5-flash:generateContent'
    assert requests[0]['headers']['x-goog-api-key'] == 'sk'
    assert requests[0]['body'] == {
        'contents': [{'parts': [{'text': 'Hi'}], 'role': 'user'}],
        'generationConfig': {'candidateCount': 1, 'temperature': 0.7},
        'safetySettings': [],
        'systemInstruction': {'parts': [{'text': 'Be terse.'}]},
    }


async def test_gemini_3_has_no_default_temperature():
    _, requests = await invoke(
        model('gemini-3-pro-preview'), [canned.gemini_response()]
    )
    assert requests[0]['body']['generationConfig'] == {'candidateCount': 1}


async def test_only_a_leading_system_message_starts_the_instruction():
    messages = [HumanMessage('a'), SystemMessage('dropped'), HumanMessage('b')]
    _, requests = await invoke(model(), [canned.gemini_response()], messages)
    assert 'systemInstruction' not in requests[0]['body']
    assert len(requests[0]['body']['contents']) == 2


async def test_model_and_call_params_map_to_generation_config():
    chat_model = model(max_tokens=128, top_k=3, seed=7)
    _, requests = await invoke(
        chat_model,
        [canned.gemini_response()],
        temperature=0.2,
        top_p=0.9,
        max_output_tokens=64,
        stop=['END'],
        stream=True,
        stream_options={'include_usage': True},
    )
    assert requests[0]['body']['generationConfig'] == {
        'candidateCount': 1,
        'maxOutputTokens': 64,
        'seed': 7,
        'stopSequences': ['END'],
        'temperature': 0.2,
        'topK': 3,
        'topP': 0.9,
    }


async def test_unknown_call_kwarg_fails_the_call():
    with pytest.raises(ValueError):
        await invoke(model(), [canned.gemini_response()], n=2)


async def test_response_format_maps_to_json_schema():
    schema = {'type': 'object', 'properties': {'a': {'type': 'string'}}}
    _, requests = await invoke(
        model(),
        [canned.gemini_response()],
        response_format={'type': 'json_schema', 'json_schema': {'schema': schema}},
    )
    config = requests[0]['body']['generationConfig']
    assert config['responseMimeType'] == 'application/json'
    assert config['responseJsonSchema'] == schema


async def test_tool_roundtrip_contents():
    messages = [
        HumanMessage('Weather?'),
        AIMessage(
            'None',
            tool_calls=[{'name': 'get_weather', 'args': {'city': 'Rome'}, 'id': 'c1'}],
        ),
        ToolMessage('{"temp": 18}', tool_call_id='c1'),
        ToolMessage('orphan', tool_call_id='unknown'),
    ]
    _, requests = await invoke(model(), [canned.gemini_response()], messages)
    assert requests[0]['body']['contents'][1:] == [
        {
            'parts': [
                {'text': 'None'},
                {'functionCall': {'args': {'city': 'Rome'}, 'name': 'get_weather'}},
            ],
            'role': 'model',
        },
        {
            'parts': [
                {
                    'functionResponse': {
                        'name': 'get_weather',
                        'response': {'temp': 18},
                    }
                }
            ],
            'role': 'user',
        },
    ]


async def test_gemini_3_function_calls_get_a_placeholder_signature():
    messages = [
        HumanMessage('Weather?'),
        AIMessage('', tool_calls=[{'name': 'f', 'args': {}, 'id': 'c1'}]),
        ToolMessage('ok', tool_call_id='c1'),
    ]
    _, requests = await invoke(
        model('gemini-3-pro-preview'), [canned.gemini_response()], messages
    )
    call_part = requests[0]['body']['contents'][1]['parts'][0]
    assert call_part['thoughtSignature'] == 'skip_thought_signature_validator'


async def test_image_blocks_become_inline_data():
    content = [
        {'type': 'text', 'text': 'What is this?'},
        {
            'type': 'image',
            'source_type': 'base64',
            'data': PNG,
            'mime_type': 'image/png',
        },
        {'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{PNG}'}},
    ]
    _, requests = await invoke(
        model(), [canned.gemini_response()], [HumanMessage(content)]
    )
    parts = requests[0]['body']['contents'][0]['parts']
    assert parts[0] == {'text': 'What is this?'}
    # The SDK serializes bytes as url-safe base64.
    expected = {'inlineData': {'data': PNG.replace('+', '-'), 'mimeType': 'image/png'}}
    assert parts[1] == parts[2] == expected


async def test_unknown_block_type_fails_the_call():
    with pytest.raises(ValueError, match='Unrecognized message part type'):
        await invoke(model(), [], [HumanMessage([{'type': 'weird'}])])


async def test_tools_become_function_declarations():
    chat_model = model().bind_tools([WEATHER_TOOL], tool_choice='auto')
    _, requests = await invoke(chat_model, [canned.gemini_response()])
    body = requests[0]['body']
    assert body['toolConfig'] == {'functionCallingConfig': {'mode': 'AUTO'}}
    assert body['tools'][0]['functionDeclarations'][0] == {
        'description': 'Get the weather.',
        'name': 'get_weather',
        'parameters': {
            'properties': {
                'city': {'type': 'STRING'},
                'place': {
                    'properties': {'lat': {'type': 'NUMBER'}},
                    'required': ['lat'],
                    'type': 'OBJECT',
                },
                'unit': {'nullable': True, 'type': 'STRING'},
            },
            'required': ['city'],
            'type': 'OBJECT',
        },
    }


@pytest.mark.parametrize(
    ('tool_choice', 'expected'),
    [
        ('none', {'mode': 'NONE'}),
        ('required', {'mode': 'ANY', 'allowedFunctionNames': ['get_weather']}),
        (
            {'type': 'function', 'function': {'name': 'get_weather'}},
            {'mode': 'ANY', 'allowedFunctionNames': ['get_weather']},
        ),
    ],
)
async def test_tool_choice_mapping(tool_choice, expected):
    chat_model = model().bind_tools([WEATHER_TOOL], tool_choice=tool_choice)
    _, requests = await invoke(chat_model, [canned.gemini_response()])
    assert requests[0]['body']['toolConfig'] == {'functionCallingConfig': expected}


async def test_unrecognized_tool_choice_fails_the_call_not_the_bind():
    chat_model = model().bind_tools([WEATHER_TOOL], tool_choice={'bogus': 1})
    with pytest.raises(ValueError, match='Unrecognized tool choice'):
        await invoke(chat_model, [])


# ── Response ─────────────────────────────────────────────────────────────────


async def test_response_parsing():
    result, _ = await invoke(
        model(), [canned.gemini_response('Hello\n', prompt_tokens=30, cached_tokens=10)]
    )
    assert result.content == 'Hello'
    assert result.response_metadata == {
        'finish_reason': 'STOP',
        'model_name': 'gemini-2.5-flash',
        'safety_ratings': [],
        'model_provider': 'google_genai',
    }
    assert result.usage_metadata == {
        'input_tokens': 30,
        'output_tokens': 7,
        'total_tokens': 37,
        'input_token_details': {'cache_read': 10},
    }
    assert result.id.startswith('run-')


async def test_function_calls_become_tool_calls():
    response = canned.gemini_response(
        None, function_calls=[{'name': 'get_weather', 'args': {'n': 2.0}}]
    )
    result, _ = await invoke(model(), [response])
    assert result.content == ''
    [call] = result.tool_calls
    assert call['name'] == 'get_weather'
    assert call['args'] == {'n': 2}
    assert call['id']
    assert result.additional_kwargs['function_call'] == {
        'name': 'get_weather',
        'arguments': '{"n": 2}',
    }


async def test_thoughts_count_as_reasoning_output():
    payload = canned.gemini_response().json_body
    payload['usageMetadata']['thoughtsTokenCount'] = 5
    result, _ = await invoke(model(), [CannedResponse(json_body=payload)])
    assert result.usage_metadata['output_tokens'] == 12
    assert result.usage_metadata['output_token_details'] == {'reasoning': 5}


async def test_blocked_prompt_returns_empty_message():
    payload = {'promptFeedback': {'blockReason': 'SAFETY'}}
    result, _ = await invoke(model(), [CannedResponse(json_body=payload)])
    assert result.content == ''
    assert result.response_metadata['prompt_feedback']['block_reason'] == 'SAFETY'


async def test_stream_yields_usage_deltas_and_tool_call_chunks():
    response = canned.gemini_stream(
        ['Hel', 'lo'], function_calls=[canned.GEMINI_WEATHER_CALL], cached_tokens=4
    )
    chunks, requests = await stream(
        model().bind_tools([WEATHER_TOOL], tool_choice='auto'),
        [response],
        stream=True,
        stream_options={'include_usage': True},
    )
    assert requests[0]['url'] == f'{BASE}/gemini-2.5-flash:streamGenerateContent'
    assert requests[0]['query'] == [('alt', 'sse')]
    assert 'stream' not in requests[0]['body']['generationConfig']
    assert [c.content for c in chunks] == ['Hel', 'lo', '', '', '']
    output = [c.usage_metadata['output_tokens'] for c in chunks if c.usage_metadata]
    assert sum(output) == 7
    assert chunks[0].usage_metadata['input_tokens'] == 21
    assert chunks[0].usage_metadata['input_token_details'] == {'cache_read': 4}
    assert chunks[1].usage_metadata['input_tokens'] == 0
    [tool_chunk] = chunks[2].tool_call_chunks
    assert tool_chunk['index'] == 0
    assert chunks[2].tool_calls[0]['args'] == {'city': 'Paris', 'unit': 'c'}
    assert chunks[3].response_metadata['finish_reason'] == 'STOP'
    assert chunks[-1].chunk_position == 'last'
    assert len({c.id for c in chunks}) == 1


# ── Errors ───────────────────────────────────────────────────────────────────


async def test_client_error_is_classified():
    with pytest.raises(ChatGoogleGenerativeAIError) as exc_info:
        await invoke(model(), [gemini_error(400, 'bad', 'INVALID_ARGUMENT')])
    assert str(exc_info.value).startswith(
        "Error calling model 'gemini-2.5-flash' (INVALID_ARGUMENT): 400"
    )


async def test_stream_client_error_is_classified():
    with pytest.raises(ChatGoogleGenerativeAIError):
        await stream(model(), [gemini_error(400, 'bad', 'INVALID_ARGUMENT')])


async def test_server_error_propagates_after_retries():
    responses = [gemini_error(503, 'busy', 'UNAVAILABLE')] * 2
    with pytest.raises(errors.ServerError):
        await invoke(model(max_retries=2), responses)


# ── Structured output ────────────────────────────────────────────────────────


async def test_structured_output_uses_json_schema():
    structured = model(temperature=0, max_tokens=50).with_structured_output(
        Judgement, include_raw=True
    )
    result, requests = await invoke(
        structured, [canned.gemini_response('```json\n{"ok": true}\n```')]
    )
    config = requests[0]['body']['generationConfig']
    assert config['responseMimeType'] == 'application/json'
    assert config['responseJsonSchema'] == Judgement.model_json_schema()
    assert result['parsed'] == Judgement(ok=True)
    assert result['parsing_error'] is None
    assert isinstance(result['raw'], AIMessage)


async def test_structured_output_parsing_error():
    structured = model().with_structured_output(Judgement, include_raw=True)
    result, _ = await invoke(structured, [canned.gemini_response('not json')])
    assert result['parsed'] is None
    assert isinstance(result['parsing_error'], OutputParserError)

    strict = model().with_structured_output(Judgement)
    with pytest.raises(OutputParserError, match='Failed to parse Judgement'):
        await invoke(strict, [canned.gemini_response('{"ok": "maybe"}')])


# ── Embeddings ───────────────────────────────────────────────────────────────


def embeddings(**kwargs) -> GoogleGenerativeAIEmbeddings:
    return init_embeddings(
        'gemini-embedding-001', provider='google-genai', api_key='sk', **kwargs
    )


async def test_embed_documents_and_query_task_types():
    emb = embeddings()
    assert type(emb).__name__ == 'GoogleGenerativeAIEmbeddings'
    with ProviderRecorder(
        [canned.gemini_embeddings(count=2), canned.gemini_embeddings(count=1)]
    ) as recorder:
        docs = await emb.aembed_documents(['a', 'b'])
        query = await emb.aembed_query('q')
    assert len(docs) == 2
    assert query == [0.1, 0.11, 0.12, 0.13]
    docs_request, query_request = recorder.requests
    assert docs_request['url'] == f'{BASE}/gemini-embedding-001:batchEmbedContents'
    assert {r['taskType'] for r in docs_request['body']['requests']} == {
        'RETRIEVAL_DOCUMENT'
    }
    assert query_request['body']['requests'][0]['taskType'] == 'RETRIEVAL_QUERY'


async def test_configured_task_type_and_dimensions():
    emb = embeddings(task_type='clustering', output_dimensionality=8)
    with ProviderRecorder([canned.gemini_embeddings(count=1)]) as recorder:
        await emb.aembed_documents(['a'])
    request = recorder.requests[0]['body']['requests'][0]
    assert request['taskType'] == 'CLUSTERING'
    assert request['outputDimensionality'] == 8


def test_batches_split_by_size_and_tokens():
    assert _prepare_batches([], 100) == []
    assert [len(b) for b in _prepare_batches(['x'] * 150, 100)] == [100, 50]
    long_text = 'word ' * 6000
    assert [len(b) for b in _prepare_batches([long_text, 'a', 'b'], 100)] == [1, 2]
    assert [len(b) for b in _prepare_batches(['a', long_text], 100)] == [1, 1]


async def test_embedding_errors_are_wrapped():
    with (
        ProviderRecorder([gemini_error(400, 'bad', 'INVALID_ARGUMENT')]),
        pytest.raises(GoogleGenerativeAIError, match='Error embedding content'),
    ):
        await embeddings().aembed_query('q')


# ── Construction: endpoints and thinking ─────────────────────────────────────


async def test_base_url_dict_with_api_endpoint_sets_the_host():
    chat_model = model(base_url={'api_endpoint': 'https://proxy.example.com'})
    _, requests = await invoke(chat_model, [canned.gemini_response()])
    assert requests[0]['url'].startswith('https://proxy.example.com/')


@pytest.mark.parametrize(
    ('base_url', 'match'),
    [
        ({'api_endpoint': 'https://x', 'extra': 1}, "Extra keys found: \\['extra'\\]"),
        ({'endpoint': 'https://x'}, 'must only contain the api_endpoint key'),
        ({}, 'must be a string or a dict'),
    ],
)
def test_invalid_base_url_dict_is_rejected(base_url, match):
    with pytest.raises(ValueError, match=match):
        model(base_url=base_url)


async def test_thinking_config_object_is_sent():
    chat_model = model(thinking_config=types.ThinkingConfig(thinking_budget=128))
    _, requests = await invoke(chat_model, [canned.gemini_response()])
    config = requests[0]['body']['generationConfig']
    # The SDK serializes the nested thinking config with snake_case keys.
    assert config['thinkingConfig'] == {'thinking_budget': 128}


async def test_thinking_params_are_merged_into_thinking_config():
    chat_model = model(thinking_config={'include_thoughts': False}, thinking_budget=64)
    _, requests = await invoke(
        chat_model, [canned.gemini_response()], include_thoughts=True
    )
    config = requests[0]['body']['generationConfig']
    assert config['thinkingConfig'] == {
        'include_thoughts': True,
        'thinking_budget': 64,
    }


async def test_thinking_level_wins_over_budget():
    chat_model = model('gemini-3-pro-preview', thinking_budget=64)
    with pytest.warns(UserWarning, match="'thinking_level' takes precedence"):
        _, requests = await invoke(
            chat_model, [canned.gemini_response()], reasoning_effort='low'
        )
    config = requests[0]['body']['generationConfig']
    assert config['thinkingConfig'] == {'thinking_level': 'LOW'}


# ── Request: generation settings ─────────────────────────────────────────────


async def test_fixed_sampling_models_drop_sampling_params():
    chat_model = model('gemini-3.6-flash', temperature=0.3, top_k=2)
    with pytest.warns(UserWarning, match='temperature, top_k will be ignored'):
        _, requests = await invoke(chat_model, [canned.gemini_response()])
    assert requests[0]['body']['generationConfig'] == {'candidateCount': 1}


async def test_fixed_sampling_models_reject_a_model_prefill():
    messages = [HumanMessage('Hi'), AIMessage('Sure,')]
    with pytest.raises(ValueError, match='does not support model prefilling'):
        await invoke(model('models/gemini-3.5-flash-lite-001'), [], messages)


async def test_timeout_is_sent_as_server_timeout():
    _, requests = await invoke(model(request_timeout=2.5), [canned.gemini_response()])
    assert requests[0]['headers']['x-server-timeout'] == '3'

    _, requests = await invoke(model(), [canned.gemini_response()], timeout=7)
    assert requests[0]['headers']['x-server-timeout'] == '7'


async def test_per_request_http_options_are_merged():
    _, requests = await invoke(
        model(additional_headers={'x-base': 'a'}),
        [canned.gemini_response()],
        timeout=4,
        http_options={'headers': {'x-call': 'b'}},
    )
    headers = requests[0]['headers']
    assert headers['x-call'] == 'b'
    assert headers['x-base'] == 'a'
    assert headers['x-server-timeout'] == '4'


async def test_per_request_http_options_without_defaults():
    _, requests = await invoke(
        model(max_retries=None),
        [canned.gemini_response()],
        http_options={'api_version': 'v1alpha'},
    )
    assert requests[0]['url'].endswith(
        '/v1alpha/models/gemini-2.5-flash:generateContent'
    )


async def test_safety_settings_are_sent():
    _, requests = await invoke(
        model(safety_settings={'HARM_CATEGORY_HARASSMENT': 'BLOCK_NONE'}),
        [canned.gemini_response()],
    )
    assert requests[0]['body']['safetySettings'] == [
        {'category': 'HARM_CATEGORY_HARASSMENT', 'threshold': 'BLOCK_NONE'}
    ]


async def test_non_dict_safety_settings_fail_the_call():
    with pytest.raises(TypeError, match='safety_settings must be'):
        await invoke(model(), [], safety_settings=['BLOCK_NONE'])


async def test_generation_config_overrides_the_model_settings():
    _, requests = await invoke(
        model(),
        [canned.gemini_response()],
        generation_config={'temperature': 0.1, 'response_modalities': ['TEXT']},
        cached_content='cachedContents/abc',
    )
    body = requests[0]['body']
    assert body['generationConfig']['temperature'] == 0.1
    assert body['generationConfig']['responseModalities'] == ['TEXT']
    assert body['cachedContent'] == 'cachedContents/abc'


@pytest.mark.parametrize(
    ('mime_type', 'match'),
    [(None, "set to 'application/json'$"), ('text/x.enum', 'define enums')],
)
async def test_schema_requires_json_mime_type(mime_type, match):
    chat_model = model(response_schema={'type': 'object'})
    with pytest.raises(ValueError, match=match):
        await invoke(chat_model, [], response_mime_type=mime_type)


async def test_json_object_response_format_sets_only_the_mime_type():
    _, requests = await invoke(
        model(), [canned.gemini_response()], response_format={'type': 'json_object'}
    )
    config = requests[0]['body']['generationConfig']
    assert config['responseMimeType'] == 'application/json'
    assert 'responseJsonSchema' not in config


# ── Request: tools ───────────────────────────────────────────────────────────


async def tool_request(tools, **kwargs) -> dict:
    chat_model = model().bind_tools(tools, tool_choice=kwargs.pop('tool_choice', None))
    _, requests = await invoke(chat_model, [canned.gemini_response()], **kwargs)
    return requests[0]['body']


async def test_builtin_and_native_tools_are_passed_through():
    body = await tool_request(
        [
            {'google_search': {}},
            types.Tool(code_execution=types.ToolCodeExecution()),
            {
                'function_declarations': [
                    {'name': 'a', 'description': 'A.'},
                    {'name': 'b', 'parameters': {'type': 'object', 'properties': {}}},
                ]
            },
        ],
        tool_choice='any',
    )
    assert body['tools'] == [
        {'googleSearch': {}},
        {'codeExecution': {}},
        {'functionDeclarations': [{'description': 'A.', 'name': 'a'}, {'name': 'b'}]},
    ]
    assert body['toolConfig'] == {
        'functionCallingConfig': {'mode': 'ANY', 'allowedFunctionNames': ['a', 'b']}
    }


async def test_tool_choice_with_only_builtin_tools_is_ignored():
    body = await tool_request([{'google_search': {}}], tool_choice='auto')
    assert 'toolConfig' not in body


@pytest.mark.parametrize(
    ('tools', 'match'),
    [
        (['not a dict'], 'Unsupported tool type'),
        (
            [{'google_search': {}, 'code_execution': {}}],
            'cannot have multiple special tool types',
        ),
        (
            [{'google_search_retrieval': {}}, {'google_search_retrieval': {}}],
            'multiple google_search_retrieval tools',
        ),
    ],
)
async def test_invalid_tools_fail_the_call(tools, match):
    with pytest.raises(ValueError, match=match):
        await invoke(model().bind_tools(tools), [])


async def test_tool_choice_without_tools_fails_the_call():
    with pytest.raises(ValueError, match="'tool_choice' can only be specified"):
        await invoke(model(), [], tool_choice='auto')


@pytest.mark.parametrize(
    ('tool_choice', 'expected'),
    [
        (True, {'mode': 'ANY', 'allowedFunctionNames': ['get_weather']}),
        ('get_weather', {'mode': 'ANY', 'allowedFunctionNames': ['get_weather']}),
        (['get_weather'], {'mode': 'ANY', 'allowedFunctionNames': ['get_weather']}),
        ({'mode': 'AUTO'}, {'mode': 'AUTO'}),
        (
            {
                'function_calling_config': {
                    'mode': 'ANY',
                    'allowed_function_names': ['get_weather'],
                }
            },
            {'mode': 'ANY', 'allowedFunctionNames': ['get_weather']},
        ),
    ],
)
async def test_more_tool_choice_formats(tool_choice, expected):
    body = await tool_request([WEATHER_TOOL], tool_choice=tool_choice)
    assert body['toolConfig'] == {'functionCallingConfig': expected}


async def test_non_string_non_dict_tool_choice_fails_the_call():
    with pytest.raises(ValueError, match='Unrecognized tool choice'):
        await tool_request([WEATHER_TOOL], tool_choice=3)


async def test_tool_config_is_passed_through():
    tool_config = {'function_calling_config': {'mode': 'NONE'}}
    body = await tool_request([WEATHER_TOOL], tool_config=tool_config)
    assert body['toolConfig'] == {'functionCallingConfig': {'mode': 'NONE'}}


async def test_tool_choice_keeps_the_tool_config_retrieval_config():
    tool_config = types.ToolConfig(
        retrieval_config=types.RetrievalConfig(language_code='it')
    )
    body = await tool_request(
        [WEATHER_TOOL], tool_choice='auto', tool_config=tool_config
    )
    assert body['toolConfig'] == {
        'functionCallingConfig': {'mode': 'AUTO'},
        'retrievalConfig': {'language_code': 'it'},
    }


async def test_tool_choice_conflicting_with_tool_config_fails_the_call():
    with pytest.raises(ValueError, match='Cannot specify both tool_choice'):
        await tool_request(
            [WEATHER_TOOL],
            tool_choice='auto',
            tool_config={'function_calling_config': {'mode': 'NONE'}},
        )


# ── Request: tool schemas ────────────────────────────────────────────────────


async def declared_parameters(parameters: dict) -> dict:
    tool = {'name': 'f', 'parameters': parameters}
    body = await tool_request([tool])
    return body['tools'][0]['functionDeclarations'][0]['parameters']


async def test_array_and_union_properties_are_converted():
    parameters = await declared_parameters(
        {
            'type': 'object',
            'definitions': {'ignored': {}},
            'additionalProperties': False,
            'properties': {
                'tags': {
                    'type': 'array',
                    'items': {'type': 'string', 'enum': ['a', 'b']},
                    'description': 'Tags.',
                },
                'grid': {
                    'type': 'array',
                    'items': {
                        'type': 'array',
                        'items': {'allOf': [{'type': 'number'}, {'type': 'string'}]},
                    },
                },
                'rows': {
                    'type': 'array',
                    'items': {
                        'type': 'object',
                        'title': 'Row',
                        'properties': {'k': {'type': 'string'}},
                        'required': ['k'],
                    },
                },
                'tuple': {'type': 'array', 'items': [{'type': 'string'}]},
                'names': {'type': 'array', 'items': 'string'},
                'blank': {'type': 'array', 'items': ''},
                'loose': {'type': 'array', 'items': {'description': 'Anything.'}},
                'opt_enum': {
                    'anyOf': [{'type': 'string'}, {'type': 'null'}],
                    'enum': ['a'],
                },
                'opt_items': {
                    'anyOf': [{'type': 'array'}, {'type': 'null'}],
                    'items': {'type': 'integer'},
                },
                'maybe': {
                    'type': 'array',
                    'items': {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
                },
                'either': {'anyOf': [{'type': 'string'}, {'type': 'integer'}]},
                'choice': {
                    'anyOf': [{'type': 'string', 'enum': ['x']}, {'type': 'null'}],
                    'description': 'Pick.',
                },
                'opt_list': {
                    'anyOf': [
                        {'type': 'array', 'items': {'type': 'number'}},
                        {'type': 'null'},
                    ]
                },
                'opt_obj': {
                    'anyOf': [
                        {
                            'type': 'object',
                            'properties': {'x': {'type': 'boolean', 'default': True}},
                        },
                        {'type': 'null'},
                    ]
                },
                'free': {'type': 'object'},
                'mapping': {
                    'type': 'object',
                    'additionalProperties': {'type': 'string'},
                },
                'title': {'type': 'string'},
                'typed': {'type': {'_value_': 'BOOLEAN'}},
                'bad': 'not a schema',
            },
            'required': ['tags'],
        }
    )
    assert parameters == {
        'properties': {
            'tags': {
                'description': 'Tags.',
                'items': {'enum': ['a', 'b'], 'type': 'STRING'},
                'type': 'ARRAY',
            },
            # Only the first allOf member is kept.
            'grid': {
                'items': {'items': {'type': 'NUMBER'}, 'type': 'ARRAY'},
                'type': 'ARRAY',
            },
            'rows': {
                'items': {
                    'description': 'Row',
                    'properties': {'k': {'type': 'STRING'}},
                    'required': ['k'],
                    'type': 'OBJECT',
                },
                'type': 'ARRAY',
            },
            'tuple': {'items': {'type': 'STRING'}, 'type': 'ARRAY'},
            'names': {'items': {'type': 'STRING'}, 'type': 'ARRAY'},
            'blank': {'items': {'type': 'STRING'}, 'type': 'ARRAY'},
            'loose': {
                'items': {'description': 'Anything.', 'type': 'STRING'},
                'type': 'ARRAY',
            },
            # The union's enum and items carry over to the chosen member.
            'opt_enum': {'enum': ['a'], 'nullable': True, 'type': 'STRING'},
            'opt_items': {
                'items': {'type': 'INTEGER'},
                'nullable': True,
                'type': 'ARRAY',
            },
            'maybe': {
                'items': {'nullable': True, 'type': 'STRING'},
                'type': 'ARRAY',
            },
            # The SDK leaves this nested key in snake_case.
            'either': {'any_of': [{'type': 'STRING'}, {'type': 'INTEGER'}]},
            'choice': {
                'description': 'Pick.',
                'enum': ['x'],
                'nullable': True,
                'type': 'STRING',
            },
            'opt_list': {
                'items': {'type': 'NUMBER'},
                'nullable': True,
                'type': 'ARRAY',
            },
            'opt_obj': {
                'nullable': True,
                'properties': {'x': {'type': 'BOOLEAN'}},
                'required': [],
                'type': 'OBJECT',
            },
            # Gemini needs a type for an object without properties.
            'free': {'type': 'STRING'},
            'mapping': {'type': 'OBJECT'},
            'title': {'description': "title is {'type': 'string'}", 'type': 'STRING'},
            'typed': {'type': 'BOOLEAN'},
        },
        'required': ['tags'],
        'type': 'OBJECT',
    }


async def test_refs_are_inlined_and_cycles_broken():
    parameters = await declared_parameters(
        {
            'type': {'_value_': 'OBJECT'},
            'title': 'Args',
            'description': 'Arguments.',
            '$defs': {
                'Node': {
                    'type': 'object',
                    'properties': {
                        'child': {'$ref': '#/$defs/Node'},
                        'v': {'type': 'integer'},
                    },
                },
                'Pair': [{'type': 'string'}, {'type': 'integer'}],
            },
            'properties': {
                'node': {'$ref': '#/$defs/Node'},
                'place': {'$ref': '#/$defs/Node', 'description': 'Where.'},
                'second': {'$ref': '#/$defs/Pair/1'},
            },
        }
    )
    node = {
        'properties': {'child': {'type': 'STRING'}, 'v': {'type': 'INTEGER'}},
        'required': ['child', 'v'],
        'type': 'OBJECT',
    }
    assert parameters == {
        'description': 'Arguments.',
        'properties': {
            'node': node,
            'place': {'description': 'Where.', **node},
            'second': {'type': 'INTEGER'},
        },
        'required': [],
        'title': 'Args',
        'type': 'OBJECT',
    }


@pytest.mark.parametrize(
    ('ref', 'error', 'match'),
    [
        ('other.json#/Place', ValueError, 'URI fragments'),
        ('#/$defs/Missing', KeyError, 'not found'),
        ('#/$defs/Pair/5', KeyError, 'not found'),
        ('#/$defs/Pair/type', KeyError, 'not found'),
    ],
)
async def test_unresolvable_refs_fail_the_call(ref, error, match):
    parameters = {
        'type': 'object',
        '$defs': {'Pair': [{'type': 'string'}]},
        'properties': {'p': {'$ref': ref}},
    }
    with pytest.raises(error, match=match):
        await declared_parameters(parameters)


@pytest.mark.parametrize(
    ('parameters', 'match'),
    [
        ({'type': 'object', 'properties': {'p': {'type': 3}}}, 'int not supported'),
        ({'type': ['object'], 'properties': {'p': {}}}, 'Invalid type'),
    ],
)
async def test_invalid_schema_types_fail_the_call(parameters, match):
    with pytest.raises(ValueError, match=match):
        await declared_parameters(parameters)


# ── Request: message content ─────────────────────────────────────────────────

SIG = base64.b64encode(b'sig').decode()
PNG_BYTES = base64.b64decode(PNG)


def wire_b64(data: bytes) -> str:
    # The SDK serializes bytes as url-safe base64.
    return base64.urlsafe_b64encode(data).decode()


async def user_parts(content, chat_model=None, responses=()) -> list[dict]:
    _, requests = await invoke(
        chat_model or model(),
        [*responses, canned.gemini_response()],
        [HumanMessage(content)],
    )
    return requests[-1]['body']['contents'][0]['parts']


async def test_text_thinking_and_reasoning_blocks():
    parts = await user_parts(
        [
            {'type': 'text', 'text': 'signed', 'extras': {'signature': SIG}},
            {'type': 'text', 'text': 'raw', 'thought_signature': b'sig'},
            {'no_type': 1},
            {'type': 'thinking', 'thinking': 'hmm', 'signature': SIG},
            {'type': 'reasoning', 'reasoning': 'because'},
            {
                'type': 'reasoning',
                'summary': [{'text': ' one '}, {'text': ''}, 'x', {'text': 'two'}],
            },
            {'type': 'reasoning', 'summary': []},
        ]
    )
    assert parts == [
        {'text': 'signed', 'thoughtSignature': wire_b64(b'sig')},
        {'text': 'raw', 'thoughtSignature': wire_b64(b'sig')},
        {'text': "{'no_type': 1}"},
        {'text': 'hmm', 'thought': True, 'thoughtSignature': wire_b64(b'sig')},
        {'text': 'because', 'thought': True},
        {'text': 'one two', 'thought': True},
    ]


async def test_file_and_provider_resolved_blocks_become_file_data():
    parts = await user_parts(
        [
            {
                'type': 'file',
                'file_id': 'files/abc',
                'mime_type': 'application/pdf',
                'media_processing': 'STATIC',
            },
            {'type': 'file', 'file_id': 'files/def'},
            {'type': 'video', 'url': 'https://www.youtube.com/watch?v=1'},
            {'type': 'image', 'file_id': 'files/img', 'mime_type': 'image/png'},
        ]
    )
    assert parts == [
        {
            'fileData': {'fileUri': 'files/abc', 'mimeType': 'application/pdf'},
            'mediaProcessing': 'STATIC',
        },
        {
            'fileData': {
                'fileUri': 'files/def',
                'mimeType': 'application/octet-stream',
            }
        },
        {'fileData': {'fileUri': 'https://www.youtube.com/watch?v=1'}},
        {'fileData': {'fileUri': 'files/img', 'mimeType': 'image/png'}},
    ]


async def test_inline_data_blocks_are_decoded_or_downloaded():
    download = CannedResponse(json_body='pixels')
    parts = await user_parts(
        [
            {'type': 'image', 'base64': PNG},
            {'type': 'image', 'url': 'https://example.com/cat.png'},
            {'type': 'audio', 'source_type': 'url', 'url': 'https://example.com/a'},
        ],
        responses=[download, download],
    )
    assert parts == [
        # The mime type is sniffed from the bytes.
        {'inlineData': {'data': wire_b64(PNG_BYTES), 'mimeType': 'image/png'}},
        # ... or guessed from the URL.
        {'inlineData': {'data': wire_b64(b'"pixels"'), 'mimeType': 'image/png'}},
        {'inlineData': {'data': wire_b64(b'"pixels"')}},
    ]


@pytest.mark.parametrize(
    ('block', 'match'),
    [
        ({'type': 'image', 'source_type': 'id', 'id': 'x'}, 'must be url or base64'),
        ({'type': 'file', 'text': 'x'}, "must contain 'url', 'base64'"),
    ],
)
async def test_unusable_data_blocks_fail_the_call(block, match):
    with pytest.raises(ValueError, match=match):
        await user_parts([block])


async def test_media_resolution_is_sent_to_gemini_3_only():
    block = {
        'type': 'image',
        'base64': PNG,
        'mime_type': 'image/png',
        'media_resolution': 'MEDIA_RESOLUTION_HIGH',
    }
    [part] = await user_parts([block], model('gemini-3-pro-preview'))
    assert part['mediaResolution'] == {'level': 'MEDIA_RESOLUTION_HIGH'}

    with pytest.warns(UserWarning, match='media resolution'):
        [part] = await user_parts([block])
    assert 'mediaResolution' not in part


async def test_image_url_variants():
    parts = await user_parts(
        [
            {'type': 'image_url', 'image_url': 'gs://bucket/cat.jpg'},
            {
                'type': 'image_url',
                'image_url': {'url': 'https://example.com/pic'},
                'extras': {'signature': SIG},
            },
        ],
        responses=[CannedResponse(json_body='pixels')],
    )
    assert parts == [
        {'fileData': {'fileUri': 'gs://bucket/cat.jpg', 'mimeType': 'image/jpeg'}},
        {
            'inlineData': {'data': wire_b64(b'"pixels"')},
            'thoughtSignature': wire_b64(b'sig'),
        },
    ]


@pytest.mark.parametrize(
    ('image_url', 'match'),
    [
        ({'detail': 'high'}, 'Unrecognized message image format'),
        ('data:image/png,abc', 'Invalid base64 data URI'),
        ('not-a-url', 'Media string must be one of'),
    ],
)
async def test_invalid_image_urls_fail_the_call(image_url, match):
    with pytest.raises(ValueError, match=match):
        await user_parts([{'type': 'image_url', 'image_url': image_url}])


async def test_media_blocks():
    parts = await user_parts(
        [
            {'type': 'media', 'data': PNG, 'mime_type': 'image/png'},
            {
                'type': 'media',
                'data': b'raw',
                'mime_type': 'audio/wav',
                'extras': {'signature': b'sig'},
            },
            {
                'type': 'media',
                'file_uri': 'files/v',
                'mime_type': 'video/mp4',
                'video_metadata': {'start_offset': '1s'},
                'media_processing': 'AGENTIC',
                'extras': {'signature': SIG},
            },
        ]
    )
    assert parts == [
        {'inlineData': {'data': wire_b64(PNG_BYTES), 'mimeType': 'image/png'}},
        {
            'inlineData': {'data': wire_b64(b'raw'), 'mimeType': 'audio/wav'},
            'thoughtSignature': wire_b64(b'sig'),
        },
        {
            'fileData': {'fileUri': 'files/v', 'mimeType': 'video/mp4'},
            'mediaProcessing': 'AGENTIC',
            'thoughtSignature': wire_b64(b'sig'),
            # The SDK leaves this nested key in snake_case.
            'videoMetadata': {'start_offset': '1s'},
        },
    ]


@pytest.mark.parametrize(
    ('block', 'match'),
    [
        ({'type': 'media', 'data': PNG}, 'Missing mime_type'),
        ({'type': 'media', 'data': 'not base64!', 'mime_type': 'x/y'}, 'valid base64'),
        ({'type': 'media', 'mime_type': 'x/y'}, 'either data or file_uri'),
    ],
)
async def test_invalid_media_blocks_fail_the_call(block, match):
    with pytest.raises(ValueError, match=match):
        await user_parts([block])


# ── Request: conversation history ────────────────────────────────────────────


async def contents_for(messages, chat_model=None) -> list[dict]:
    _, requests = await invoke(
        chat_model or model(), [canned.gemini_response()], messages
    )
    return requests[0]['body']['contents']


async def test_foreign_ai_blocks_are_dropped_and_native_ones_fail():
    foreign = AIMessage([{'type': 'weird'}, {'type': 'text', 'text': 'kept'}])
    empty = AIMessage([{'type': 'weird'}])
    contents = await contents_for(
        [HumanMessage('a'), foreign, empty, HumanMessage('b')]
    )
    assert contents[1] == {'parts': [{'text': 'kept'}], 'role': 'model'}
    # Gemini rejects a content without parts.
    assert contents[2] == {'parts': [{'text': ''}], 'role': 'model'}

    native = AIMessage(
        [{'type': 'weird'}], response_metadata={'model_provider': 'google_genai'}
    )
    with pytest.raises(ValueError, match='Unrecognized message part type'):
        await contents_for([HumanMessage('a'), native, HumanMessage('b')])


async def test_gcs_uris_are_dropped_from_ai_history():
    history = AIMessage(
        [
            'text',
            {'type': 'image_url', 'image_url': {'url': 'gs://b/1.png'}},
            {'type': 'image_url', 'image_url': 'gs://b/2.png'},
            {'type': 'image', 'url': 'gs://b/3.png', 'mime_type': 'image/png'},
            {'type': 'file', 'url': 'gs://b/4.pdf', 'mime_type': 'application/pdf'},
            {'type': 'media', 'file_uri': 'gs://b/5.mp4', 'mime_type': 'video/mp4'},
            {'type': 'any', 'file_data': {'file_uri': 'gs://b/6'}},
            {'type': 'media', 'file_uri': 'files/7', 'mime_type': 'video/mp4'},
        ]
    )
    contents = await contents_for([HumanMessage('a'), history, HumanMessage('b')])
    assert contents[1]['parts'] == [
        {'text': 'text'},
        {'fileData': {'fileUri': 'files/7', 'mimeType': 'video/mp4'}},
    ]


async def test_tool_calling_turn_keeps_content_and_signatures():
    call_sig = base64.b64encode(b'call-sig').decode()
    turn = AIMessage(
        [
            '',
            'thinking aloud',
            {'type': 'text', 'text': ''},
            {'type': 'tool_call', 'name': 'f', 'args': {}, 'id': 'c1'},
            {'type': 'file_data', 'file_uri': 'files/x'},
            {'type': 'function_call_signature', 'signature': SIG},
            {'type': 'function_call_signature', 'signature': ''},
        ],
        tool_calls=[
            {'name': 'f', 'args': {}, 'id': 'c1'},
            {'name': 'g', 'args': {'n': 1}, 'id': 'c2'},
        ],
        additional_kwargs={
            '__gemini_function_call_thought_signatures__': {'c2': call_sig}
        },
        response_metadata={'model_provider': 'google_genai'},
    )
    contents = await contents_for([HumanMessage('a'), turn])
    assert contents[1] == {
        'parts': [
            {'text': 'thinking aloud'},
            {
                'fileData': {
                    'fileUri': 'files/x',
                    'mimeType': 'application/octet-stream',
                }
            },
            {
                'functionCall': {'args': {}, 'name': 'f'},
                'thoughtSignature': wire_b64(b'sig'),
            },
            {
                'functionCall': {'args': {'n': 1}, 'name': 'g'},
                'thoughtSignature': wire_b64(b'call-sig'),
            },
        ],
        'role': 'model',
    }


async def test_tool_calling_turn_with_empty_text_has_only_calls():
    turn = AIMessage('', tool_calls=[{'name': 'f', 'args': {}, 'id': 'c1'}])
    contents = await contents_for([HumanMessage('a'), turn])
    assert contents[1]['parts'] == [{'functionCall': {'args': {}, 'name': 'f'}}]


async def test_tool_results_with_media_and_plain_text():
    turn = AIMessage(
        '',
        tool_calls=[
            {'name': 'snap', 'args': {}, 'id': 'c1'},
            {'name': 'echo', 'args': {}, 'id': 'c2'},
        ],
    )
    messages = [
        HumanMessage('a'),
        turn,
        ToolMessage(
            [
                {'type': 'text', 'text': 'a photo'},
                {'type': 'image', 'base64': PNG, 'mime_type': 'image/png'},
            ],
            tool_call_id='c1',
        ),
        ToolMessage('plain text', tool_call_id='c2', name='echo_tool'),
    ]
    contents = await contents_for(messages)
    assert contents[2] == {
        'parts': [
            {'inlineData': {'data': wire_b64(PNG_BYTES), 'mimeType': 'image/png'}},
            {
                'functionResponse': {
                    'name': 'snap',
                    'response': {'output': [{'type': 'text', 'text': 'a photo'}]},
                }
            },
            {
                'functionResponse': {
                    'name': 'echo_tool',
                    'response': {'output': 'plain text'},
                }
            },
        ],
        'role': 'user',
    }


async def test_legacy_function_call_and_function_message():
    messages = [
        HumanMessage('a'),
        AIMessage(
            '',
            additional_kwargs={'function_call': {'name': 'f', 'arguments': '{"x": 1}'}},
        ),
        FunctionMessage('{"ok": true}', name='f'),
    ]
    contents = await contents_for(messages)
    assert contents[1:] == [
        {'parts': [{'functionCall': {'args': {'x': 1}, 'name': 'f'}}], 'role': 'model'},
        {
            'parts': [{'functionResponse': {'name': 'f', 'response': {'ok': True}}}],
            'role': 'user',
        },
    ]


async def test_unexpected_message_type_fails_the_call():
    with pytest.raises(ValueError, match='Unexpected message'):
        await contents_for([BaseMessage('x', type='custom')])


async def test_system_message_can_be_merged_into_the_first_human_turn():
    chat_model = model(convert_system_message_to_human=True)
    _, requests = await invoke(chat_model, [canned.gemini_response()])
    body = requests[0]['body']
    assert 'systemInstruction' not in body
    assert body['contents'] == [
        {'parts': [{'text': 'Be terse.'}, {'text': 'Hi'}], 'role': 'user'}
    ]


async def test_later_system_messages_extend_the_instruction():
    messages = [SystemMessage('One.'), HumanMessage('a'), SystemMessage('Two.')]
    _, requests = await invoke(model(), [canned.gemini_response()], messages)
    assert requests[0]['body']['systemInstruction'] == {
        'parts': [{'text': 'One.'}, {'text': 'Two.'}]
    }


# ── Response: content parts ──────────────────────────────────────────────────


def gemini_payload(parts, *, model_version='gemini-2.5-flash', **candidate) -> dict:
    return {
        'candidates': [
            {
                'content': {'parts': parts, 'role': 'model'},
                'finishReason': 'STOP',
                **candidate,
            }
        ],
        'modelVersion': model_version,
        'usageMetadata': {
            'promptTokenCount': 3,
            'candidatesTokenCount': 2,
            'totalTokenCount': 5,
        },
    }


async def reply(parts, **kwargs) -> AIMessage:
    payload = CannedResponse(json_body=gemini_payload(parts, **kwargs))
    result, _ = await invoke(model(), [payload])
    return result


async def test_thoughts_and_signed_text_become_blocks():
    result = await reply(
        [
            {'text': 'pondering', 'thought': True, 'thoughtSignature': SIG},
            {'text': 'plain\n'},
            {'text': '', 'thoughtSignature': SIG},
        ]
    )
    assert result.content == [
        {'type': 'thinking', 'thinking': 'pondering', 'signature': SIG},
        # Once thinking is present, text is kept as blocks.
        {'type': 'text', 'text': 'plain'},
        {'type': 'text', 'text': '', 'extras': {'signature': SIG}},
    ]
    assert result.text == 'plain'


async def test_gemini_3_replies_are_text_blocks():
    result = await reply([{'text': 'hi'}], model_version='gemini-3-pro-preview')
    assert result.content == [{'type': 'text', 'text': 'hi'}]

    empty = await reply([], model_version='gemini-3-pro-preview')
    assert empty.content == []


async def test_code_execution_parts():
    result = await reply(
        [
            {'text': 'Running.'},
            {'executableCode': {'code': 'print(1)', 'language': 'PYTHON'}},
            {'codeExecutionResult': {'output': '1\n', 'outcome': 'OUTCOME_OK'}},
            {'codeExecutionResult': {'output': 'boom', 'outcome': 'OUTCOME_FAILED'}},
            {'codeExecutionResult': {'outcome': 'OUTCOME_OK'}},
        ]
    )
    text, code, ok, failed = result.content
    assert text == 'Running.'
    assert code['type'] == 'executable_code'
    assert code['executable_code'] == 'print(1)'
    assert code['language'] == 'PYTHON'
    assert ok == {
        'type': 'code_execution_result',
        'code_execution_result': '1\n',
        'outcome': 1,
        'tool_call_id': '',
    }
    assert failed['outcome'] == 2


async def test_server_tool_parts():
    result = await reply(
        [
            {
                'toolCall': {
                    'id': 's1',
                    'toolType': 'GOOGLE_SEARCH_WEB',
                    'args': {'q': 'x'},
                },
                'thoughtSignature': SIG,
            },
            {
                'toolResponse': {
                    'id': 's1',
                    'toolType': 'GOOGLE_SEARCH_WEB',
                    'response': {'hits': 1},
                },
                'thoughtSignature': SIG,
            },
            {'toolCall': {}},
            {'toolResponse': {}},
        ]
    )
    call, response, bare_call, bare_response = result.content
    assert call == {
        'type': 'server_tool_call',
        'name': 'google_search_web',
        'id': 's1',
        'args': {'q': 'x'},
        'extras': {'signature': SIG},
    }
    assert response == {
        'type': 'server_tool_result',
        'tool_call_id': 's1',
        'status': 'success',
        'output': {'hits': 1},
        'extras': {'block_type': 'google_search_web', 'signature': SIG},
    }
    assert bare_call['name'] == 'media_processing'
    assert bare_call['id']
    assert bare_response['tool_call_id'] == ''
    assert bare_response['extras'] == {'block_type': 'media_processing'}


async def test_inline_image_and_audio_output():
    result = await reply(
        [
            {
                'inlineData': {'data': PNG, 'mimeType': 'image/png'},
                'thoughtSignature': SIG,
            },
            {'inlineData': {'data': 'AAAA', 'mimeType': 'audio/L16'}},
        ]
    )
    assert result.content == [
        {
            'type': 'image_url',
            'image_url': {'url': f'data:image/png;base64,{PNG}'},
            'extras': {'signature': SIG},
        }
    ]
    audio = result.additional_kwargs['audio']
    assert audio.startswith(b'RIFF')
    assert audio.endswith(b'\x00\x00\x00')


async def test_function_call_signatures_are_kept_by_call_id():
    result = await reply(
        [
            {
                'functionCall': {
                    'id': 'call-1',
                    'name': 'f',
                    'args': {'xs': [1.0, 2.5]},
                },
                'thoughtSignature': SIG,
            }
        ]
    )
    assert result.tool_calls[0]['id'] == 'call-1'
    assert result.tool_calls[0]['args'] == {'xs': [1, 2.5]}
    assert result.additional_kwargs['__gemini_function_call_thought_signatures__'] == {
        'call-1': SIG
    }


async def test_signatures_round_trip_into_the_next_request():
    previous = await reply(
        [
            {'text': 'pondering', 'thought': True, 'thoughtSignature': SIG},
            {
                'functionCall': {'id': 'c1', 'name': 'f', 'args': {}},
                'thoughtSignature': SIG,
            },
        ]
    )
    contents = await contents_for(
        [HumanMessage('a'), previous, ToolMessage('ok', tool_call_id='c1')]
    )
    assert contents[1]['parts'] == [
        {'text': 'pondering', 'thought': True, 'thoughtSignature': wire_b64(b'sig')},
        {
            'functionCall': {'args': {}, 'name': 'f'},
            'thoughtSignature': wire_b64(b'sig'),
        },
    ]


async def test_grounding_metadata_is_exposed():
    result = await reply(
        [{'text': 'grounded'}],
        groundingMetadata={'webSearchQueries': ['q']},
    )
    grounding = result.response_metadata['grounding_metadata']
    assert grounding['web_search_queries'] == ['q']
    assert grounding['grounding_chunks'] == []
    assert grounding['grounding_supports'] == []


async def test_unknown_finish_reason_is_named():
    result = await reply([{'text': 'x'}], finishReason='SOMETHING_NEW')
    assert result.response_metadata['finish_reason'] == 'SOMETHING_NEW'


# ── Response: usage ──────────────────────────────────────────────────────────


async def test_server_tool_prompt_tokens_count_as_input():
    payload = gemini_payload([{'text': 'x'}])
    payload['usageMetadata']['toolUsePromptTokenCount'] = 4
    result, _ = await invoke(model(), [CannedResponse(json_body=payload)])
    assert result.usage_metadata['input_tokens'] == 7


async def test_zero_usage_is_omitted():
    payload = gemini_payload([{'text': 'x'}])
    payload['usageMetadata'] = {'promptTokenCount': 0}
    result, _ = await invoke(model(), [CannedResponse(json_body=payload)])
    assert result.usage_metadata is None


async def test_stream_usage_compensates_a_lower_final_prompt_count():
    first = gemini_payload([{'text': 'a'}])
    first['usageMetadata'] = {
        'promptTokenCount': 10,
        'candidatesTokenCount': 1,
        'totalTokenCount': 11,
    }
    last = gemini_payload([{'text': 'b'}])
    last['usageMetadata'] = {
        'promptTokenCount': 8,
        'candidatesTokenCount': 2,
        'totalTokenCount': 10,
    }
    chunks, _ = await stream(model(), [CannedResponse(sse_events=[first, last])])
    inputs = [c.usage_metadata['input_tokens'] for c in chunks if c.usage_metadata]
    assert inputs == [10, -2]
    assert sum(inputs) == 8


async def test_stream_without_usage_reports_none():
    payload = gemini_payload([{'text': 'a'}])
    del payload['usageMetadata']
    chunks, _ = await stream(model(), [CannedResponse(sse_events=[payload])])
    assert all(c.usage_metadata is None for c in chunks)


# ── Response: streaming blocks ───────────────────────────────────────────────


async def test_stream_indexes_content_blocks():
    events = [
        gemini_payload(
            [{'text': 'th', 'thought': True}], model_version='gemini-3-pro-preview'
        ),
        gemini_payload(
            [{'text': 'ink', 'thought': True}], model_version='gemini-3-pro-preview'
        ),
        gemini_payload(
            [{'text': 'Hi'}, {'functionCall': {'name': 'f', 'args': {}}}],
            model_version='gemini-3-pro-preview',
        ),
        gemini_payload([{'text': ' there'}], model_version='gemini-3-pro-preview'),
    ]
    chunks, _ = await stream(
        model('gemini-3-pro-preview'), [CannedResponse(sse_events=events)]
    )
    blocks = [b for c in chunks if isinstance(c.content, list) for b in c.content]
    assert [(b['type'], b['index']) for b in blocks] == [
        ('thinking', 0),
        ('thinking', 0),
        ('text', 1),
        ('text', 3),
    ]
    [call] = [tc for c in chunks for tc in c.tool_call_chunks]
    assert call['index'] == 2


async def test_stream_blocked_prompt_yields_feedback():
    payload = {'promptFeedback': {'blockReason': 'SAFETY'}}
    chunks, _ = await stream(model(), [CannedResponse(sse_events=[payload])])
    assert chunks[0].content == ''
    assert chunks[0].response_metadata['prompt_feedback']['block_reason'] == 'SAFETY'


# ── Errors and structured output parsing ─────────────────────────────────────


async def test_token_limit_errors_are_not_wrapped():
    response = gemini_error(
        400,
        'The input token count exceeds the maximum number of tokens allowed.',
        'INVALID_ARGUMENT',
    )
    with pytest.raises(errors.ClientError) as exc_info:
        await invoke(model(), [response])
    assert not isinstance(exc_info.value, ChatGoogleGenerativeAIError)


async def test_structured_output_finds_json_after_a_preamble():
    structured = model().with_structured_output(Judgement)
    text = 'Here it is:\n```json\n{"ok": false, "why": "no"}\n```'
    result, _ = await invoke(structured, [canned.gemini_response(text)])
    assert result == Judgement(ok=False, why='no')


async def test_top_level_properties_without_type_are_an_object():
    parameters = await declared_parameters({'properties': {'a': {'type': 'string'}}})
    assert parameters == {
        'properties': {'a': {'type': 'STRING'}},
        'required': [],
        'type': 'OBJECT',
    }


async def test_gcs_and_downloaded_blocks_with_a_custom_http_client():
    async with httpx.AsyncClient() as client:
        chat_model = model(http_async_client=client)
        parts = await user_parts(
            [
                {'type': 'image', 'url': 'gs://bucket/x.png', 'mime_type': 'image/png'},
                {'type': 'image', 'url': 'https://example.com/y.png'},
            ],
            chat_model,
            responses=[CannedResponse(json_body='pixels')],
        )
    assert parts == [
        {'fileData': {'fileUri': 'gs://bucket/x.png', 'mimeType': 'image/png'}},
        {'inlineData': {'data': wire_b64(b'"pixels"'), 'mimeType': 'image/png'}},
    ]


async def test_stream_skips_plain_strings_when_indexing():
    events = [gemini_payload([{'text': 'a'}, {'text': 'b', 'thought': True}])]
    chunks, _ = await stream(model(), [CannedResponse(sse_events=events)])
    assert chunks[0].content == ['a', {'type': 'thinking', 'thinking': 'b', 'index': 0}]


def test_sync_embeddings():
    emb = embeddings(task_type='semantic_similarity')
    with ProviderRecorder(
        [canned.gemini_embeddings(count=2), canned.gemini_embeddings(count=1)]
    ) as recorder:
        docs = emb.embed_documents(['a', 'b'])
        query = emb.embed_query('q')
    assert len(docs) == 2
    assert query == [0.1, 0.11, 0.12, 0.13]
    docs_request, query_request = recorder.requests
    assert docs_request['url'] == f'{BASE}/gemini-embedding-001:batchEmbedContents'
    assert [r['taskType'] for r in docs_request['body']['requests']] == [
        'SEMANTIC_SIMILARITY',
        'SEMANTIC_SIMILARITY',
    ]
    assert query_request['body']['requests'][0]['taskType'] == 'SEMANTIC_SIMILARITY'


def test_sync_embedding_errors_are_wrapped():
    emb = embeddings()
    with (
        ProviderRecorder([gemini_error(400, 'bad', 'INVALID_ARGUMENT')]),
        pytest.raises(GoogleGenerativeAIError, match='INVALID_ARGUMENT'),
    ):
        emb.embed_documents(['a'])
    with (
        ProviderRecorder([gemini_error(400, 'bad', 'INVALID_ARGUMENT')]),
        pytest.raises(GoogleGenerativeAIError, match='INVALID_ARGUMENT'),
    ):
        emb.embed_query('q')


async def test_embedding_server_errors_are_wrapped():
    with (
        ProviderRecorder([gemini_error(500, 'boom', 'INTERNAL')]),
        pytest.raises(GoogleGenerativeAIError, match='Error embedding content: 500'),
    ):
        await embeddings().aembed_documents(['a'])
