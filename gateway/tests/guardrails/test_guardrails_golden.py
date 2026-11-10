"""Golden values of the guardrails: what must not change when the code does.

Every endpoint that runs guardrails is driven through the HTTP app on real
routes, with the providers mocked over HTTP. Status codes, bodies, headers,
guardrail events and log lines are compared with literals. Only the drivers
(the functions that build the routes and send the requests) may change.
"""

import json
from unittest.mock import patch

import pook
import pytest
import tiktoken

from tests.common.gateway_harness import LOGGER, Gateway, build_routes, open_gateway
from tests.common.mocked_build_openai_chat_completion import (
    to_mock_openai_chat_completion,
)

from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.server import app

OPENAI_URL = 'https://api.openai.com/v1/chat/completions'
OPENAI_RESPONSES_URL = 'https://api.openai.com/v1/responses'
OPENAI_EMBEDDINGS_URL = 'https://api.openai.com/v1/embeddings'

EVENT_EMITS = (
    'radicalbit_ai_gateway.guardrails.guardrail_check.emit_event',
    'radicalbit_ai_gateway.guardrails.guardrail_redact.emit_event',
)
QUIET_EMITS = (
    'radicalbit_ai_gateway.invocation.recorder.emit_event',
    'radicalbit_ai_gateway.pipeline.conversation.emit_event',
)

EMAIL = 'ada.lovelace@analytical-engine.example.com'

GPT = {
    'model_id': 'gpt',
    'model': 'openai/gpt-4o',
    'credentials': {'api_key': 'sk-123'},
}
EMBEDDING = {
    'model_id': 'emb',
    'model': 'openai/text-embedding-3-small',
    'credentials': {'api_key': 'sk-123'},
}
JEV = {
    'model_id': 'jev',
    'model': 'typesafe/jev-latest',
    'credentials': {'api_key': 'ts-123'},
}


def _redact(name: str, where: str) -> dict:
    return {
        'name': name,
        'type': 'presidio_anonymizer',
        'where': where,
        'parameters': {'language': 'en', 'entities': ['EMAIL_ADDRESS']},
    }


def _contains(name: str, where: str, behavior: str, value: str, **extra) -> dict:
    return {
        'name': name,
        'type': 'contains',
        'where': where,
        'behavior': behavior,
        'parameters': {'values': [value]},
        **extra,
    }


REDACT_IN = _redact('redact_in', 'input')
REDACT_OUT = _redact('redact_out', 'output')
WARN_IN = _contains('warn_in', 'input', 'warn', 'warnme')
SOFT_IN = _contains('soft_in', 'input', 'soft_block', 'softme')
BLOCK_IN = _contains('block_in', 'input', 'block', 'blockme', response_message='no')
WARN_OUT = _contains('warn_out', 'output', 'warn', 'warnout')
SOFT_OUT = _contains('soft_out', 'output', 'soft_block', 'softout')
SOFT_IO = _contains('soft_io', 'io', 'soft_block', 'softout')


def _build_routes(
    *guardrails: dict, unknown: tuple[str, ...] = (), **chat_route
) -> dict:
    """Build a chat, an embedding and a decision route, each with
    ``guardrails`` (output ones on the chat route only).
    """
    names = [g['name'] for g in guardrails]
    input_names = [g['name'] for g in guardrails if g['where'] != 'output']
    config = GatewayConfig.model_validate(
        {
            'chat_models': [GPT],
            'embedding_models': [EMBEDDING],
            'decision_models': [JEV],
            'guardrails': list(guardrails),
            # Without a Redis client the routes cache in memory.
            **(
                {'cache': {'redis_host': 'localhost', 'redis_port': 6379}}
                if 'caching' in chat_route
                else {}
            ),
            'routes': {
                'chat': {'chat_models': ['gpt'], 'guardrails': names, **chat_route},
                'embed': {'embedding_models': ['emb'], 'guardrails': input_names},
                'agent': {'decision_models': ['jev'], 'guardrails': input_names},
            },
        }
    )
    # The config rejects unknown names: only code that builds routes by hand
    # can hand one over.
    config.routes['chat'].guardrails = [*unknown, *names]
    return build_routes(config)


