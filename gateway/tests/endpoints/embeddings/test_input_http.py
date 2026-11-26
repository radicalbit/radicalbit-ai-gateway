"""What an embeddings request may send as its input."""

import pytest

from tests.common.gateway_harness import build_routes, open_gateway
from tests.common.provider_recorder import CannedResponse

CONFIG = {
    'embedding_models': [
        {
            'model_id': 'emb',
            'model': 'openai/text-embedding-3-small',
            'credentials': {'api_key': 'sk-dummy'},
        }
    ],
    'routes': {'r': {'embedding_models': ['emb']}},
}
EMBEDDING_RESPONSE = {
    'object': 'list',
    'data': [
        {'object': 'embedding', 'index': 0, 'embedding': [0.1, 0.2]},
        {'object': 'embedding', 'index': 1, 'embedding': [0.3, 0.4]},
    ],
    'model': 'text-embedding-3-small',
    'usage': {'prompt_tokens': 4, 'total_tokens': 4},
}


@pytest.fixture
def gateway(caplog):
    with open_gateway(build_routes(CONFIG), caplog=caplog) as gateway:
        yield gateway


def test_a_list_of_texts_is_embedded(gateway):
    response = gateway.post(
        '/v1/embeddings',
        [CannedResponse(json_body=EMBEDDING_RESPONSE)],
        json={'model': 'proj/r', 'input': ['hello', 'world']},
    )

    assert response.status_code == 200
    assert len(response.json()['data']) == 2


@pytest.mark.parametrize(
    'tokens', [[15339, 1917], [[15339], [1917]]], ids=['tokens', 'token_lists']
)
def test_token_arrays_are_a_bad_request(gateway, tokens):
    response = gateway.post(
        '/v1/embeddings', [], json={'model': 'proj/r', 'input': tokens}
    )

    assert response.status_code == 400
    assert 'token arrays are not supported' in response.text
    assert gateway.upstream == []
