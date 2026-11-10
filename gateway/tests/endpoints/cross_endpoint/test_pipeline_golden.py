"""Golden values of the request path: what must not change when the code does.

Every endpoint is driven through the HTTP app on real routes, with the
providers faked at the transport. Compared with literals: the status code, the
body, the gateway's headers, the upstream calls in the order they are made,
the events, the request event, the HTTP metrics' route label, the route the
log lines are filtered on, and the trace spans. The scenarios are the ones the
other golden files leave open: what runs before a limit or a soft block
stops a request, the headers of every soft block, membership, the limits of a
streamed transcription. Only the drivers (the functions that build the routes,
send the requests and read what they caused) may change.
"""

import json
import re

import pytest

from tests.common import provider_responses as upstream
from tests.common.audio import make_wav_bytes
from tests.common.gateway_harness import Gateway, build_routes, open_gateway
from tests.common.limits import consumed
from tests.common.provider_recorder import CannedResponse

from radicalbit_ai_gateway import server
from radicalbit_ai_gateway.limiting.windows import Category

CREDENTIALS = {'api_key': 'sk-test'}
LONG_WAV = make_wav_bytes(2.0)


def _priced(model_id: str, name: str) -> dict:
    return {
        'model_id': model_id,
        'model': name,
        'credentials': CREDENTIALS,
        'input_cost_per_million_tokens': 1,
        'output_cost_per_million_tokens': 2,
    }


def _contains(name: str, where: str, behavior: str, value: str) -> dict:
    return {
        'name': name,
        'type': 'contains',
        'where': where,
        'behavior': behavior,
        'parameters': {'values': [value]},
    }


INPUT_GUARDRAILS = ['warn_in', 'judge', 'soft_in']
INPUT_LIMIT = {'input': {'window_size': '1 minute', 'max_token': 3}}
ROOMY_LIMIT = {'input': {'window_size': '1 minute', 'max_token': 1000}}

CONFIG = {
    'chat_models': [
        _priced('a', 'openai/gpt-a'),
        _priced('b', 'openai/gpt-b'),
        _priced('j1', 'openai/gpt-j1'),
        _priced('r1', 'openai/gpt-r1'),
    ],
    'embedding_models': [_priced('e1', 'openai/text-embedding-3-small')],
    'transcription_models': [_priced('t1', 'openai/gpt-4o-transcribe')],
    'decision_models': [
        {
            'model_id': 'd1',
            'model': 'typesafe/jev-latest',
            'credentials': {'api_key': 'ts-test'},
            'input_cost_per_million_tokens': 3,
        }
    ],
    'guardrails': [
        _contains('warn_in', 'input', 'warn', 'warnme'),
        _contains('soft_in', 'input', 'soft_block', 'softme'),
        _contains('soft_out', 'output', 'soft_block', 'softout'),
        _contains('block_out', 'output', 'block', 'blockout'),
        {
            'name': 'judge',
            'type': 'judge',
            'where': 'input',
            'behavior': 'block',
            'parameters': {'model_id': 'j1', 'prompt': 'Judge this.'},
        },
    ],
    'routing': [
        {
            'name': 'by-llm',
            'type': 'llm',
            'router_model_id': 'r1',
            'default_model_id': 'a',
            'output_mapping': [
                {'model_id': 'a', 'description': 'Questions about geography'},
                {'model_id': 'b', 'description': 'Questions about code'},
            ],
        }
    ],
    'routes': {
        'chat': {
            'chat_models': ['a', 'b'],
            'routing': 'by-llm',
            'guardrails': INPUT_GUARDRAILS,
        },
        'limited': {
            'chat_models': ['a', 'b'],
            'routing': 'by-llm',
            'guardrails': INPUT_GUARDRAILS,
            'token_limiting': INPUT_LIMIT,
        },
        'output': {
            'chat_models': ['a'],
            'guardrails': ['warn_in', 'soft_in', 'soft_out'],
        },
        'embed': {'embedding_models': ['e1'], 'guardrails': ['warn_in', 'soft_in']},
        'embed_limited': {'embedding_models': ['e1'], 'token_limiting': INPUT_LIMIT},
        'audio': {'transcription_models': ['t1']},
        'audio_limited': {
            'transcription_models': ['t1'],
            'duration_limiting': {
                'window_size': '1 minute',
                'max_duration_seconds': 1,
            },
        },
        'agent': {'decision_models': ['d1'], 'guardrails': ['warn_in', 'soft_in']},
        # Limits that let every request through: their checks show in traces.
        'chat_metered': {'chat_models': ['a'], 'token_limiting': ROOMY_LIMIT},
        'embed_metered': {'embedding_models': ['e1'], 'token_limiting': ROOMY_LIMIT},
        'audio_metered': {
            'transcription_models': ['t1'],
            'duration_limiting': {
                'window_size': '1 minute',
                'max_duration_seconds': 60,
            },
        },
        'agent_metered': {'decision_models': ['d1'], 'token_limiting': ROOMY_LIMIT},
        'output_metered': {
            'chat_models': ['a'],
            'guardrails': ['soft_out', 'block_out'],
            'token_limiting': ROOMY_LIMIT,
        },
    },
}


@pytest.fixture
def gateway(caplog):
    with open_gateway(build_routes(CONFIG), caplog=caplog) as gateway:
        yield gateway


def _upstream_call(request: dict) -> str:
    """Return a provider call as the URL path and the model it asks."""
    body = request['body'] if isinstance(request['body'], dict) else {}
    path = request['url'].split('://', 1)[1]
    return f'{path} {body.get("model", "")}'.strip()


def _event(e: dict) -> tuple:
    kind = e['EVENT_TYPE'].name
    if kind == 'GUARDRAIL':
        return (
            kind,
            e['GUARDRAIL_NAME'],
            e['GUARDRAIL_WHERE'],
            e['GUARDRAIL_BEHAVIOR'],
        )
    if kind == 'ROUTING':
        return (kind, e['ROUTING_SELECTED_MODEL_ID'])
    if e.get('MODEL_ID'):
        return (kind, e['MODEL_ID'], e['IS_JUDGE'], e['IS_ROUTING'])
    return (kind,)


def _body(response):
    text = re.sub(r'msg_[0-9a-f]{32}', 'msg_*', response.text)
    try:
        body = json.loads(text)
    except ValueError:
        return _frames(text)
    if isinstance(body, dict):
        for field in ('id', 'created', 'created_at', 'completed_at'):
            body.pop(field, None)
    return body


def _frames(text: str) -> list:
    """Return the data frames of a stream, without ids and timestamps."""
    frames = []
    for line in text.splitlines():
        if not line.startswith('data: '):
            continue
        data = line[len('data: ') :]
        if data == '[DONE]':
            frames.append(data)
            continue
        frame = json.loads(data)
        for field in ('id', 'created', 'sequence_number'):
            frame.pop(field, None)
        if isinstance(frame.get('response'), dict):
            for field in ('id', 'created_at', 'completed_at'):
                frame['response'].pop(field, None)
        frames.append(frame)
    return frames or text


def _distinct(values: list) -> list:
    seen = []
    for value in values:
        if not seen or seen[-1] != value:
            seen.append(value)
    return seen