@pytest.fixture
def gateway(caplog):
    events: list = []
    with open_gateway(
        caplog=caplog,
        use_pook=True,
        patches=[
            *(patch(target, side_effect=events.append) for target in EVENT_EMITS),
            *(patch(target) for target in QUIET_EMITS),
        ],
        gateway_class=_Gateway,
    ) as gateway:
        gateway.events = events
        yield gateway


class _Gateway(Gateway):
    """Sends the requests with no canned replies: pook answers for the providers."""

    def chat(self, text: str, stream: bool = False):
        return super().chat(None, text=text, stream=stream)

    def responses(self, text: str, stream: bool = False):
        return super().responses(None, text=text, stream=stream)

    def embed(self, texts: list[str]):
        return super().embed(None, texts=texts)

    def decide(self, ticket: str):
        return self.post(
            '/v1/systemone', json={'model': 'proj/agent', 'state': {'ticket': ticket}}
        )

    def guardrail_events(self) -> list[tuple]:
        return [(e.name, e.type, e.where, e.behavior, e.is_judge) for e in self.events]

    def guardrail_logs(self) -> list[tuple[str, str]]:
        """Return the log lines guardrails write, in order, at every level."""
        return [
            (r.levelname, r.getMessage())
            for r in self.caplog.records
            if r.name == LOGGER
            and ('uardrail' in r.getMessage() or 'GUARDRAIL' in r.getMessage())
            and not r.getMessage().startswith(('Invoke response', 'Streaming chunk'))
        ]


def _guardrail_headers(response) -> dict[str, str]:
    return {
        k.upper(): v
        for k, v in response.headers.items()
        if k.upper().startswith('X-RB-AIGATEWAY-GUARDRAILS')
    }


def _mock_openai(content: str):
    mock = pook.post(OPENAI_URL).times(1)
    completion = to_mock_openai_chat_completion(content=content).model_dump()
    completion['usage'] = {
        'prompt_tokens': 5,
        'completion_tokens': 3,
        'total_tokens': 8,
    }
    mock.reply(200).json(completion)
    return mock


def _mock_openai_stream(*parts: str):
    def chunk(delta, finish_reason=None):
        return {
            'id': 'chatcmpl-1',
            'object': 'chat.completion.chunk',
            'created': 1,
            'model': 'gpt-4o',
            'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish_reason}],
        }

    events = [chunk({'content': p}) for p in parts] + [chunk({}, 'stop')]
    body = ''.join(f'data: {json.dumps(e)}\n\n' for e in events) + 'data: [DONE]\n\n'
    mock = pook.post(OPENAI_URL).times(1)
    mock.reply(200).header('Content-Type', 'text/event-stream').body(body)
    return mock


def _openai_response(text: str) -> dict:
    return {
        'id': 'resp_1',
        'object': 'response',
        'created_at': 1,
        'model': 'gpt-4o',
        'status': 'completed',
        'output': [
            {
                'type': 'message',
                'id': 'msg_1',
                'role': 'assistant',
                'status': 'completed',
                'content': [{'type': 'output_text', 'text': text, 'annotations': []}],
            }
        ],
        'parallel_tool_calls': True,
        'tool_choice': 'auto',
        'tools': [],
        'usage': {
            'input_tokens': 10,
            'input_tokens_details': {'cached_tokens': 0},
            'output_tokens': 1,
            'output_tokens_details': {'reasoning_tokens': 0},
            'total_tokens': 11,
        },
    }


def _mock_openai_responses(text: str):
    mock = pook.post(OPENAI_RESPONSES_URL).times(1)
    mock.reply(200).json(_openai_response(text))
    return mock


