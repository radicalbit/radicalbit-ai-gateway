"""Golden values of model calls and their fallbacks: what must not change when
the code does.

Every path that calls a model with a fallback is driven through the HTTP app
on real routes, with the providers faked at the transport: chat (complete,
live stream), Responses (complete, stream), embeddings, transcription
(complete, stream), decision models, LLM and decision judges, LLM and decision
routers. Status codes, bodies, the model events, the model metrics and the log
lines are compared with literals. Only the drivers (the functions that build
the routes and send the requests) may change.
"""

from decimal import Decimal
import json
import logging

import pytest

from tests.common import provider_responses as upstream
from tests.common.gateway_harness import LOGGER, Gateway, build_routes, open_gateway
from tests.common.provider_recorder import CannedResponse

from radicalbit_ai_gateway.models.event_type import EventType

MODEL_EVENTS = {
    EventType.MODEL_INVOCATION,
    EventType.FALLBACK,
    EventType.INPUT_TOKEN_PROCESSED,
    EventType.OUTPUT_TOKEN_PROCESSED,
}
METRICS = (
    ('model_invocations_counter', 'add'),
    ('invocations_latency_histogram', 'record'),
    ('fallbacks_triggered_counter', 'add'),
    ('total_tokens_counter_input', 'add'),
    ('total_tokens_counter_output', 'add'),
)
CREDENTIALS = {'api_key': 'sk-test'}
TYPESAFE = {'api_key': 'ts-test'}


def _chat(model_id: str, name: str, **extra) -> dict:
    return {
        'model_id': model_id,
        'model': name,
        'credentials': CREDENTIALS,
        'input_cost_per_million_tokens': 1,
        'output_cost_per_million_tokens': 2,
        **extra,
    }


def _decision(model_id: str, name: str, retries: int = 0) -> dict:
    return {
        'model_id': model_id,
        'model': f'typesafe/{name}',
        'credentials': TYPESAFE,
        'retry_attempts': retries,
        'input_cost_per_million_tokens': 3,
    }


def _routing_options() -> list[dict]:
    return [
        {'model_id': 'a', 'description': 'Questions about geography'},
        {'model_id': 'b', 'description': 'Questions about code'},
    ]


CONFIG = {
    'chat_models': [
        _chat('a', 'openai/gpt-a'),
        _chat('b', 'openai/gpt-b'),
        _chat('j1', 'openai/gpt-j1'),
        _chat('j2', 'openai/gpt-j2'),
        _chat('r1', 'openai/gpt-r1'),
        _chat('r2', 'openai/gpt-r2'),
        _chat('claude', 'anthropic/claude-sonnet-4-5'),
        _chat('gemini', 'google-genai/gemini-2.5-flash', params={'max_retries': 1}),
        _chat('mistral', 'mistralai/mistral-small-latest'),
    ],
    'embedding_models': [
        {
            'model_id': 'e1',
            'model': 'openai/text-embedding-3-small',
            'credentials': CREDENTIALS,
            'input_cost_per_million_tokens': 1,
        },
        {
            'model_id': 'e2',
            'model': 'openai/text-embedding-3-large',
            'credentials': CREDENTIALS,
            'input_cost_per_million_tokens': 1,
        },
    ],
    'transcription_models': [
        {
            'model_id': 't1',
            'model': 'openai/gpt-4o-transcribe',
            'credentials': CREDENTIALS,
            'input_cost_per_million_tokens': 1,
            'output_cost_per_million_tokens': 2,
        },
        {
            'model_id': 't2',
            'model': 'openai/gpt-4o-mini-transcribe',
            'credentials': CREDENTIALS,
            'input_cost_per_million_tokens': 1,
            'output_cost_per_million_tokens': 2,
        },
    ],
    'decision_models': [
        _decision('d1', 'jev-latest', retries=1),
        _decision('d2', 'jev-backup'),
    ],
    'guardrails': [
        {
            'name': 'judge',
            'type': 'judge',
            'where': 'input',
            'behavior': 'block',
            'parameters': {
                'model_id': 'j1',
                'fallback_model_id': 'j2',
                'prompt': 'Judge this.',
            },
        },
        {
            'name': 'djudge',
            'type': 'decision_judge',
            'where': 'input',
            'behavior': 'block',
            'parameters': {
                'model_id': 'd1',
                'fallback_model_id': 'd2',
                'instructions': 'Is the text off topic?',
            },
        },
    ],
    'routing': [
        {
            'name': 'by-llm',
            'type': 'llm',
            'router_model_id': 'r1',
            'fallback_model_id': 'r2',
            'default_model_id': 'a',
            'output_mapping': _routing_options(),
        },
        {
            'name': 'by-decision',
            'type': 'decision',
            'decision_model_id': 'd1',
            'fallback_model_id': 'd2',
            'default_model_id': 'a',
            'instructions': 'Pick the model.',
            'output_mapping': _routing_options(),
        },
    ],
    'routes': {
        'chat': {
            'chat_models': ['a', 'b'],
            'fallback': [{'target': 'a', 'fallbacks': ['b'], 'type': 'chat'}],
        },
        'embed': {
            'embedding_models': ['e1', 'e2'],
            'fallback': [{'target': 'e1', 'fallbacks': ['e2'], 'type': 'embedding'}],
        },
        'audio': {
            'transcription_models': ['t1', 't2'],
            'fallback': [
                {'target': 't1', 'fallbacks': ['t2'], 'type': 'transcription'}
            ],
        },
        'agent': {
            'decision_models': ['d1', 'd2'],
            'fallback': [{'target': 'd1', 'fallbacks': ['d2'], 'type': 'decision'}],
        },
        'judged': {'chat_models': ['a'], 'guardrails': ['judge']},
        'djudged': {'chat_models': ['a'], 'guardrails': ['djudge']},
        'llm-routed': {'chat_models': ['a', 'b'], 'routing': 'by-llm'},
        'decision-routed': {'chat_models': ['a', 'b'], 'routing': 'by-decision'},
        **{
            provider: {'chat_models': [provider]}
            for provider in ('claude', 'gemini', 'mistral')
        },
    },
}


class _Gateway(Gateway):
    embed_texts = ('one', 'two')

    def chat(self, replies, route='chat', stream=False, text=None):
        return super().chat(replies, route=route, text=text, stream=stream)

    def responses(self, replies, stream=False):
        return super().responses(replies, stream=stream)

    def events(self) -> list[tuple]:
        """Return the model events: type, model, model type, target, fallback,
        value, cost, cached, cache type, judge, routing.
        """
        return [
            (
                e['EVENT_TYPE'].name,
                e['MODEL_ID'],
                e['MODEL_TYPE'],
                e['TARGET'],
                e['FALLBACK'],
                e['VALUE'],
                Decimal(str(e['COST'])),
                e['IS_CACHED_TOKENS'],
                e['CACHE_TYPE'],
                e['IS_JUDGE'],
                e['IS_ROUTING'],
            )
            for e in self.event_rows
            if e['EVENT_TYPE'] in MODEL_EVENTS
        ]

    def logs(self) -> list[tuple[str, str]]:
        """Return the gateway's log lines about model calls, in order."""
        words = ('model', 'Model', 'fallback', 'Fallback', 'judge', 'routing')
        return [
            (r.levelname, r.getMessage())
            for r in self.caplog.records
            if r.name == LOGGER
            and (
                r.levelno >= logging.WARNING
                or (
                    r.levelno == logging.INFO
                    and any(w in r.getMessage() for w in words)
                )
            )
            and not r.getMessage().startswith(
                (
                    'Invoke response',
                    'Invoked route name',
                    'Streaming chunk',
                    'Selected',
                    'Judge result',
                )
            )
        ]


@pytest.fixture
def gateway(caplog):
    with open_gateway(
        build_routes(CONFIG), caplog=caplog, metrics=METRICS, gateway_class=_Gateway
    ) as gateway:
        yield gateway


def _openai_error(status: int, message: str = 'upstream says no') -> CannedResponse:
    return CannedResponse(
        status=status,
        json_body={
            'error': {
                'message': message,
                'type': 'invalid_request_error',
                'param': None,
                'code': f'code_{status}',
            }
        },
    )


def _completion(model: str, text: str = 'Paris is in France') -> CannedResponse:
    return upstream.openai_completion(
        text, model=model, prompt_tokens=11, completion_tokens=5
    )


def _stream(model: str) -> CannedResponse:
    return upstream.openai_stream(
        ['Paris', ' is in France'], model=model, prompt_tokens=11, completion_tokens=5
    )


def _broken_stream(model: str) -> CannedResponse:
    """Return a stream that fails after its first chunk."""
    first = upstream.openai_stream(['Paris'], model=model).sse_events[1]
    return CannedResponse(sse_events=[first, {'choices': 'broken'}])


def _transcription(text: str = 'hello') -> CannedResponse:
    return CannedResponse(
        json_body={
            'text': text,
            'usage': {
                'type': 'tokens',
                'input_tokens': 10,
                'output_tokens': 3,
                'total_tokens': 13,
                'input_token_details': {'audio_tokens': 8, 'text_tokens': 2},
            },
        }
    )


