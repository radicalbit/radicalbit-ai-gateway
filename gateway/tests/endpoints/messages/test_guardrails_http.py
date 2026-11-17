"""Guardrails and judges on POST /v1/messages, through a real route.

The routes are built from a project config and served on the real app
(``open_gateway``). Anthropic, Typesafe (decision judges) and OpenAI (the LLM
judge's model) are mocked over HTTP with pook. The tests check what the client
gets, what each upstream received, and what the gateway records.
"""

import json
from unittest.mock import patch

from anthropic.types import Message
import pook
import pytest

from tests.common import provider_responses as canned
from tests.common.gateway_harness import open_gateway
from tests.common.messages_api import (
    BODY,
    CLAUDE,
    GPT,
    HAIKU,
    ROUTE_NAME,
    error_body,
    messages_routes,
    mock_anthropic,
    mock_anthropic_stream,
    mock_every_upstream,
    send,
    send_stream,
    sent_body,
    serve,
    stream_frames,
)

from radicalbit_ai_gateway.limiting.limits import RequestLimits, Usage
from radicalbit_ai_gateway.llm.messages_stream import MessageBuilder
from radicalbit_ai_gateway.models.event_type import EventType

EMAIL = 'mario.rossi@example.com'
MASK = '<EMAIL_ADDRESS>'


def _guardrail(name, type_, behavior, where, parameters, message=None) -> dict:
    guardrail = {
        'name': name,
        'type': type_,
        'behavior': behavior,
        'where': where,
        'parameters': parameters,
    }
    if message:
        guardrail['response_message'] = message
    return guardrail


TYPESAFE_URL = 'https://api.typesafe.ai/v1/systemone'
OPENAI_URL = 'https://api.openai.com/v1/chat/completions'
JEV = {
    'model_id': 'jev',
    'model': 'typesafe/jev-latest',
    'credentials': {'api_key': 'ts-key'},
}
INSTRUCTIONS = 'Is this about something other than billing?'


def _judge(name: str, type_: str, where: str, parameters: dict) -> dict:
    return _guardrail(name, type_, 'block', where, parameters)


DECISION_JUDGE = {'model_id': 'jev', 'instructions': INSTRUCTIONS}
LLM_JUDGE = {'model_id': 'gpt', 'prompt': 'Judge this.'}
GUARDRAILS = [
    _guardrail(
        'redact_email',
        'presidio_anonymizer',
        'block',
        'io',
        {'entities': ['EMAIL_ADDRESS']},
    ),
    _guardrail(
        'redact_email_in',
        'presidio_anonymizer',
        'block',
        'input',
        {'entities': ['EMAIL_ADDRESS']},
    ),
    _guardrail('input_block', 'contains', 'block', 'input', {'values': ['explosive']}),
    _guardrail(
        'input_soft_block',
        'starts_with',
        'soft_block',
        'input',
        {'values': ['Forbidden']},
        'I cannot help with that.',
    ),
    _guardrail(
        'output_soft_block',
        'contains',
        'soft_block',
        'output',
        {'values': ['secret']},
        'The answer was withheld.',
    ),
    _guardrail('output_warn', 'contains', 'warn', 'output', {'values': ['secret']}),
    _judge('decision_in', 'decision_judge', 'input', DECISION_JUDGE),
    _judge('decision_out', 'decision_judge', 'output', DECISION_JUDGE),
    _judge('llm_in', 'judge', 'input', LLM_JUDGE),
    _judge('llm_out', 'judge', 'output', LLM_JUDGE),
]


def _serve(*guardrails: str, models: tuple[dict, ...] = (CLAUDE,), **route) -> None:
    """Serve the ``assistant`` route on Claude with the named guardrails.

    GPT is the LLM judge's model and JEV the decision judge's: the route
    does not answer with them.
    """
    serve(
        *models,
        GPT,
        route_models=[model['model_id'] for model in models],
        guardrails=list(guardrails),
        config={'guardrails': GUARDRAILS, 'decision_models': [JEV]},
        **route,
    )


