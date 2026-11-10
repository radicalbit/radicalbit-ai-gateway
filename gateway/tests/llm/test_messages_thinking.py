import copy

import anthropic
import httpx

from radicalbit_ai_gateway.llm.messages_thinking import (
    is_invalid_thinking_signature,
    without_old_thinking,
)

THINKING = {'type': 'thinking', 'thinking': 'Hm.', 'signature': 'deepseek'}
REDACTED = {'type': 'redacted_thinking', 'data': 'opaque'}
TEXT = {'type': 'text', 'text': 'Hello'}


def _body(*messages: dict) -> dict:
    return {'model': 'proj/assistant', 'max_tokens': 10, 'messages': list(messages)}


def test_thinking_and_redacted_thinking_leave_assistant_messages():
    body = _body(
        {'role': 'user', 'content': 'Hi'},
        {'role': 'assistant', 'content': [THINKING, REDACTED, TEXT]},
        {'role': 'user', 'content': 'And now?'},
    )

    stripped, count = without_old_thinking(body)

    assert count == 2
    assert stripped['messages'][1] == {'role': 'assistant', 'content': [TEXT]}
    assert stripped['max_tokens'] == 10


def test_the_body_sent_is_not_changed():
    body = _body(
        {'role': 'user', 'content': 'Hi'},
        {'role': 'assistant', 'content': [THINKING, TEXT]},
        {'role': 'user', 'content': 'And now?'},
    )
    sent = copy.deepcopy(body)

    without_old_thinking(body)

    assert body == sent


def test_a_message_with_only_thinking_is_kept_as_it_is():
    only_thinking = {'role': 'assistant', 'content': [THINKING]}
    body = _body(
        {'role': 'user', 'content': 'Hi'},
        only_thinking,
        {'role': 'user', 'content': 'Go on'},
        {'role': 'assistant', 'content': [THINKING, TEXT]},
        {'role': 'user', 'content': 'And now?'},
    )

    stripped, count = without_old_thinking(body)

    assert count == 1
    assert stripped['messages'][1] == only_thinking
    assert stripped['messages'][3] == {'role': 'assistant', 'content': [TEXT]}


def test_thinking_in_user_messages_is_not_touched():
    body = _body(
        {'role': 'user', 'content': [THINKING, TEXT]},
        {'role': 'assistant', 'content': 'Hello'},
        {'role': 'user', 'content': 'And now?'},
    )

    assert without_old_thinking(body) == (body, 0)


def test_a_body_without_messages_is_returned_as_it_is():
    body = {'model': 'proj/assistant', 'max_tokens': 10}

    assert without_old_thinking(body) == (body, 0)


def _bad_request(body: object, message: str) -> anthropic.APIStatusError:
    """Return the SDK's error for a 400 whose JSON body is ``body``."""
    response = httpx.Response(
        400,
        request=httpx.Request('POST', 'https://api.anthropic.com/v1/messages'),
        **({} if body is None else {'json': body}),
    )
    return anthropic.APIStatusError(message, response=response, body=body)


def test_a_signature_refusal_is_read_from_the_error_body():
    error = _bad_request(
        {
            'type': 'error',
            'error': {
                'type': 'invalid_request_error',
                'message': 'Invalid `signature` in `thinking` block',
            },
        },
        'Error code: 400',
    )

    assert is_invalid_thinking_signature(error)


def test_a_signature_refusal_without_a_messages_body_is_read_from_its_message():
    error = _bad_request(None, 'Invalid signature in thinking block')

    assert is_invalid_thinking_signature(error)


def test_other_refusals_are_not_signature_refusals():
    assert not is_invalid_thinking_signature(_bad_request(None, 'max_tokens too big'))
    assert not is_invalid_thinking_signature(RuntimeError('signature thinking'))


def test_thinking_goes_when_no_user_message_ends_a_tool_loop():
    body = _body(
        {'role': 'assistant', 'content': [THINKING, TEXT]},
    )

    stripped, count = without_old_thinking(body)

    assert count == 1
    assert stripped['messages'] == [{'role': 'assistant', 'content': [TEXT]}]