def _transcription_stream(text: str = 'hello') -> CannedResponse:
    return CannedResponse(
        sse_events=[
            {'type': 'transcript.text.delta', 'delta': text},
            {
                'type': 'transcript.text.done',
                'text': text,
                'usage': {
                    'type': 'tokens',
                    'input_tokens': 10,
                    'output_tokens': 3,
                    'total_tokens': 13,
                    'input_token_details': {'audio_tokens': 8, 'text_tokens': 2},
                },
            },
        ]
    )


def _typesafe(answers: dict, input_tokens: int = 40) -> CannedResponse:
    return CannedResponse(
        json_body={
            'answers': answers,
            'model': 'jev-1',
            'usage': {'input_tokens': input_tokens, 'output_tokens': 2},
        }
    )


def _typesafe_error(status: int) -> CannedResponse:
    return CannedResponse(status=status, json_body={'error': f'typesafe {status}'})


def _structured(model: str, content: dict) -> CannedResponse:
    return upstream.openai_completion(
        json.dumps(content), model=model, prompt_tokens=30, completion_tokens=4
    )


NOT_TRIGGERED = {'triggered': False, 'reasoning': None, 'violation_type': None}
SCORES = {'option_1': 0.9, 'option_2': 0.1}
CHOICE = {
    'decision_routing': {'type': 'choice', 'choice': 'option_2', 'confidence': 0.9}
}
NOUL = {'decision_judge': {'type': 'noul', 'noul': 0.1}}


# The model events, as tuples: (type, model, model type, target, fallback,
# value, cost, cached, cache type, judge, routing).
def _invocation(model, model_type='chat-model', judge=False, routing=False):
    return (
        'MODEL_INVOCATION',
        model,
        model_type,
        '',
        '',
        1.0,
        Decimal(0),
        False,
        '',
        judge,
        routing,
    )


def _fallback(target, fallback, judge=False, routing=False):
    return (
        'FALLBACK',
        '',
        '',
        target,
        fallback,
        1.0,
        Decimal(0),
        False,
        '',
        judge,
        routing,
    )


def _anthropic_error(status: int) -> CannedResponse:
    return CannedResponse(
        status=status,
        json_body={
            'type': 'error',
            'error': {'type': 'rate_limit_error', 'message': 'slow down'},
        },
    )


def _gemini_error(status: int) -> CannedResponse:
    return CannedResponse(
        status=status,
        json_body={
            'error': {
                'code': status,
                'message': 'bad request',
                'status': 'INVALID_ARGUMENT',
            }
        },
    )


def _mistral_error(status: int) -> CannedResponse:
    return CannedResponse(
        status=status,
        json_body={
            'object': 'error',
            'message': 'Unauthorized',
            'type': 'unauthorized',
            'param': None,
            'code': None,
        },
    )


SCENARIOS = {
    # chat, complete
    'chat_ok': lambda g: g.chat([_completion('gpt-a')]),
    'chat_fallback': lambda g: g.chat([_openai_error(500), _completion('gpt-b')]),
    'chat_exhausted_4xx': lambda g: g.chat([_openai_error(429), _openai_error(500)]),
    'chat_exhausted_5xx': lambda g: g.chat([_openai_error(500), _openai_error(429)]),
    'chat_anthropic_4xx': lambda g: g.chat([_anthropic_error(429)], route='claude'),
    'chat_gemini_4xx': lambda g: g.chat([_gemini_error(400)], route='gemini'),
    'chat_mistral_4xx': lambda g: g.chat([_mistral_error(401)], route='mistral'),
    # chat, live stream
    'stream_ok': lambda g: g.chat([_stream('gpt-a')], stream=True),
    'stream_fallback': lambda g: g.chat(
        [_openai_error(500), _stream('gpt-b')], stream=True
    ),
    'stream_exhausted_4xx': lambda g: g.chat(
        [_openai_error(429), _openai_error(500)], stream=True
    ),
    'stream_exhausted_5xx': lambda g: g.chat(
        [_openai_error(500), _openai_error(429)], stream=True
    ),
    'stream_breaks_after_output': lambda g: g.chat(
        [_broken_stream('gpt-a')], stream=True
    ),
    'stream_fallback_breaks_after_output': lambda g: g.chat(
        [_openai_error(500), _broken_stream('gpt-b')], stream=True
    ),
    # Responses
    'responses_fallback': lambda g: g.responses(
        [_openai_error(500), upstream.openai_response(model='gpt-b')]
    ),
    'responses_exhausted_4xx': lambda g: g.responses(
        [_openai_error(429), _openai_error(500)]
    ),
    'responses_exhausted_5xx': lambda g: g.responses(
        [_openai_error(500), _openai_error(429)]
    ),
    'responses_stream_fallback': lambda g: g.responses(
        [_openai_error(500), upstream.openai_response_stream(model='gpt-b')],
        stream=True,
    ),
    'responses_stream_exhausted': lambda g: g.responses(
        [_openai_error(429), _openai_error(500)], stream=True
    ),
    # embeddings
    'embed_fallback': lambda g: g.embed(
        [_openai_error(500), upstream.openai_embeddings()]
    ),
    'embed_exhausted': lambda g: g.embed([_openai_error(429), _openai_error(500)]),
    # transcription
    'audio_fallback': lambda g: g.transcribe([_openai_error(500), _transcription()]),
    'audio_exhausted': lambda g: g.transcribe([_openai_error(500), _openai_error(503)]),
    'audio_rejected': lambda g: g.transcribe([_openai_error(400)]),
    'audio_stream_fallback': lambda g: g.transcribe(
        [_openai_error(500), _transcription_stream()], stream=True
    ),
    'audio_stream_exhausted': lambda g: g.transcribe(
        [_openai_error(500), _openai_error(503)], stream=True
    ),
    # decision models: d1 retries once
    'decision_fallback': lambda g: g.decide(
        [_typesafe_error(503), _typesafe_error(503), _typesafe(NOUL)]
    ),
    'decision_exhausted': lambda g: g.decide(
        [_typesafe_error(503), _typesafe_error(429), _typesafe_error(503)]
    ),
    'decision_rejected': lambda g: g.decide([_typesafe_error(400)]),
    # LLM judge
    'judge_fallback': lambda g: g.chat(
        [
            _openai_error(500),
            _structured('gpt-j2', NOT_TRIGGERED),
            _completion('gpt-a'),
        ],
        route='judged',
    ),
    'judge_bad_answer': lambda g: g.chat(
        [
            _structured('gpt-j1', {'nonsense': True}),
            _structured('gpt-j2', NOT_TRIGGERED),
            _completion('gpt-a'),
        ],
        route='judged',
    ),
    'judge_exhausted': lambda g: g.chat(
        [_openai_error(500), _openai_error(429)], route='judged'
    ),
    'judge_exhausted_bad_answer': lambda g: g.chat(
        [_openai_error(500), _structured('gpt-j2', {'nonsense': True})],
        route='judged',
    ),
    # decision judge: d1 retries once
    'djudge_fallback': lambda g: g.chat(
        [
            _typesafe_error(503),
            _typesafe_error(503),
            _typesafe(NOUL),
            _completion('gpt-a'),
        ],
        route='djudged',
    ),
    'djudge_exhausted': lambda g: g.chat(
        [_typesafe_error(503), _typesafe_error(503), _typesafe_error(500)],
        route='djudged',
    ),
    'djudge_rejected': lambda g: g.chat([_typesafe_error(400)], route='djudged'),
    'djudge_bad_answer': lambda g: g.chat(
        [_typesafe({'other': {}}), _typesafe(NOUL), _completion('gpt-a')],
        route='djudged',
    ),
    # LLM router
    'llm_router_fallback': lambda g: g.chat(
        [_openai_error(500), _structured('gpt-r2', SCORES), _completion('gpt-a')],
        route='llm-routed',
    ),
    'llm_router_exhausted': lambda g: g.chat(
        [_openai_error(500), _openai_error(429), _completion('gpt-a')],
        route='llm-routed',
    ),
    # decision router: d1 retries once
    'decision_router_fallback': lambda g: g.chat(
        [
            _typesafe_error(503),
            _typesafe_error(503),
            _typesafe(CHOICE),
            _completion('gpt-b'),
        ],
        route='decision-routed',
    ),
    'decision_router_exhausted': lambda g: g.chat(
        [
            _typesafe_error(503),
            _typesafe_error(503),
            _typesafe_error(500),
            _completion('gpt-a'),
        ],
        route='decision-routed',
    ),
}


def _snapshot(gateway: _Gateway, response) -> dict:
    try:
        body = response.json()
    except ValueError:
        # A stream that went through carries generated ids and times.
        body = response.text if response.status_code >= 400 else None
    if isinstance(body, dict):
        body = {k: v for k, v in body.items() if k not in ('created', 'created_at')}
    return {
        'status': response.status_code,
        'body': body,
        'upstream': [r['url'] for r in gateway.upstream],
        'events': gateway.events(),
        # A latency is a measure, not a golden value.
        'metrics': [
            (name, None if name == 'invocations_latency_histogram' else value, labels)
            for name, value, labels in gateway.metrics
        ],
        'logs': gateway.logs(),
    }