def _mock_openai_responses_stream(text: str):
    events = [
        {
            'type': 'response.output_text.delta',
            'item_id': 'msg_1',
            'output_index': 0,
            'content_index': 0,
            'delta': text,
            'logprobs': [],
        },
        {'type': 'response.completed', 'response': _openai_response(text)},
    ]
    body = ''.join(
        f'event: {event["type"]}\ndata: {json.dumps(event)}\n\n' for event in events
    )
    mock = pook.post(OPENAI_RESPONSES_URL).times(1)
    mock.reply(200).header('Content-Type', 'text/event-stream').body(body)
    return mock


def _mock_openai_embeddings():
    mock = pook.post(OPENAI_EMBEDDINGS_URL).times(1)
    mock.reply(200).json(
        {
            'object': 'list',
            'data': [{'object': 'embedding', 'index': 0, 'embedding': [0.1, 0.2]}],
            'model': 'text-embedding-3-small',
            'usage': {'prompt_tokens': 4, 'total_tokens': 4},
        }
    )
    return mock


def _sse(response) -> list:
    """Return the data frames of a stream, without ids and timestamps."""
    frames = []
    for line in response.text.splitlines():
        if not line.startswith('data: '):
            continue
        data = line[len('data: ') :]
        if data == '[DONE]':
            frames.append(data)
            continue
        frame = json.loads(data)
        frame.pop('id', None)
        frame.pop('created', None)
        frames.append(frame)
    return frames


def _completion(response) -> dict:
    body = response.json()
    body.pop('id')
    body.pop('created')
    return body


# ---------------------------------------------------------------------------
# Chat completions
# ---------------------------------------------------------------------------

INPUT_SOFT_BLOCK_MESSAGE = (
    'I cannot process this request as it violates content policy: soft_in'
)
OUTPUT_SOFT_BLOCK_MESSAGE = (
    'This response has been blocked due to policy violation: soft_out'
)

REDACT_IN_EVENT = ('redact_in', 'PRESIDIO_ANONYMIZER', 'INPUT', 'BLOCK', False)
REDACT_IN_LOG = (
    'WARNING',
    (
        '[GUARDRAIL TRIGGERED] [route=chat] [name=redact_in] '
        '[type=PRESIDIO_ANONYMIZER] [where=INPUT] [behavior=BLOCK]'
    ),
)
SOFT_IN_LOG = (
    'WARNING',
    (
        '[GUARDRAIL TRIGGERED] [route=chat] [name=soft_in] [type=CONTAINS] '
        '[where=INPUT] [behavior=SOFT_BLOCK] [reason=contains '
        'value=\'softme\' message_indices=[0] context="Mail <EMAIL_ADDRESS> <<softme>>"]'
    ),
)


def test_chat_input_soft_block_after_a_redaction(gateway):
    gateway_routes = _build_routes(REDACT_IN, SOFT_IN)
    app.state.routes = gateway_routes
    openai = _mock_openai('never')

    response = gateway.chat(f'Mail {EMAIL} softme')

    assert response.status_code == 200
    assert _completion(response) == {
        'choices': [
            {
                'finish_reason': 'stop',
                'index': 0,
                'logprobs': None,
                'message': {
                    'content': INPUT_SOFT_BLOCK_MESSAGE,
                    'refusal': None,
                    'role': 'assistant',
                    'annotations': None,
                    'audio': None,
                    'function_call': None,
                    'tool_calls': None,
                },
            }
        ],
        'model': 'chat',
        'object': 'chat.completion',
        'metadata': None,
        'moderation': None,
        'service_tier': None,
        'system_fingerprint': None,
        'usage': {
            'completion_tokens': 0,
            'prompt_tokens': 0,
            'total_tokens': 0,
            'completion_tokens_details': None,
            'prompt_tokens_details': None,
        },
    }
    assert _guardrail_headers(response) == GOLDEN_HEADERS['chat_input_soft_block']
    assert not openai.isdone()
    assert gateway.guardrail_events() == [
        REDACT_IN_EVENT,
        ('soft_in', 'CONTAINS', 'INPUT', 'SOFT_BLOCK', False),
    ]
    assert gateway.guardrail_logs() == [REDACT_IN_LOG, SOFT_IN_LOG]


