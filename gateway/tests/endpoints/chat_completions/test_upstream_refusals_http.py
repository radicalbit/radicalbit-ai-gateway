"""A provider's refusal of a chat request, through a real route over HTTP.

A refusal of the request itself reaches the client as the provider sent it.
A 401 or 403 refuses the gateway's own access to the provider: it falls back,
and the client gets a bad gateway without the provider's body. The provider
is mocked over HTTP with pook.
"""

import pook
import pytest

from tests.common.gateway_harness import build_routes, open_gateway
from tests.common.mocked_build_openai_chat_completion import (
    to_mock_openai_chat_completion,
)

OPENAI_URL = 'https://api.openai.com/v1/chat/completions'

KEY_REFUSAL = {
    'error': {
        'message': 'Incorrect API key provided: sk-123****',
        'type': 'invalid_request_error',
        'code': 'invalid_api_key',
    }
}


def _model(model_id: str) -> dict:
    return {
        'model_id': model_id,
        'model': 'openai/gpt-4o-mini',
        'credentials': {'api_key': 'sk-123'},
    }


@pytest.fixture
def gateway():
    routes = build_routes(
        {
            'chat_models': [_model('chat'), _model('backup')],
            'routes': {
                'alone': {'chat_models': ['chat']},
                'backed': {
                    'chat_models': ['chat', 'backup'],
                    'fallback': [{'target': 'chat', 'fallbacks': ['backup']}],
                },
            },
        }
    )
    with open_gateway(routes, use_pook=True) as gateway:
        yield gateway


def _refuse(status: int, body: dict) -> None:
    pook.post(OPENAI_URL).times(1).reply(status).json(body)


def _send(gateway, route: str, stream: bool = False):
    return gateway.client.post(
        '/v1/chat/completions',
        json={
            'model': f'proj/{route}',
            'messages': [{'role': 'user', 'content': 'Hi'}],
            'stream': stream,
        },
        headers=gateway.headers,
    )


@pytest.mark.parametrize('stream', [False, True], ids=['complete', 'stream'])
@pytest.mark.parametrize('status', [401, 403])
def test_an_access_refusal_is_a_bad_gateway_without_the_provider_body(
    gateway, status, stream
):
    _refuse(status, KEY_REFUSAL)

    response = _send(gateway, 'alone', stream)

    assert response.status_code == 502
    assert 'sk-123' not in response.text
    assert "refused the gateway's credentials" in response.text


def test_an_access_refusal_falls_back_to_the_next_model(gateway):
    _refuse(401, KEY_REFUSAL)
    pook.post(OPENAI_URL).times(1).reply(200).json(
        to_mock_openai_chat_completion(content='Done').model_dump()
    )

    response = _send(gateway, 'backed')

    assert response.status_code == 200, response.text


def test_a_refusal_of_the_request_reaches_the_client_as_sent(gateway):
    body = {'error': {'message': 'context_length_exceeded', 'type': 'x'}}
    _refuse(400, body)

    response = _send(gateway, 'alone')

    assert (response.status_code, response.json()) == (400, body)
