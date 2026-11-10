"""A model with no price entry: the request succeeds and is costed at 0."""

import logging

import pytest

from tests.common.gateway_harness import build_routes, open_gateway
from tests.common.provider_recorder import CannedResponse

from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.services.cost_service import (
    CostService,
    logger as cost_service_logger,
)

CONFIG = {
    'chat_models': [
        {
            'model_id': 'gpt',
            'model': 'openai/gpt-4o-mini',
            'credentials': {'api_key': 'sk-dummy'},
        }
    ],
    'embedding_models': [
        {
            'model_id': 'emb',
            'model': 'openai/text-embedding-3-small',
            'credentials': {'api_key': 'sk-dummy'},
        }
    ],
    'routes': {'r': {'chat_models': ['gpt'], 'embedding_models': ['emb']}},
}
CHAT_RESPONSE = {
    'id': 'chatcmpl-mock',
    'object': 'chat.completion',
    'created': 1234567890,
    'model': 'gpt-4o-mini',
    'choices': [
        {
            'index': 0,
            'message': {'role': 'assistant', 'content': 'Paris'},
            'finish_reason': 'stop',
        }
    ],
    'usage': {'prompt_tokens': 12, 'completion_tokens': 3, 'total_tokens': 15},
}
EMBEDDING_RESPONSE = {
    'object': 'list',
    'data': [{'object': 'embedding', 'index': 0, 'embedding': [0.1, 0.2, 0.3]}],
    'model': 'text-embedding-3-small',
    'usage': {'prompt_tokens': 4, 'total_tokens': 4},
}


@pytest.fixture
def gateway(caplog):
    # A cost service that knows no model: every lookup misses its price entry.
    routes = build_routes(CONFIG, cost_service=CostService())
    with open_gateway(routes, caplog=caplog) as gateway:
        yield gateway


def _input_costs(gateway) -> list:
    return [
        e['COST']
        for e in gateway.event_rows
        if e['EVENT_TYPE'] is EventType.INPUT_TOKEN_PROCESSED
    ]


def _price_warnings(caplog) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == cost_service_logger.name and r.levelno >= logging.WARNING
    ]


def test_chat_request_succeeds_and_is_costed_at_zero(gateway, caplog):
    response = gateway.chat(
        [CannedResponse(json_body=CHAT_RESPONSE)], route='r', text='Capital of France?'
    )

    assert response.status_code == 200
    assert response.json()['choices'][0]['message']['content'] == 'Paris'
    assert [r['url'] for r in gateway.upstream] == [
        'https://api.openai.com/v1/chat/completions'
    ]
    assert _input_costs(gateway) == [0]
    assert any('gpt' in line for line in _price_warnings(caplog))


def test_embedding_request_succeeds_and_is_costed_at_zero(gateway, caplog):
    response = gateway.post(
        '/v1/embeddings',
        [CannedResponse(json_body=EMBEDDING_RESPONSE)],
        json={'model': 'proj/r', 'input': 'hello'},
    )

    assert response.status_code == 200
    assert [r['url'] for r in gateway.upstream] == [
        'https://api.openai.com/v1/embeddings'
    ]
    assert _input_costs(gateway) == [0]
    assert any('emb' in line for line in _price_warnings(caplog))