@pytest.mark.parametrize('extra', [(), (WARN_OUT,)], ids=['live', 'buffered'])
def test_chat_input_soft_block_without_a_redaction(gateway, extra):
    app.state.routes = _build_routes(SOFT_IN, *extra)

    for stream in (False, True):
        response = gateway.chat('please softme', stream=stream)

        assert response.status_code == 200
        assert _guardrail_headers(response) == {
            'X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED': 'true',
            'X-RB-AIGATEWAY-GUARDRAILS-INPUT-TRIGGERED': 'true',
        }


@pytest.mark.parametrize('extra', [(), (WARN_OUT,)], ids=['live', 'buffered'])
def test_chat_stream_cache_hit_after_a_redaction(gateway, extra):
    app.state.routes = _build_routes(REDACT_IN, *extra, caching={'type': 'exact'})
    _mock_openai_stream('a reply')
    gateway.chat(f'Mail {EMAIL}', stream=True)

    response = gateway.chat(f'Mail {EMAIL}', stream=True)

    assert response.status_code == 200
    assert response.headers['X-RB-AIGATEWAY-CACHE-HIT'] == 'true'
    assert _guardrail_headers(response) == {
        'X-RB-AIGATEWAY-GUARDRAILS-WARN': 'true',
        'X-RB-AIGATEWAY-GUARDRAILS-INPUT-WARN': 'true',
    }


def test_chat_live_stream_input_soft_block_after_a_redaction(gateway):
    app.state.routes = _build_routes(REDACT_IN, SOFT_IN)
    openai = _mock_openai_stream('never')

    response = gateway.chat(f'Mail {EMAIL} softme', stream=True)

    assert response.status_code == 200
    assert _sse(response) == [
        {
            'choices': [
                {
                    'delta': {
                        'content': INPUT_SOFT_BLOCK_MESSAGE,
                        'role': 'assistant',
                    },
                    'finish_reason': 'stop',
                    'index': 0,
                }
            ],
            'model': 'chat',
            'object': 'chat.completion.chunk',
        },
        '[DONE]',
    ]
    assert _guardrail_headers(response) == {
        'X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED': 'true',
        'X-RB-AIGATEWAY-GUARDRAILS-INPUT-TRIGGERED': 'true',
        'X-RB-AIGATEWAY-GUARDRAILS-WARN': 'true',
        'X-RB-AIGATEWAY-GUARDRAILS-INPUT-WARN': 'true',
    }
    assert not openai.isdone()


def test_chat_buffered_stream_input_soft_block_after_a_redaction(gateway):
    app.state.routes = _build_routes(REDACT_IN, SOFT_IN, WARN_OUT)
    openai = _mock_openai_stream('never')

    response = gateway.chat(f'Mail {EMAIL} softme', stream=True)

    assert response.status_code == 200
    assert _sse(response) == [
        {
            'choices': [
                {
                    'delta': {
                        'content': INPUT_SOFT_BLOCK_MESSAGE,
                        'role': 'assistant',
                    },
                    'finish_reason': 'stop',
                    'index': 0,
                }
            ],
            'model': 'chat',
            'object': 'chat.completion.chunk',
        },
        '[DONE]',
    ]
    assert _guardrail_headers(response) == GOLDEN_HEADERS['buffered_input_soft_block']
    assert not openai.isdone()


