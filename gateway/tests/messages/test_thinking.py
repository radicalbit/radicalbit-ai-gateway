import copy

from radicalbit_ai_gateway.messages.thinking import without_old_thinking

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
