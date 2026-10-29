"""Tests for the native DeepSeek chat model."""

from httpx_aiohttp import HttpxAiohttpClient
from pydantic import BaseModel
import pytest

from tests.common import provider_responses as canned
from tests.common.provider_recorder import ProviderRecorder

from radicalbit_ai_gateway.llm.factory import init_chat_model
from radicalbit_ai_gateway.llm.messages import AIMessage, HumanMessage
from radicalbit_ai_gateway.llm.providers.deepseek import GatewayDeepSeekChatModel

MESSAGES = [HumanMessage('Hi')]


def model(name='deepseek-reasoner', **kwargs) -> GatewayDeepSeekChatModel:
    return init_chat_model(
        f'deepseek:{name}',
        api_key='sk',
        http_async_client=HttpxAiohttpClient(),
        **kwargs,
    )


class Judgement(BaseModel):
    ok: bool


def test_factory_builds_the_native_model():
    assert isinstance(model(), GatewayDeepSeekChatModel)


def test_default_endpoint_requires_an_api_key(monkeypatch):
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    with pytest.raises(ValueError, match='DEEPSEEK_API_KEY'):
        GatewayDeepSeekChatModel(model='deepseek-chat')


async def test_request_and_reasoning_content_reply():
    messages = [
        HumanMessage('Hi'),
        AIMessage('Hello.', additional_kwargs={'reasoning_content': 'greeting'}),
        HumanMessage('Again?'),
    ]
    response = canned.openai_completion(
        model='deepseek-reasoner', extra_message={'reasoning_content': 'Thinking.'}
    )
    with ProviderRecorder([response]) as recorder:
        result = await model(max_tokens=10).ainvoke(messages)

    request = recorder.requests[0]
    assert request['url'] == 'https://api.deepseek.com/v1/chat/completions'
    # DeepSeek keeps the max_tokens name.
    assert request['body']['max_tokens'] == 10
    assert request['body']['messages'][1] == {
        'content': 'Hello.',
        'role': 'assistant',
        'reasoning_content': 'greeting',
    }
    assert result.additional_kwargs['reasoning_content'] == 'Thinking.'
    assert result.response_metadata['model_provider'] == 'deepseek'


async def test_stream_reasoning_content_in_deltas():
    response = canned.openai_stream(
        model='deepseek-reasoner', extra_first_delta={'reasoning_content': 'Hmm.'}
    )
    with ProviderRecorder([response]) as recorder:
        chunks = [c async for c in model().astream(MESSAGES)]

    # DeepSeek does not ask for streamed usage unless requested.
    assert 'stream_options' not in recorder.requests[0]['body']
    assert chunks[0].additional_kwargs == {'reasoning_content': 'Hmm.'}
    assert chunks[0].response_metadata == {'model_provider': 'deepseek'}
    assert ''.join(c.content for c in chunks) == 'Hello from the model'


async def test_structured_output_uses_function_calling():
    tool_call = {
        'id': 'c',
        'type': 'function',
        'function': {'name': 'Judgement', 'arguments': '{"ok": true}'},
    }
    with ProviderRecorder(
        [canned.openai_completion(None, tool_calls=[tool_call])]
    ) as recorder:
        result = (
            await model('deepseek-chat')
            .with_structured_output(Judgement, include_raw=True)
            .ainvoke(MESSAGES)
        )

    body = recorder.requests[0]['body']
    assert body['tool_choice'] == {
        'type': 'function',
        'function': {'name': 'Judgement'},
    }
    assert body['parallel_tool_calls'] is False
    assert 'response_format' not in body
    assert result['parsed'] == Judgement(ok=True)


async def test_azure_hosted_deepseek_only_gets_string_tool_choice():
    tool = {'type': 'function', 'function': {'name': 'f', 'parameters': {}}}
    chat_model = model(base_url='https://x.services.ai.azure.com/models').bind_tools(
        [tool], tool_choice={'type': 'function', 'function': {'name': 'f'}}
    )
    with ProviderRecorder([canned.openai_completion()]) as recorder:
        await chat_model.ainvoke(MESSAGES)
    assert recorder.requests[0]['body']['tool_choice'] == 'required'