def _snapshot(gateway: Gateway, response) -> dict:
    request_event = gateway.request_events[-1] if gateway.request_events else None
    return {
        'status': response.status_code,
        'body': _body(response),
        'headers': {
            k.upper(): v
            for k, v in response.headers.items()
            if k.upper().startswith('X-RB-AIGATEWAY-')
        },
        'upstream': [_upstream_call(r) for r in gateway.upstream],
        'events': [_event(e) for e in gateway.event_rows],
        'request_event': None
        if request_event is None
        else (
            request_event.route_name,
            request_event.http_status_code,
            request_event.status.name,
            request_event.error_type,
            request_event.is_streaming,
        ),
        'metrics_route': [m['route.name'] for m in gateway.http_metrics],
        'log_routes': _distinct(gateway.route_context.routes),
    }


def _structured(model: str, content: dict) -> CannedResponse:
    return upstream.openai_completion(
        json.dumps(content), model=model, prompt_tokens=30, completion_tokens=4
    )


def _completion(text: str = 'Paris is in France') -> CannedResponse:
    return upstream.openai_completion(
        text, model='gpt-a', prompt_tokens=11, completion_tokens=5
    )


def _stream(*parts: str) -> CannedResponse:
    return upstream.openai_stream(
        list(parts or ('Paris', ' is in France')),
        model='gpt-a',
        prompt_tokens=11,
        completion_tokens=5,
    )


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


def _typesafe() -> CannedResponse:
    return CannedResponse(
        json_body={
            'answers': {'urgent': {'type': 'noul', 'noul': 0.9}},
            'model': 'jev-1',
            'usage': {'input_tokens': 40, 'output_tokens': 2},
        }
    )


ROUTED = _structured('gpt-r1', {'option_1': 0.9, 'option_2': 0.1})
NOT_TRIGGERED = _structured(
    'gpt-j1', {'triggered': False, 'reasoning': None, 'violation_type': None}
)
WARN_AND_SOFT = 'Where is Paris? warnme softme'


def _no_member(send):
    def run(g):
        g.member = False
        return send(g)

    return run


SCENARIOS = {
    # What runs before a soft block, and its headers.
    'chat_soft_block': lambda g: g.chat([ROUTED, NOT_TRIGGERED], text=WARN_AND_SOFT),
    'chat_live_stream_soft_block': lambda g: g.chat(
        [ROUTED, NOT_TRIGGERED], text=WARN_AND_SOFT, stream=True
    ),
    'responses_soft_block': lambda g: g.responses(
        [ROUTED, NOT_TRIGGERED], text=WARN_AND_SOFT
    ),
    'responses_stream_soft_block': lambda g: g.responses(
        [ROUTED, NOT_TRIGGERED], text=WARN_AND_SOFT, stream=True
    ),
    'chat_output_soft_block': lambda g: g.chat(
        [_completion('softout')], route='output', text='warnme'
    ),
    'chat_buffered_input_soft_block': lambda g: g.chat(
        [], route='output', text='warnme softme', stream=True
    ),
    'chat_buffered_output_soft_block': lambda g: g.chat(
        [_stream('softout')], route='output', text='warnme', stream=True
    ),
    'embeddings_soft_block': lambda g: g.embed([], texts=('warnme softme',)),
    'decision_soft_block': lambda g: g.decide([], ticket='warnme softme'),
    # What runs before a limit stops a request.
    'chat_over_limit': lambda g: g.chat([], route='limited'),
    'chat_stream_over_limit': lambda g: g.chat([], route='limited', stream=True),
    'chat_soft_block_over_limit': lambda g: g.chat(
        [], route='limited', text=WARN_AND_SOFT
    ),
    'responses_over_limit': lambda g: g.responses([], route='limited'),
    'responses_soft_block_over_limit': lambda g: g.responses(
        [], route='limited', text=WARN_AND_SOFT
    ),
    'embeddings_over_limit': lambda g: g.embed([], route='embed_limited'),
    'transcription_over_limit': lambda g: g.transcribe(
        [], route='audio_limited', audio=LONG_WAV
    ),
    'transcription_stream_over_limit': lambda g: g.transcribe(
        [], route='audio_limited', audio=LONG_WAV, stream=True
    ),
    # Requests served: the route the metrics and the log lines carry.
    'chat_ok': lambda g: g.chat([ROUTED, NOT_TRIGGERED, _completion()]),
    'chat_live_stream_with_usage': lambda g: g.chat(
        [_stream()],
        route='chat_metered',
        stream=True,
        stream_options={'include_usage': True},
    ),
    'embeddings_ok': lambda g: g.embed([upstream.openai_embeddings(count=1)]),
    'transcription_ok': lambda g: g.transcribe([_transcription()]),
    'decision_ok': lambda g: g.decide([_typesafe()]),
    # A key that is not a member of the route.
    'chat_not_member': _no_member(lambda g: g.chat([])),
    'responses_not_member': _no_member(lambda g: g.responses([])),
    'embeddings_not_member': _no_member(lambda g: g.embed([])),
    'transcription_not_member': _no_member(lambda g: g.transcribe([])),
    'decision_not_member': _no_member(lambda g: g.decide([])),
    # No key: the metrics' route label of a request that fails auth.
    'chat_no_key': lambda g: g.chat([], key=False),
    'responses_no_key': lambda g: g.responses([], key=False),
    'embeddings_no_key': lambda g: g.embed([], key=False),
    'transcription_no_key': lambda g: g.transcribe([], key=False),
    'decision_no_key': lambda g: g.decide([], key=False),
    # An unknown route.
    'chat_unknown_route': lambda g: g.chat([], route='nowhere'),
    'embeddings_unknown_route': lambda g: g.embed([], route='nowhere'),
}