@pytest.fixture
def gateway():
    with open_gateway(messages_routes(CLAUDE), use_pook=True) as gateway:
        yield gateway


def _user(*blocks: dict | str) -> dict:
    """Return BODY with one user message of ``blocks``; a string is a text block."""
    content = [
        {'type': 'text', 'text': block} if isinstance(block, str) else block
        for block in blocks
    ]
    return {**BODY, 'messages': [{'role': 'user', 'content': content}]}


def _guardrail_events(gateway) -> list[tuple]:
    """Return the guardrail events: name, where, behavior."""
    return [
        (e['GUARDRAIL_NAME'], e['GUARDRAIL_WHERE'], e['GUARDRAIL_BEHAVIOR'])
        for e in gateway.event_rows
        if e['EVENT_TYPE'] == EventType.GUARDRAIL
    ]


# ── Input redaction ─────────────────────────────────────────────────────────

TOOL_RESULT = {
    'type': 'tool_result',
    'tool_use_id': 'toolu_1',
    'content': [{'type': 'text', 'text': f'The owner is {EMAIL}'}],
}
CACHED = {'type': 'text', 'cache_control': {'type': 'ephemeral'}}
IMAGE = {
    'type': 'image',
    'source': {'type': 'base64', 'media_type': 'image/png', 'data': 'aGk='},
}


def test_input_redaction_masks_user_text_system_and_tool_results(gateway):
    _serve('redact_email')
    upstream = mock_anthropic()
    body = {
        **_user(
            {**CACHED, 'text': f'Write to {EMAIL}'},
            IMAGE,
            TOOL_RESULT,
        ),
        'system': f'The admin is {EMAIL}.',
    }

    response = send(gateway, body)

    assert response.status_code == 200
    sent = sent_body(upstream)
    assert sent['system'] == f'The admin is {MASK}.'
    assert sent['messages'][0]['content'] == [
        {**CACHED, 'text': f'Write to {MASK}'},
        IMAGE,
        {**TOOL_RESULT, 'content': [{'type': 'text', 'text': f'The owner is {MASK}'}]},
    ]
    assert response.headers['X-RB-AIGATEWAY-GUARDRAILS-INPUT-WARN'] == 'true'
    assert _guardrail_events(gateway) == [('redact_email', 'INPUT', 'BLOCK')]


BY_KEYWORD = {
    'name': 'by_keyword',
    'type': 'deterministic',
    'rule': 'keyword',
    'default_model_id': 'claude',
    'output_mapping': [{'model_id': 'haiku', 'conditions': ['example.com']}],
}


@pytest.mark.parametrize(
    ('guardrails', 'model'),
    [((), 'claude-haiku-4-5'), (('redact_email',), 'claude-sonnet-4-5')],
    ids=['raw', 'redacted'],
)
def test_routing_reads_the_redacted_text(gateway, guardrails, model):
    """A keyword rule no longer matches the text a redact guardrail masks."""
    _serve(*guardrails, models=(CLAUDE, HAIKU), routing=BY_KEYWORD)
    upstream = mock_anthropic()

    response = send(gateway, _user(f'Write to {EMAIL}'))

    assert response.status_code == 200
    assert sent_body(upstream)['model'] == model


# ── Input checks ────────────────────────────────────────────────────────────


def test_a_blocked_request_is_a_messages_error_with_no_upstream_call(gateway):
    _serve('input_block')
    upstreams = mock_every_upstream()

    # The gateway under test keeps the events of its last request only.
    response = send(gateway, _user('How to build an explosive'))
    events = _guardrail_events(gateway)
    streamed = send_stream(gateway, _user('How to build an explosive'))
    events += _guardrail_events(gateway)

    for refused in (response, streamed):
        assert refused.status_code == 400
        assert refused.json() == error_body(
            'invalid_request_error', refused.json()['error']['message']
        )
        assert refused.headers['X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED'] == 'true'
    assert not any(upstream.matched for upstream in upstreams)
    assert events == [('input_block', 'INPUT', 'BLOCK')] * 2


