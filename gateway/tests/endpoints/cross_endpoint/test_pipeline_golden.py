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
from tests.common.pipeline_gateway import CONFIG, gpt_a_completion, gpt_a_stream
from tests.common.provider_recorder import CannedResponse

from radicalbit_ai_gateway import server
from radicalbit_ai_gateway.limiting.windows import Category

LONG_WAV = make_wav_bytes(2.0)


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


# fmt: off
GOLDEN = [
    # What runs before a soft block, and its headers.
    pytest.param(
        lambda g: g.chat([ROUTED, NOT_TRIGGERED], text=WARN_AND_SOFT),
        {
            'status': 200,
            'body': {'choices': [{'finish_reason': 'stop', 'index': 0, 'logprobs': None, 'message': {'content': 'I cannot process this request as it violates content policy: soft_in', 'refusal': None, 'role': 'assistant', 'annotations': None, 'audio': None, 'function_call': None, 'tool_calls': None}}], 'model': 'chat', 'object': 'chat.completion', 'metadata': None, 'moderation': None, 'service_tier': None, 'system_fingerprint': None, 'usage': {'completion_tokens': 0, 'prompt_tokens': 0, 'total_tokens': 0, 'completion_tokens_details': None, 'prompt_tokens_details': None}},
            'headers': {'X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-INPUT-TRIGGERED': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-WARN': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-INPUT-WARN': 'true'},
            'upstream': ['api.openai.com/v1/chat/completions gpt-r1', 'api.openai.com/v1/chat/completions gpt-j1'],
            'events': [('MODEL_INVOCATION', 'r1', False, True), ('INPUT_TOKEN_PROCESSED', 'r1', False, True), ('OUTPUT_TOKEN_PROCESSED', 'r1', False, True), ('ROUTING', 'a'), ('GUARDRAIL', 'warn_in', 'INPUT', 'WARN'), ('MODEL_INVOCATION', 'j1', True, False), ('INPUT_TOKEN_PROCESSED', 'j1', True, False), ('OUTPUT_TOKEN_PROCESSED', 'j1', True, False), ('GUARDRAIL', 'soft_in', 'INPUT', 'SOFT_BLOCK')],
            'request_event': ('chat', 200, 'SUCCESS', None, False),
            'metrics_route': ['chat'],
            'log_routes': ['chat', None],
        },
        id='chat_soft_block',
    ),
    pytest.param(
        lambda g: g.chat(
            [ROUTED, NOT_TRIGGERED], text=WARN_AND_SOFT, stream=True
        ),
        {
            'status': 200,
            'body': [{'choices': [{'delta': {'content': 'I cannot process this request as it violates content policy: soft_in', 'role': 'assistant'}, 'finish_reason': 'stop', 'index': 0}], 'model': 'chat', 'object': 'chat.completion.chunk'}, '[DONE]'],
            'headers': {'X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-INPUT-TRIGGERED': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-WARN': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-INPUT-WARN': 'true'},
            'upstream': ['api.openai.com/v1/chat/completions gpt-r1', 'api.openai.com/v1/chat/completions gpt-j1'],
            'events': [('MODEL_INVOCATION', 'r1', False, True), ('INPUT_TOKEN_PROCESSED', 'r1', False, True), ('OUTPUT_TOKEN_PROCESSED', 'r1', False, True), ('ROUTING', 'a'), ('GUARDRAIL', 'warn_in', 'INPUT', 'WARN'), ('MODEL_INVOCATION', 'j1', True, False), ('INPUT_TOKEN_PROCESSED', 'j1', True, False), ('OUTPUT_TOKEN_PROCESSED', 'j1', True, False), ('GUARDRAIL', 'soft_in', 'INPUT', 'SOFT_BLOCK')],
            'request_event': ('chat', 200, 'SUCCESS', None, True),
            'metrics_route': ['chat'],
            'log_routes': ['chat'],
        },
        id='chat_live_stream_soft_block',
    ),
    pytest.param(
        lambda g: g.responses(
            [ROUTED, NOT_TRIGGERED], text=WARN_AND_SOFT
        ),
        {
            'status': 200,
            'body': {'object': 'response', 'status': 'completed', 'background': False, 'error': None, 'incomplete_details': None, 'instructions': None, 'max_output_tokens': None, 'max_tool_calls': None, 'model': 'chat', 'output': [{'id': 'msg_*', 'type': 'message', 'status': 'completed', 'content': [{'type': 'output_text', 'annotations': [], 'logprobs': [], 'text': 'I cannot process this request as it violates content policy: soft_in'}], 'role': 'assistant'}], 'parallel_tool_calls': True, 'previous_response_id': None, 'prompt_cache_key': None, 'reasoning': {'effort': None, 'summary': None}, 'safety_identifier': None, 'service_tier': 'default', 'store': False, 'temperature': None, 'text': {'format': {'type': 'text'}}, 'tool_choice': 'auto', 'tools': [], 'top_logprobs': None, 'top_p': None, 'truncation': 'disabled', 'usage': {'input_tokens': 0, 'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0}, 'output_tokens': 0, 'output_tokens_details': {'reasoning_tokens': 0}, 'total_tokens': 0}, 'user': None, 'metadata': {}},
            'headers': {'X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-INPUT-TRIGGERED': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-WARN': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-INPUT-WARN': 'true'},
            'upstream': ['api.openai.com/v1/chat/completions gpt-r1', 'api.openai.com/v1/chat/completions gpt-j1'],
            'events': [('MODEL_INVOCATION', 'r1', False, True), ('INPUT_TOKEN_PROCESSED', 'r1', False, True), ('OUTPUT_TOKEN_PROCESSED', 'r1', False, True), ('ROUTING', 'a'), ('GUARDRAIL', 'warn_in', 'INPUT', 'WARN'), ('MODEL_INVOCATION', 'j1', True, False), ('INPUT_TOKEN_PROCESSED', 'j1', True, False), ('OUTPUT_TOKEN_PROCESSED', 'j1', True, False), ('GUARDRAIL', 'soft_in', 'INPUT', 'SOFT_BLOCK')],
            'request_event': ('chat', 200, 'SUCCESS', None, False),
            'metrics_route': ['chat'],
            'log_routes': ['chat', None],
        },
        id='responses_soft_block',
    ),
    pytest.param(
        lambda g: g.responses(
            [ROUTED, NOT_TRIGGERED], text=WARN_AND_SOFT, stream=True
        ),
        {
            'status': 200,
            'body': [{'type': 'response.created', 'response': {'object': 'response', 'status': 'in_progress', 'background': False, 'error': None, 'incomplete_details': None, 'instructions': None, 'max_output_tokens': None, 'max_tool_calls': None, 'model': 'chat', 'output': [], 'parallel_tool_calls': True, 'previous_response_id': None, 'prompt_cache_key': None, 'reasoning': {'effort': None, 'summary': None}, 'safety_identifier': None, 'service_tier': 'default', 'store': False, 'temperature': None, 'text': {'format': {'type': 'text'}}, 'tool_choice': 'auto', 'tools': [], 'top_logprobs': None, 'top_p': None, 'truncation': 'disabled', 'usage': None, 'user': None, 'metadata': {}}}, {'type': 'response.in_progress', 'response': {'object': 'response', 'status': 'in_progress', 'background': False, 'error': None, 'incomplete_details': None, 'instructions': None, 'max_output_tokens': None, 'max_tool_calls': None, 'model': 'chat', 'output': [], 'parallel_tool_calls': True, 'previous_response_id': None, 'prompt_cache_key': None, 'reasoning': {'effort': None, 'summary': None}, 'safety_identifier': None, 'service_tier': 'default', 'store': False, 'temperature': None, 'text': {'format': {'type': 'text'}}, 'tool_choice': 'auto', 'tools': [], 'top_logprobs': None, 'top_p': None, 'truncation': 'disabled', 'usage': None, 'user': None, 'metadata': {}}}, {'type': 'response.output_item.added', 'item': {'id': 'msg_*', 'type': 'message', 'status': 'in_progress', 'content': [], 'role': 'assistant'}, 'output_index': 0}, {'type': 'response.content_part.added', 'content_index': 0, 'item_id': 'msg_*', 'output_index': 0, 'part': {'type': 'output_text', 'annotations': [], 'logprobs': [], 'text': ''}}, {'type': 'response.output_text.delta', 'content_index': 0, 'item_id': 'msg_*', 'output_index': 0, 'delta': 'I cannot process this request as it violates content policy: soft_in', 'logprobs': []}, {'type': 'response.output_text.done', 'content_index': 0, 'item_id': 'msg_*', 'output_index': 0, 'logprobs': [], 'text': 'I cannot process this request as it violates content policy: soft_in'}, {'type': 'response.content_part.done', 'content_index': 0, 'item_id': 'msg_*', 'output_index': 0, 'part': {'type': 'output_text', 'annotations': [], 'logprobs': [], 'text': 'I cannot process this request as it violates content policy: soft_in'}}, {'type': 'response.output_item.done', 'item': {'id': 'msg_*', 'type': 'message', 'status': 'completed', 'content': [{'type': 'output_text', 'annotations': [], 'logprobs': [], 'text': 'I cannot process this request as it violates content policy: soft_in'}], 'role': 'assistant'}, 'output_index': 0}, {'type': 'response.completed', 'response': {'object': 'response', 'status': 'completed', 'background': False, 'error': None, 'incomplete_details': None, 'instructions': None, 'max_output_tokens': None, 'max_tool_calls': None, 'model': 'chat', 'output': [{'id': 'msg_*', 'type': 'message', 'status': 'completed', 'content': [{'type': 'output_text', 'annotations': [], 'logprobs': [], 'text': 'I cannot process this request as it violates content policy: soft_in'}], 'role': 'assistant'}], 'parallel_tool_calls': True, 'previous_response_id': None, 'prompt_cache_key': None, 'reasoning': {'effort': None, 'summary': None}, 'safety_identifier': None, 'service_tier': 'default', 'store': False, 'temperature': None, 'text': {'format': {'type': 'text'}}, 'tool_choice': 'auto', 'tools': [], 'top_logprobs': None, 'top_p': None, 'truncation': 'disabled', 'usage': {'input_tokens': 0, 'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0}, 'output_tokens': 0, 'output_tokens_details': {'reasoning_tokens': 0}, 'total_tokens': 0}, 'user': None, 'metadata': {}}}],
            'headers': {'X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-INPUT-TRIGGERED': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-WARN': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-INPUT-WARN': 'true'},
            'upstream': ['api.openai.com/v1/chat/completions gpt-r1', 'api.openai.com/v1/chat/completions gpt-j1'],
            'events': [('MODEL_INVOCATION', 'r1', False, True), ('INPUT_TOKEN_PROCESSED', 'r1', False, True), ('OUTPUT_TOKEN_PROCESSED', 'r1', False, True), ('ROUTING', 'a'), ('GUARDRAIL', 'warn_in', 'INPUT', 'WARN'), ('MODEL_INVOCATION', 'j1', True, False), ('INPUT_TOKEN_PROCESSED', 'j1', True, False), ('OUTPUT_TOKEN_PROCESSED', 'j1', True, False), ('GUARDRAIL', 'soft_in', 'INPUT', 'SOFT_BLOCK')],
            'request_event': ('chat', 200, 'SUCCESS', None, True),
            'metrics_route': ['chat'],
            'log_routes': ['chat'],
        },
        id='responses_stream_soft_block',
    ),
    pytest.param(
        lambda g: g.chat(
            [gpt_a_completion('softout')], route='output', text='warnme'
        ),
        {
            'status': 200,
            'body': {'choices': [{'finish_reason': 'stop', 'index': 0, 'logprobs': None, 'message': {'content': 'This response has been blocked due to policy violation: soft_out', 'refusal': None, 'role': 'assistant', 'annotations': None, 'audio': None, 'function_call': None, 'tool_calls': None}}], 'model': 'output', 'object': 'chat.completion', 'metadata': None, 'moderation': None, 'service_tier': None, 'system_fingerprint': None, 'usage': {'completion_tokens': 5, 'prompt_tokens': 11, 'total_tokens': 16, 'completion_tokens_details': None, 'prompt_tokens_details': None}},
            'headers': {'X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-TRIGGERED': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-WARN': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-INPUT-WARN': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-WARN': 'true'},
            'upstream': ['api.openai.com/v1/chat/completions gpt-a'],
            'events': [('GUARDRAIL', 'warn_in', 'INPUT', 'WARN'), ('MODEL_INVOCATION', 'a', False, False), ('INPUT_TOKEN_PROCESSED', 'a', False, False), ('OUTPUT_TOKEN_PROCESSED', 'a', False, False), ('GUARDRAIL', 'soft_out', 'OUTPUT', 'SOFT_BLOCK')],
            'request_event': ('output', 200, 'SUCCESS', None, False),
            'metrics_route': ['output'],
            'log_routes': ['output', None],
        },
        id='chat_output_soft_block',
    ),
    pytest.param(
        lambda g: g.chat(
            [], route='output', text='warnme softme', stream=True
        ),
        {
            'status': 200,
            'body': [{'choices': [{'delta': {'content': 'I cannot process this request as it violates content policy: soft_in', 'role': 'assistant'}, 'finish_reason': 'stop', 'index': 0}], 'model': 'output', 'object': 'chat.completion.chunk'}, '[DONE]'],
            'headers': {'X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-INPUT-TRIGGERED': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-WARN': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-INPUT-WARN': 'true'},
            'upstream': [],
            'events': [('GUARDRAIL', 'warn_in', 'INPUT', 'WARN'), ('GUARDRAIL', 'soft_in', 'INPUT', 'SOFT_BLOCK')],
            'request_event': ('output', 200, 'SUCCESS', None, True),
            'metrics_route': ['output'],
            'log_routes': ['output'],
        },
        id='chat_buffered_input_soft_block',
    ),
    pytest.param(
        lambda g: g.chat(
            [gpt_a_stream('softout')], route='output', text='warnme', stream=True
        ),
        {
            'status': 400,
            'body': {'error': {'message': 'This response has been blocked due to policy violation: soft_out', 'type': 'guardrail_error', 'param': {'name': 'soft_out', 'type': 'CONTAINS', 'where': 'OUTPUT', 'behavior': 'SOFT_BLOCK', 'parameters': {'type': 'CHECK', 'values': ['softout'], 'ignore_case': False}, 'reason': {'action': 'soft_block'}}, 'code': 'guardrail_violation_bad_request'}},
            'headers': {'X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-TRIGGERED': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-WARN': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-INPUT-WARN': 'true', 'X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-WARN': 'true'},
            'upstream': ['api.openai.com/v1/chat/completions gpt-a'],
            'events': [('GUARDRAIL', 'warn_in', 'INPUT', 'WARN'), ('MODEL_INVOCATION', 'a', False, False), ('INPUT_TOKEN_PROCESSED', 'a', False, False), ('OUTPUT_TOKEN_PROCESSED', 'a', False, False), ('GUARDRAIL', 'soft_out', 'OUTPUT', 'SOFT_BLOCK')],
            'request_event': ('output', 400, 'HANDLED_ERROR', 'GuardrailBadRequest', True),
            'metrics_route': ['output'],
            'log_routes': ['output', None],
        },
        id='chat_buffered_output_soft_block',
    ),
    pytest.param(
        lambda g: g.embed([], texts=('warnme softme',)),
        {
            'status': 200,
            'body': {'data': [], 'model': 'embed', 'object': 'list', 'usage': {'prompt_tokens': 0, 'total_tokens': 0}, 'error': 'I cannot process this request as it violates content policy: soft_in'},
            'headers': {},
            'upstream': [],
            'events': [('GUARDRAIL', 'warn_in', 'INPUT', 'WARN'), ('GUARDRAIL', 'soft_in', 'INPUT', 'SOFT_BLOCK')],
            'request_event': ('embed', 200, 'SUCCESS', None, False),
            'metrics_route': ['embed'],
            'log_routes': ['embed', None],
        },
        id='embeddings_soft_block',
    ),
    pytest.param(
        lambda g: g.decide([], ticket='warnme softme'),
        {
            'status': 400,
            'body': {'error': {'message': 'I cannot process this request as it violates content policy: soft_in', 'type': 'guardrail_error', 'param': {'name': 'soft_in', 'type': 'CONTAINS', 'where': 'INPUT', 'behavior': 'SOFT_BLOCK', 'parameters': {'type': 'CHECK', 'values': ['softme'], 'ignore_case': False}}, 'code': 'guardrail_violation_bad_request'}},
            'headers': {'X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED': 'true'},
            'upstream': [],
            'events': [('GUARDRAIL', 'warn_in', 'INPUT', 'WARN'), ('GUARDRAIL', 'soft_in', 'INPUT', 'SOFT_BLOCK')],
            'request_event': ('agent', 400, 'HANDLED_ERROR', 'GuardrailBadRequest', False),
            'metrics_route': ['agent'],
            'log_routes': ['agent', None],
        },
        id='decision_soft_block',
    ),
    # What runs before a limit stops a request.
    pytest.param(
        lambda g: g.chat([], route='limited'),
        {
            'status': 429,
            'body': {'error': {'message': 'Input token limit exceeded: 3 tokens per 1 minute. Please retry after 60 seconds.', 'type': 'rate_limit_error', 'param': None, 'code': 'token_limit_rate_limited'}},
            'headers': {},
            'upstream': [],
            'events': [('TOKEN_INPUT_LIMIT',)],
            'request_event': ('limited', 429, 'HANDLED_ERROR', 'InputTokenLimitExceeded', False),
            'metrics_route': ['limited'],
            'log_routes': ['limited', None],
        },
        id='chat_over_limit',
    ),
    pytest.param(
        lambda g: g.chat([], route='limited', stream=True),
        {
            'status': 429,
            'body': {'error': {'message': 'Input token limit exceeded: 3 tokens per 1 minute. Please retry after 60 seconds.', 'type': 'rate_limit_error', 'param': None, 'code': 'token_limit_rate_limited'}},
            'headers': {},
            'upstream': [],
            'events': [('TOKEN_INPUT_LIMIT',)],
            'request_event': ('limited', 429, 'HANDLED_ERROR', 'InputTokenLimitExceeded', True),
            'metrics_route': ['limited'],
            'log_routes': ['limited', None],
        },
        id='chat_stream_over_limit',
    ),
    pytest.param(
        lambda g: g.chat(
            [], route='limited', text=WARN_AND_SOFT
        ),
        {
            'status': 429,
            'body': {'error': {'message': 'Input token limit exceeded: 3 tokens per 1 minute. Please retry after 60 seconds.', 'type': 'rate_limit_error', 'param': None, 'code': 'token_limit_rate_limited'}},
            'headers': {},
            'upstream': [],
            'events': [('TOKEN_INPUT_LIMIT',)],
            'request_event': ('limited', 429, 'HANDLED_ERROR', 'InputTokenLimitExceeded', False),
            'metrics_route': ['limited'],
            'log_routes': ['limited', None],
        },
        id='chat_soft_block_over_limit',
    ),
    pytest.param(
        lambda g: g.responses([], route='limited'),
        {
            'status': 429,
            'body': {'error': {'message': 'Input token limit exceeded: 3 tokens per 1 minute. Please retry after 60 seconds.', 'type': 'rate_limit_error', 'param': None, 'code': 'token_limit_rate_limited'}},
            'headers': {},
            'upstream': [],
            'events': [('TOKEN_INPUT_LIMIT',)],
            'request_event': ('limited', 429, 'HANDLED_ERROR', 'InputTokenLimitExceeded', False),
            'metrics_route': ['limited'],
            'log_routes': ['limited', None],
        },
        id='responses_over_limit',
    ),
    pytest.param(
        lambda g: g.responses(
            [], route='limited', text=WARN_AND_SOFT
        ),
        {
            'status': 429,
            'body': {'error': {'message': 'Input token limit exceeded: 3 tokens per 1 minute. Please retry after 60 seconds.', 'type': 'rate_limit_error', 'param': None, 'code': 'token_limit_rate_limited'}},
            'headers': {},
            'upstream': [],
            'events': [('TOKEN_INPUT_LIMIT',)],
            'request_event': ('limited', 429, 'HANDLED_ERROR', 'InputTokenLimitExceeded', False),
            'metrics_route': ['limited'],
            'log_routes': ['limited', None],
        },
        id='responses_soft_block_over_limit',
    ),
    pytest.param(
        lambda g: g.embed([], route='embed_limited'),
        {
            'status': 429,
            'body': {'error': {'message': 'Input token limit exceeded: 3 tokens per 1 minute. Please retry after 60 seconds.', 'type': 'rate_limit_error', 'param': None, 'code': 'token_limit_rate_limited'}},
            'headers': {},
            'upstream': [],
            'events': [('TOKEN_INPUT_LIMIT',)],
            'request_event': ('embed_limited', 429, 'HANDLED_ERROR', 'InputTokenLimitExceeded', False),
            'metrics_route': ['embed_limited'],
            'log_routes': ['embed_limited', None],
        },
        id='embeddings_over_limit',
    ),
    pytest.param(
        lambda g: g.transcribe(
            [], route='audio_limited', audio=LONG_WAV
        ),
        {
            'status': 429,
            'body': {'error': {'message': 'Audio duration limit exceeded: 1.0 seconds per 1 minute. Please retry after 60 seconds.', 'type': 'rate_limit_error', 'param': 'audio_limited', 'code': 'audio_duration_rate_limited'}},
            'headers': {},
            'upstream': [],
            'events': [('AUDIO_DURATION_LIMIT',)],
            'request_event': ('audio_limited', 429, 'HANDLED_ERROR', 'AudioDurationLimitExceeded', False),
            'metrics_route': ['audio_limited'],
            'log_routes': ['audio_limited', None],
        },
        id='transcription_over_limit',
    ),
    pytest.param(
        lambda g: g.transcribe(
            [], route='audio_limited', audio=LONG_WAV, stream=True
        ),
        {
            'status': 429,
            'body': {'error': {'message': 'Audio duration limit exceeded: 1.0 seconds per 1 minute. Please retry after 60 seconds.', 'type': 'rate_limit_error', 'param': 'audio_limited', 'code': 'audio_duration_rate_limited'}},
            'headers': {},
            'upstream': [],
            'events': [('AUDIO_DURATION_LIMIT',)],
            'request_event': ('audio_limited', 429, 'HANDLED_ERROR', 'AudioDurationLimitExceeded', True),
            'metrics_route': ['audio_limited'],
            'log_routes': ['audio_limited', None],
        },
        id='transcription_stream_over_limit',
    ),
    # Requests served: the route the metrics and the log lines carry.
    pytest.param(
        lambda g: g.chat([ROUTED, NOT_TRIGGERED, gpt_a_completion()]),
        {
            'status': 200,
            'body': {'choices': [{'finish_reason': 'stop', 'index': 0, 'logprobs': None, 'message': {'content': 'Paris is in France', 'refusal': None, 'role': 'assistant', 'annotations': None, 'audio': None, 'function_call': None, 'tool_calls': None}}], 'model': 'chat', 'object': 'chat.completion', 'metadata': None, 'moderation': None, 'service_tier': None, 'system_fingerprint': None, 'usage': {'completion_tokens': 5, 'prompt_tokens': 11, 'total_tokens': 16, 'completion_tokens_details': None, 'prompt_tokens_details': None}},
            'headers': {},
            'upstream': ['api.openai.com/v1/chat/completions gpt-r1', 'api.openai.com/v1/chat/completions gpt-j1', 'api.openai.com/v1/chat/completions gpt-a'],
            'events': [('MODEL_INVOCATION', 'r1', False, True), ('INPUT_TOKEN_PROCESSED', 'r1', False, True), ('OUTPUT_TOKEN_PROCESSED', 'r1', False, True), ('ROUTING', 'a'), ('MODEL_INVOCATION', 'j1', True, False), ('INPUT_TOKEN_PROCESSED', 'j1', True, False), ('OUTPUT_TOKEN_PROCESSED', 'j1', True, False), ('MODEL_INVOCATION', 'a', False, False), ('INPUT_TOKEN_PROCESSED', 'a', False, False), ('OUTPUT_TOKEN_PROCESSED', 'a', False, False)],
            'request_event': ('chat', 200, 'SUCCESS', None, False),
            'metrics_route': ['chat'],
            'log_routes': ['chat', None],
        },
        id='chat_ok',
    ),
    pytest.param(
        lambda g: g.chat(
            [gpt_a_stream()],
            route='chat_metered',
            stream=True,
            stream_options={'include_usage': True},
        ),
        {
            'status': 200,
            'body': [{'choices': [{'delta': {'role': 'assistant'}, 'index': 0}], 'model': 'chat_metered', 'object': 'chat.completion.chunk'}, {'choices': [{'delta': {'content': 'Paris', 'role': 'assistant'}, 'index': 0}], 'model': 'chat_metered', 'object': 'chat.completion.chunk'}, {'choices': [{'delta': {'content': ' is in France', 'role': 'assistant'}, 'index': 0}], 'model': 'chat_metered', 'object': 'chat.completion.chunk'}, {'choices': [{'delta': {'role': 'assistant'}, 'finish_reason': 'stop', 'index': 0}], 'model': 'chat_metered', 'object': 'chat.completion.chunk'}, {'choices': [{'delta': {'role': 'assistant'}, 'index': 0}], 'model': 'chat_metered', 'object': 'chat.completion.chunk', 'usage': {'completion_tokens': 5, 'prompt_tokens': 11, 'total_tokens': 16, 'completion_tokens_details': {'accepted_prediction_tokens': 0, 'audio_tokens': 0, 'reasoning_tokens': 0, 'rejected_prediction_tokens': 0}, 'prompt_tokens_details': {'audio_tokens': 0, 'cached_tokens': 0}}}, {'choices': [{'delta': {'role': 'assistant'}, 'index': 0}], 'model': 'chat_metered', 'object': 'chat.completion.chunk'}, {'choices': [], 'model': 'chat_metered', 'object': 'chat.completion.chunk', 'usage': {'completion_tokens': 5, 'prompt_tokens': 11, 'total_tokens': 16, 'completion_tokens_details': {'accepted_prediction_tokens': 0, 'audio_tokens': 0, 'reasoning_tokens': 0, 'rejected_prediction_tokens': 0}, 'prompt_tokens_details': {'audio_tokens': 0, 'cached_tokens': 0}}}, '[DONE]'],
            'headers': {},
            'upstream': ['api.openai.com/v1/chat/completions gpt-a'],
            'events': [('MODEL_INVOCATION', 'a', False, False), ('INPUT_TOKEN_PROCESSED', 'a', False, False), ('OUTPUT_TOKEN_PROCESSED', 'a', False, False)],
            'request_event': ('chat_metered', 200, 'SUCCESS', None, True),
            'metrics_route': ['chat_metered'],
            'log_routes': ['chat_metered'],
        },
        id='chat_live_stream_with_usage',
    ),
    pytest.param(
        lambda g: g.embed([upstream.openai_embeddings(count=1)]),
        {
            'status': 200,
            'body': {'data': [{'embedding': [0.1, 0.11, 0.12, 0.13], 'index': 0, 'object': 'embedding'}], 'model': 'text-embedding-3-small', 'object': 'list', 'usage': {'prompt_tokens': 4, 'total_tokens': 4}},
            'headers': {},
            'upstream': ['api.openai.com/v1/embeddings text-embedding-3-small'],
            'events': [('MODEL_INVOCATION', 'e1', False, False), ('INPUT_TOKEN_PROCESSED', 'e1', False, False)],
            'request_event': ('embed', 200, 'SUCCESS', None, False),
            'metrics_route': ['embed'],
            'log_routes': ['embed', None],
        },
        id='embeddings_ok',
    ),
    pytest.param(
        lambda g: g.transcribe([_transcription()]),
        {
            'status': 200,
            'body': {'text': 'hello', 'languages': None, 'logprobs': None, 'usage': {'input_tokens': 10, 'output_tokens': 3, 'total_tokens': 13, 'type': 'tokens', 'input_token_details': {'audio_tokens': 8, 'text_tokens': 2}}},
            'headers': {},
            'upstream': ['api.openai.com/v1/audio/transcriptions'],
            'events': [('MODEL_INVOCATION', 't1', False, False), ('INPUT_TOKEN_PROCESSED', 't1', False, False), ('INPUT_TOKEN_PROCESSED', 't1', False, False), ('OUTPUT_TOKEN_PROCESSED', 't1', False, False)],
            'request_event': ('audio', 200, 'SUCCESS', None, False),
            'metrics_route': ['audio'],
            'log_routes': ['audio', None],
        },
        id='transcription_ok',
    ),
    pytest.param(
        lambda g: g.decide([_typesafe()]),
        {
            'status': 200,
            'body': {'answers': {'urgent': {'type': 'noul', 'noul': 0.9}}, 'model': 'd1', 'usage': {'input_tokens': 40, 'output_tokens': 2}},
            'headers': {},
            'upstream': ['api.typesafe.ai/v1/systemone jev-latest'],
            'events': [('MODEL_INVOCATION', 'd1', False, False), ('INPUT_TOKEN_PROCESSED', 'd1', False, False), ('OUTPUT_TOKEN_PROCESSED', 'd1', False, False)],
            'request_event': ('agent', 200, 'SUCCESS', None, False),
            'metrics_route': ['agent'],
            'log_routes': ['agent', None],
        },
        id='decision_ok',
    ),
    # A key that is not a member of the route.
    pytest.param(
        _no_member(lambda g: g.chat([])),
        {
            'status': 401,
            'body': {'error': {'message': 'Incorrect API key provided.', 'type': 'authentication_error', 'param': None, 'code': 'key_invalid_unauthorized'}},
            'headers': {},
            'upstream': [],
            'events': [],
            'request_event': ('chat', 401, 'HANDLED_ERROR', 'InvalidApiKey', False),
            'metrics_route': ['chat'],
            'log_routes': ['chat', None],
        },
        id='chat_not_member',
    ),
    pytest.param(
        _no_member(lambda g: g.responses([])),
        {
            'status': 401,
            'body': {'error': {'message': 'Incorrect API key provided.', 'type': 'authentication_error', 'param': None, 'code': 'key_invalid_unauthorized'}},
            'headers': {},
            'upstream': [],
            'events': [],
            'request_event': ('chat', 401, 'HANDLED_ERROR', 'InvalidApiKey', False),
            'metrics_route': ['chat'],
            'log_routes': ['chat', None],
        },
        id='responses_not_member',
    ),
    pytest.param(
        _no_member(lambda g: g.embed([])),
        {
            'status': 401,
            'body': {'error': {'message': 'Incorrect API key provided.', 'type': 'authentication_error', 'param': None, 'code': 'key_invalid_unauthorized'}},
            'headers': {},
            'upstream': [],
            'events': [],
            'request_event': ('embed', 401, 'HANDLED_ERROR', 'InvalidApiKey', False),
            'metrics_route': ['embed'],
            'log_routes': [None],
        },
        id='embeddings_not_member',
    ),
    pytest.param(
        _no_member(lambda g: g.transcribe([])),
        {
            'status': 401,
            'body': {'error': {'message': 'Incorrect API key provided.', 'type': 'authentication_error', 'param': None, 'code': 'key_invalid_unauthorized'}},
            'headers': {},
            'upstream': [],
            'events': [],
            'request_event': ('audio', 401, 'HANDLED_ERROR', 'InvalidApiKey', False),
            'metrics_route': ['audio'],
            'log_routes': [None],
        },
        id='transcription_not_member',
    ),
    pytest.param(
        _no_member(lambda g: g.decide([])),
        {
            'status': 401,
            'body': {'error': {'message': 'Incorrect API key provided.', 'type': 'authentication_error', 'param': None, 'code': 'key_invalid_unauthorized'}},
            'headers': {},
            'upstream': [],
            'events': [],
            'request_event': ('agent', 401, 'HANDLED_ERROR', 'InvalidApiKey', False),
            'metrics_route': ['agent'],
            'log_routes': [None],
        },
        id='decision_not_member',
    ),
    # No key: the metrics' route label of a request that fails auth.
    pytest.param(
        lambda g: g.chat([], key=False),
        {
            'status': 401,
            'body': {'error': {'message': 'Missing API key', 'type': 'authentication_error', 'param': None, 'code': 'key_missing_unauthorized'}},
            'headers': {},
            'upstream': [],
            'events': [],
            'request_event': ('chat', 401, 'HANDLED_ERROR', 'MissingApiKey', False),
            'metrics_route': ['chat'],
            'log_routes': [None],
        },
        id='chat_no_key',
    ),
    pytest.param(
        lambda g: g.responses([], key=False),
        {
            'status': 401,
            'body': {'error': {'message': 'Missing API key', 'type': 'authentication_error', 'param': None, 'code': 'key_missing_unauthorized'}},
            'headers': {},
            'upstream': [],
            'events': [],
            'request_event': ('chat', 401, 'HANDLED_ERROR', 'MissingApiKey', False),
            'metrics_route': ['chat'],
            'log_routes': [None],
        },
        id='responses_no_key',
    ),
    pytest.param(
        lambda g: g.embed([], key=False),
        {
            'status': 401,
            'body': {'error': {'message': 'Missing API key', 'type': 'authentication_error', 'param': None, 'code': 'key_missing_unauthorized'}},
            'headers': {},
            'upstream': [],
            'events': [],
            'request_event': ('embed', 401, 'HANDLED_ERROR', 'MissingApiKey', False),
            'metrics_route': ['embed'],
            'log_routes': [None],
        },
        id='embeddings_no_key',
    ),
    pytest.param(
        lambda g: g.transcribe([], key=False),
        {
            'status': 401,
            'body': {'error': {'message': 'Missing API key', 'type': 'authentication_error', 'param': None, 'code': 'key_missing_unauthorized'}},
            'headers': {},
            'upstream': [],
            'events': [],
            'request_event': ('audio', 401, 'HANDLED_ERROR', 'MissingApiKey', False),
            'metrics_route': ['audio'],
            'log_routes': [None],
        },
        id='transcription_no_key',
    ),
    pytest.param(
        lambda g: g.decide([], key=False),
        {
            'status': 401,
            'body': {'error': {'message': 'Missing API key', 'type': 'authentication_error', 'param': None, 'code': 'key_missing_unauthorized'}},
            'headers': {},
            'upstream': [],
            'events': [],
            'request_event': ('agent', 401, 'HANDLED_ERROR', 'MissingApiKey', False),
            'metrics_route': ['agent'],
            'log_routes': [None],
        },
        id='decision_no_key',
    ),
    # An unknown route.
    pytest.param(
        lambda g: g.chat([], route='nowhere'),
        {
            'status': 400,
            'body': {'error': {'message': 'The route name [proj/nowhere] was not found in the config', 'type': 'gateway_error', 'param': None, 'code': 'gateway_bad_request'}},
            'headers': {},
            'upstream': [],
            'events': [],
            'request_event': ('', 400, 'HANDLED_ERROR', 'GatewayBadRequest', False),
            'metrics_route': ['unknown'],
            'log_routes': [None],
        },
        id='chat_unknown_route',
    ),
    pytest.param(
        lambda g: g.embed([], route='nowhere'),
        {
            'status': 400,
            'body': {'error': {'message': 'The route name [proj/nowhere] was not found in the config', 'type': 'gateway_error', 'param': None, 'code': 'gateway_bad_request'}},
            'headers': {},
            'upstream': [],
            'events': [],
            'request_event': ('', 400, 'HANDLED_ERROR', 'GatewayBadRequest', False),
            'metrics_route': ['unknown'],
            'log_routes': [None],
        },
        id='embeddings_unknown_route',
    ),
]
# fmt: on


@pytest.mark.parametrize(('send', 'expected'), GOLDEN)
async def test_golden(gateway, send, expected):
    response = send(gateway)

    assert _snapshot(gateway, response) == expected


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


# fmt: off
SPAN_CASES = [
    pytest.param(
        lambda g: g.chat([ROUTED, NOT_TRIGGERED, gpt_a_completion()]),
        [('auth_api_key.task', 'chat_completions.workflow'), ('ChatOpenAI.chat', 'select_model.task'), ('select_model.task', 'chat_completions.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('ChatOpenAI.chat', 'check_judge.task'), ('check_judge.task', 'apply_check_guardrails.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('apply_check_guardrails.workflow', 'chat_completions.workflow'), ('ChatOpenAI.chat', 'llm_complete.task'), ('llm_complete.task', 'chat_completions.workflow'), ('chat_completions.workflow', None)],
        id='chat',
    ),
    pytest.param(
        lambda g: g.chat(
            [ROUTED, NOT_TRIGGERED, gpt_a_stream()], stream=True
        ),
        [('auth_api_key.task', 'chat_completions.workflow'), ('ChatOpenAI.chat', 'select_model.task'), ('select_model.task', 'chat_completions.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('ChatOpenAI.chat', 'check_judge.task'), ('check_judge.task', 'apply_check_guardrails.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('apply_check_guardrails.workflow', 'chat_completions.workflow'), ('chat_completions.workflow', None), ('ChatOpenAI.chat', 'llm_stream.task'), ('llm_stream.task', 'chat_completions.workflow')],
        id='chat_live_stream',
    ),
    pytest.param(
        lambda g: g.chat([gpt_a_stream()], route='output', stream=True),
        [('auth_api_key.task', 'chat_completions.workflow'), ('select_model.task', 'chat_completions.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('apply_check_guardrails.workflow', 'chat_completions.workflow'), ('ChatOpenAI.chat', 'llm_stream.task'), ('llm_stream.task', 'stream_with_output_guardrails.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('apply_check_guardrails.workflow', 'stream_with_output_guardrails.workflow'), ('stream_with_output_guardrails.workflow', 'chat_completions.workflow'), ('chat_completions.workflow', None)],
        id='chat_buffered_stream',
    ),
    pytest.param(
        lambda g: g.chat([gpt_a_completion()], route='output'),
        [('auth_api_key.task', 'chat_completions.workflow'), ('select_model.task', 'chat_completions.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('apply_check_guardrails.workflow', 'chat_completions.workflow'), ('ChatOpenAI.chat', 'llm_complete.task'), ('llm_complete.task', 'chat_completions.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('apply_check_guardrails.workflow', 'apply_output_guardrails.workflow'), ('apply_output_guardrails.workflow', 'chat_completions.workflow'), ('chat_completions.workflow', None)],
        id='chat_output',
    ),
    pytest.param(
        lambda g: g.responses(
            [ROUTED, NOT_TRIGGERED, upstream.openai_response('Paris', model='gpt-a')]
        ),
        [('auth_api_key.task', 'responses.workflow'), ('ChatOpenAI.chat', 'select_model.task'), ('select_model.task', 'responses.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('ChatOpenAI.chat', 'check_judge.task'), ('check_judge.task', 'apply_check_guardrails.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('apply_check_guardrails.workflow', 'responses.workflow'), ('ChatOpenAI.chat', 'llm_complete_responses.task'), ('llm_complete_responses.task', 'responses.workflow'), ('apply_responses_output_guardrails.workflow', 'responses.workflow'), ('responses.workflow', None)],
        id='responses',
    ),
    pytest.param(
        lambda g: g.responses(
            [
                ROUTED,
                NOT_TRIGGERED,
                upstream.openai_response_stream(model='gpt-a'),
            ],
            stream=True,
        ),
        [('auth_api_key.task', 'responses.workflow'), ('ChatOpenAI.chat', 'select_model.task'), ('select_model.task', 'responses.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('ChatOpenAI.chat', 'check_judge.task'), ('check_judge.task', 'apply_check_guardrails.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('apply_check_guardrails.workflow', 'responses.workflow'), ('responses.workflow', None), ('ChatOpenAI.chat', 'llm_stream_responses.task'), ('llm_stream_responses.task', 'responses.workflow')],
        id='responses_stream',
    ),
    pytest.param(
        lambda g: g.embed([upstream.openai_embeddings(count=1)]),
        [('auth_api_key.task', 'embeddings.workflow'), ('select_embedding_model.task', 'embeddings.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('apply_check_guardrails.workflow', 'embeddings.workflow'), ('llm_embed.task', 'embeddings.workflow'), ('embeddings.workflow', None)],
        id='embeddings',
    ),
    pytest.param(
        lambda g: g.transcribe([_transcription()]),
        [('auth_api_key.task', 'audio_transcriptions.workflow'), ('select_transcription_model.task', 'audio_transcriptions.workflow'), ('llm_transcribe.task', 'audio_transcriptions.workflow'), ('audio_transcriptions.workflow', None)],
        id='transcription',
    ),
    pytest.param(
        lambda g: g.decide([_typesafe()]),
        [('auth_api_key.task', 'decision_model.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('check_contains.task', 'apply_check_guardrails.workflow'), ('apply_check_guardrails.workflow', 'decision_model.workflow'), ('decide.task', 'decision_model.workflow'), ('decision_model.workflow', None)],
        id='decision',
    ),
    pytest.param(
        lambda g: g.chat([gpt_a_completion()], route='chat_metered'),
        [('auth_api_key.task', 'chat_completions.workflow'), ('check_token_input_limit.task', 'check_limiters.task'), ('check_limiters.task', 'chat_completions.workflow'), ('select_model.task', 'chat_completions.workflow'), ('ChatOpenAI.chat', 'llm_complete.task'), ('llm_complete.task', 'chat_completions.workflow'), ('chat_completions.workflow', None)],
        id='chat_metered',
    ),
    pytest.param(
        lambda g: g.chat(
            [gpt_a_stream()], route='chat_metered', stream=True
        ),
        [('auth_api_key.task', 'chat_completions.workflow'), ('check_token_input_limit.task', 'check_limiters.task'), ('check_limiters.task', 'chat_completions.workflow'), ('select_model.task', 'chat_completions.workflow'), ('chat_completions.workflow', None), ('ChatOpenAI.chat', 'llm_stream.task'), ('llm_stream.task', 'chat_completions.workflow')],
        id='chat_stream_metered',
    ),
    pytest.param(
        lambda g: g.responses(
            [upstream.openai_response('Paris', model='gpt-a')], route='chat_metered'
        ),
        [('auth_api_key.task', 'responses.workflow'), ('check_token_input_limit.task', 'check_limiters.task'), ('check_limiters.task', 'responses.workflow'), ('select_model.task', 'responses.workflow'), ('ChatOpenAI.chat', 'llm_complete_responses.task'), ('llm_complete_responses.task', 'responses.workflow'), ('apply_responses_output_guardrails.workflow', 'responses.workflow'), ('responses.workflow', None)],
        id='responses_metered',
    ),
    pytest.param(
        lambda g: g.embed(
            [upstream.openai_embeddings(count=1)], route='embed_metered'
        ),
        [('auth_api_key.task', 'embeddings.workflow'), ('select_embedding_model.task', 'embeddings.workflow'), ('check_token_input_limit.task', 'check_embedding_limiters.task'), ('check_embedding_limiters.task', 'embeddings.workflow'), ('llm_embed.task', 'embeddings.workflow'), ('embeddings.workflow', None)],
        id='embeddings_metered',
    ),
    pytest.param(
        lambda g: g.transcribe(
            [_transcription()], route='audio_metered'
        ),
        [('auth_api_key.task', 'audio_transcriptions.workflow'), ('select_transcription_model.task', 'audio_transcriptions.workflow'), ('check_audio_duration_limit.task', 'audio_transcriptions.workflow'), ('llm_transcribe.task', 'audio_transcriptions.workflow'), ('audio_transcriptions.workflow', None)],
        id='transcription_metered',
    ),
    pytest.param(
        lambda g: g.transcribe(
            [_transcription_stream()], route='audio_metered', stream=True
        ),
        [('auth_api_key.task', 'audio_transcriptions.workflow'), ('select_transcription_model.task', 'audio_transcriptions.workflow'), ('check_audio_duration_limit.task', 'audio_transcriptions.workflow'), ('audio_transcriptions.workflow', None), ('llm_transcribe_stream.task', 'audio_transcriptions.workflow')],
        id='transcription_stream_metered',
    ),
    pytest.param(
        lambda g: g.decide([_typesafe()], route='agent_metered'),
        [('auth_api_key.task', 'decision_model.workflow'), ('check_token_input_room.task', 'decision_model.workflow'), ('decide.task', 'decision_model.workflow'), ('decision_model.workflow', None)],
        id='decision_metered',
    ),
]
# fmt: on


# The span scenarios, by name, for the tests below that read every span.
SPAN_SCENARIOS = {case.id: case.values[0] for case in SPAN_CASES}


@pytest.mark.parametrize(('send', 'expected'), SPAN_CASES)
async def test_spans(gateway, span_collector, send, expected):
    span_collector.spans.clear()
    span_collector.on = True
    try:
        response = send(gateway)
    finally:
        span_collector.on = False

    assert response.status_code == 200
    assert _span_tree(span_collector.spans) == expected


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
        [gpt_a_stream('softout')], route='output_metered', stream=True
    ),
    'chat_buffered_block': lambda g: g.chat(
        [gpt_a_stream('blockout')], route='output_metered', stream=True
    ),
    'chat_block': lambda g: g.chat(
        [gpt_a_completion('blockout')], route='output_metered'
    ),
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