def _tokens(
    kind: str,
    model: str,
    model_type: str,
    value: float,
    cost: str,
    cached: bool = False,
    cache_type: str = '',
    judge: bool = False,
    routing: bool = False,
):
    return (
        f'{kind}_TOKEN_PROCESSED',
        model,
        model_type,
        '',
        '',
        value,
        Decimal(cost),
        cached,
        cache_type,
        judge,
        routing,
    )


def _err(status: int) -> str:
    """Return how an OpenAI SDK error reads for ``_openai_error(status)``."""
    return (
        f"Error code: {status} - {{'error': {{'message': 'upstream says no', "
        f"'type': 'invalid_request_error', 'param': None, 'code': 'code_{status}'}}}}"
    )


CHAT_BODY = {
    'id': '00000000-0000-0000-0000-000000000000',
    'choices': [
        {
            'finish_reason': 'stop',
            'index': 0,
            'logprobs': None,
            'message': {
                'content': 'Paris is in France',
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
        'completion_tokens': 5,
        'prompt_tokens': 11,
        'total_tokens': 16,
        'completion_tokens_details': None,
        'prompt_tokens_details': None,
    },
}

# One line per value, so a diff shows the value that changed.
# fmt: off
EXPECTED = {
    'chat_ok': {
        'status': 200,
        'body': CHAT_BODY,
        'upstream': ['https://api.openai.com/v1/chat/completions'],
        'events': [_invocation('a', 'chat-model'), _tokens('INPUT', 'a', 'chat-model', 11.0, '0.000011'), _tokens('OUTPUT', 'a', 'chat-model', 5.0, '0.00001')],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'chat', 'model_name': 'a'}), ('invocations_latency_histogram', None, {'route_name': 'chat', 'model_name': 'a'}), ('total_tokens_counter_input', 11, {'route_name': 'chat', 'model_name': 'a'}), ('total_tokens_counter_output', 5, {'route_name': 'chat', 'model_name': 'a'})],
        'logs': [],
    },
    'chat_fallback': {
        'status': 200,
        'body': CHAT_BODY,
        'upstream': ['https://api.openai.com/v1/chat/completions', 'https://api.openai.com/v1/chat/completions'],
        'events': [_invocation('b', 'chat-model'), _tokens('INPUT', 'b', 'chat-model', 11.0, '0.000011'), _tokens('OUTPUT', 'b', 'chat-model', 5.0, '0.00001'), _fallback('a', 'b')],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'chat', 'model_name': 'b'}), ('invocations_latency_histogram', None, {'route_name': 'chat', 'model_name': 'b'}), ('total_tokens_counter_input', 11, {'route_name': 'chat', 'model_name': 'b'}), ('total_tokens_counter_output', 5, {'route_name': 'chat', 'model_name': 'b'}), ('fallbacks_triggered_counter', 1, {'route_name': 'chat', 'target': 'a', 'fallback': 'b'})],
        'logs': [('WARNING', f'Primary chat model a failed: {_err(500)}. Trying fallbacks...')],
    },
    'chat_exhausted_4xx': {
        'status': 429,
        'body': {'error': {'message': 'upstream says no', 'type': 'invalid_request_error', 'param': None, 'code': 'code_429'}},
        'upstream': ['https://api.openai.com/v1/chat/completions', 'https://api.openai.com/v1/chat/completions'],
        'events': [_invocation('b', 'chat-model'), _fallback('a', 'b')],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'chat', 'model_name': 'b'}), ('invocations_latency_histogram', None, {'route_name': 'chat', 'model_name': 'b'}), ('fallbacks_triggered_counter', 1, {'route_name': 'chat', 'target': 'a', 'fallback': 'b'})],
        'logs': [('WARNING', f'Primary chat model a failed: {_err(429)}. Trying fallbacks...'), ('WARNING', f'Fallback chat model b failed: {_err(500)}'), ('ERROR', 'All chat models failed for route chat'), ('WARNING', f'{_err(429)}')],
    },
    'chat_exhausted_5xx': {
        'status': 500,
        'body': {'error': {'message': f'All chat models failed for model chat: {_err(500)}', 'type': 'model_invoker_error', 'param': None, 'code': 'model_invoker_internal_error'}},
        'upstream': ['https://api.openai.com/v1/chat/completions', 'https://api.openai.com/v1/chat/completions'],
        'events': [_invocation('b', 'chat-model'), _fallback('a', 'b')],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'chat', 'model_name': 'b'}), ('invocations_latency_histogram', None, {'route_name': 'chat', 'model_name': 'b'}), ('fallbacks_triggered_counter', 1, {'route_name': 'chat', 'target': 'a', 'fallback': 'b'})],
        'logs': [('WARNING', f'Primary chat model a failed: {_err(500)}. Trying fallbacks...'), ('WARNING', f'Fallback chat model b failed: {_err(429)}'), ('ERROR', 'All chat models failed for route chat'), ('ERROR', f'All chat models failed for model chat: {_err(500)}')],
    },
    'chat_anthropic_4xx': {
        'status': 429,
        'body': {'type': 'error', 'error': {'type': 'rate_limit_error', 'message': 'slow down'}},
        'upstream': ['https://api.anthropic.com/v1/messages'],
        'events': [_invocation('claude', 'chat-model')],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'claude', 'model_name': 'claude'}), ('invocations_latency_histogram', None, {'route_name': 'claude', 'model_name': 'claude'})],
        'logs': [('WARNING', "Primary chat model claude failed: Error code: 429 - {'type': 'error', 'error': {'type': 'rate_limit_error', 'message': 'slow down'}}. Trying fallbacks..."), ('ERROR', 'All chat models failed for route claude'), ('WARNING', "Error code: 429 - {'type': 'error', 'error': {'type': 'rate_limit_error', 'message': 'slow down'}}")],
    },
    'chat_gemini_4xx': {
        'status': 400,
        'body': {'error': {'code': 400, 'message': 'bad request', 'status': 'INVALID_ARGUMENT'}},
        'upstream': ['https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent'],
        'events': [_invocation('gemini', 'chat-model')],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'gemini', 'model_name': 'gemini'}), ('invocations_latency_histogram', None, {'route_name': 'gemini', 'model_name': 'gemini'})],
        'logs': [('WARNING', "Primary chat model gemini failed: Error calling model 'gemini-2.5-flash' (INVALID_ARGUMENT): 400 INVALID_ARGUMENT. {'error': {'code': 400, 'message': 'bad request', 'status': 'INVALID_ARGUMENT'}}. Trying fallbacks..."), ('ERROR', 'All chat models failed for route gemini'), ('WARNING', 'bad request')],
    },
    'chat_mistral_4xx': {
        'status': 401,
        'body': {'object': 'error', 'message': 'Unauthorized', 'type': 'unauthorized', 'param': None, 'code': None},
        'upstream': ['https://api.mistral.ai/v1/chat/completions'],
        'events': [_invocation('mistral', 'chat-model')],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'mistral', 'model_name': 'mistral'}), ('invocations_latency_histogram', None, {'route_name': 'mistral', 'model_name': 'mistral'})],
        'logs': [('WARNING', 'Primary chat model mistral failed: Error response 401 while fetching https://api.mistral.ai/v1/chat/completions: {"object": "error", "message": "Unauthorized", "type": "unauthorized", "param": null, "code": null}. Trying fallbacks...'), ('ERROR', 'All chat models failed for route mistral'), ('WARNING', 'Error response 401 while fetching https://api.mistral.ai/v1/chat/completions: {"object": "error", "message": "Unauthorized", "type": "unauthorized", "param": null, "code": null}')],
    },
    'stream_ok': {
        'status': 200,
        'body': None,
        'upstream': ['https://api.openai.com/v1/chat/completions'],
        'events': [_invocation('a', 'chat-model'), _tokens('INPUT', 'a', 'chat-model', 11.0, '0.000011'), _tokens('OUTPUT', 'a', 'chat-model', 5.0, '0.00001')],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'chat', 'model_name': 'a'}), ('invocations_latency_histogram', None, {'route_name': 'chat', 'model_name': 'a'}), ('total_tokens_counter_input', 11, {'route_name': 'chat', 'model_name': 'a'}), ('total_tokens_counter_output', 5, {'route_name': 'chat', 'model_name': 'a'})],
        'logs': [],
    },
    'stream_fallback': {
        'status': 200,
        'body': None,
        'upstream': ['https://api.openai.com/v1/chat/completions', 'https://api.openai.com/v1/chat/completions'],
        'events': [_invocation('b', 'chat-model'), _tokens('INPUT', 'b', 'chat-model', 11.0, '0.000011'), _tokens('OUTPUT', 'b', 'chat-model', 5.0, '0.00001'), _fallback('a', 'b')],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'chat', 'model_name': 'b'}), ('invocations_latency_histogram', None, {'route_name': 'chat', 'model_name': 'b'}), ('total_tokens_counter_input', 11, {'route_name': 'chat', 'model_name': 'b'}), ('total_tokens_counter_output', 5, {'route_name': 'chat', 'model_name': 'b'}), ('fallbacks_triggered_counter', 1, {'route_name': 'chat', 'target': 'a', 'fallback': 'b'})],
        'logs': [('WARNING', f'Primary model a stream failed: {_err(500)}'), ('INFO', 'Trying fallback model b for streaming')],
    },
    'stream_exhausted_4xx': {
        'status': 429,
        'body': {'error': {'message': 'upstream says no', 'type': 'invalid_request_error', 'param': None, 'code': 'code_429'}},
        'upstream': ['https://api.openai.com/v1/chat/completions', 'https://api.openai.com/v1/chat/completions'],
        'events': [_invocation('b', 'chat-model'), _fallback('a', 'b')],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'chat', 'model_name': 'b'}), ('invocations_latency_histogram', None, {'route_name': 'chat', 'model_name': 'b'}), ('fallbacks_triggered_counter', 1, {'route_name': 'chat', 'target': 'a', 'fallback': 'b'})],
        'logs': [('WARNING', f'Primary model a stream failed: {_err(429)}'), ('INFO', 'Trying fallback model b for streaming'), ('WARNING', f'Fallback b stream failed: {_err(500)}')],
    },
    'stream_exhausted_5xx': {
        'status': 500,
        'body': {'error': {'message': 'All models failed for streaming chat', 'type': 'model_invoker_error', 'param': None, 'code': 500}},
        'upstream': ['https://api.openai.com/v1/chat/completions', 'https://api.openai.com/v1/chat/completions'],
        'events': [_invocation('b', 'chat-model'), _fallback('a', 'b')],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'chat', 'model_name': 'b'}), ('invocations_latency_histogram', None, {'route_name': 'chat', 'model_name': 'b'}), ('fallbacks_triggered_counter', 1, {'route_name': 'chat', 'target': 'a', 'fallback': 'b'})],
        'logs': [('WARNING', f'Primary model a stream failed: {_err(500)}'), ('INFO', 'Trying fallback model b for streaming'), ('WARNING', f'Fallback b stream failed: {_err(429)}')],
    },
    'stream_breaks_after_output': {
        'status': 200,
        'body': None,
        'upstream': ['https://api.openai.com/v1/chat/completions'],
        'events': [_invocation('a', 'chat-model')],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'chat', 'model_name': 'a'}), ('invocations_latency_histogram', None, {'route_name': 'chat', 'model_name': 'a'})],
        'logs': [('ERROR', 'Unhandled error during streaming')],
    },
    'stream_fallback_breaks_after_output': {
        'status': 200,
        'body': None,
        'upstream': ['https://api.openai.com/v1/chat/completions', 'https://api.openai.com/v1/chat/completions'],
        'events': [_invocation('b', 'chat-model'), _fallback('a', 'b')],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'chat', 'model_name': 'b'}), ('invocations_latency_histogram', None, {'route_name': 'chat', 'model_name': 'b'}), ('fallbacks_triggered_counter', 1, {'route_name': 'chat', 'target': 'a', 'fallback': 'b'})],
        'logs': [('WARNING', f'Primary model a stream failed: {_err(500)}'), ('INFO', 'Trying fallback model b for streaming'), ('ERROR', 'Unhandled error during streaming')],
    },
    'responses_fallback': {
        'status': 200,
        'body': {'id': 'resp_golden_1', 'object': 'response', 'status': 'completed', 'model': 'chat', 'output': [{'type': 'reasoning', 'id': 'rs_golden_1', 'summary': [{'type': 'summary_text', 'text': 'Thinking.'}]}, {'type': 'message', 'id': 'msg_golden_1', 'status': 'completed', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': 'Hello from the model', 'annotations': []}]}], 'error': None, 'incomplete_details': None, 'instructions': None, 'metadata': {}, 'parallel_tool_calls': True, 'temperature': 1.0, 'top_p': 1.0, 'tool_choice': 'auto', 'tools': [], 'text': {'format': {'type': 'text'}}, 'usage': {'input_tokens': 21, 'input_tokens_details': {'cached_tokens': 4}, 'output_tokens': 7, 'output_tokens_details': {'reasoning_tokens': 3}, 'total_tokens': 28}},
        'upstream': ['https://api.openai.com/v1/responses', 'https://api.openai.com/v1/responses'],
        'events': [_invocation('b', 'chat-model'), _tokens('INPUT', 'b', 'chat-model', 17.0, '0.000017'), _tokens('INPUT', 'b', 'chat-model', 4.0, '0.0', cached=True, cache_type='read'), _tokens('OUTPUT', 'b', 'chat-model', 7.0, '0.000014'), _fallback('a', 'b')],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'chat', 'model_name': 'b'}), ('invocations_latency_histogram', None, {'route_name': 'chat', 'model_name': 'b'}), ('total_tokens_counter_input', 17, {'route_name': 'chat', 'model_name': 'b'}), ('total_tokens_counter_input', 4, {'route_name': 'chat', 'model_name': 'b'}), ('total_tokens_counter_output', 7, {'route_name': 'chat', 'model_name': 'b'}), ('fallbacks_triggered_counter', 1, {'route_name': 'chat', 'target': 'a', 'fallback': 'b'})],
        'logs': [('WARNING', f'Responses model a failed: {_err(500)}')],
    },
    'responses_exhausted_4xx': {
        'status': 429,
        'body': {'error': {'message': 'upstream says no', 'type': 'invalid_request_error', 'param': None, 'code': 'code_429'}},
        'upstream': ['https://api.openai.com/v1/responses', 'https://api.openai.com/v1/responses'],
        'events': [_invocation('b', 'chat-model'), _fallback('a', 'b')],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'chat', 'model_name': 'b'}), ('invocations_latency_histogram', None, {'route_name': 'chat', 'model_name': 'b'}), ('fallbacks_triggered_counter', 1, {'route_name': 'chat', 'target': 'a', 'fallback': 'b'})],
        'logs': [('WARNING', f'Responses model a failed: {_err(429)}'), ('WARNING', f'Responses model b failed: {_err(500)}'), ('WARNING', f'{_err(429)}')],
    },
    'responses_exhausted_5xx': {
        'status': 500,
        'body': {'error': {'message': f'All chat models failed for model chat: {_err(500)}', 'type': 'model_invoker_error', 'param': None, 'code': 'model_invoker_internal_error'}},
        'upstream': ['https://api.openai.com/v1/responses', 'https://api.openai.com/v1/responses'],
        'events': [_invocation('b', 'chat-model'), _fallback('a', 'b')],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'chat', 'model_name': 'b'}), ('invocations_latency_histogram', None, {'route_name': 'chat', 'model_name': 'b'}), ('fallbacks_triggered_counter', 1, {'route_name': 'chat', 'target': 'a', 'fallback': 'b'})],
        'logs': [('WARNING', f'Responses model a failed: {_err(500)}'), ('WARNING', f'Responses model b failed: {_err(429)}'), ('ERROR', f'All chat models failed for model chat: {_err(500)}')],
    },
    'responses_stream_fallback': {
        'status': 200,
        'body': None,
        'upstream': ['https://api.openai.com/v1/responses', 'https://api.openai.com/v1/responses'],
        'events': [_invocation('b', 'chat-model'), _tokens('INPUT', 'b', 'chat-model', 17.0, '0.000017'), _tokens('INPUT', 'b', 'chat-model', 4.0, '0.0', cached=True, cache_type='read'), _tokens('OUTPUT', 'b', 'chat-model', 7.0, '0.000014'), _fallback('a', 'b')],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'chat', 'model_name': 'b'}), ('invocations_latency_histogram', None, {'route_name': 'chat', 'model_name': 'b'}), ('total_tokens_counter_input', 17, {'route_name': 'chat', 'model_name': 'b'}), ('total_tokens_counter_input', 4, {'route_name': 'chat', 'model_name': 'b'}), ('total_tokens_counter_output', 7, {'route_name': 'chat', 'model_name': 'b'}), ('fallbacks_triggered_counter', 1, {'route_name': 'chat', 'target': 'a', 'fallback': 'b'})],
        'logs': [('WARNING', f'Responses model a failed: {_err(500)}')],
    },
    'responses_stream_exhausted': {
        'status': 429,
        'body': {'error': {'message': 'upstream says no', 'type': 'invalid_request_error', 'param': None, 'code': 'code_429'}},
        'upstream': ['https://api.openai.com/v1/responses', 'https://api.openai.com/v1/responses'],
        'events': [_invocation('b', 'chat-model'), _fallback('a', 'b')],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'chat', 'model_name': 'b'}), ('invocations_latency_histogram', None, {'route_name': 'chat', 'model_name': 'b'}), ('fallbacks_triggered_counter', 1, {'route_name': 'chat', 'target': 'a', 'fallback': 'b'})],
        'logs': [('WARNING', f'Responses model a failed: {_err(429)}'), ('WARNING', f'Responses model b failed: {_err(500)}')],
    },
    'embed_fallback': {
        'status': 200,
        'body': {'data': [{'embedding': [0.1, 0.11, 0.12, 0.13], 'index': 0, 'object': 'embedding'}, {'embedding': [0.2, 0.21, 0.22, 0.23], 'index': 1, 'object': 'embedding'}], 'model': 'text-embedding-3-large', 'object': 'list', 'usage': {'prompt_tokens': 2, 'total_tokens': 2}},
        'upstream': ['https://api.openai.com/v1/embeddings', 'https://api.openai.com/v1/embeddings'],
        'events': [_invocation('e2', 'embeddings'), _tokens('INPUT', 'e2', 'embeddings', 2.0, '0.000002'), _fallback('e1', 'e2')],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'embed', 'model_name': 'e2'}), ('invocations_latency_histogram', None, {'route_name': 'embed', 'model_name': 'e2'}), ('total_tokens_counter_input', 2, {'route_name': 'embed', 'model_name': 'e2'}), ('fallbacks_triggered_counter', 1, {'route_name': 'embed', 'target': 'e1', 'fallback': 'e2'})],
        'logs': [('WARNING', f'Primary embedding model e1 failed: {_err(500)}. Trying fallbacks...')],
    },
    'embed_exhausted': {
        'status': 500,
        'body': {'error': {'message': f'All embedding models failed for model embed: {_err(429)}', 'type': 'model_invoker_error', 'param': None, 'code': 'model_invoker_internal_error'}},
        'upstream': ['https://api.openai.com/v1/embeddings', 'https://api.openai.com/v1/embeddings'],
        'events': [_invocation('e2', 'embeddings'), _fallback('e1', 'e2')],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'embed', 'model_name': 'e2'}), ('invocations_latency_histogram', None, {'route_name': 'embed', 'model_name': 'e2'}), ('fallbacks_triggered_counter', 1, {'route_name': 'embed', 'target': 'e1', 'fallback': 'e2'})],
        'logs': [('WARNING', f'Primary embedding model e1 failed: {_err(429)}. Trying fallbacks...'), ('WARNING', f'Fallback embedding model text-embedding-3-large failed: {_err(500)}'), ('ERROR', 'All embedding models failed for route embed, model e1'), ('ERROR', f'All embedding models failed for model embed: {_err(429)}')],
    },
    'audio_fallback': {
        'status': 200,
        'body': {'text': 'hello', 'languages': None, 'logprobs': None, 'usage': {'input_tokens': 10, 'output_tokens': 3, 'total_tokens': 13, 'type': 'tokens', 'input_token_details': {'audio_tokens': 8, 'text_tokens': 2}}},
        'upstream': ['https://api.openai.com/v1/audio/transcriptions', 'https://api.openai.com/v1/audio/transcriptions'],
        'events': [_invocation('t2', 'transcription'), _fallback('t1', 't2'), _tokens('INPUT', 't2', 'transcription', 8.0, '0.00001', cache_type='audio'), _tokens('INPUT', 't2', 'transcription', 2.0, '0.000002'), _tokens('OUTPUT', 't2', 'transcription', 3.0, '0.000006')],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'audio', 'model_name': 't2'}), ('invocations_latency_histogram', None, {'route_name': 'audio', 'model_name': 't2'}), ('fallbacks_triggered_counter', 1, {'route_name': 'audio', 'target': 't1', 'fallback': 't2'}), ('total_tokens_counter_input', 8, {'route_name': 'audio', 'model_name': 't2'}), ('total_tokens_counter_input', 2, {'route_name': 'audio', 'model_name': 't2'}), ('total_tokens_counter_output', 3, {'route_name': 'audio', 'model_name': 't2'})],
        'logs': [('WARNING', f'Primary transcription model t1 failed: Transcription upstream call failed: {_err(500)}. Trying fallbacks...')],
    },
    'audio_exhausted': {
        'status': 500,
        'body': {'error': {'message': f'All transcription models failed for route audio: Transcription upstream call failed: {_err(500)}', 'type': 'model_invoker_error', 'param': None, 'code': 'model_invoker_internal_error'}},
        'upstream': ['https://api.openai.com/v1/audio/transcriptions', 'https://api.openai.com/v1/audio/transcriptions'],
        'events': [_invocation('t2', 'transcription'), _fallback('t1', 't2')],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'audio', 'model_name': 't2'}), ('invocations_latency_histogram', None, {'route_name': 'audio', 'model_name': 't2'}), ('fallbacks_triggered_counter', 1, {'route_name': 'audio', 'target': 't1', 'fallback': 't2'})],
        'logs': [('WARNING', f'Primary transcription model t1 failed: Transcription upstream call failed: {_err(500)}. Trying fallbacks...'), ('WARNING', f'Fallback transcription model t2 failed: Transcription upstream call failed: {_err(503)}'), ('ERROR', f'All transcription models failed for route audio: Transcription upstream call failed: {_err(500)}')],
    },
    'audio_rejected': {
        'status': 400,
        'body': {'error': {'message': f'Transcription request rejected by upstream provider: {_err(400)}', 'type': 'model_invoker_error', 'param': None, 'code': 'model_invoker_bad_request'}},
        'upstream': ['https://api.openai.com/v1/audio/transcriptions'],
        'events': [_invocation('t1', 'transcription')],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'audio', 'model_name': 't1'}), ('invocations_latency_histogram', None, {'route_name': 'audio', 'model_name': 't1'})],
        'logs': [('WARNING', f'Transcription request rejected by upstream provider: {_err(400)}')],
    },
    'audio_stream_fallback': {
        'status': 200,
        'body': None,
        'upstream': ['https://api.openai.com/v1/audio/transcriptions', 'https://api.openai.com/v1/audio/transcriptions'],
        'events': [_invocation('t2', 'transcription'), _fallback('t1', 't2'), _tokens('INPUT', 't2', 'transcription', 8.0, '0.00001', cache_type='audio'), _tokens('INPUT', 't2', 'transcription', 2.0, '0.000002'), _tokens('OUTPUT', 't2', 'transcription', 3.0, '0.000006')],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'audio', 'model_name': 't2'}), ('invocations_latency_histogram', None, {'route_name': 'audio', 'model_name': 't2'}), ('fallbacks_triggered_counter', 1, {'route_name': 'audio', 'target': 't1', 'fallback': 't2'}), ('total_tokens_counter_input', 8, {'route_name': 'audio', 'model_name': 't2'}), ('total_tokens_counter_input', 2, {'route_name': 'audio', 'model_name': 't2'}), ('total_tokens_counter_output', 3, {'route_name': 'audio', 'model_name': 't2'})],
        'logs': [('WARNING', f'Primary transcription model t1 stream failed: Transcription upstream call failed: {_err(500)}. Trying fallbacks...')],
    },
    'audio_stream_exhausted': {
        'status': 500,
        'body': {'error': {'message': f'All transcription models failed for streaming audio: Transcription upstream call failed: {_err(500)}', 'type': 'model_invoker_error', 'param': None, 'code': 500}},
        'upstream': ['https://api.openai.com/v1/audio/transcriptions', 'https://api.openai.com/v1/audio/transcriptions'],
        'events': [_invocation('t2', 'transcription'), _fallback('t1', 't2')],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'audio', 'model_name': 't2'}), ('invocations_latency_histogram', None, {'route_name': 'audio', 'model_name': 't2'}), ('fallbacks_triggered_counter', 1, {'route_name': 'audio', 'target': 't1', 'fallback': 't2'})],
        'logs': [('WARNING', f'Primary transcription model t1 stream failed: Transcription upstream call failed: {_err(500)}. Trying fallbacks...'), ('WARNING', f'Fallback transcription model t2 stream failed: Transcription upstream call failed: {_err(503)}')],
    },
    'decision_fallback': {
        'status': 200,
        'body': {'answers': {'decision_judge': {'type': 'noul', 'noul': 0.1}}, 'model': 'd2', 'usage': {'input_tokens': 40, 'output_tokens': 2}},
        'upstream': ['https://api.typesafe.ai/v1/systemone', 'https://api.typesafe.ai/v1/systemone', 'https://api.typesafe.ai/v1/systemone'],
        'events': [_invocation('d2', 'decision_model'), _tokens('INPUT', 'd2', 'decision_model', 40.0, '0.00012'), _tokens('OUTPUT', 'd2', 'decision_model', 0.0, '0.0'), _fallback('d1', 'd2')],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'agent', 'model_name': 'd2'}), ('invocations_latency_histogram', None, {'route_name': 'agent', 'model_name': 'd2'}), ('total_tokens_counter_input', 40, {'route_name': 'agent', 'model_name': 'd2'}), ('total_tokens_counter_output', 0, {'route_name': 'agent', 'model_name': 'd2'}), ('fallbacks_triggered_counter', 1, {'route_name': 'agent', 'target': 'd1', 'fallback': 'd2'})],
        'logs': [('WARNING', 'Decision model d1 returned 503'), ('WARNING', 'Decision model d1 returned 503'), ('WARNING', 'Decision model d1 failed. Falling back to d2')],
    },
    'decision_exhausted': {
        'status': 503,
        'body': {'error': 'typesafe 503'},
        'upstream': ['https://api.typesafe.ai/v1/systemone', 'https://api.typesafe.ai/v1/systemone', 'https://api.typesafe.ai/v1/systemone'],
        'events': [_invocation('d2', 'decision_model'), _fallback('d1', 'd2')],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'agent', 'model_name': 'd2'}), ('invocations_latency_histogram', None, {'route_name': 'agent', 'model_name': 'd2'}), ('fallbacks_triggered_counter', 1, {'route_name': 'agent', 'target': 'd1', 'fallback': 'd2'})],
        'logs': [('WARNING', 'Decision model d1 returned 503'), ('WARNING', 'Decision model d1 returned 429'), ('WARNING', 'Decision model d1 failed. Falling back to d2'), ('WARNING', 'Decision model d2 returned 503')],
    },
    'decision_rejected': {
        'status': 400,
        'body': {'error': 'typesafe 400'},
        'upstream': ['https://api.typesafe.ai/v1/systemone'],
        'events': [_invocation('d1', 'decision_model')],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'agent', 'model_name': 'd1'}), ('invocations_latency_histogram', None, {'route_name': 'agent', 'model_name': 'd1'})],
        'logs': [],
    },
    'judge_fallback': {
        'status': 200,
        'body': {'id': '00000000-0000-0000-0000-000000000000', 'choices': [{'finish_reason': 'stop', 'index': 0, 'logprobs': None, 'message': {'content': 'Paris is in France', 'refusal': None, 'role': 'assistant', 'annotations': None, 'audio': None, 'function_call': None, 'tool_calls': None}}], 'model': 'judged', 'object': 'chat.completion', 'metadata': None, 'moderation': None, 'service_tier': None, 'system_fingerprint': None, 'usage': {'completion_tokens': 5, 'prompt_tokens': 11, 'total_tokens': 16, 'completion_tokens_details': None, 'prompt_tokens_details': None}},
        'upstream': ['https://api.openai.com/v1/chat/completions', 'https://api.openai.com/v1/chat/completions', 'https://api.openai.com/v1/chat/completions'],
        'events': [_fallback('j1', 'j2', judge=True), _tokens('INPUT', 'j2', 'chat-model', 30.0, '0.00003', judge=True), _tokens('OUTPUT', 'j2', 'chat-model', 4.0, '0.000008', judge=True), _invocation('a', 'chat-model'), _tokens('INPUT', 'a', 'chat-model', 11.0, '0.000011'), _tokens('OUTPUT', 'a', 'chat-model', 5.0, '0.00001')],
        'metrics': [('fallbacks_triggered_counter', 1, {'route_name': 'judged', 'target': 'j1', 'fallback': 'j2'}), ('invocations_latency_histogram', None, {'route_name': 'judged', 'model_name': 'j2'}), ('total_tokens_counter_input', 30, {'route_name': 'judged', 'model_name': 'j2'}), ('total_tokens_counter_output', 4, {'route_name': 'judged', 'model_name': 'j2'}), ('model_invocations_counter', 1, {'route_name': 'judged', 'model_name': 'a'}), ('invocations_latency_histogram', None, {'route_name': 'judged', 'model_name': 'a'}), ('total_tokens_counter_input', 11, {'route_name': 'judged', 'model_name': 'a'}), ('total_tokens_counter_output', 5, {'route_name': 'judged', 'model_name': 'a'})],
        'logs': [('WARNING', f'Primary model failed with unexpected error: {_err(500)}'), ('INFO', 'Attempting fallback model j2 after primary model j1 failed')],
    },
    'judge_bad_answer': {
        'status': 200,
        'body': {'id': '00000000-0000-0000-0000-000000000000', 'choices': [{'finish_reason': 'stop', 'index': 0, 'logprobs': None, 'message': {'content': 'Paris is in France', 'refusal': None, 'role': 'assistant', 'annotations': None, 'audio': None, 'function_call': None, 'tool_calls': None}}], 'model': 'judged', 'object': 'chat.completion', 'metadata': None, 'moderation': None, 'service_tier': None, 'system_fingerprint': None, 'usage': {'completion_tokens': 5, 'prompt_tokens': 11, 'total_tokens': 16, 'completion_tokens_details': None, 'prompt_tokens_details': None}},
        'upstream': ['https://api.openai.com/v1/chat/completions', 'https://api.openai.com/v1/chat/completions', 'https://api.openai.com/v1/chat/completions'],
        'events': [_fallback('j1', 'j2', judge=True), _tokens('INPUT', 'j2', 'chat-model', 30.0, '0.00003', judge=True), _tokens('OUTPUT', 'j2', 'chat-model', 4.0, '0.000008', judge=True), _invocation('a', 'chat-model'), _tokens('INPUT', 'a', 'chat-model', 11.0, '0.000011'), _tokens('OUTPUT', 'a', 'chat-model', 5.0, '0.00001')],
        'metrics': [('fallbacks_triggered_counter', 1, {'route_name': 'judged', 'target': 'j1', 'fallback': 'j2'}), ('invocations_latency_histogram', None, {'route_name': 'judged', 'model_name': 'j2'}), ('total_tokens_counter_input', 30, {'route_name': 'judged', 'model_name': 'j2'}), ('total_tokens_counter_output', 4, {'route_name': 'judged', 'model_name': 'j2'}), ('model_invocations_counter', 1, {'route_name': 'judged', 'model_name': 'a'}), ('invocations_latency_histogram', None, {'route_name': 'judged', 'model_name': 'a'}), ('total_tokens_counter_input', 11, {'route_name': 'judged', 'model_name': 'a'}), ('total_tokens_counter_output', 5, {'route_name': 'judged', 'model_name': 'a'})],
        'logs': [('WARNING', "Primary model failed with unexpected error: 1 validation error for JudgeResult\ntriggered\n  Field required [type=missing, input_value={'nonsense': True}, input_type=dict]\n    For further information visit https://errors.pydantic.dev/2.13/v/missing"), ('INFO', 'Attempting fallback model j2 after primary model j1 failed')],
    },
    'judge_exhausted': {
        'status': 500,
        'body': {'error': {'message': 'Both primary and fallback judge models failed', 'type': 'judge_internal_error', 'param': None, 'code': 'judge_internal_error'}},
        'upstream': ['https://api.openai.com/v1/chat/completions', 'https://api.openai.com/v1/chat/completions'],
        'events': [_invocation('j2', 'chat-model', judge=True), _fallback('j1', 'j2', judge=True)],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'judged', 'model_name': 'j2'}), ('invocations_latency_histogram', None, {'route_name': 'judged', 'model_name': 'j2'}), ('fallbacks_triggered_counter', 1, {'route_name': 'judged', 'target': 'j1', 'fallback': 'j2'})],
        'logs': [('WARNING', f'Primary model failed with unexpected error: {_err(500)}'), ('INFO', 'Attempting fallback model j2 after primary model j1 failed'), ('ERROR', f'Both primary and fallback models failed: {_err(500)} | {_err(429)}'), ('ERROR', f'Judge communication error: Both primary and fallback models failed: primary={_err(500)}, fallback={_err(429)}'), ('ERROR', f'Error applying guardrail judge: Both primary and fallback models failed: primary={_err(500)}, fallback={_err(429)}'), ('ERROR', f'Both primary and fallback models failed: primary={_err(500)}, fallback={_err(429)}')],
    },
    'judge_exhausted_bad_answer': {
        'status': 500,
        'body': {'error': {'message': 'Both primary and fallback judge models failed', 'type': 'judge_internal_error', 'param': None, 'code': 'judge_internal_error'}},
        'upstream': ['https://api.openai.com/v1/chat/completions', 'https://api.openai.com/v1/chat/completions'],
        'events': [_invocation('j2', 'chat-model', judge=True), _fallback('j1', 'j2', judge=True)],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'judged', 'model_name': 'j2'}), ('invocations_latency_histogram', None, {'route_name': 'judged', 'model_name': 'j2'}), ('fallbacks_triggered_counter', 1, {'route_name': 'judged', 'target': 'j1', 'fallback': 'j2'})],
        'logs': [('WARNING', f'Primary model failed with unexpected error: {_err(500)}'), ('INFO', 'Attempting fallback model j2 after primary model j1 failed'), ('ERROR', f"Both primary and fallback models failed: {_err(500)} | 1 validation error for JudgeResult\ntriggered\n  Field required [type=missing, input_value={{'nonsense': True}}, input_type=dict]\n    For further information visit https://errors.pydantic.dev/2.13/v/missing"), ('ERROR', f"Judge communication error: Both primary and fallback models failed: primary={_err(500)}, fallback=1 validation error for JudgeResult\ntriggered\n  Field required [type=missing, input_value={{'nonsense': True}}, input_type=dict]\n    For further information visit https://errors.pydantic.dev/2.13/v/missing"), ('ERROR', f"Error applying guardrail judge: Both primary and fallback models failed: primary={_err(500)}, fallback=1 validation error for JudgeResult\ntriggered\n  Field required [type=missing, input_value={{'nonsense': True}}, input_type=dict]\n    For further information visit https://errors.pydantic.dev/2.13/v/missing"), ('ERROR', f"Both primary and fallback models failed: primary={_err(500)}, fallback=1 validation error for JudgeResult\ntriggered\n  Field required [type=missing, input_value={{'nonsense': True}}, input_type=dict]\n    For further information visit https://errors.pydantic.dev/2.13/v/missing")],
    },
    'djudge_fallback': {
        'status': 200,
        'body': {'id': '00000000-0000-0000-0000-000000000000', 'choices': [{'finish_reason': 'stop', 'index': 0, 'logprobs': None, 'message': {'content': 'Paris is in France', 'refusal': None, 'role': 'assistant', 'annotations': None, 'audio': None, 'function_call': None, 'tool_calls': None}}], 'model': 'djudged', 'object': 'chat.completion', 'metadata': None, 'moderation': None, 'service_tier': None, 'system_fingerprint': None, 'usage': {'completion_tokens': 5, 'prompt_tokens': 11, 'total_tokens': 16, 'completion_tokens_details': None, 'prompt_tokens_details': None}},
        'upstream': ['https://api.typesafe.ai/v1/systemone', 'https://api.typesafe.ai/v1/systemone', 'https://api.typesafe.ai/v1/systemone', 'https://api.openai.com/v1/chat/completions'],
        'events': [_invocation('d2', 'decision_model', judge=True), _tokens('INPUT', 'd2', 'decision_model', 40.0, '0.00012', judge=True), _tokens('OUTPUT', 'd2', 'decision_model', 0.0, '0.0', judge=True), _fallback('d1', 'd2', judge=True), _invocation('a', 'chat-model'), _tokens('INPUT', 'a', 'chat-model', 11.0, '0.000011'), _tokens('OUTPUT', 'a', 'chat-model', 5.0, '0.00001')],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'djudged', 'model_name': 'd2'}), ('invocations_latency_histogram', None, {'route_name': 'djudged', 'model_name': 'd2'}), ('total_tokens_counter_input', 40, {'route_name': 'djudged', 'model_name': 'd2'}), ('total_tokens_counter_output', 0, {'route_name': 'djudged', 'model_name': 'd2'}), ('fallbacks_triggered_counter', 1, {'route_name': 'djudged', 'target': 'd1', 'fallback': 'd2'}), ('model_invocations_counter', 1, {'route_name': 'djudged', 'model_name': 'a'}), ('invocations_latency_histogram', None, {'route_name': 'djudged', 'model_name': 'a'}), ('total_tokens_counter_input', 11, {'route_name': 'djudged', 'model_name': 'a'}), ('total_tokens_counter_output', 5, {'route_name': 'djudged', 'model_name': 'a'})],
        'logs': [('WARNING', 'Decision model d1 returned 503'), ('WARNING', 'Decision model d1 returned 503'), ('ERROR', 'Decision judge on model d1 failed: Typesafe returned 503'), ('WARNING', 'Decision judge falls back from model d1 to model d2'), ('INFO', 'Decision judge on route=djudged: noul=0.1, threshold=0.5, triggered=False')],
    },
    'djudge_exhausted': {
        'status': 500,
        'body': {'error': {'message': 'Decision judge failed', 'type': 'judge_internal_error', 'param': None, 'code': 'judge_internal_error'}},
        'upstream': ['https://api.typesafe.ai/v1/systemone', 'https://api.typesafe.ai/v1/systemone', 'https://api.typesafe.ai/v1/systemone'],
        'events': [_invocation('d2', 'decision_model', judge=True), _fallback('d1', 'd2', judge=True)],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'djudged', 'model_name': 'd2'}), ('invocations_latency_histogram', None, {'route_name': 'djudged', 'model_name': 'd2'}), ('fallbacks_triggered_counter', 1, {'route_name': 'djudged', 'target': 'd1', 'fallback': 'd2'})],
        'logs': [('WARNING', 'Decision model d1 returned 503'), ('WARNING', 'Decision model d1 returned 503'), ('ERROR', 'Decision judge on model d1 failed: Typesafe returned 503'), ('WARNING', 'Decision judge falls back from model d1 to model d2'), ('WARNING', 'Decision model d2 returned 500'), ('ERROR', 'Decision judge on model d2 failed: Typesafe returned 500'), ('ERROR', 'Error applying guardrail djudge: Decision judge on model d2 failed: Typesafe returned 500'), ('ERROR', 'Decision judge on model d2 failed: Typesafe returned 500')],
    },
    'djudge_rejected': {
        'status': 500,
        'body': {'error': {'message': 'Decision judge failed', 'type': 'judge_internal_error', 'param': None, 'code': 'judge_internal_error'}},
        'upstream': ['https://api.typesafe.ai/v1/systemone'],
        'events': [_invocation('d1', 'decision_model', judge=True)],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'djudged', 'model_name': 'd1'}), ('invocations_latency_histogram', None, {'route_name': 'djudged', 'model_name': 'd1'})],
        'logs': [('ERROR', 'Decision judge on model d1 failed: Typesafe returned 400'), ('ERROR', 'Error applying guardrail djudge: Decision judge on model d1 failed: Typesafe returned 400'), ('ERROR', 'Decision judge on model d1 failed: Typesafe returned 400')],
    },
    'djudge_bad_answer': {
        'status': 200,
        'body': {'id': '00000000-0000-0000-0000-000000000000', 'choices': [{'finish_reason': 'stop', 'index': 0, 'logprobs': None, 'message': {'content': 'Paris is in France', 'refusal': None, 'role': 'assistant', 'annotations': None, 'audio': None, 'function_call': None, 'tool_calls': None}}], 'model': 'djudged', 'object': 'chat.completion', 'metadata': None, 'moderation': None, 'service_tier': None, 'system_fingerprint': None, 'usage': {'completion_tokens': 5, 'prompt_tokens': 11, 'total_tokens': 16, 'completion_tokens_details': None, 'prompt_tokens_details': None}},
        'upstream': ['https://api.typesafe.ai/v1/systemone', 'https://api.typesafe.ai/v1/systemone', 'https://api.openai.com/v1/chat/completions'],
        'events': [_invocation('d1', 'decision_model', judge=True), _tokens('INPUT', 'd1', 'decision_model', 40.0, '0.00012', judge=True), _tokens('OUTPUT', 'd1', 'decision_model', 0.0, '0.0', judge=True), _invocation('d2', 'decision_model', judge=True), _tokens('INPUT', 'd2', 'decision_model', 40.0, '0.00012', judge=True), _tokens('OUTPUT', 'd2', 'decision_model', 0.0, '0.0', judge=True), _fallback('d1', 'd2', judge=True), _invocation('a', 'chat-model'), _tokens('INPUT', 'a', 'chat-model', 11.0, '0.000011'), _tokens('OUTPUT', 'a', 'chat-model', 5.0, '0.00001')],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'djudged', 'model_name': 'd1'}), ('invocations_latency_histogram', None, {'route_name': 'djudged', 'model_name': 'd1'}), ('total_tokens_counter_input', 40, {'route_name': 'djudged', 'model_name': 'd1'}), ('total_tokens_counter_output', 0, {'route_name': 'djudged', 'model_name': 'd1'}), ('model_invocations_counter', 1, {'route_name': 'djudged', 'model_name': 'd2'}), ('invocations_latency_histogram', None, {'route_name': 'djudged', 'model_name': 'd2'}), ('total_tokens_counter_input', 40, {'route_name': 'djudged', 'model_name': 'd2'}), ('total_tokens_counter_output', 0, {'route_name': 'djudged', 'model_name': 'd2'}), ('fallbacks_triggered_counter', 1, {'route_name': 'djudged', 'target': 'd1', 'fallback': 'd2'}), ('model_invocations_counter', 1, {'route_name': 'djudged', 'model_name': 'a'}), ('invocations_latency_histogram', None, {'route_name': 'djudged', 'model_name': 'a'}), ('total_tokens_counter_input', 11, {'route_name': 'djudged', 'model_name': 'a'}), ('total_tokens_counter_output', 5, {'route_name': 'djudged', 'model_name': 'a'})],
        'logs': [('ERROR', 'Decision judge on model d1 failed: the answer has no noul'), ('WARNING', 'Decision judge falls back from model d1 to model d2'), ('INFO', 'Decision judge on route=djudged: noul=0.1, threshold=0.5, triggered=False')],
    },
    'llm_router_fallback': {
        'status': 200,
        'body': {'id': '00000000-0000-0000-0000-000000000000', 'choices': [{'finish_reason': 'stop', 'index': 0, 'logprobs': None, 'message': {'content': 'Paris is in France', 'refusal': None, 'role': 'assistant', 'annotations': None, 'audio': None, 'function_call': None, 'tool_calls': None}}], 'model': 'llm-routed', 'object': 'chat.completion', 'metadata': None, 'moderation': None, 'service_tier': None, 'system_fingerprint': None, 'usage': {'completion_tokens': 5, 'prompt_tokens': 11, 'total_tokens': 16, 'completion_tokens_details': None, 'prompt_tokens_details': None}},
        'upstream': ['https://api.openai.com/v1/chat/completions', 'https://api.openai.com/v1/chat/completions', 'https://api.openai.com/v1/chat/completions'],
        'events': [_invocation('r2', 'chat-model', routing=True), _tokens('INPUT', 'r2', 'chat-model', 30.0, '0.00003', routing=True), _tokens('OUTPUT', 'r2', 'chat-model', 4.0, '0.000008', routing=True), _fallback('r1', 'r2', routing=True), _invocation('a', 'chat-model'), _tokens('INPUT', 'a', 'chat-model', 11.0, '0.000011'), _tokens('OUTPUT', 'a', 'chat-model', 5.0, '0.00001')],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'llm-routed', 'model_name': 'r2'}), ('invocations_latency_histogram', None, {'route_name': 'llm-routed', 'model_name': 'r2'}), ('total_tokens_counter_input', 30, {'route_name': 'llm-routed', 'model_name': 'r2'}), ('total_tokens_counter_output', 4, {'route_name': 'llm-routed', 'model_name': 'r2'}), ('fallbacks_triggered_counter', 1, {'route_name': 'llm-routed', 'target': 'r1', 'fallback': 'r2'}), ('model_invocations_counter', 1, {'route_name': 'llm-routed', 'model_name': 'a'}), ('invocations_latency_histogram', None, {'route_name': 'llm-routed', 'model_name': 'a'}), ('total_tokens_counter_input', 11, {'route_name': 'llm-routed', 'model_name': 'a'}), ('total_tokens_counter_output', 5, {'route_name': 'llm-routed', 'model_name': 'a'})],
        'logs': [('WARNING', 'LLM routing model r1 failed'), ('WARNING', 'LLM routing falls back from model r1 to model r2')],
    },
    'llm_router_exhausted': {
        'status': 200,
        'body': {'id': '00000000-0000-0000-0000-000000000000', 'choices': [{'finish_reason': 'stop', 'index': 0, 'logprobs': None, 'message': {'content': 'Paris is in France', 'refusal': None, 'role': 'assistant', 'annotations': None, 'audio': None, 'function_call': None, 'tool_calls': None}}], 'model': 'llm-routed', 'object': 'chat.completion', 'metadata': None, 'moderation': None, 'service_tier': None, 'system_fingerprint': None, 'usage': {'completion_tokens': 5, 'prompt_tokens': 11, 'total_tokens': 16, 'completion_tokens_details': None, 'prompt_tokens_details': None}},
        'upstream': ['https://api.openai.com/v1/chat/completions', 'https://api.openai.com/v1/chat/completions', 'https://api.openai.com/v1/chat/completions'],
        'events': [_invocation('r2', 'chat-model', routing=True), _fallback('r1', 'r2', routing=True), _invocation('a', 'chat-model'), _tokens('INPUT', 'a', 'chat-model', 11.0, '0.000011'), _tokens('OUTPUT', 'a', 'chat-model', 5.0, '0.00001')],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'llm-routed', 'model_name': 'r2'}), ('invocations_latency_histogram', None, {'route_name': 'llm-routed', 'model_name': 'r2'}), ('fallbacks_triggered_counter', 1, {'route_name': 'llm-routed', 'target': 'r1', 'fallback': 'r2'}), ('model_invocations_counter', 1, {'route_name': 'llm-routed', 'model_name': 'a'}), ('invocations_latency_histogram', None, {'route_name': 'llm-routed', 'model_name': 'a'}), ('total_tokens_counter_input', 11, {'route_name': 'llm-routed', 'model_name': 'a'}), ('total_tokens_counter_output', 5, {'route_name': 'llm-routed', 'model_name': 'a'})],
        'logs': [('WARNING', 'LLM routing model r1 failed'), ('WARNING', 'LLM routing falls back from model r1 to model r2'), ('WARNING', 'LLM routing model r2 failed'), ('INFO', 'LLM routing uses the default model: error')],
    },
    'decision_router_fallback': {
        'status': 200,
        'body': {'id': '00000000-0000-0000-0000-000000000000', 'choices': [{'finish_reason': 'stop', 'index': 0, 'logprobs': None, 'message': {'content': 'Paris is in France', 'refusal': None, 'role': 'assistant', 'annotations': None, 'audio': None, 'function_call': None, 'tool_calls': None}}], 'model': 'decision-routed', 'object': 'chat.completion', 'metadata': None, 'moderation': None, 'service_tier': None, 'system_fingerprint': None, 'usage': {'completion_tokens': 5, 'prompt_tokens': 11, 'total_tokens': 16, 'completion_tokens_details': None, 'prompt_tokens_details': None}},
        'upstream': ['https://api.typesafe.ai/v1/systemone', 'https://api.typesafe.ai/v1/systemone', 'https://api.typesafe.ai/v1/systemone', 'https://api.openai.com/v1/chat/completions'],
        'events': [_invocation('d2', 'decision_model', routing=True), _tokens('INPUT', 'd2', 'decision_model', 40.0, '0.00012', routing=True), _fallback('d1', 'd2', routing=True), _invocation('b', 'chat-model'), _tokens('INPUT', 'b', 'chat-model', 11.0, '0.000011'), _tokens('OUTPUT', 'b', 'chat-model', 5.0, '0.00001')],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'decision-routed', 'model_name': 'd2'}), ('invocations_latency_histogram', None, {'route_name': 'decision-routed', 'model_name': 'd2'}), ('total_tokens_counter_input', 40, {'route_name': 'decision-routed', 'model_name': 'd2'}), ('fallbacks_triggered_counter', 1, {'route_name': 'decision-routed', 'target': 'd1', 'fallback': 'd2'}), ('model_invocations_counter', 1, {'route_name': 'decision-routed', 'model_name': 'b'}), ('invocations_latency_histogram', None, {'route_name': 'decision-routed', 'model_name': 'b'}), ('total_tokens_counter_input', 11, {'route_name': 'decision-routed', 'model_name': 'b'}), ('total_tokens_counter_output', 5, {'route_name': 'decision-routed', 'model_name': 'b'})],
        'logs': [('WARNING', 'Decision model d1 returned 503'), ('WARNING', 'Decision model d1 returned 503'), ('WARNING', 'Decision routing model d1: Typesafe returned 503'), ('WARNING', 'Decision routing falls back from model d1 to model d2')],
    },
    'decision_router_exhausted': {
        'status': 200,
        'body': {'id': '00000000-0000-0000-0000-000000000000', 'choices': [{'finish_reason': 'stop', 'index': 0, 'logprobs': None, 'message': {'content': 'Paris is in France', 'refusal': None, 'role': 'assistant', 'annotations': None, 'audio': None, 'function_call': None, 'tool_calls': None}}], 'model': 'decision-routed', 'object': 'chat.completion', 'metadata': None, 'moderation': None, 'service_tier': None, 'system_fingerprint': None, 'usage': {'completion_tokens': 5, 'prompt_tokens': 11, 'total_tokens': 16, 'completion_tokens_details': None, 'prompt_tokens_details': None}},
        'upstream': ['https://api.typesafe.ai/v1/systemone', 'https://api.typesafe.ai/v1/systemone', 'https://api.typesafe.ai/v1/systemone', 'https://api.openai.com/v1/chat/completions'],
        'events': [_invocation('d2', 'decision_model', routing=True), _fallback('d1', 'd2', routing=True), _invocation('a', 'chat-model'), _tokens('INPUT', 'a', 'chat-model', 11.0, '0.000011'), _tokens('OUTPUT', 'a', 'chat-model', 5.0, '0.00001')],
        'metrics': [('model_invocations_counter', 1, {'route_name': 'decision-routed', 'model_name': 'd2'}), ('invocations_latency_histogram', None, {'route_name': 'decision-routed', 'model_name': 'd2'}), ('fallbacks_triggered_counter', 1, {'route_name': 'decision-routed', 'target': 'd1', 'fallback': 'd2'}), ('model_invocations_counter', 1, {'route_name': 'decision-routed', 'model_name': 'a'}), ('invocations_latency_histogram', None, {'route_name': 'decision-routed', 'model_name': 'a'}), ('total_tokens_counter_input', 11, {'route_name': 'decision-routed', 'model_name': 'a'}), ('total_tokens_counter_output', 5, {'route_name': 'decision-routed', 'model_name': 'a'})],
        'logs': [('WARNING', 'Decision model d1 returned 503'), ('WARNING', 'Decision model d1 returned 503'), ('WARNING', 'Decision routing model d1: Typesafe returned 503'), ('WARNING', 'Decision routing falls back from model d1 to model d2'), ('WARNING', 'Decision model d2 returned 500'), ('WARNING', 'Decision routing model d2: Typesafe returned 500'), ('INFO', 'Decision routing uses the default model: error')],
    },
}
# fmt: on


@pytest.mark.parametrize('name', list(SCENARIOS))
@pytest.mark.filterwarnings('ignore:Pydantic serializer warnings')  # broken chunks
async def test_golden(gateway, name):
    response = SCENARIOS[name](gateway)

    assert _snapshot(gateway, response) == EXPECTED[name]
