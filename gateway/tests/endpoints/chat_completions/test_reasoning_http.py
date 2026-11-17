"""The model's reasoning on a chat route, through the real endpoint over HTTP.

A client sends it back on assistant messages, as ``reasoning_content``
(DeepSeek) or ``reasoning`` (vLLM, Ollama, OpenRouter): the endpoint keeps
it, DeepSeek gets it back, and an input guardrail with ``read_reasoning``
reads it. On output, a redact guardrail with the flag masks the reasoning of
the model's reply, streamed or not. The provider is mocked over HTTP with
pook.
"""

import json

import pook
import pytest

from tests.common.gateway_harness import build_routes, open_gateway
from tests.common.mocked_build_openai_chat_completion import (
    to_mock_openai_chat_completion,
)

from radicalbit_ai_gateway.server import app

OPENAI_URL = 'https://api.openai.com/v1/chat/completions'
DEEPSEEK_URL = 'https://api.deepseek.com/v1/chat/completions'
BAD = 'banana'

OPENAI = {
    'model_id': 'gpt',
    'model': 'openai/gpt-4o-mini',
    'credentials': {'api_key': 'sk-123'},
}
DEEPSEEK = {
    'model_id': 'ds',
    'model': 'deepseek/deepseek-reasoner',
    'credentials': {'api_key': 'sk-123'},
}