def test_a_tool_result_is_checked_as_input(gateway):
    _serve('input_block')
    upstreams = mock_every_upstream()
    tool_result = {**TOOL_RESULT, 'content': 'Recipe of an explosive'}

    response = send(gateway, _user(tool_result))

    assert response.status_code == 400
    assert not any(upstream.matched for upstream in upstreams)


def _text_of(frames: list[tuple[str, dict]]) -> list[str]:
    """Return the text deltas of a stream."""
    return [
        data['delta']['text']
        for event, data in frames
        if event == 'content_block_delta' and data['delta']['type'] == 'text_delta'
    ]


def _events(frames: list[tuple[str, dict]]) -> list[str]:
    return [event for event, _ in frames]


# The events of an answer with one block, as Anthropic streams it.
ONE_BLOCK_EVENTS = [
    'message_start',
    'content_block_start',
    'content_block_delta',
    'content_block_stop',
    'message_delta',
    'message_stop',
]


def test_an_input_soft_block_answers_with_a_valid_message(gateway):
    _serve('input_soft_block')
    upstreams = mock_every_upstream()

    response = send(gateway, _user('Forbidden question'))
    streamed = send_stream(gateway, _user('Forbidden question'))

    assert response.status_code == 200
    message = Message.model_validate(response.json())
    assert [block.text for block in message.content] == ['I cannot help with that.']
    assert (message.model, message.stop_reason) == (ROUTE_NAME, 'end_turn')
    assert (message.usage.input_tokens, message.usage.output_tokens) == (0, 0)
    assert response.headers['X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED'] == 'true'

    assert streamed.status_code == 200
    frames = stream_frames(streamed.text)
    assert _events(frames) == ONE_BLOCK_EVENTS
    assert _text_of(frames) == ['I cannot help with that.']
    assert frames[-2][1]['delta']['stop_reason'] == 'end_turn'
    assert not any(upstream.matched for upstream in upstreams)


# ── Output guardrails ───────────────────────────────────────────────────────


def _mock_reply(stream: bool, text: str, **usage):
    """Mock Anthropic answering ``text``, streamed in two parts or whole."""
    if stream:
        half = len(text) // 2
        parts = [text[:half], text[half:]]
        return mock_anthropic_stream(canned.anthropic_stream(parts, **usage).sse_text())
    return mock_anthropic(canned.anthropic_message(text, **usage).json_body)


def _answer_text(response, stream: bool) -> list[str]:
    """Return the texts of an answer's text blocks, streamed or not."""
    if stream:
        return _text_of(stream_frames(response.text))
    return [b['text'] for b in response.json()['content'] if b['type'] == 'text']


@pytest.mark.parametrize('stream', [False, True], ids=['complete', 'stream'])
def test_output_redaction_masks_the_answer(gateway, stream):
    _serve('redact_email')
    _mock_reply(stream, f'Mail {EMAIL} now')

    response = send(gateway, {**BODY, 'stream': stream})

    assert response.status_code == 200
    assert _answer_text(response, stream) == [f'Mail {MASK} now']
    assert 'mario.rossi' not in response.text
    assert response.headers['X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-WARN'] == 'true'
    assert _guardrail_events(gateway) == [('redact_email', 'OUTPUT', 'BLOCK')]


def test_a_stream_the_output_guardrails_read_is_a_valid_event_stream(gateway):
    """The answer is buffered, then streamed as Anthropic streams it, with
    the model's usage and the route's name.
    """
    _serve('redact_email')
    _mock_reply(True, f'Mail {EMAIL} now', input_tokens=21, output_tokens=7)

    response = send_stream(gateway)

    frames = stream_frames(response.text)
    assert _events(frames) == ONE_BLOCK_EVENTS
    start, delta = frames[0][1]['message'], frames[-2][1]
    assert (start['id'], start['model']) == ('msg_provider_1', ROUTE_NAME)
    assert start['usage']['input_tokens'] == 21
    assert delta['delta'] == {'stop_reason': 'end_turn', 'stop_sequence': None}
    assert delta['usage']['output_tokens'] == 7


