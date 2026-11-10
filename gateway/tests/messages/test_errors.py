import json

from fastapi.responses import JSONResponse, PlainTextResponse, Response
from starlette.requests import Request

from radicalbit_ai_gateway.messages.errors import with_messages_error_shape


def _request(path: str = '/v1/messages') -> Request:
    return Request({'type': 'http', 'method': 'POST', 'path': path, 'headers': []})


async def _shaped(response: Response) -> Response:
    handler = with_messages_error_shape(lambda request, exc: response)
    return await handler(_request(), RuntimeError('boom'))


async def test_a_detail_becomes_the_error_message():
    response = await _shaped(JSONResponse({'detail': 'Too many requests'}, 429))

    assert response.status_code == 429
    assert json.loads(response.body) == {
        'type': 'error',
        'error': {'type': 'rate_limit_error', 'message': 'Too many requests'},
    }


async def test_a_body_that_is_not_json_gets_a_generic_message():
    response = await _shaped(PlainTextResponse('Bad gateway', 502))

    assert response.status_code == 502
    assert json.loads(response.body)['error']['message'] == 'Error'


async def test_a_json_body_without_a_message_gets_a_generic_message():
    response = await _shaped(JSONResponse({'detail': ['a', 'list']}, 500))

    assert json.loads(response.body)['error'] == {
        'type': 'api_error',
        'message': 'Error',
    }


async def test_other_paths_keep_the_handler_response():
    original = PlainTextResponse('Bad gateway', 502)
    handler = with_messages_error_shape(lambda request, exc: original)

    assert await handler(_request('/v1/chat/completions'), RuntimeError()) is original