def _contains(read_reasoning: bool) -> dict:
    return {
        'name': 'no_banana',
        'type': 'contains',
        'where': 'input',
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
    """Serve one chat route on ``model`` with ``guardrails``."""
    with open_gateway(use_pook=True) as gateway:

        def _serve(model: dict, guardrails: list[dict] | None = None):
            app.state.routes = build_routes(
                {
                    'chat_models': [model],
                    'guardrails': guardrails,
                    'routes': {
                        'chat': {
                            'chat_models': [model['model_id']],
                            'guardrails': [g['name'] for g in guardrails or []],
                        }
                    },
                }
            )
            return gateway

        yield _serve


def _send(gateway, messages: list[dict], stream: bool = False):
    return gateway.client.post(
        '/v1/chat/completions',
        json={'model': 'proj/chat', 'messages': messages, 'stream': stream},
        headers=gateway.headers,
    )


def _reply(url: str, reasoning: str | None = None):
    body = to_mock_openai_chat_completion(content='Done').model_dump()
    if reasoning is not None:
        body['choices'][0]['message']['reasoning_content'] = reasoning
    return pook.post(url).times(1).reply(200).json(body).mock


def _history(field: str) -> list[dict]:
    return [
        {'role': 'user', 'content': 'Name a fruit'},
        {'role': 'assistant', 'content': 'OK', field: f'I thought of a {BAD}.'},
        {'role': 'user', 'content': 'Thanks'},
    ]


# ---------------------------------------------------------------------------
# Input: the reasoning in the history
# ---------------------------------------------------------------------------


@pytest.mark.parametrize('field', ['reasoning_content', 'reasoning'])
def test_deepseek_gets_the_reasoning_back_under_either_name(serve, field):
    gateway = serve(DEEPSEEK)
    upstream = _reply(DEEPSEEK_URL)

    response = _send(gateway, _history(field))

    assert response.status_code == 200, response.text
    sent = upstream.matches[0].json
    assert sent['messages'][1]['reasoning_content'] == f'I thought of a {BAD}.'


@pytest.mark.parametrize('field', ['reasoning_content', 'reasoning'])
def test_an_input_guardrail_with_the_flag_reads_the_history_reasoning(serve, field):
    gateway = serve(OPENAI, [_contains(read_reasoning=True)])

    response = _send(gateway, _history(field))

    assert response.status_code == 400, response.text
    assert response.json()['error']['param']['name'] == 'no_banana'


def test_an_input_guardrail_without_the_flag_ignores_the_history_reasoning(serve):
    gateway = serve(OPENAI, [_contains(read_reasoning=False)])
    upstream = _reply(OPENAI_URL)

    response = _send(gateway, _history('reasoning'))

    assert response.status_code == 200, response.text
    # OpenAI never gets reasoning back.
    assert 'reasoning_content' not in upstream.matches[0].json['messages'][1]


# ---------------------------------------------------------------------------
# Output: the reasoning of the model's reply
# ---------------------------------------------------------------------------


def test_the_reply_reasoning_is_redacted_with_the_flag(serve):
    gateway = serve(DEEPSEEK, [_redact(read_reasoning=True)])
    _reply(DEEPSEEK_URL, reasoning='Mail john@example.com')

    response = _send(gateway, [{'role': 'user', 'content': 'Hi'}])

    assert response.status_code == 200, response.text
    message = response.json()['choices'][0]['message']
    assert message['content'] == 'Done'
    assert message['reasoning_content'] == 'Mail <EMAIL_ADDRESS>'
    assert message['reasoning'] == 'Mail <EMAIL_ADDRESS>'
    assert response.headers['X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-WARN'] == 'true'


def test_the_reply_reasoning_is_left_alone_without_the_flag(serve):
    gateway = serve(DEEPSEEK, [_redact(read_reasoning=False)])
    _reply(DEEPSEEK_URL, reasoning='Mail john@example.com')

    response = _send(gateway, [{'role': 'user', 'content': 'Hi'}])

    assert response.status_code == 200, response.text
    message = response.json()['choices'][0]['message']
    assert message['reasoning_content'] == 'Mail john@example.com'
    assert 'X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-WARN' not in response.headers


def test_a_reply_reasoning_without_pii_is_left_alone(serve):
    gateway = serve(DEEPSEEK, [_redact(read_reasoning=True)])
    _reply(DEEPSEEK_URL, reasoning='Just thinking')

    response = _send(gateway, [{'role': 'user', 'content': 'Hi'}])

    assert response.status_code == 200, response.text
    message = response.json()['choices'][0]['message']
    assert message['reasoning_content'] == 'Just thinking'
    assert 'X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-WARN' not in response.headers


def test_an_output_check_with_the_flag_blocks_on_the_reasoning(serve):
    check = {
        'name': 'no_banana',
        'type': 'contains',
        'where': 'output',
        'behavior': 'block',
        'read_reasoning': True,
        'parameters': {'values': [BAD]},
    }
    gateway = serve(DEEPSEEK, [check])
    _reply(DEEPSEEK_URL, reasoning=f'I thought of a {BAD}.')

    response = _send(gateway, [{'role': 'user', 'content': 'Hi'}])

    assert response.status_code == 400, response.text
    assert response.json()['error']['param']['name'] == 'no_banana'


# ---------------------------------------------------------------------------
# Output, streamed: the reply is buffered, then rewritten whole
# ---------------------------------------------------------------------------


def _sse(deltas: list[dict]) -> str:
    def chunk(delta: dict, finish_reason=None, **extra) -> dict:
        return {
            'id': 'chatcmpl-1',
            'object': 'chat.completion.chunk',
            'created': 0,
            'model': 'deepseek-reasoner',
            'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish_reason}],
            **extra,
        }

    chunks = [chunk(delta) for delta in deltas]
    chunks.append(
        chunk(
            {},
            'stop',
            usage={'prompt_tokens': 5, 'completion_tokens': 7, 'total_tokens': 12},
        )
    )
    return ''.join(f'data: {json.dumps(c)}\n\n' for c in chunks) + 'data: [DONE]\n\n'


def _stream(gateway):
    """Stream a reply whose emails each cross two chunks; return the
    response and the texts its deltas join to.
    """
    pook.post(DEEPSEEK_URL).times(1).reply(200).header(
        'Content-Type', 'text/event-stream'
    ).body(
        _sse(
            [
                {'role': 'assistant', 'reasoning_content': 'Mail john@exa'},
                {'reasoning_content': 'mple.com'},
                {'content': 'Write to jane@exa'},
                {'content': 'mple.com'},
            ]
        )
    )
    response = _send(gateway, [{'role': 'user', 'content': 'Hi'}], stream=True)
    choices = [
        json.loads(line[len('data: ') :])['choices']
        for line in response.text.splitlines()
        if line.startswith('data: {')
    ]
    joined = {
        name: ''.join(c[0]['delta'].get(name) or '' for c in choices if c)
        for name in ('reasoning_content', 'reasoning', 'content')
    }
    return response, joined


def test_a_streamed_reply_has_its_reasoning_and_text_redacted_with_the_flag(serve):
    gateway = serve(DEEPSEEK, [_redact(read_reasoning=True)])

    response, joined = _stream(gateway)

    assert response.status_code == 200, response.text
    assert joined == {
        'reasoning_content': 'Mail <EMAIL_ADDRESS>',
        'reasoning': 'Mail <EMAIL_ADDRESS>',
        'content': 'Write to <EMAIL_ADDRESS>',
    }
    assert response.headers['X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-WARN'] == 'true'


def test_a_streamed_reply_has_only_its_text_redacted_without_the_flag(serve):
    gateway = serve(DEEPSEEK, [_redact(read_reasoning=False)])

    response, joined = _stream(gateway)

    assert response.status_code == 200, response.text
    assert joined['reasoning_content'] == 'Mail john@example.com'
    assert joined['content'] == 'Write to <EMAIL_ADDRESS>'