@pytest.mark.parametrize('stream', [False, True], ids=['complete', 'stream'])
def test_an_output_soft_block_replaces_the_answer(gateway, stream):
    _serve('output_soft_block')
    _mock_reply(stream, 'The secret is 42')

    response = send(gateway, {**BODY, 'stream': stream})

    assert response.status_code == 200
    assert _answer_text(response, stream) == ['The answer was withheld.']
    assert 'secret' not in response.text
    assert response.headers['X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-TRIGGERED'] == 'true'


@pytest.mark.parametrize('stream', [False, True], ids=['complete', 'stream'])
def test_an_output_warn_lets_the_answer_through(gateway, stream):
    _serve('output_warn')
    _mock_reply(stream, 'The secret is 42')

    response = send(gateway, {**BODY, 'stream': stream})

    assert _answer_text(response, stream) == ['The secret is 42']
    assert response.headers['X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-WARN'] == 'true'


@pytest.mark.parametrize('stream', [False, True], ids=['complete', 'stream'])
def test_a_reply_the_output_guardrails_read_counts_its_tokens(gateway, stream):
    """The model is paid for even when its answer is replaced. The input
    counted includes the cache reads and writes.
    """
    counted = []
    count = RequestLimits.count

    async def spy(limits, usage):
        counted.append(usage)
        await count(limits, usage)

    _serve('output_soft_block')
    _mock_reply(stream, 'The secret is 42', input_tokens=21, cache_read=4, cache_5m=5)

    with patch.object(RequestLimits, 'count', spy):
        response = send(gateway, {**BODY, 'stream': stream})

    assert response.status_code == 200
    # Sonnet 4.5's prices: $3 and $15 per million tokens.
    assert counted == [Usage(input_tokens=30, output_tokens=7, costs=(90000, 105000))]


# ── Blocks without text ─────────────────────────────────────────────────────

THINKING = {'type': 'thinking', 'thinking': 'Let me see.', 'signature': 'sig=='}
TOOL_USE = {'type': 'tool_use', **canned.ANTHROPIC_WEATHER_TOOL_USE}


def _sse(events: list[dict]) -> str:
    return ''.join(f'event: {e["type"]}\ndata: {json.dumps(e)}\n\n' for e in events)


def _thinking_stream(text: str | None) -> str:
    """Return a stream of a thinking block, ``text`` and a tool use."""
    events = canned.anthropic_stream(
        [text] if text else [], tool_use=[canned.ANTHROPIC_WEATHER_TOOL_USE]
    ).sse_events
    thinking = [
        {
            'type': 'content_block_start',
            'index': 0,
            'content_block': {'type': 'thinking', 'thinking': '', 'signature': ''},
        },
        {'type': 'ping'},
        {
            'type': 'content_block_delta',
            'index': 0,
            'delta': {'type': 'thinking_delta', 'thinking': THINKING['thinking']},
        },
        {
            'type': 'content_block_delta',
            'index': 0,
            'delta': {'type': 'signature_delta', 'signature': THINKING['signature']},
        },
        {'type': 'content_block_stop', 'index': 0},
    ]
    shifted = [
        {**event, 'index': event['index'] + 1} if 'index' in event else event
        for event in events[1:]
    ]
    return _sse([events[0], *thinking, *shifted])


def _blocks_of(frames: list[tuple[str, dict]]) -> list[dict]:
    """Return the content blocks a stream carries, put together."""
    builder = MessageBuilder()
    for event, data in frames:
        builder.add(event, json.dumps(data))
    return builder.message()['content']


