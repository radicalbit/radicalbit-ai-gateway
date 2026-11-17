"""The model's reasoning on a Responses route, through the real endpoint over
HTTP.

A reasoning item rides on the assistant message after it. A guardrail with
``read_reasoning`` reads its readable text (the summary, the raw text), on
input (a reasoning item the client sends back) and on output (the model's
reply, streamed or not); without the flag the reasoning is not read. A
redaction masks it, and the copy of it some providers (Ollama) put in
``encrypted_content``; a real encrypted blob is never touched. OpenAI is
mocked over HTTP with pook.
"""

import copy

import pook
import pytest

from tests.common.gateway_harness import build_routes, open_gateway
from tests.endpoints.responses.test_http import (
    OPENAI,
    OPENAI_URL,
    ROUTE_KEY,
    _final,
    _sent,
    _sse,
    upstream_events,
)

from radicalbit_ai_gateway.server import app

BAD = 'banana'
EMAIL = 'john@example.com'
BLOB = 'gAAAAABq301x'


def _check(read_reasoning: bool, where: str) -> dict:
    return {
        'name': 'no_banana',
        'type': 'contains',
        'where': where,
        'behavior': 'block',
        'read_reasoning': read_reasoning,
        'parameters': {'values': [BAD]},
    }


def _redact(read_reasoning: bool) -> dict:
    return {
        'name': 'redact_email',
        'type': 'presidio_anonymizer',
        'where': 'output',
        'read_reasoning': read_reasoning,
        'parameters': {'language': 'en', 'entities': ['EMAIL_ADDRESS']},
    }


@pytest.fixture
def serve():
    """Serve the route on OpenAI with ``guardrails``."""
    with open_gateway(use_pook=True) as gateway:

        def _serve(*guardrails: dict):
            app.state.routes = build_routes(
                {
                    'chat_models': [OPENAI],
                    'guardrails': list(guardrails),
                    'routes': {
                        'agents': {
                            'chat_models': [OPENAI['model_id']],
                            'guardrails': [g['name'] for g in guardrails],
                        }
                    },
                }
            )
            return gateway

        yield _serve


def _send(gateway, stream: bool = False, **body):
    body.setdefault('input', 'Hi')
    return gateway.post(
        '/v1/responses', json={'model': ROUTE_KEY, 'stream': stream, **body}
    )


def _reasoning_item(summary: str, encrypted: str | None = None) -> dict:
    item = {
        'id': 'rs_1',
        'type': 'reasoning',
        'summary': [{'type': 'summary_text', 'text': summary}],
    }
    if encrypted is not None:
        item['encrypted_content'] = encrypted
    return item


def _mock_reasoning(summary: str, stream: bool, encrypted: str | None = None):
    """Mock OpenAI answering 'Hello' after a reasoning item."""
    events = upstream_events()
    completed = events[-1]['response']
    completed['output'].insert(0, _reasoning_item(summary, encrypted))
    mock = pook.post(OPENAI_URL).times(1)
    if stream:
        mock.reply(200).header('Content-Type', 'text/event-stream').body(_sse(events))
    else:
        mock.reply(200).json(completed)
    return mock


def _reasoning_of(response: dict) -> dict:
    return next(item for item in response['output'] if item['type'] == 'reasoning')


# ---------------------------------------------------------------------------
# Output: the reasoning of the model's reply
# ---------------------------------------------------------------------------


@pytest.mark.parametrize('stream', [False, True], ids=['complete', 'stream'])
def test_an_output_check_with_the_flag_blocks_on_the_reasoning(serve, stream):
    gateway = serve(_check(read_reasoning=True, where='output'))
    _mock_reasoning(f'I thought of a {BAD}.', stream)

    response = _send(gateway, stream=stream)

    assert response.status_code == 400, response.text
    assert 'no_banana' in response.text


@pytest.mark.parametrize('stream', [False, True], ids=['complete', 'stream'])
def test_an_output_check_without_the_flag_ignores_the_reasoning(serve, stream):
    gateway = serve(_check(read_reasoning=False, where='output'))
    _mock_reasoning(f'I thought of a {BAD}.', stream)

    response = _send(gateway, stream=stream)

    assert response.status_code == 200, response.text


