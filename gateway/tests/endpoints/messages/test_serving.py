import json

import anthropic
import httpx

from radicalbit_ai_gateway.endpoints.messages.serving import serve_stream
from radicalbit_ai_gateway.utils.exceptions import (
    GatewayBadRequest,
    ModelInvokerUpstreamError,
)

START = 'event: message_start\ndata: {}\n\n'
OVERLOADED = {
    'type': 'error',
    'error': {'type': 'overloaded_error', 'message': 'Overloaded'},
}


async def _frames(*items):
    """Yield each item, raising it if it is an exception."""
    for item in items:
        if isinstance(item, Exception):
            raise item
        yield item


async def _served(*items) -> list:
    return [item async for item in serve_stream(_frames(*items))]


def _error_event(item: str) -> dict:
    event, data = item.strip().split('\n')
    assert event == 'event: error'
    return json.loads(data.removeprefix('data: '))


def _api_status_error(body: dict) -> anthropic.APIStatusError:
    """Return the SDK's error for a 529 whose JSON body is ``body``."""
    response = httpx.Response(
        529,
        request=httpx.Request('POST', 'https://api.anthropic.com/v1/messages'),
        json=body,
    )
    return anthropic.APIStatusError('Overloaded', response=response, body=body)


async def test_an_empty_stream_sends_nothing():
    assert await _served() == []


async def test_unexpected_failure_before_streaming_is_a_500_api_error():
    served = await _served(RuntimeError('secret internals'))

    [(body, status_code)] = served
    assert status_code == 500
    assert json.loads(body) == {
        'type': 'error',
        'error': {'type': 'api_error', 'message': 'Unhandled error during streaming'},
    }


async def test_gateway_error_before_streaming_keeps_its_status_and_message():
    served = await _served(GatewayBadRequest('Route x has no chat models defined'))

    [(body, status_code)] = served
    assert status_code == 400
    assert json.loads(body)['error'] == {
        'type': 'invalid_request_error',
        'message': 'Route x has no chat models defined',
    }


async def test_upstream_refusal_before_streaming_is_relayed_as_sent():
    served = await _served(ModelInvokerUpstreamError('no', 529, OVERLOADED))

    [(body, status_code)] = served
    assert status_code == 529
    assert json.loads(body) == OVERLOADED


async def test_upstream_error_after_the_first_event_keeps_its_body():
    served = await _served(START, _api_status_error(OVERLOADED))

    assert served[0] == START
    assert _error_event(served[-1]) == OVERLOADED


async def test_relayed_upstream_error_after_the_first_event_keeps_its_body():
    served = await _served(START, ModelInvokerUpstreamError('no', 529, OVERLOADED))

    assert _error_event(served[-1]) == OVERLOADED


async def test_upstream_error_without_a_messages_body_is_an_api_error():
    served = await _served(START, _api_status_error({'detail': 'html page'}))

    assert _error_event(served[-1]) == {
        'type': 'error',
        'error': {'type': 'api_error', 'message': 'Internal server error'},
    }
