"""Server-sent events of the proxy endpoints (``endpoints/common/http.py``)."""

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
import pytest

from radicalbit_ai_gateway.endpoints.common.http import sse_response
from radicalbit_ai_gateway.models.event_payload import LimitScope
from radicalbit_ai_gateway.utils.exceptions import (
    LIMIT_SCOPE_HEADER,
    AppError,
    BudgetLimitExceededError,
    ModelInvokerUpstreamError,
)


class _Item(BaseModel):
    text: str


ERRORS = {
    'app': AppError(client_message='model went away', status_code=502),
    'upstream': ModelInvokerUpstreamError(
        'refused', 429, {'error': {'message': 'slow down'}}
    ),
    'unhandled': RuntimeError('boom'),
}


def _client(items_before_error: int, error: Exception) -> TestClient:
    async def items():
        for i in range(items_before_error):
            yield _Item(text=f'part {i}')
        raise error

    # Its own app: sse_response is driven with items no endpoint sends.
    app = FastAPI()

    @app.get('/stream')
    async def stream():
        return sse_response(items())

    return TestClient(app)


@pytest.mark.parametrize('name', list(ERRORS))
def test_an_error_before_the_first_event_answers_with_its_status(name):
    response = _client(0, ERRORS[name]).get('/stream')

    assert response.status_code >= 400
    assert 'error' in response.json()


@pytest.mark.parametrize('name', list(ERRORS))
def test_an_error_after_the_first_event_is_the_streams_last_event(name):
    """Once the 200 is sent, the error goes out as an SSE event, as OpenAI
    streams one, and ends the stream: no [DONE].
    """
    response = _client(1, ERRORS[name]).get('/stream')

    assert response.status_code == 200
    frames = [f for f in response.text.split('\n\n') if f]
    assert all(f.startswith('data: ') for f in frames), frames
    assert json.loads(frames[0].removeprefix('data: ')) == {'text': 'part 0'}
    assert 'error' in json.loads(frames[-1].removeprefix('data: '))
    assert len(frames) == 2


def test_a_limit_that_blocks_before_the_first_event_names_its_scope():
    """A streamed 429 names the scope that blocked, as the non-streaming
    handlers do (AG-1063).
    """
    error = BudgetLimitExceededError('blocked', limit_scope=LimitScope.CREDENTIAL)

    response = _client(0, error).get('/stream')

    assert response.status_code == 429
    assert response.headers[LIMIT_SCOPE_HEADER] == 'credential'


@pytest.mark.parametrize('name', list(ERRORS))
def test_an_error_that_is_no_limit_names_no_scope(name):
    response = _client(0, ERRORS[name]).get('/stream')

    assert LIMIT_SCOPE_HEADER not in response.headers