# fmt: off
EXPECTED = {
    'chat_soft_block': {
        'status': 200,
        'body': {'choices': [{'finish_reason': 'stop', 'index': 0, 'logprobs': None, 'message': {'content': 'I cannot process this request as it violates content policy: soft_in', 'refusal': None, 'role': 'assistant', 'annotations': None, 'audio': None, 'function_call': None, 'tool_calls': None}}], 'model': 'chat', 'object': 'chat.completion', 'metadata': None, 'moderation': None, 'service_tier': None, 'system_fingerprint': None, 'usage': {'completion_tokens': 0, 'prompt_tokens': 0, 'total_tokens': 0, 'completion_tokens_details': None, 'prompt_tokens_details': None}},
        'headers': {'X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-INPUT-TRIGGERED': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-WARN': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-INPUT-WARN': 'true'},
        'upstream': ['api.openai.com/v1/chat/completions gpt-r1', 'api.openai.com/v1/chat/completions gpt-j1'],
        'events': [('MODEL_INVOCATION', 'r1', False, True), ('INPUT_TOKEN_PROCESSED', 'r1', False, True), ('OUTPUT_TOKEN_PROCESSED', 'r1', False, True), ('ROUTING', 'a'), ('GUARDRAIL', 'warn_in', 'INPUT', 'WARN'), ('MODEL_INVOCATION', 'j1', True, False), ('INPUT_TOKEN_PROCESSED', 'j1', True, False), ('OUTPUT_TOKEN_PROCESSED', 'j1', True, False), ('GUARDRAIL', 'soft_in', 'INPUT', 'SOFT_BLOCK')],
        'request_event': ('chat', 200, 'SUCCESS', None, False),
        'metrics_route': ['chat'],
        'log_routes': ['chat', None],
    },
    'chat_live_stream_soft_block': {
        'status': 200,
        'body': [{'choices': [{'delta': {'content': 'I cannot process this request as it violates content policy: soft_in', 'role': 'assistant'}, 'finish_reason': 'stop', 'index': 0}], 'model': 'chat', 'object': 'chat.completion.chunk'}, '[DONE]'],
        'headers': {'X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-INPUT-TRIGGERED': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-WARN': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-INPUT-WARN': 'true'},
        'upstream': ['api.openai.com/v1/chat/completions gpt-r1', 'api.openai.com/v1/chat/completions gpt-j1'],
        'events': [('MODEL_INVOCATION', 'r1', False, True), ('INPUT_TOKEN_PROCESSED', 'r1', False, True), ('OUTPUT_TOKEN_PROCESSED', 'r1', False, True), ('ROUTING', 'a'), ('GUARDRAIL', 'warn_in', 'INPUT', 'WARN'), ('MODEL_INVOCATION', 'j1', True, False), ('INPUT_TOKEN_PROCESSED', 'j1', True, False), ('OUTPUT_TOKEN_PROCESSED', 'j1', True, False), ('GUARDRAIL', 'soft_in', 'INPUT', 'SOFT_BLOCK')],
        'request_event': ('chat', 200, 'SUCCESS', None, True),
        'metrics_route': ['chat'],
        'log_routes': ['chat'],
    },
    'responses_soft_block': {
        'status': 200,
        'body': {'object': 'response', 'status': 'completed', 'background': False, 'error': None, 'incomplete_details': None, 'instructions': None, 'max_output_tokens': None, 'max_tool_calls': None, 'model': 'chat', 'output': [{'id': 'msg_*', 'type': 'message', 'status': 'completed', 'content': [{'type': 'output_text', 'annotations': [], 'logprobs': [], 'text': 'I cannot process this request as it violates content policy: soft_in'}], 'role': 'assistant'}], 'parallel_tool_calls': True, 'previous_response_id': None, 'prompt_cache_key': None, 'reasoning': {'effort': None, 'summary': None}, 'safety_identifier': None, 'service_tier': 'default', 'store': False, 'temperature': None, 'text': {'format': {'type': 'text'}}, 'tool_choice': 'auto', 'tools': [], 'top_logprobs': None, 'top_p': None, 'truncation': 'disabled', 'usage': {'input_tokens': 0, 'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0}, 'output_tokens': 0, 'output_tokens_details': {'reasoning_tokens': 0}, 'total_tokens': 0}, 'user': None, 'metadata': {}},
        'headers': {'X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-INPUT-TRIGGERED': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-WARN': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-INPUT-WARN': 'true'},
        'upstream': ['api.openai.com/v1/chat/completions gpt-r1', 'api.openai.com/v1/chat/completions gpt-j1'],
        'events': [('MODEL_INVOCATION', 'r1', False, True), ('INPUT_TOKEN_PROCESSED', 'r1', False, True), ('OUTPUT_TOKEN_PROCESSED', 'r1', False, True), ('ROUTING', 'a'), ('GUARDRAIL', 'warn_in', 'INPUT', 'WARN'), ('MODEL_INVOCATION', 'j1', True, False), ('INPUT_TOKEN_PROCESSED', 'j1', True, False), ('OUTPUT_TOKEN_PROCESSED', 'j1', True, False), ('GUARDRAIL', 'soft_in', 'INPUT', 'SOFT_BLOCK')],
        'request_event': ('chat', 200, 'SUCCESS', None, False),
        'metrics_route': ['chat'],
        'log_routes': ['chat', None],
    },
    'responses_stream_soft_block': {
        'status': 200,
        'body': [{'type': 'response.created', 'response': {'object': 'response', 'status': 'in_progress', 'background': False, 'error': None, 'incomplete_details': None, 'instructions': None, 'max_output_tokens': None, 'max_tool_calls': None, 'model': 'chat', 'output': [], 'parallel_tool_calls': True, 'previous_response_id': None, 'prompt_cache_key': None, 'reasoning': {'effort': None, 'summary': None}, 'safety_identifier': None, 'service_tier': 'default', 'store': False, 'temperature': None, 'text': {'format': {'type': 'text'}}, 'tool_choice': 'auto', 'tools': [], 'top_logprobs': None, 'top_p': None, 'truncation': 'disabled', 'usage': None, 'user': None, 'metadata': {}}}, {'type': 'response.in_progress', 'response': {'object': 'response', 'status': 'in_progress', 'background': False, 'error': None, 'incomplete_details': None, 'instructions': None, 'max_output_tokens': None, 'max_tool_calls': None, 'model': 'chat', 'output': [], 'parallel_tool_calls': True, 'previous_response_id': None, 'prompt_cache_key': None, 'reasoning': {'effort': None, 'summary': None}, 'safety_identifier': None, 'service_tier': 'default', 'store': False, 'temperature': None, 'text': {'format': {'type': 'text'}}, 'tool_choice': 'auto', 'tools': [], 'top_logprobs': None, 'top_p': None, 'truncation': 'disabled', 'usage': None, 'user': None, 'metadata': {}}}, {'type': 'response.output_item.added', 'item': {'id': 'msg_*', 'type': 'message', 'status': 'in_progress', 'content': [], 'role': 'assistant'}, 'output_index': 0}, {'type': 'response.content_part.added', 'content_index': 0, 'item_id': 'msg_*', 'output_index': 0, 'part': {'type': 'output_text', 'annotations': [], 'logprobs': [], 'text': ''}}, {'type': 'response.output_text.delta', 'content_index': 0, 'item_id': 'msg_*', 'output_index': 0, 'delta': 'I cannot process this request as it violates content policy: soft_in', 'logprobs': []}, {'type': 'response.output_text.done', 'content_index': 0, 'item_id': 'msg_*', 'output_index': 0, 'logprobs': [], 'text': 'I cannot process this request as it violates content policy: soft_in'}, {'type': 'response.content_part.done', 'content_index': 0, 'item_id': 'msg_*', 'output_index': 0, 'part': {'type': 'output_text', 'annotations': [], 'logprobs': [], 'text': 'I cannot process this request as it violates content policy: soft_in'}}, {'type': 'response.output_item.done', 'item': {'id': 'msg_*', 'type': 'message', 'status': 'completed', 'content': [{'type': 'output_text', 'annotations': [], 'logprobs': [], 'text': 'I cannot process this request as it violates content policy: soft_in'}], 'role': 'assistant'}, 'output_index': 0}, {'type': 'response.completed', 'response': {'object': 'response', 'status': 'completed', 'background': False, 'error': None, 'incomplete_details': None, 'instructions': None, 'max_output_tokens': None, 'max_tool_calls': None, 'model': 'chat', 'output': [{'id': 'msg_*', 'type': 'message', 'status': 'completed', 'content': [{'type': 'output_text', 'annotations': [], 'logprobs': [], 'text': 'I cannot process this request as it violates content policy: soft_in'}], 'role': 'assistant'}], 'parallel_tool_calls': True, 'previous_response_id': None, 'prompt_cache_key': None, 'reasoning': {'effort': None, 'summary': None}, 'safety_identifier': None, 'service_tier': 'default', 'store': False, 'temperature': None, 'text': {'format': {'type': 'text'}}, 'tool_choice': 'auto', 'tools': [], 'top_logprobs': None, 'top_p': None, 'truncation': 'disabled', 'usage': {'input_tokens': 0, 'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0}, 'output_tokens': 0, 'output_tokens_details': {'reasoning_tokens': 0}, 'total_tokens': 0}, 'user': None, 'metadata': {}}}],
        'headers': {'X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-INPUT-TRIGGERED': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-WARN': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-INPUT-WARN': 'true'},
        'upstream': ['api.openai.com/v1/chat/completions gpt-r1', 'api.openai.com/v1/chat/completions gpt-j1'],
        'events': [('MODEL_INVOCATION', 'r1', False, True), ('INPUT_TOKEN_PROCESSED', 'r1', False, True), ('OUTPUT_TOKEN_PROCESSED', 'r1', False, True), ('ROUTING', 'a'), ('GUARDRAIL', 'warn_in', 'INPUT', 'WARN'), ('MODEL_INVOCATION', 'j1', True, False), ('INPUT_TOKEN_PROCESSED', 'j1', True, False), ('OUTPUT_TOKEN_PROCESSED', 'j1', True, False), ('GUARDRAIL', 'soft_in', 'INPUT', 'SOFT_BLOCK')],
        'request_event': ('chat', 200, 'SUCCESS', None, True),
        'metrics_route': ['chat'],
        'log_routes': ['chat'],
    },
    'chat_output_soft_block': {
        'status': 200,
        'body': {'choices': [{'finish_reason': 'stop', 'index': 0, 'logprobs': None, 'message': {'content': 'This response has been blocked due to policy violation: soft_out', 'refusal': None, 'role': 'assistant', 'annotations': None, 'audio': None, 'function_call': None, 'tool_calls': None}}], 'model': 'output', 'object': 'chat.completion', 'metadata': None, 'moderation': None, 'service_tier': None, 'system_fingerprint': None, 'usage': {'completion_tokens': 5, 'prompt_tokens': 11, 'total_tokens': 16, 'completion_tokens_details': None, 'prompt_tokens_details': None}},
        'headers': {'X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-TRIGGERED': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-WARN': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-INPUT-WARN': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-WARN': 'true'},
        'upstream': ['api.openai.com/v1/chat/completions gpt-a'],
        'events': [('GUARDRAIL', 'warn_in', 'INPUT', 'WARN'), ('MODEL_INVOCATION', 'a', False, False), ('INPUT_TOKEN_PROCESSED', 'a', False, False), ('OUTPUT_TOKEN_PROCESSED', 'a', False, False), ('GUARDRAIL', 'soft_out', 'OUTPUT', 'SOFT_BLOCK')],
        'request_event': ('output', 200, 'SUCCESS', None, False),
        'metrics_route': ['output'],
        'log_routes': ['output', None],
    },
    'chat_buffered_input_soft_block': {
        'status': 200,
        'body': [{'choices': [{'delta': {'content': 'I cannot process this request as it violates content policy: soft_in', 'role': 'assistant'}, 'finish_reason': 'stop', 'index': 0}], 'model': 'output', 'object': 'chat.completion.chunk'}, '[DONE]'],
        'headers': {'X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-INPUT-TRIGGERED': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-WARN': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-INPUT-WARN': 'true'},
        'upstream': [],
        'events': [('GUARDRAIL', 'warn_in', 'INPUT', 'WARN'), ('GUARDRAIL', 'soft_in', 'INPUT', 'SOFT_BLOCK')],
        'request_event': ('output', 200, 'SUCCESS', None, True),
        'metrics_route': ['output'],
        'log_routes': ['output'],
    },
    'chat_buffered_output_soft_block': {
        'status': 400,
        'body': {'error': {'message': 'This response has been blocked due to policy violation: soft_out', 'type': 'guardrail_error', 'param': {'name': 'soft_out', 'type': 'CONTAINS', 'where': 'OUTPUT', 'behavior': 'SOFT_BLOCK', 'parameters': {'type': 'CHECK', 'values': ['softout'], 'ignore_case': False}, 'reason': {'action': 'soft_block'}}, 'code': 'guardrail_violation_bad_request'}},
        'headers': {'X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-TRIGGERED': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-WARN': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-INPUT-WARN': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-WARN': 'true'},
        'upstream': ['api.openai.com/v1/chat/completions gpt-a'],
        'events': [('GUARDRAIL', 'warn_in', 'INPUT', 'WARN'), ('MODEL_INVOCATION', 'a', False, False), ('INPUT_TOKEN_PROCESSED', 'a', False, False), ('OUTPUT_TOKEN_PROCESSED', 'a', False, False), ('GUARDRAIL', 'soft_out', 'OUTPUT', 'SOFT_BLOCK')],
        'request_event': ('output', 400, 'HANDLED_ERROR', 'GuardrailBadRequest', True),
        'metrics_route': ['output'],
        'log_routes': ['output', None],
    },
    'embeddings_soft_block': {
        'status': 200,
        'body': {'data': [], 'model': 'embed', 'object': 'list', 'usage': {'prompt_tokens': 0, 'total_tokens': 0}, 'error': 'I cannot process this request as it violates content policy: soft_in'},
        'headers': {},
        'upstream': [],
        'events': [('GUARDRAIL', 'warn_in', 'INPUT', 'WARN'), ('GUARDRAIL', 'soft_in', 'INPUT', 'SOFT_BLOCK')],
        'request_event': ('embed', 200, 'SUCCESS', None, False),
        'metrics_route': ['embed'],
        'log_routes': ['embed', None],
    },
    'decision_soft_block': {
        'status': 400,
        'body': {'error': {'message': 'I cannot process this request as it violates content policy: soft_in', 'type': 'guardrail_error', 'param': {'name': 'soft_in', 'type': 'CONTAINS', 'where': 'INPUT', 'behavior': 'SOFT_BLOCK', 'parameters': {'type': 'CHECK', 'values': ['softme'], 'ignore_case': False}}, 'code': 'guardrail_violation_bad_request'}},
        'headers': {'X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED': 'true'},
        'upstream': [],
        'events': [('GUARDRAIL', 'warn_in', 'INPUT', 'WARN'), ('GUARDRAIL', 'soft_in', 'INPUT', 'SOFT_BLOCK')],
        'request_event': ('agent', 400, 'HANDLED_ERROR', 'GuardrailBadRequest', False),
        'metrics_route': ['agent'],
        'log_routes': ['agent', None],
    },
    'chat_over_limit': {
        'status': 429,
        'body': {'error': {'message': 'Input token limit exceeded: 3 tokens per 1 minute. Please retry after 60 seconds.', 'type': 'rate_limit_error', 'param': None, 'code': 'token_limit_rate_limited'}},
        'headers': {},
        'upstream': [],
        'events': [('TOKEN_INPUT_LIMIT',)],
        'request_event': ('limited', 429, 'HANDLED_ERROR', 'InputTokenLimitExceeded', False),
        'metrics_route': ['limited'],
        'log_routes': ['limited', None],
    },
    'chat_stream_over_limit': {
        'status': 429,
        'body': {'error': {'message': 'Input token limit exceeded: 3 tokens per 1 minute. Please retry after 60 seconds.', 'type': 'rate_limit_error', 'param': None, 'code': 'token_limit_rate_limited'}},
        'headers': {},
        'upstream': [],
        'events': [('TOKEN_INPUT_LIMIT',)],
        'request_event': ('limited', 429, 'HANDLED_ERROR', 'InputTokenLimitExceeded', True),
        'metrics_route': ['limited'],
        'log_routes': ['limited', None],
    },
    'chat_soft_block_over_limit': {
        'status': 429,
        'body': {'error': {'message': 'Input token limit exceeded: 3 tokens per 1 minute. Please retry after 60 seconds.', 'type': 'rate_limit_error', 'param': None, 'code': 'token_limit_rate_limited'}},
        'headers': {},
        'upstream': [],
        'events': [('TOKEN_INPUT_LIMIT',)],
        'request_event': ('limited', 429, 'HANDLED_ERROR', 'InputTokenLimitExceeded', False),
        'metrics_route': ['limited'],
        'log_routes': ['limited', None],
    },
    'responses_over_limit': {
        'status': 429,
        'body': {'error': {'message': 'Input token limit exceeded: 3 tokens per 1 minute. Please retry after 60 seconds.', 'type': 'rate_limit_error', 'param': None, 'code': 'token_limit_rate_limited'}},
        'headers': {},
        'upstream': [],
        'events': [('TOKEN_INPUT_LIMIT',)],
        'request_event': ('limited', 429, 'HANDLED_ERROR', 'InputTokenLimitExceeded', False),
        'metrics_route': ['limited'],
        'log_routes': ['limited', None],
    },
    'responses_soft_block_over_limit': {
        'status': 429,
        'body': {'error': {'message': 'Input token limit exceeded: 3 tokens per 1 minute. Please retry after 60 seconds.', 'type': 'rate_limit_error', 'param': None, 'code': 'token_limit_rate_limited'}},
        'headers': {},
        'upstream': [],
        'events': [('TOKEN_INPUT_LIMIT',)],
        'request_event': ('limited', 429, 'HANDLED_ERROR', 'InputTokenLimitExceeded', False),
        'metrics_route': ['limited'],
        'log_routes': ['limited', None],
    },
    'embeddings_over_limit': {
        'status': 429,
        'body': {'error': {'message': 'Input token limit exceeded: 3 tokens per 1 minute. Please retry after 60 seconds.', 'type': 'rate_limit_error', 'param': None, 'code': 'token_limit_rate_limited'}},
        'headers': {},
        'upstream': [],
        'events': [('TOKEN_INPUT_LIMIT',)],
        'request_event': ('embed_limited', 429, 'HANDLED_ERROR', 'InputTokenLimitExceeded', False),
        'metrics_route': ['embed_limited'],
        'log_routes': ['embed_limited', None],
    },
    'transcription_over_limit': {
        'status': 429,
        'body': {'error': {'message': 'Audio duration limit exceeded: 1.0 seconds per 1 minute. Please retry after 60 seconds.', 'type': 'rate_limit_error', 'param': 'audio_limited', 'code': 'audio_duration_rate_limited'}},
        'headers': {},
        'upstream': [],
        'events': [('AUDIO_DURATION_LIMIT',)],
        'request_event': ('audio_limited', 429, 'HANDLED_ERROR', 'AudioDurationLimitExceeded', False),
        'metrics_route': ['audio_limited'],
        'log_routes': ['audio_limited', None],
    },
    'transcription_stream_over_limit': {
        'status': 429,
        'body': {'error': {'message': 'Audio duration limit exceeded: 1.0 seconds per 1 minute. Please retry after 60 seconds.', 'type': 'rate_limit_error', 'param': 'audio_limited', 'code': 'audio_duration_rate_limited'}},
        'headers': {},
        'upstream': [],
        'events': [('AUDIO_DURATION_LIMIT',)],
        'request_event': ('audio_limited', 429, 'HANDLED_ERROR', 'AudioDurationLimitExceeded', True),
        'metrics_route': ['audio_limited'],
        'log_routes': ['audio_limited', None],
    },
    'chat_ok': {
        'status': 200,
        'body': {'choices': [{'finish_reason': 'stop', 'index': 0, 'logprobs': None, 'message': {'content': 'Paris is in France', 'refusal': None, 'role': 'assistant', 'annotations': None, 'audio': None, 'function_call': None, 'tool_calls': None}}], 'model': 'chat', 'object': 'chat.completion', 'metadata': None, 'moderation': None, 'service_tier': None, 'system_fingerprint': None, 'usage': {'completion_tokens': 5, 'prompt_tokens': 11, 'total_tokens': 16, 'completion_tokens_details': None, 'prompt_tokens_details': None}},
        'headers': {},
        'upstream': ['api.openai.com/v1/chat/completions gpt-r1', 'api.openai.com/v1/chat/completions gpt-j1', 'api.openai.com/v1/chat/completions gpt-a'],
        'events': [('MODEL_INVOCATION', 'r1', False, True), ('INPUT_TOKEN_PROCESSED', 'r1', False, True), ('OUTPUT_TOKEN_PROCESSED', 'r1', False, True), ('ROUTING', 'a'), ('MODEL_INVOCATION', 'j1', True, False), ('INPUT_TOKEN_PROCESSED', 'j1', True, False), ('OUTPUT_TOKEN_PROCESSED', 'j1', True, False), ('MODEL_INVOCATION', 'a', False, False), ('INPUT_TOKEN_PROCESSED', 'a', False, False), ('OUTPUT_TOKEN_PROCESSED', 'a', False, False)],
        'request_event': ('chat', 200, 'SUCCESS', None, False),
        'metrics_route': ['chat'],
        'log_routes': ['chat', None],
    },
    'chat_live_stream_with_usage': {
        'status': 200,
        'body': [{'choices': [{'delta': {'role': 'assistant'}, 'index': 0}], 'model': 'chat_metered', 'object': 'chat.completion.chunk'}, {'choices': [{'delta': {'content': 'Paris', 'role': 'assistant'}, 'index': 0}], 'model': 'chat_metered', 'object': 'chat.completion.chunk'}, {'choices': [{'delta': {'content': ' is in France', 'role': 'assistant'}, 'index': 0}], 'model': 'chat_metered', 'object': 'chat.completion.chunk'}, {'choices': [{'delta': {'role': 'assistant'}, 'finish_reason': 'stop', 'index': 0}], 'model': 'chat_metered', 'object': 'chat.completion.chunk'}, {'choices': [{'delta': {'role': 'assistant'}, 'index': 0}], 'model': 'chat_metered', 'object': 'chat.completion.chunk', 'usage': {'completion_tokens': 5, 'prompt_tokens': 11, 'total_tokens': 16, 'completion_tokens_details': {'accepted_prediction_tokens': 0, 'audio_tokens': 0, 'reasoning_tokens': 0, 'rejected_prediction_tokens': 0}, 'prompt_tokens_details': {'audio_tokens': 0, 'cached_tokens': 0}}}, {'choices': [{'delta': {'role': 'assistant'}, 'index': 0}], 'model': 'chat_metered', 'object': 'chat.completion.chunk'}, {'choices': [], 'model': 'chat_metered', 'object': 'chat.completion.chunk', 'usage': {'completion_tokens': 5, 'prompt_tokens': 11, 'total_tokens': 16, 'completion_tokens_details': {'accepted_prediction_tokens': 0, 'audio_tokens': 0, 'reasoning_tokens': 0, 'rejected_prediction_tokens': 0}, 'prompt_tokens_details': {'audio_tokens': 0, 'cached_tokens': 0}}}, '[DONE]'],
        'headers': {},
        'upstream': ['api.openai.com/v1/chat/completions gpt-a'],
        'events': [('MODEL_INVOCATION', 'a', False, False), ('INPUT_TOKEN_PROCESSED', 'a', False, False), ('OUTPUT_TOKEN_PROCESSED', 'a', False, False)],
        'request_event': ('chat_metered', 200, 'SUCCESS', None, True),
        'metrics_route': ['chat_metered'],
        'log_routes': ['chat_metered'],
    },
    'embeddings_ok': {
        'status': 200,
        'body': {'data': [{'embedding': [0.1, 0.11, 0.12, 0.13], 'index': 0, 'object': 'embedding'}], 'model': 'text-embedding-3-small', 'object': 'list', 'usage': {'prompt_tokens': 4, 'total_tokens': 4}},
        'headers': {},
        'upstream': ['api.openai.com/v1/embeddings text-embedding-3-small'],
        'events': [('MODEL_INVOCATION', 'e1', False, False), ('INPUT_TOKEN_PROCESSED', 'e1', False, False)],
        'request_event': ('embed', 200, 'SUCCESS', None, False),
        'metrics_route': ['embed'],
        'log_routes': ['embed', None],
    },
    'transcription_ok': {
        'status': 200,
        'body': {'text': 'hello', 'languages': None, 'logprobs': None, 'usage': {'input_tokens': 10, 'output_tokens': 3, 'total_tokens': 13, 'type': 'tokens', 'input_token_details': {'audio_tokens': 8, 'text_tokens': 2}}},
        'headers': {},
        'upstream': ['api.openai.com/v1/audio/transcriptions'],
        'events': [('MODEL_INVOCATION', 't1', False, False), ('INPUT_TOKEN_PROCESSED', 't1', False, False), ('INPUT_TOKEN_PROCESSED', 't1', False, False), ('OUTPUT_TOKEN_PROCESSED', 't1', False, False)],
        'request_event': ('audio', 200, 'SUCCESS', None, False),
        'metrics_route': ['audio'],
        'log_routes': ['audio', None],
    },
    'decision_ok': {
        'status': 200,
        'body': {'answers': {'urgent': {'type': 'noul', 'noul': 0.9}}, 'model': 'd1', 'usage': {'input_tokens': 40, 'output_tokens': 2}},
        'headers': {},
        'upstream': ['api.typesafe.ai/v1/systemone jev-latest'],
        'events': [('MODEL_INVOCATION', 'd1', False, False), ('INPUT_TOKEN_PROCESSED', 'd1', False, False), ('OUTPUT_TOKEN_PROCESSED', 'd1', False, False)],
        'request_event': ('agent', 200, 'SUCCESS', None, False),
        'metrics_route': ['agent'],
        'log_routes': ['agent', None],
    },
    'chat_not_member': {
        'status': 401,
        'body': {'error': {'message': 'Incorrect API key provided.', 'type': 'authentication_error', 'param': None, 'code': 'key_invalid_unauthorized'}},
        'headers': {},
        'upstream': [],
        'events': [],
        'request_event': ('chat', 401, 'HANDLED_ERROR', 'InvalidApiKey', False),
        'metrics_route': ['chat'],
        'log_routes': ['chat', None],
    },
    'responses_not_member': {
        'status': 401,
        'body': {'error': {'message': 'Incorrect API key provided.', 'type': 'authentication_error', 'param': None, 'code': 'key_invalid_unauthorized'}},
        'headers': {},
        'upstream': [],
        'events': [],
        'request_event': ('chat', 401, 'HANDLED_ERROR', 'InvalidApiKey', False),
        'metrics_route': ['chat'],
        'log_routes': ['chat', None],
    },
    'embeddings_not_member': {
        'status': 401,
        'body': {'error': {'message': 'Incorrect API key provided.', 'type': 'authentication_error', 'param': None, 'code': 'key_invalid_unauthorized'}},
        'headers': {},
        'upstream': [],
        'events': [],
        'request_event': ('embed', 401, 'HANDLED_ERROR', 'InvalidApiKey', False),
        'metrics_route': ['embed'],
        'log_routes': [None],
    },
    'transcription_not_member': {
        'status': 401,
        'body': {'error': {'message': 'Incorrect API key provided.', 'type': 'authentication_error', 'param': None, 'code': 'key_invalid_unauthorized'}},
        'headers': {},
        'upstream': [],
        'events': [],
        'request_event': ('audio', 401, 'HANDLED_ERROR', 'InvalidApiKey', False),
        'metrics_route': ['audio'],
        'log_routes': [None],
    },
    'decision_not_member': {
        'status': 401,
        'body': {'error': {'message': 'Incorrect API key provided.', 'type': 'authentication_error', 'param': None, 'code': 'key_invalid_unauthorized'}},
        'headers': {},
        'upstream': [],
        'events': [],
        'request_event': ('agent', 401, 'HANDLED_ERROR', 'InvalidApiKey', False),
        'metrics_route': ['agent'],
        'log_routes': [None],
    },
    'chat_no_key': {
        'status': 401,
        'body': {'error': {'message': 'Missing API key', 'type': 'authentication_error', 'param': None, 'code': 'key_missing_unauthorized'}},
        'headers': {},
        'upstream': [],
        'events': [],
        'request_event': ('chat', 401, 'HANDLED_ERROR', 'MissingApiKey', False),
        'metrics_route': ['chat'],
        'log_routes': [None],
    },
    'responses_no_key': {
        'status': 401,
        'body': {'error': {'message': 'Missing API key', 'type': 'authentication_error', 'param': None, 'code': 'key_missing_unauthorized'}},
        'headers': {},
        'upstream': [],
        'events': [],
        'request_event': ('chat', 401, 'HANDLED_ERROR', 'MissingApiKey', False),
        'metrics_route': ['chat'],
        'log_routes': [None],
    },
    'embeddings_no_key': {
        'status': 401,
        'body': {'error': {'message': 'Missing API key', 'type': 'authentication_error', 'param': None, 'code': 'key_missing_unauthorized'}},
        'headers': {},
        'upstream': [],
        'events': [],
        'request_event': ('embed', 401, 'HANDLED_ERROR', 'MissingApiKey', False),
        'metrics_route': ['embed'],
        'log_routes': [None],
    },
    'transcription_no_key': {
        'status': 401,
        'body': {'error': {'message': 'Missing API key', 'type': 'authentication_error', 'param': None, 'code': 'key_missing_unauthorized'}},
        'headers': {},
        'upstream': [],
        'events': [],
        'request_event': ('audio', 401, 'HANDLED_ERROR', 'MissingApiKey', False),
        'metrics_route': ['audio'],
        'log_routes': [None],
    },
    'decision_no_key': {
        'status': 401,
        'body': {'error': {'message': 'Missing API key', 'type': 'authentication_error', 'param': None, 'code': 'key_missing_unauthorized'}},
        'headers': {},
        'upstream': [],
        'events': [],
        'request_event': ('agent', 401, 'HANDLED_ERROR', 'MissingApiKey', False),
        'metrics_route': ['agent'],
        'log_routes': [None],
    },
    'chat_unknown_route': {
        'status': 400,
        'body': {'error': {'message': 'The route name [proj/nowhere] was not found in the config', 'type': 'gateway_error', 'param': None, 'code': 'gateway_bad_request'}},
        'headers': {},
        'upstream': [],
        'events': [],
        'request_event': ('', 400, 'HANDLED_ERROR', 'GatewayBadRequest', False),
        'metrics_route': ['unknown'],
        'log_routes': [None],
    },
    'embeddings_unknown_route': {
        'status': 400,
        'body': {'error': {'message': 'The route name [proj/nowhere] was not found in the config', 'type': 'gateway_error', 'param': None, 'code': 'gateway_bad_request'}},
        'headers': {},
        'upstream': [],
        'events': [],
        'request_event': ('', 400, 'HANDLED_ERROR', 'GatewayBadRequest', False),
        'metrics_route': ['unknown'],
        'log_routes': [None],
    },
}
# fmt: on


@pytest.mark.parametrize('name', list(SCENARIOS))
async def test_golden(gateway, name):
    response = SCENARIOS[name](gateway)

    assert _snapshot(gateway, response) == EXPECTED[name]


# ---------------------------------------------------------------------------
# Trace spans: their names and parents, as the trace shows them
# ---------------------------------------------------------------------------


def _span_tree(spans: list) -> list[tuple[str, str | None]]:
    """Return each span's name and its parent's, in the order they end."""
    names = {span.context.span_id: span.name for span in spans}
    return [
        (span.name, names.get(span.parent.span_id) if span.parent else None)
        for span in spans
    ]


SPAN_SCENARIOS = {
    'chat': lambda g: g.chat([ROUTED, NOT_TRIGGERED, _completion()]),
    'chat_live_stream': lambda g: g.chat(
        [ROUTED, NOT_TRIGGERED, _stream()], stream=True
    ),
    'chat_buffered_stream': lambda g: g.chat([_stream()], route='output', stream=True),
    'chat_output': lambda g: g.chat([_completion()], route='output'),
    'responses': lambda g: g.responses(
        [ROUTED, NOT_TRIGGERED, upstream.openai_response('Paris', model='gpt-a')]
    ),
    'responses_stream': lambda g: g.responses(
        [
            ROUTED,
            NOT_TRIGGERED,
            upstream.openai_response_stream(model='gpt-a'),
        ],
        stream=True,
    ),
    'embeddings': lambda g: g.embed([upstream.openai_embeddings(count=1)]),
    'transcription': lambda g: g.transcribe([_transcription()]),
    'decision': lambda g: g.decide([_typesafe()]),
    'chat_metered': lambda g: g.chat([_completion()], route='chat_metered'),
    'chat_stream_metered': lambda g: g.chat(
        [_stream()], route='chat_metered', stream=True
    ),
    'responses_metered': lambda g: g.responses(
        [upstream.openai_response('Paris', model='gpt-a')], route='chat_metered'
    ),
    'embeddings_metered': lambda g: g.embed(
        [upstream.openai_embeddings(count=1)], route='embed_metered'
    ),
    'transcription_metered': lambda g: g.transcribe(
        [_transcription()], route='audio_metered'
    ),
    'transcription_stream_metered': lambda g: g.transcribe(
        [_transcription_stream()], route='audio_metered', stream=True
    ),
    'decision_metered': lambda g: g.decide([_typesafe()], route='agent_metered'),
}

# fmt: off
EXPECTED_SPANS = {
    'chat': [('auth_api_key.task', 'chat_completions.workflow'), ('ChatOpenAI.chat', 'select_model.task'), ('select_model.task', 'chat_completions.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('ChatOpenAI.chat', 'check_judge.task'), ('check_judge.task', 'apply_check_guardrails.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('apply_check_guardrails.workflow', 'chat_completions.workflow'), ('ChatOpenAI.chat', 'llm_complete.task'), ('llm_complete.task', 'chat_completions.workflow'), ('chat_completions.workflow', None)],
    'chat_metered': [('auth_api_key.task', 'chat_completions.workflow'), ('check_token_input_limit.task', 'check_limiters.task'), ('check_limiters.task', 'chat_completions.workflow'), ('select_model.task', 'chat_completions.workflow'), ('ChatOpenAI.chat', 'llm_complete.task'), ('llm_complete.task', 'chat_completions.workflow'), ('chat_completions.workflow', None)],
    'chat_live_stream': [('auth_api_key.task', 'chat_completions.workflow'), ('ChatOpenAI.chat', 'select_model.task'), ('select_model.task', 'chat_completions.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('ChatOpenAI.chat', 'check_judge.task'), ('check_judge.task', 'apply_check_guardrails.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('apply_check_guardrails.workflow', 'chat_completions.workflow'), ('chat_completions.workflow', None), ('ChatOpenAI.chat', 'llm_stream.task'), ('llm_stream.task', 'chat_completions.workflow')],
    'chat_buffered_stream': [('auth_api_key.task', 'chat_completions.workflow'), ('select_model.task', 'chat_completions.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('apply_check_guardrails.workflow', 'chat_completions.workflow'), ('ChatOpenAI.chat', 'llm_stream.task'), ('llm_stream.task', 'stream_with_output_guardrails.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('apply_check_guardrails.workflow', 'stream_with_output_guardrails.workflow'), ('stream_with_output_guardrails.workflow', 'chat_completions.workflow'), ('chat_completions.workflow', None)],
    'chat_output': [('auth_api_key.task', 'chat_completions.workflow'), ('select_model.task', 'chat_completions.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('apply_check_guardrails.workflow', 'chat_completions.workflow'), ('ChatOpenAI.chat', 'llm_complete.task'), ('llm_complete.task', 'chat_completions.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('apply_check_guardrails.workflow', 'apply_output_guardrails.workflow'), ('apply_output_guardrails.workflow', 'chat_completions.workflow'), ('chat_completions.workflow', None)],
    'responses': [('auth_api_key.task', 'responses.workflow'), ('ChatOpenAI.chat', 'select_model.task'), ('select_model.task', 'responses.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('ChatOpenAI.chat', 'check_judge.task'), ('check_judge.task', 'apply_check_guardrails.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('apply_check_guardrails.workflow', 'responses.workflow'), ('ChatOpenAI.chat', 'llm_complete_responses.task'), ('llm_complete_responses.task', 'responses.workflow'), ('apply_responses_output_guardrails.workflow', 'responses.workflow'), ('responses.workflow', None)],
    'responses_stream': [('auth_api_key.task', 'responses.workflow'), ('ChatOpenAI.chat', 'select_model.task'), ('select_model.task', 'responses.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('ChatOpenAI.chat', 'check_judge.task'), ('check_judge.task', 'apply_check_guardrails.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('apply_check_guardrails.workflow', 'responses.workflow'), ('responses.workflow', None), ('ChatOpenAI.chat', 'llm_stream_responses.task'), ('llm_stream_responses.task', 'responses.workflow')],
    'embeddings': [('auth_api_key.task', 'embeddings.workflow'), ('select_embedding_model.task', 'embeddings.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('apply_check_guardrails.workflow', 'embeddings.workflow'), ('llm_embed.task', 'embeddings.workflow'), ('embeddings.workflow', None)],
    'transcription': [('auth_api_key.task', 'audio_transcriptions.workflow'), ('select_transcription_model.task', 'audio_transcriptions.workflow'), ('llm_transcribe.task', 'audio_transcriptions.workflow'), ('audio_transcriptions.workflow', None)],
    'decision': [('auth_api_key.task', 'decision_model.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('apply_check_guardrails.workflow', 'decision_model.workflow'), ('decide.task', 'decision_model.workflow'), ('decision_model.workflow', None)],
    'chat_stream_metered': [('auth_api_key.task', 'chat_completions.workflow'), ('check_token_input_limit.task', 'check_limiters.task'), ('check_limiters.task', 'chat_completions.workflow'), ('select_model.task', 'chat_completions.workflow'), ('chat_completions.workflow', None), ('ChatOpenAI.chat', 'llm_stream.task'), ('llm_stream.task', 'chat_completions.workflow')],
    'responses_metered': [('auth_api_key.task', 'responses.workflow'), ('check_token_input_limit.task', 'check_limiters.task'), ('check_limiters.task', 'responses.workflow'), ('select_model.task', 'responses.workflow'), ('ChatOpenAI.chat', 'llm_complete_responses.task'), ('llm_complete_responses.task', 'responses.workflow'), ('apply_responses_output_guardrails.workflow', 'responses.workflow'), ('responses.workflow', None)],
    'embeddings_metered': [('auth_api_key.task', 'embeddings.workflow'), ('select_embedding_model.task', 'embeddings.workflow'), ('check_token_input_limit.task', 'check_embedding_limiters.task'), ('check_embedding_limiters.task', 'embeddings.workflow'), ('llm_embed.task', 'embeddings.workflow'), ('embeddings.workflow', None)],
    'transcription_metered': [('auth_api_key.task', 'audio_transcriptions.workflow'), ('select_transcription_model.task', 'audio_transcriptions.workflow'), ('check_audio_duration_limit.task', 'audio_transcriptions.workflow'), ('llm_transcribe.task', 'audio_transcriptions.workflow'), ('audio_transcriptions.workflow', None)],
    'transcription_stream_metered': [('auth_api_key.task', 'audio_transcriptions.workflow'), ('select_transcription_model.task', 'audio_transcriptions.workflow'), ('check_audio_duration_limit.task', 'audio_transcriptions.workflow'), ('audio_transcriptions.workflow', None), ('llm_transcribe_stream.task', 'audio_transcriptions.workflow')],
    'decision_metered': [('auth_api_key.task', 'decision_model.workflow'), ('check_token_input_room.task', 'decision_model.workflow'), ('decide.task', 'decision_model.workflow'), ('decision_model.workflow', None)],
}
# fmt: on


@pytest.mark.parametrize('name', list(SPAN_SCENARIOS))
async def test_spans(gateway, span_collector, name):
    span_collector.spans.clear()
    span_collector.on = True
    try:
        response = SPAN_SCENARIOS[name](gateway)
    finally:
        span_collector.on = False

    assert response.status_code == 200
    assert _span_tree(span_collector.spans) == EXPECTED_SPANS[name]


SCOPED_SPANS = {
    'chat': 'select_model.task',
    'embeddings': 'select_embedding_model.task',
    'transcription': 'select_transcription_model.task',
    'chat_output': 'apply_output_guardrails.workflow',
    'chat_buffered_stream': 'stream_with_output_guardrails.workflow',
    'responses': 'apply_responses_output_guardrails.workflow',
}


@pytest.mark.parametrize('name', list(SCOPED_SPANS))
async def test_a_request_span_records_its_input_with_the_route_by_name(
    gateway, span_collector, name
):
    """A span taking the request records its input, the request as the
    route's name, as the route's methods did: the route is never copied.
    """
    span_collector.spans.clear()
    span_collector.on = True
    try:
        SPAN_SCENARIOS[name](gateway)
    finally:
        span_collector.on = False

    (span,) = [s for s in span_collector.spans if s.name == SCOPED_SPANS[name]]
    recorded = json.loads(span.attributes['traceloop.entity.input'])
    assert recorded['args'][0] == 'GatewayRoute'


@pytest.mark.parametrize('name', list(SPAN_SCENARIOS))
async def test_no_span_input_records_a_credential(gateway, span_collector, name):
    span_collector.spans.clear()
    span_collector.on = True
    try:
        SPAN_SCENARIOS[name](gateway)
    finally:
        span_collector.on = False

    inputs = [
        s.attributes.get('traceloop.entity.input', '') for s in span_collector.spans
    ]
    assert not [i for i in inputs if 'sk-test' in i or 'ts-test' in i]


@pytest.mark.parametrize('name', list(SPAN_SCENARIOS))
async def test_no_span_output_records_a_credential(gateway, span_collector, name):
    span_collector.spans.clear()
    span_collector.on = True
    try:
        SPAN_SCENARIOS[name](gateway)
    finally:
        span_collector.on = False

    leaking = [
        s.name
        for s in span_collector.spans
        if any(
            secret in s.attributes.get('traceloop.entity.output', '')
            for secret in ('sk-test', 'ts-test')
        )
    ]
    assert leaking == []


BLOCKED_OUTPUTS = {
    'chat_buffered_soft_block': lambda g: g.chat(
        [_stream('softout')], route='output_metered', stream=True
    ),
    'chat_buffered_block': lambda g: g.chat(
        [_stream('blockout')], route='output_metered', stream=True
    ),
    'chat_block': lambda g: g.chat([_completion('blockout')], route='output_metered'),
    'responses_block': lambda g: g.responses(
        [upstream.openai_response('blockout', model='gpt-a')], route='output_metered'
    ),
    'responses_buffered_block': lambda g: g.responses(
        [upstream.openai_response_stream(['blockout'], model='gpt-a')],
        route='output_metered',
        stream=True,
    ),
}


@pytest.mark.parametrize('name', list(BLOCKED_OUTPUTS))
async def test_a_reply_the_output_guardrails_block_is_counted(gateway, name):
    """The model was paid for: its tokens count on the caller's limits even
    when the output guardrails refuse the reply (ADR 0006).
    """
    window = server.app.state.routes['proj/output_metered'].route_limits.window(
        Category.INPUT_TOKENS
    )
    before = await consumed(window)

    response = BLOCKED_OUTPUTS[name](gateway)

    assert response.status_code != 200 or 'softout' not in response.text
    assert await consumed(window) > before