def test_chat_warns_on_input_and_output(gateway):
    app.state.routes = _build_routes(WARN_IN, WARN_OUT)
    _mock_openai('a warnout reply')

    response = gateway.chat('please warnme')

    assert response.status_code == 200
    assert response.json()['choices'][0]['message']['content'] == 'a warnout reply'
    assert _guardrail_headers(response) == {
        'X-RB-AIGATEWAY-GUARDRAILS-WARN': 'true',
        'X-RB-AIGATEWAY-GUARDRAILS-INPUT-WARN': 'true',
        'X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-WARN': 'true',
    }
    assert gateway.guardrail_events() == [
        ('warn_in', 'CONTAINS', 'INPUT', 'WARN', False),
        ('warn_out', 'CONTAINS', 'OUTPUT', 'WARN', False),
    ]
    assert gateway.guardrail_logs() == [
        (
            'WARNING',
            (
                '[GUARDRAIL TRIGGERED] [route=chat] [name=warn_in] [type=CONTAINS] '
                "[where=INPUT] [behavior=WARN] [reason=contains value='warnme' "
                'message_indices=[0] context="please <<warnme>>"]'
            ),
        ),
        (
            'WARNING',
            (
                '[GUARDRAIL TRIGGERED] [route=chat] [name=warn_out] [type=CONTAINS] '
                "[where=OUTPUT] [behavior=WARN] [reason=contains value='warnout' "
                'message_indices=[0] context="a <<warnout>> reply"]'
            ),
        ),
    ]


def test_chat_unknown_guardrail_names_are_logged_where_guardrails_run(gateway):
    app.state.routes = _build_routes(REDACT_IN, WARN_IN, unknown=('ghost',))
    _mock_openai('a reply')

    response = gateway.chat('please warnme')

    assert response.status_code == 200
    assert gateway.guardrail_logs() == [
        ('WARNING', "Guardrail name 'ghost' not found for route chat"),
        ('WARNING', "Guardrail id 'ghost' not found for route chat"),
        (
            'WARNING',
            (
                '[GUARDRAIL TRIGGERED] [route=chat] [name=warn_in] [type=CONTAINS] '
                "[where=INPUT] [behavior=WARN] [reason=contains value='warnme' "
                'message_indices=[0] context="please <<warnme>>"]'
            ),
        ),
    ]


def test_chat_buffered_stream_warns_on_input_and_output(gateway):
    app.state.routes = _build_routes(WARN_IN, WARN_OUT)
    _mock_openai_stream('a warnout ', 'reply')

    response = gateway.chat('please warnme', stream=True)

    assert response.status_code == 200
    assert [f['choices'][0]['delta'].get('content') for f in _sse(response)[:-1]] == [
        'a warnout ',
        'reply',
        None,
        None,
    ]
    assert _guardrail_headers(response) == GOLDEN_HEADERS['buffered_warn']
    assert gateway.guardrail_events() == [
        ('warn_in', 'CONTAINS', 'INPUT', 'WARN', False),
        ('warn_out', 'CONTAINS', 'OUTPUT', 'WARN', False),
    ]


def test_chat_output_soft_block_keeps_the_usage(gateway):
    app.state.routes = _build_routes(WARN_OUT, SOFT_OUT)
    _mock_openai('a softout warnout reply')

    response = gateway.chat('hello')

    assert response.status_code == 200
    body = _completion(response)
    assert body['choices'][0]['message']['content'] == OUTPUT_SOFT_BLOCK_MESSAGE
    assert body['usage']['total_tokens'] == 8
    assert body['model'] == 'chat'
    assert _guardrail_headers(response) == {
        'X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED': 'true',
        'X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-TRIGGERED': 'true',
        'X-RB-AIGATEWAY-GUARDRAILS-WARN': 'true',
        'X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-WARN': 'true',
    }
    assert gateway.guardrail_events() == [
        ('warn_out', 'CONTAINS', 'OUTPUT', 'WARN', False),
        ('soft_out', 'CONTAINS', 'OUTPUT', 'SOFT_BLOCK', False),
    ]


def test_chat_output_redaction(gateway):
    app.state.routes = _build_routes(REDACT_OUT)
    _mock_openai(f'Write to {EMAIL}')

    response = gateway.chat('hello')

    assert response.status_code == 200
    assert (
        response.json()['choices'][0]['message']['content']
        == 'Write to <EMAIL_ADDRESS>'
    )
    assert _guardrail_headers(response) == {
        'X-RB-AIGATEWAY-GUARDRAILS-WARN': 'true',
        'X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-WARN': 'true',
    }
    assert gateway.guardrail_events() == [
        ('redact_out', 'PRESIDIO_ANONYMIZER', 'OUTPUT', 'BLOCK', False)
    ]
    assert gateway.guardrail_logs()[-1] == (
        'WARNING',
        (
            '[GUARDRAIL TRIGGERED] [route=chat] [name=redact_out] '
            '[type=PRESIDIO_ANONYMIZER] [where=OUTPUT] [behavior=BLOCK]'
        ),
    )