@pytest.mark.parametrize('stream', [False, True], ids=['complete', 'stream'])
def test_the_reasoning_summary_is_redacted_with_the_flag(serve, stream):
    gateway = serve(_redact(read_reasoning=True))
    _mock_reasoning(f'Mail {EMAIL}', stream)

    response = _send(gateway, stream=stream)

    assert response.status_code == 200, response.text
    reasoning = _reasoning_of(_final(response, stream))
    assert reasoning['summary'][0]['text'] == 'Mail <EMAIL_ADDRESS>'
    assert response.headers['X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-WARN'] == 'true'


def test_the_reasoning_summary_is_left_alone_without_the_flag(serve):
    gateway = serve(_redact(read_reasoning=False))
    _mock_reasoning(f'Mail {EMAIL}', stream=False)

    response = _send(gateway)

    assert response.status_code == 200, response.text
    assert _reasoning_of(response.json())['summary'][0]['text'] == f'Mail {EMAIL}'
    assert 'X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-WARN' not in response.headers


def test_a_plain_copy_in_encrypted_content_is_redacted_too(serve):
    # Ollama copies the readable text in encrypted_content.
    gateway = serve(_redact(read_reasoning=True))
    _mock_reasoning(f'Mail {EMAIL}', stream=False, encrypted=f'Mail {EMAIL}')

    response = _send(gateway)

    reasoning = _reasoning_of(response.json())
    assert reasoning['summary'][0]['text'] == 'Mail <EMAIL_ADDRESS>'
    assert reasoning['encrypted_content'] == 'Mail <EMAIL_ADDRESS>'


def test_an_encrypted_blob_is_never_touched(serve):
    gateway = serve(_redact(read_reasoning=True))
    _mock_reasoning(f'Mail {EMAIL}', stream=False, encrypted=BLOB)

    response = _send(gateway)

    reasoning = _reasoning_of(response.json())
    assert reasoning['summary'][0]['text'] == 'Mail <EMAIL_ADDRESS>'
    assert reasoning['encrypted_content'] == BLOB


# ---------------------------------------------------------------------------
# Input: a reasoning item the client sends back
# ---------------------------------------------------------------------------


def _history(*after: dict) -> list[dict]:
    return [
        {'type': 'message', 'role': 'user', 'content': 'Name a fruit'},
        _reasoning_item(f'I thought of a {BAD}.'),
        *after,
    ]


ANSWER = {
    'type': 'message',
    'role': 'assistant',
    'content': [{'type': 'output_text', 'text': 'OK'}],
}
CALL = {
    'type': 'function_call',
    'call_id': 'call_A',
    'name': 'read',
    'arguments': '{}',
}
CALL_OUTPUT = {'type': 'function_call_output', 'call_id': 'call_A', 'output': 'x'}
THANKS = {'type': 'message', 'role': 'user', 'content': 'Thanks'}


@pytest.mark.parametrize(
    'after',
    [(ANSWER, THANKS), (CALL, CALL_OUTPUT)],
    ids=['before_a_message', 'before_a_tool_call'],
)
def test_an_input_check_with_the_flag_reads_the_history_reasoning(serve, after):
    gateway = serve(_check(read_reasoning=True, where='input'))

    response = _send(gateway, input=_history(*after))

    assert response.status_code == 400, response.text
    assert 'no_banana' in response.text


def test_an_input_check_without_the_flag_ignores_the_history_reasoning(serve):
    gateway = serve(_check(read_reasoning=False, where='input'))
    upstream = pook.post(OPENAI_URL).times(1)
    upstream.reply(200).json(upstream_events()[-1]['response'])
    sent_input = _history(ANSWER, THANKS)

    response = _send(gateway, input=copy.deepcopy(sent_input))

    assert response.status_code == 200, response.text
    # The reasoning item goes upstream as the client sent it.
    assert _sent(upstream)['input'][1] == sent_input[1]
