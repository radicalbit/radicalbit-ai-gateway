"""A chat request's tools reach the model: through a real route over HTTP.

The provider is mocked over HTTP with pook.
"""

import json

import pook
import pytest

from tests.common.gateway_harness import build_routes, open_gateway
from tests.common.mocked_build_openai_chat_completion import (
    to_mock_openai_chat_completion,
)

OPENAI_URL = 'https://api.openai.com/v1/chat/completions'

WEATHER_TOOL = {
    'type': 'function',
    'function': {
        'name': 'get_weather',
        'description': 'Get the weather in a city',
        'parameters': {
            'type': 'object',
            'properties': {'city': {'type': 'string'}},
            'required': ['city'],
        },
    },
}


def _chunk(delta: dict, finish_reason: str | None) -> dict:
    return {
        'id': 'chatcmpl-1',
        'object': 'chat.completion.chunk',
        'created': 1,
        'model': 'gpt-4o-mini',
        'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish_reason}],
    }


STREAM_BODY = (
    ''.join(
        f'data: {json.dumps(chunk)}\n\n'
        for chunk in [_chunk({'content': 'Done'}, None), _chunk({}, 'stop')]
    )
    + 'data: [DONE]\n\n'
)


def _mock_openai(stream: bool):
    mock = pook.post(OPENAI_URL).times(1)
    if stream:
        mock.reply(200).header('Content-Type', 'text/event-stream').body(STREAM_BODY)
    else:
        mock.reply(200).json(
            to_mock_openai_chat_completion(content='Done').model_dump()
        )
    return mock


@pytest.fixture
def gateway():
    routes = build_routes(
        {
            'chat_models': [
                {
                    'model_id': 'chat',
                    'model': 'openai/gpt-4o-mini',
                    'credentials': {'api_key': 'sk-123'},
                }
            ],
            'routes': {'tools': {'chat_models': ['chat']}},
        }
    )
    with open_gateway(routes, use_pook=True) as gateway:
        yield gateway


@pytest.mark.parametrize('stream', [False, True], ids=['complete', 'stream'])
def test_tools_and_tool_choice_reach_the_model(gateway, stream):
    mock = _mock_openai(stream)

    response = gateway.client.post(
        '/v1/chat/completions',
        json={
            'model': 'proj/tools',
            'messages': [{'role': 'user', 'content': 'Weather in Rome?'}],
            'tools': [WEATHER_TOOL],
            'tool_choice': 'required',
            'stream': stream,
        },
        headers=gateway.headers,
    )

    assert response.status_code == 200, response.text
    sent = mock.matches[0].json
    assert [t['function']['name'] for t in sent['tools']] == ['get_weather']
    assert sent['tool_choice'] == 'required'