@pytest.mark.parametrize('stream', [False, True], ids=['complete', 'live_stream'])
def test_chat_input_block(gateway, stream):
    app.state.routes = _build_routes(BLOCK_IN)
    openai = _mock_openai('never')

    response = gateway.chat('please blockme', stream=stream)

    assert response.status_code == 400
    assert response.json() == {
        'error': {
            'message': 'no',
            'type': 'guardrail_error',
            'param': {
                'name': 'block_in',
                'type': 'CONTAINS',
                'where': 'INPUT',
                'behavior': 'BLOCK',
                'parameters': {
                    'type': 'CHECK',
                    'values': ['blockme'],
                    'ignore_case': False,
                },
                'reason': {
                    'kind': 'contains',
                    'value': 'blockme',
                    'message_indices': [0],
                    'role': 'user',
                    'context': 'please <<blockme>>',
                },
            },
            'code': 'guardrail_violation_bad_request',
        }
    }
    assert _guardrail_headers(response) == {
        'X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED': 'true'
    }
    assert not openai.isdone()


def _buffered_soft_block_error(name: str, where: str) -> dict:
    return {
        'error': {
            'message': f'This response has been blocked due to policy violation: {name}',
            'type': 'guardrail_error',
            'param': {
                'name': name,
                'type': 'CONTAINS',
                'where': where,
                'behavior': 'SOFT_BLOCK',
                'parameters': {
                    'type': 'CHECK',
                    'values': ['softout'],
                    'ignore_case': False,
                },
                'reason': {'action': 'soft_block'},
            },
            'code': 'guardrail_violation_bad_request',
        }
    }


def test_chat_buffered_stream_output_soft_block_is_a_400(gateway):
    app.state.routes = _build_routes(WARN_OUT, SOFT_OUT)
    _mock_openai_stream('a softout reply')

    response = gateway.chat('hello', stream=True)

    assert response.status_code == 400
    assert response.json() == _buffered_soft_block_error('soft_out', 'OUTPUT')
    assert _guardrail_headers(response) == {
        'X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED': 'true',
        'X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-TRIGGERED': 'true',
        'X-RB-AIGATEWAY-GUARDRAILS-WARN': 'true',
        'X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-WARN': 'true',
    }


def test_chat_buffered_stream_output_redaction(gateway):
    app.state.routes = _build_routes(REDACT_OUT)
    _mock_openai_stream('Write to ', EMAIL)

    response = gateway.chat('hello', stream=True)

    assert response.status_code == 200
    # The redacted text goes out in the first content chunk (D8).
    assert [f['choices'][0]['delta'].get('content') for f in _sse(response)[:-1]] == [
        'Write to <EMAIL_ADDRESS>',
        None,
        None,
        None,
    ]
    assert EMAIL not in response.text
    assert _guardrail_headers(response) == GOLDEN_HEADERS['buffered_redact']
    assert gateway.guardrail_events() == [
        ('redact_out', 'PRESIDIO_ANONYMIZER', 'OUTPUT', 'BLOCK', False)
    ]


def test_chat_buffered_stream_redacts_before_the_output_check(gateway):
    block_email = _contains('block_email', 'output', 'block', EMAIL)
    app.state.routes = _build_routes(REDACT_OUT, block_email)
    _mock_openai_stream(f'Write to {EMAIL}')

    response = gateway.chat('hello', stream=True)

    assert response.status_code == 200
    assert 'Write to <EMAIL_ADDRESS>' in response.text


def test_chat_buffered_stream_output_block(gateway):
    block_out = _contains('block_out', 'output', 'block', 'bad', response_message='no')
    app.state.routes = _build_routes(block_out)
    _mock_openai_stream('a bad reply')

    response = gateway.chat('hello', stream=True)

    assert response.status_code == 400
    assert response.json()['error']['message'] == 'no'
    assert response.json()['error']['param']['name'] == 'block_out'
    assert _guardrail_headers(response) == {
        'X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED': 'true'
    }