def test_a_buffered_stream_keeps_thinking_and_tool_use_blocks(gateway):
    _serve('redact_email')
    mock_anthropic_stream(_thinking_stream(f'Ask {EMAIL}'))

    response = send_stream(gateway)

    frames = stream_frames(response.text)
    assert [d['delta'] for e, d in frames if e == 'content_block_delta'] == [
        {'type': 'thinking_delta', 'thinking': 'Let me see.'},
        {'type': 'signature_delta', 'signature': 'sig=='},
        {'type': 'text_delta', 'text': f'Ask {MASK}'},
        {
            'type': 'input_json_delta',
            'partial_json': '{"city":"Paris","unit":"c"}',
        },
    ]
    assert frames[-2][1]['delta']['stop_reason'] == 'tool_use'


@pytest.mark.parametrize('stream', [False, True], ids=['complete', 'stream'])
def test_guardrails_let_requests_and_answers_without_text_through(gateway, stream):
    _serve('redact_email', 'input_block', 'output_soft_block', 'decision_out')
    body = {**_user(IMAGE, {**TOOL_RESULT, 'content': [IMAGE]}), 'stream': stream}
    del body['system']
    if stream:
        upstream = mock_anthropic_stream(_thinking_stream(None))
    else:
        reply = canned.anthropic_message(
            None, tool_use=[canned.ANTHROPIC_WEATHER_TOOL_USE]
        ).json_body
        upstream = mock_anthropic({**reply, 'content': [THINKING, *reply['content']]})

    response = send(gateway, body)

    assert response.status_code == 200
    assert sent_body(upstream)['messages'] == body['messages']
    blocks = (
        _blocks_of(stream_frames(response.text))
        if stream
        else response.json()['content']
    )
    assert blocks == [THINKING, TOOL_USE]
    assert _guardrail_events(gateway) == []


def test_a_stream_is_relayed_live_without_output_guardrails(gateway):
    """Input guardrails alone do not buffer the answer."""
    _serve('redact_email_in', 'input_block', 'input_soft_block')
    mock_anthropic_stream()

    response = send_stream(gateway)

    assert _text_of(stream_frames(response.text)) == ['Hello', ' from', ' the model']


def test_an_upstream_error_in_a_buffered_stream_ends_it_with_no_text(gateway):
    _serve('output_warn')
    events = canned.anthropic_stream(['The secret']).sse_events[:3]
    error = {'type': 'error', 'error': {'type': 'overloaded_error', 'message': 'busy'}}
    mock_anthropic_stream(_sse([*events, error]))

    response = send_stream(gateway)

    assert stream_frames(response.text) == [('error', error)]


def test_a_buffered_stream_cut_before_its_end_is_an_error(gateway):
    _serve('output_warn')
    mock_anthropic_stream(_sse(canned.anthropic_stream(['The secret']).sse_events[:3]))

    response = send_stream(gateway)

    assert response.status_code == 500
    assert response.json()['type'] == 'error'
    assert 'secret' not in response.text


# ── Judges ──────────────────────────────────────────────────────────────────

QUESTION = 'Tell me a joke about cats'
ANSWER = 'Why did the cat sit on the laptop?'
JUDGE_TOKENS = 312


def _mock_decision_judge(triggered: bool):
    """Mock Typesafe judging once: a noul over the threshold triggers."""
    mock = pook.post(TYPESAFE_URL).times(1)
    mock.reply(200).json(
        {
            'model': 'jev-1.13.0',
            'answers': {
                'decision_judge': {'type': 'noul', 'noul': 0.9 if triggered else 0.1}
            },
            'usage': {'input_tokens': JUDGE_TOKENS, 'output_tokens': 1},
        }
    )
    return mock


def _mock_llm_judge(triggered: bool):
    """Mock the LLM judge's model (OpenAI) judging once."""
    verdict = {'triggered': triggered, 'reasoning': None, 'violation_type': None}
    mock = pook.post(OPENAI_URL).times(1)
    mock.reply(200).json(
        canned.openai_completion(
            json.dumps(verdict), prompt_tokens=JUDGE_TOKENS, completion_tokens=4
        ).json_body
    )
    return mock


