"""Tests for the native Mistral chat and embedding models."""

from unittest.mock import AsyncMock, patch

import httpx
from pydantic import BaseModel
import pytest

from tests.common import provider_responses as canned
from tests.common.provider_recorder import CannedResponse, ProviderRecorder

from radicalbit_ai_gateway.llm.factory import init_chat_model, init_embeddings
from radicalbit_ai_gateway.llm.messages import (
    AIMessage,
    FunctionMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from radicalbit_ai_gateway.llm.providers.mistralai import (
    ChatMistralAI,
    MistralEmbeddings,
    OutputParserError,
    SSEError,
    _mistral_tool_call_id,
)

URL = 'https://api.mistral.ai/v1/chat/completions'
MESSAGES = [SystemMessage('Be terse.'), HumanMessage('Hi')]
WEATHER_TOOL = {
    'type': 'function',
    'function': {
        'name': 'get_weather',
        'parameters': {'type': 'object', 'properties': {'city': {'type': 'string'}}},
    },
}


def model(**kwargs) -> ChatMistralAI:
    return init_chat_model('mistralai:mistral-small-latest', api_key='sk', **kwargs)


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


def judgement_reply(arguments: str, name: str = 'Judgement') -> CannedResponse:
    return canned.mistral_completion(
        None,
        tool_calls=[
            {'id': 'abcDEF123', 'function': {'name': name, 'arguments': arguments}}
        ],
    )


# ── Construction ─────────────────────────────────────────────────────────────


def test_factory_builds_native_model():
    chat_model = model()
    assert type(chat_model).__name__ == 'ChatMistralAI'
    assert chat_model.model_name == 'mistral-small-latest'


@pytest.mark.parametrize('param', ['temperature', 'top_p'])
def test_rejects_out_of_range_sampling(param):
    with pytest.raises(ValueError, match=f'{param} must be in the range'):
        model(**{param: 1.5})


# ── Request building ─────────────────────────────────────────────────────────


async def test_request_carries_injected_defaults():
    _, [request] = await invoke(model(), [canned.mistral_completion()])
    assert request['url'] == URL
    assert request['headers'] == {
        'accept': 'application/json',
        'authorization': 'Bearer sk',
        'content-type': 'application/json',
    }
    assert request['body'] == {
        'messages': [
            {'role': 'system', 'content': 'Be terse.'},
            {'role': 'user', 'content': 'Hi'},
        ],
        'model': 'mistral-small-latest',
        'temperature': 0.7,
        'top_p': 1,
        'stream': False,
    }


async def test_configured_params_and_extra_kwargs():
    chat_model = model(
        base_url='http://mistral.internal/v1',
        max_tokens=10,
        random_seed=3,
        safe_mode=True,
        stop=['S'],
        timeout=5,
        max_retries=1,
        api_version='2024',
    )
    _, [request] = await invoke(chat_model, [canned.mistral_completion()])
    assert request['url'] == 'http://mistral.internal/v1/chat/completions'
    body = request['body']
    assert body['max_tokens'] == 10
    assert body['random_seed'] == 3
    assert body['safe_prompt'] is True
    assert body['stop'] == ['S']
    # Unknown params are sent as they are.
    assert body['api_version'] == '2024'
    assert 'timeout' not in body
    assert 'max_retries' not in body


async def test_call_kwargs_override_defaults():
    _, [request] = await invoke(
        model(stop=['S']),
        [canned.mistral_completion()],
        temperature=0.1,
        stop=['END'],
        max_completion_tokens=5,
        stream=True,
    )
    body = request['body']
    assert body['temperature'] == 0.1
    assert body['stop'] == ['END']
    assert body['max_completion_tokens'] == 5
    assert body['stream'] is False


async def test_message_conversion():
    messages = [
        HumanMessage(
            [
                {'type': 'text', 'text': 'look'},
                {
                    'type': 'image',
                    'source_type': 'base64',
                    'data': 'AAA',
                    'mime_type': 'image/png',
                },
                {
                    'type': 'file',
                    'source_type': 'base64',
                    'data': 'BBB',
                    'mime_type': 'application/pdf',
                },
            ]
        ),
        AIMessage(
            'ignored',
            tool_calls=[
                {'name': 'get_weather', 'args': {'city': 'Zürich'}, 'id': 'call_1'}
            ],
        ),
        ToolMessage(
            [{'type': 'text', 'text': 'sunny', 'id': 'x'}], tool_call_id='call_1'
        ),
        AIMessage([{'type': 'text', 'text': 'a', 'index': 0}, 'b']),
    ]
    _, [request] = await invoke(model(), [canned.mistral_completion()], messages)
    converted_id = _mistral_tool_call_id('call_1')
    assert request['body']['messages'] == [
        {
            'role': 'user',
            'content': [
                {'type': 'text', 'text': 'look'},
                {
                    'type': 'image_url',
                    'image_url': {'url': 'data:image/png;base64,AAA'},
                },
                {
                    'type': 'file',
                    'file': {
                        'file_data': 'data:application/pdf;base64,BBB',
                        'filename': 'LC_AUTOGENERATED',
                    },
                },
            ],
        },
        {
            'role': 'assistant',
            'tool_calls': [
                {
                    'function': {
                        'name': 'get_weather',
                        'arguments': '{"city": "Zürich"}',
                    },
                    'id': converted_id,
                }
            ],
            'content': '',
        },
        {
            'role': 'tool',
            'content': [{'type': 'text', 'text': 'sunny'}],
            'name': None,
            'tool_call_id': converted_id,
        },
        {
            'role': 'assistant',
            'content': [{'type': 'text', 'text': 'a'}, {'type': 'text', 'text': 'b'}],
        },
    ]


async def test_raw_tool_calls_in_additional_kwargs_are_parsed():
    message = AIMessage(
        '',
        additional_kwargs={
            'tool_calls': [{'id': 'q', 'function': {'name': 'f', 'arguments': '{}'}}]
        },
    )
    _, [request] = await invoke(model(), [canned.mistral_completion()], [message])
    [call] = request['body']['messages'][0]['tool_calls']
    assert call['id'] == _mistral_tool_call_id('q')


def test_tool_call_ids_are_mistral_compatible():
    assert _mistral_tool_call_id('Wx1Abc2De') == 'Wx1Abc2De'
    converted = _mistral_tool_call_id('call_weather_1')
    assert converted == 'B4i3YmNsK'
    assert _mistral_tool_call_id('call_weather_1') == converted


async def test_unsupported_message_type():
    with pytest.raises(ValueError, match='Got unknown type'):
        await model().ainvoke([FunctionMessage('x', name='f')])


@pytest.mark.parametrize(
    ('tool_choice', 'expected'),
    [
        ('auto', 'auto'),
        ('required', 'required'),
        ('get_weather', {'type': 'function', 'function': {'name': 'get_weather'}}),
        (
            {'type': 'function', 'function': {'name': 'get_weather'}},
            {'type': 'function', 'function': {'name': 'get_weather'}},
        ),
    ],
)
async def test_bind_tools(tool_choice, expected):
    bound = model().bind_tools([WEATHER_TOOL], tool_choice=tool_choice)
    assert type(bound).__name__ == 'ChatMistralAI'
    _, [request] = await invoke(bound, [canned.mistral_completion()])
    assert request['body']['tools'] == [WEATHER_TOOL]
    assert request['body']['tool_choice'] == expected


# ── Response parsing ─────────────────────────────────────────────────────────


async def test_completion_parsing():
    message, _ = await invoke(model(), [canned.mistral_completion()])
    assert message.content == 'Hello from the model'
    assert message.id.startswith('run-')
    assert message.usage_metadata == {
        'input_tokens': 21,
        'output_tokens': 7,
        'total_tokens': 28,
    }
    assert message.response_metadata == {
        'token_usage': {
            'prompt_tokens': 21,
            'completion_tokens': 7,
            'total_tokens': 28,
        },
        'model_name': 'mistral-small-latest',
        'model': 'mistral-small-latest',
        'finish_reason': 'stop',
        'model_provider': 'mistralai',
    }


async def test_tool_call_parsing():
    reply = canned.mistral_completion(
        None,
        tool_calls=[
            canned.MISTRAL_WEATHER_TOOL_CALL,
            {'function': {'name': 'bad', 'arguments': '{nope'}},
            {'function': {'name': 'noargs', 'arguments': ''}},
        ],
    )
    message, _ = await invoke(model(), [reply])
    assert message.content == ''
    [weather, noargs] = message.tool_calls
    assert weather == {
        'name': 'get_weather',
        'args': {'city': 'Paris', 'unit': 'c'},
        'id': 'Wx1Abc2De',
        'type': 'tool_call',
    }
    # A missing id is filled with a random one.
    assert noargs['args'] == {}
    assert len(noargs['id']) == 32
    [invalid] = message.invalid_tool_calls
    assert invalid['name'] == 'bad'
    assert invalid['error'].startswith('Function bad arguments:')
    assert (
        message.additional_kwargs['tool_calls'][0] == canned.MISTRAL_WEATHER_TOOL_CALL
    )


async def test_reference_blocks_become_text():
    reply = CannedResponse(
        json_body={
            'choices': [
                {
                    'message': {
                        'role': 'assistant',
                        'content': [
                            {'type': 'reference', 'text': 'cited', 'reference_ids': [1]}
                        ],
                    },
                    'finish_reason': 'stop',
                }
            ]
        }
    )
    message, _ = await invoke(model(), [reply])
    assert message.content == [
        {'type': 'text', 'text': 'cited', 'reference': {'reference_ids': [1]}}
    ]
    assert message.usage_metadata is None
    assert message.response_metadata['token_usage'] == {}


# ── Streaming ────────────────────────────────────────────────────────────────


async def test_stream():
    chunks, [request] = await stream(
        model(), [canned.mistral_stream()], stream_options={'include_usage': True}
    )
    assert request['headers']['accept'] == 'text/event-stream'
    assert request['headers']['cache-control'] == 'no-store'
    assert request['body']['stream'] is True
    assert request['body']['stream_options'] == {'include_usage': True}
    assert [c.content for c in chunks] == ['', 'Hello', ' from', ' the model', '', '']
    assert len({c.id for c in chunks}) == 1
    finish = chunks[-2]
    assert finish.response_metadata == {
        'model_provider': 'mistralai',
        'model_name': 'mistral-small-latest',
        'finish_reason': 'stop',
    }
    assert finish.usage_metadata == {
        'input_tokens': 21,
        'output_tokens': 7,
        'total_tokens': 28,
    }
    assert chunks[-1].chunk_position == 'last'


async def test_stream_tool_call_chunks():
    tool_calls = [
        canned.MISTRAL_WEATHER_TOOL_CALL,
        {'index': 1, 'function': {'name': 'f', 'arguments': '{"a'}},
    ]
    chunks, _ = await stream(
        model(), [canned.mistral_stream([], tool_calls=tool_calls)]
    )
    [chunk] = [c for c in chunks if c.tool_call_chunks]
    assert chunk.tool_call_chunks == [
        {
            'name': 'get_weather',
            'args': '{"city": "Paris", "unit": "c"}',
            'id': 'Wx1Abc2De',
            'index': None,
            'type': 'tool_call_chunk',
        },
        {'name': 'f', 'args': '{"a', 'id': None, 'index': 1, 'type': 'tool_call_chunk'},
    ]


async def test_stream_rejects_non_sse_reply():
    with pytest.raises(SSEError, match='text/event-stream'):
        await stream(model(), [canned.mistral_completion()])


# ── Errors and retries ───────────────────────────────────────────────────────


async def test_http_error_propagates_without_retry():
    with pytest.raises(httpx.HTTPStatusError) as e:
        await invoke(model(), [canned.error(429, 'slow down')])
    assert str(e.value).startswith(f'Error response 429 while fetching {URL}: ')
    assert 'slow down' in str(e.value)


async def test_stream_http_error_propagates():
    with pytest.raises(httpx.HTTPStatusError, match='Error response 500'):
        await stream(model(), [canned.error(500)])


async def test_transport_errors_are_retried_with_backoff():
    attempts = []

    async def fail(self, request):
        attempts.append(request)
        raise httpx.ConnectError('down', request=request)

    sleep = AsyncMock()
    with (
        patch.object(httpx.AsyncHTTPTransport, 'handle_async_request', fail),
        patch('asyncio.sleep', sleep),
        pytest.raises(httpx.ConnectError),
    ):
        await model().ainvoke(MESSAGES)
    assert len(attempts) == 5
    assert [c.args[0] for c in sleep.call_args_list] == [4, 4, 4, 8]


async def test_stream_transport_errors_are_not_retried():
    attempts = []

    async def fail(self, request):
        attempts.append(request)
        raise httpx.ConnectError('down', request=request)

    with (
        patch.object(httpx.AsyncHTTPTransport, 'handle_async_request', fail),
        pytest.raises(httpx.ConnectError),
    ):
        async for _ in model().astream(MESSAGES):
            pass
    assert len(attempts) == 1


# ── Structured output ────────────────────────────────────────────────────────


async def test_structured_output_forces_a_function_call():
    structured = model(temperature=0.0).with_structured_output(
        Judgement, include_raw=True
    )
    result, [request] = await invoke(structured, [judgement_reply('{"ok": true}')])
    assert request['body']['tool_choice'] == 'any'
    assert request['body']['tools'] == [
        {
            'type': 'function',
            'function': {
                'name': 'Judgement',
                'description': 'A verdict.',
                'parameters': {
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
            },
        }
    ]
    assert result['parsed'] == Judgement(ok=True)
    assert result['parsing_error'] is None
    assert isinstance(result['raw'], AIMessage)


async def test_structured_output_without_raw():
    structured = model().with_structured_output(Judgement)
    result, _ = await invoke(structured, [judgement_reply('{"ok": false}')])
    assert result == Judgement(ok=False)


@pytest.mark.parametrize(
    ('reply', 'error'),
    [
        (judgement_reply('{nope'), OutputParserError),
        (judgement_reply('{}', name='Other'), OutputParserError),
        (judgement_reply('{"ok": "maybe"}'), ValueError),
    ],
)
async def test_structured_output_parsing_errors(reply, error):
    structured = model().with_structured_output(Judgement, include_raw=True)
    result, _ = await invoke(structured, [reply])
    assert result['parsed'] is None
    assert isinstance(result['parsing_error'], error)

    with pytest.raises(error):
        await invoke(model().with_structured_output(Judgement), [reply])


async def test_structured_output_without_tool_call():
    structured = model().with_structured_output(Judgement, include_raw=True)
    result, _ = await invoke(structured, [canned.mistral_completion('plain')])
    assert result['parsed'] is None
    assert result['parsing_error'] is None


async def test_structured_output_propagates_request_errors():
    structured = model().with_structured_output(Judgement, include_raw=True)
    with pytest.raises(httpx.HTTPStatusError):
        await invoke(structured, [canned.error(500)])


# ── Embeddings ───────────────────────────────────────────────────────────────


def embeddings_reply(count: int) -> CannedResponse:
    return CannedResponse(
        json_body={
            'data': [{'index': i, 'embedding': [i, 0.5]} for i in range(count)],
        }
    )


async def test_embeddings_accept_shared_client():
    client = httpx.AsyncClient()
    embeddings = init_embeddings(
        'mistral-embed', provider='mistralai', api_key='sk', http_async_client=client
    )
    assert isinstance(embeddings, MistralEmbeddings)
    with ProviderRecorder([embeddings_reply(2)]) as recorder:
        vectors = await embeddings.aembed_documents(['a', 'b'])
    assert vectors == [[0.0, 0.5], [1.0, 0.5]]
    [request] = recorder.requests
    assert request['url'] == 'https://api.mistral.ai/v1/embeddings'
    assert request['headers'] == {
        'accept': 'application/json',
        'authorization': 'Bearer sk',
        'content-type': 'application/json',
    }
    assert request['body'] == {'model': 'mistral-embed', 'input': ['a', 'b']}


async def test_embeddings_without_shared_client_and_query():
    embeddings = MistralEmbeddings('mistral-embed', api_key='sk')
    with ProviderRecorder([embeddings_reply(1)]):
        assert await embeddings.aembed_query('a') == [0.0, 0.5]


def test_embeddings_sync():
    embeddings = MistralEmbeddings('mistral-embed', api_key='sk')
    with ProviderRecorder([embeddings_reply(1)]) as recorder:
        assert embeddings.embed_query('a') == [0.0, 0.5]
    assert recorder.requests[0]['body'] == {'model': 'mistral-embed', 'input': ['a']}


async def test_embeddings_are_batched_by_size():
    embeddings = MistralEmbeddings('mistral-embed', api_key='sk')
    texts = ['x' * 9000, 'y' * 9000, 'z']
    with ProviderRecorder([embeddings_reply(1), embeddings_reply(2)]) as recorder:
        vectors = await embeddings.aembed_documents(texts)
    assert len(vectors) == 3
    assert [r['body']['input'] for r in recorder.requests] == [
        ['x' * 9000],
        ['y' * 9000, 'z'],
    ]


def test_embeddings_reject_unknown_params():
    with pytest.raises(ValueError, match='Unsupported Mistral embeddings'):
        MistralEmbeddings('mistral-embed', dimensions=4)


async def test_embeddings_retry_rate_limits_then_raise():
    embeddings = MistralEmbeddings(
        'mistral-embed', api_key='sk', max_retries=3, wait_time=7
    )
    sleep = AsyncMock()
    with (
        patch('asyncio.sleep', sleep),
        ProviderRecorder([canned.error(429)] * 3) as recorder,
        pytest.raises(httpx.HTTPStatusError),
    ):
        await embeddings.aembed_documents(['a'])
    assert len(recorder.requests) == 3
    assert [c.args[0] for c in sleep.call_args_list] == [7, 7]


async def test_embeddings_do_not_retry_client_errors():
    embeddings = MistralEmbeddings('mistral-embed', api_key='sk')
    with (
        ProviderRecorder([canned.error(400)]) as recorder,
        pytest.raises(httpx.HTTPStatusError),
    ):
        await embeddings.aembed_documents(['a'])
    assert len(recorder.requests) == 1
    assert recorder.requests[0]['body']['input'] == ['a']