def test_chat_buffered_stream_soft_block_names_an_io_guardrail(gateway):
    app.state.routes = _build_routes(SOFT_IO)
    _mock_openai_stream('a softout reply')

    response = gateway.chat('hello', stream=True)

    assert response.status_code == 400
    assert response.json() == _buffered_soft_block_error('soft_io', 'IO')


def test_chat_buffered_stream_soft_block_with_an_unknown_name_on_the_route(gateway):
    app.state.routes = _build_routes(SOFT_OUT, unknown=('ghost',))
    _mock_openai_stream('a softout reply')

    response = gateway.chat('hello', stream=True)

    assert response.status_code == 400
    assert response.json() == _buffered_soft_block_error('soft_out', 'OUTPUT')


# ---------------------------------------------------------------------------
# Responses API
# ---------------------------------------------------------------------------


def test_responses_input_soft_block_after_a_redaction(gateway):
    app.state.routes = _build_routes(REDACT_IN, SOFT_IN)
    openai = _mock_openai_responses('never')

    response = gateway.responses(f'Mail {EMAIL} softme')

    assert response.status_code == 200
    assert response.json()['output'][0]['content'][0]['text'] == (
        INPUT_SOFT_BLOCK_MESSAGE
    )
    assert _guardrail_headers(response) == {
        'X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED': 'true',
        'X-RB-AIGATEWAY-GUARDRAILS-INPUT-TRIGGERED': 'true',
        'X-RB-AIGATEWAY-GUARDRAILS-WARN': 'true',
        'X-RB-AIGATEWAY-GUARDRAILS-INPUT-WARN': 'true',
    }
    assert not openai.isdone()
    assert gateway.guardrail_events() == [
        REDACT_IN_EVENT,
        ('soft_in', 'CONTAINS', 'INPUT', 'SOFT_BLOCK', False),
    ]


@pytest.mark.parametrize('stream', [False, True])
def test_responses_output_soft_block(gateway, stream):
    app.state.routes = _build_routes(SOFT_OUT)
    if stream:
        _mock_openai_responses_stream('a softout reply')
    else:
        _mock_openai_responses('a softout reply')

    response = gateway.responses('hello', stream=stream)

    assert response.status_code == 200
    assert OUTPUT_SOFT_BLOCK_MESSAGE in response.text
    assert 'a softout reply' not in response.text
    assert _guardrail_headers(response) == {
        'X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED': 'true',
        'X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-TRIGGERED': 'true',
        'X-RB-AIGATEWAY-GUARDRAILS-WARN': 'true',
        'X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-WARN': 'true',
    }


def test_responses_output_redaction_and_warn(gateway):
    app.state.routes = _build_routes(WARN_IN, REDACT_OUT)
    _mock_openai_responses(f'Write to {EMAIL}')

    response = gateway.responses('please warnme')

    assert response.status_code == 200
    assert response.json()['output'][0]['content'][0]['text'] == (
        'Write to <EMAIL_ADDRESS>'
    )
    assert _guardrail_headers(response) == {
        'X-RB-AIGATEWAY-GUARDRAILS-WARN': 'true',
        'X-RB-AIGATEWAY-GUARDRAILS-INPUT-WARN': 'true',
        'X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-WARN': 'true',
    }
    assert gateway.guardrail_events() == [
        ('warn_in', 'CONTAINS', 'INPUT', 'WARN', False),
        ('redact_out', 'PRESIDIO_ANONYMIZER', 'OUTPUT', 'BLOCK', False),
    ]


# ---------------------------------------------------------------------------
# Embeddings and decisions
# ---------------------------------------------------------------------------