def _judged_text(judge: str, mock) -> str:
    """Return what a judge's upstream was asked to judge."""
    sent = sent_body(mock)
    return sent['state'] if judge == 'decision' else json.dumps(sent['messages'])


JUDGES = {'decision': _mock_decision_judge, 'llm': _mock_llm_judge}
judges = pytest.mark.parametrize('judge', JUDGES)


@judges
@pytest.mark.parametrize('stream', [False, True], ids=['complete', 'stream'])
def test_an_input_judge_blocks_before_the_model(gateway, judge, stream):
    _serve(f'{judge}_in')
    judged = JUDGES[judge](triggered=True)
    upstream = mock_anthropic()

    response = send(gateway, {**_user(QUESTION, IMAGE), 'stream': stream})

    assert response.status_code == 400
    assert response.json()['type'] == 'error'
    assert response.json()['error']['type'] == 'invalid_request_error'
    assert QUESTION in _judged_text(judge, judged)
    assert not upstream.matched
    assert _guardrail_events(gateway) == [(f'{judge}_in', 'INPUT', 'BLOCK')]


@judges
def test_an_input_judge_passes_a_request(gateway, judge):
    _serve(f'{judge}_in')
    judged = JUDGES[judge](triggered=False)
    upstream = mock_anthropic()

    response = send(gateway, _user(QUESTION, IMAGE))

    assert response.status_code == 200
    assert response.json()['content'][0]['text'] == 'Hello from the model'
    assert judged.matched
    # The judge reads the request: nothing of it changes on the way upstream.
    assert sent_body(upstream)['messages'] == _user(QUESTION, IMAGE)['messages']
    assert _guardrail_events(gateway) == []


@judges
@pytest.mark.parametrize('stream', [False, True], ids=['complete', 'stream'])
def test_an_output_judge_blocks_the_answer(gateway, judge, stream):
    _serve(f'{judge}_out')
    judged = JUDGES[judge](triggered=True)
    _mock_reply(stream, ANSWER)

    response = send(gateway, {**BODY, 'stream': stream})

    assert response.status_code == 400
    assert response.json()['type'] == 'error'
    assert ANSWER in _judged_text(judge, judged)
    assert 'laptop' not in response.text
    assert _guardrail_events(gateway) == [(f'{judge}_out', 'OUTPUT', 'BLOCK')]


@judges
@pytest.mark.parametrize('stream', [False, True], ids=['complete', 'stream'])
def test_an_output_judge_passes_an_answer(gateway, judge, stream):
    _serve(f'{judge}_out')
    judged = JUDGES[judge](triggered=False)
    _mock_reply(stream, ANSWER)

    response = send(gateway, {**BODY, 'stream': stream})

    assert response.status_code == 200
    assert _answer_text(response, stream) == [ANSWER]
    assert judged.matched


# The judge's 312 tokens fill this limit: the model's 21 alone do not.
TOKEN_LIMIT = {'input': {'window_size': '1 minute', 'max_token': 200}}


@judges
@pytest.mark.parametrize('where', ['in', 'out'])
def test_judge_tokens_count_on_the_callers_limits(gateway, judge, where):
    """The next request is the one refused (ADR 0006)."""
    _serve(f'{judge}_{where}', token_limiting=TOKEN_LIMIT)
    JUDGES[judge](triggered=False)
    mock_anthropic()
    upstreams = mock_every_upstream()

    first = send(gateway)
    second = send(gateway)

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()['error']['type'] == 'rate_limit_error'
    assert not any(upstream.matched for upstream in upstreams)


def test_the_route_limit_holds_without_judge_tokens(gateway):
    """The control of the test above: the model's tokens fit the limit."""
    _serve(token_limiting=TOKEN_LIMIT)
    mock_anthropic().times(2)

    assert [send(gateway).status_code for _ in range(2)] == [200, 200]