def test_embeddings_soft_block_after_a_redaction(gateway):
    app.state.routes = _build_routes(REDACT_IN, SOFT_IN)
    openai = _mock_openai_embeddings()

    response = gateway.embed([f'Mail {EMAIL}', 'softme'])

    assert response.status_code == 200
    assert response.json() == {
        'data': [],
        'model': 'embed',
        'object': 'list',
        'usage': {'prompt_tokens': 0, 'total_tokens': 0},
        'error': INPUT_SOFT_BLOCK_MESSAGE,
    }
    assert _guardrail_headers(response) == {}
    assert not openai.isdone()
    assert gateway.guardrail_events() == [
        ('redact_in', 'PRESIDIO_ANONYMIZER', 'INPUT', 'BLOCK', False),
        ('soft_in', 'CONTAINS', 'INPUT', 'SOFT_BLOCK', False),
    ]


def test_embeddings_are_redacted_before_going_upstream(gateway):
    app.state.routes = _build_routes(REDACT_IN)
    openai = _mock_openai_embeddings()

    response = gateway.embed([f'Mail {EMAIL}'])

    assert response.status_code == 200
    [sent] = openai.matches[0].json['input']
    encoding = tiktoken.encoding_for_model('text-embedding-3-small')
    assert encoding.decode(sent) == 'Mail <EMAIL_ADDRESS>'


def test_embeddings_block_logs_the_block(gateway):
    app.state.routes = _build_routes(BLOCK_IN)
    openai = _mock_openai_embeddings()

    response = gateway.embed(['please blockme'])

    assert response.status_code == 400
    assert response.json()['error']['message'] == 'no'
    assert not openai.isdone()
    block_log = (
        '[GUARDRAIL TRIGGERED] [route=embed] [name=block_in] [type=CONTAINS] '
        "[where=INPUT] [behavior=BLOCK] [reason=contains value='blockme' "
        'message_indices=[0] context="please <<blockme>>"]'
    )
    assert ('WARNING', f'Guardrail BLOCK triggered: {block_log}') in (
        gateway.guardrail_logs()
    )


def test_decision_soft_block_is_a_400(gateway):
    app.state.routes = _build_routes(SOFT_IN)

    response = gateway.decide('please softme')

    assert response.status_code == 400
    assert response.json() == {
        'error': {
            'message': INPUT_SOFT_BLOCK_MESSAGE,
            'type': 'guardrail_error',
            'param': {
                'name': 'soft_in',
                'type': 'CONTAINS',
                'where': 'INPUT',
                'behavior': 'SOFT_BLOCK',
                'parameters': {
                    'type': 'CHECK',
                    'values': ['softme'],
                    'ignore_case': False,
                },
            },
            'code': 'guardrail_violation_bad_request',
        }
    }
    assert _guardrail_headers(response) == {
        'X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED': 'true'
    }
    assert gateway.guardrail_events() == [
        ('soft_in', 'CONTAINS', 'INPUT', 'SOFT_BLOCK', False)
    ]


# ---------------------------------------------------------------------------
# Headers
# ---------------------------------------------------------------------------

INPUT_SOFT_BLOCK_AFTER_A_REDACTION = {
    'X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED': 'true',
    'X-RB-AIGATEWAY-GUARDRAILS-INPUT-TRIGGERED': 'true',
    'X-RB-AIGATEWAY-GUARDRAILS-WARN': 'true',
    'X-RB-AIGATEWAY-GUARDRAILS-INPUT-WARN': 'true',
}
# Every endpoint sends the full set of guardrail headers.
GOLDEN_HEADERS = {
    'chat_input_soft_block': INPUT_SOFT_BLOCK_AFTER_A_REDACTION,
    'buffered_input_soft_block': INPUT_SOFT_BLOCK_AFTER_A_REDACTION,
    'buffered_warn': {
        'X-RB-AIGATEWAY-GUARDRAILS-WARN': 'true',
        'X-RB-AIGATEWAY-GUARDRAILS-INPUT-WARN': 'true',
        'X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-WARN': 'true',
    },
    'buffered_redact': {
        'X-RB-AIGATEWAY-GUARDRAILS-WARN': 'true',
        'X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-WARN': 'true',
    },
}
