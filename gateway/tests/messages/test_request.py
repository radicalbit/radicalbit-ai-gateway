import pytest

from radicalbit_ai_gateway.llm.messages import HumanMessage, SystemMessage
from radicalbit_ai_gateway.messages.request import MessagesRequest
from radicalbit_ai_gateway.utils.exceptions import GatewayInternalError

CACHED_SYSTEM = [
    {'type': 'text', 'text': 'You are Claude Code.'},
    {
        'type': 'text',
        'text': 'Project rules.',
        'cache_control': {'type': 'ephemeral'},
    },
]


def _body(**fields) -> dict:
    return {
        'model': 'proj/assistant',
        'max_tokens': 10,
        'messages': [{'role': 'user', 'content': 'Hi'}],
        **fields,
    }


def test_configured_prompt_is_the_system_prompt_when_the_client_sends_none():
    request = MessagesRequest(_body())

    request.insert_system_prompt(SystemMessage(content='Be kind.'))

    assert request.body['system'] == 'Be kind.'


def test_configured_prompt_goes_before_a_system_prompt_sent_as_blocks():
    request = MessagesRequest(_body(system=CACHED_SYSTEM))

    request.insert_system_prompt(SystemMessage(content='Be kind.'))

    assert request.body['system'] == [
        {'type': 'text', 'text': 'Be kind.'},
        *CACHED_SYSTEM,
    ]


def test_configured_prompt_in_blocks_keeps_its_blocks():
    prompt = [
        {'type': 'text', 'text': 'Be kind.', 'cache_control': {'type': 'ephemeral'}}
    ]
    request = MessagesRequest(_body())

    request.insert_system_prompt(SystemMessage(content=prompt))

    assert request.body['system'] == prompt


def test_configured_prompt_in_blocks_goes_before_the_client_blocks():
    prompt = [{'type': 'text', 'text': 'Be kind.'}, 'not a block']
    request = MessagesRequest(_body(system=CACHED_SYSTEM))

    request.insert_system_prompt(SystemMessage(content=prompt))

    assert request.body['system'] == [prompt[0], *CACHED_SYSTEM]


def test_the_body_sent_is_not_changed():
    body = _body(system=CACHED_SYSTEM)

    MessagesRequest(body).insert_system_prompt(SystemMessage(content='Be kind.'))

    assert body['system'] == CACHED_SYSTEM


def test_entries_that_are_not_messages_are_left_out():
    body = _body(
        messages=[
            'not a message',
            {'role': 'user', 'content': None},
            {'role': 'user', 'content': 'Hi'},
        ]
    )

    assert MessagesRequest(body).messages() == [HumanMessage(content='Hi')]


def test_changed_texts_of_a_message_with_several_text_blocks_are_written_back():
    body = _body(
        messages=[
            {
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': 'one'},
                    {'type': 'image', 'source': {'type': 'url', 'url': 'x'}},
                    {'type': 'text', 'text': 'two'},
                ],
            }
        ]
    )
    request = MessagesRequest(body)

    request.write_back(
        [
            HumanMessage(
                content=[
                    {'type': 'text', 'text': 'ONE'},
                    {'type': 'text', 'text': 'TWO'},
                ]
            )
        ]
    )

    content = request.body['messages'][0]['content']
    assert [block.get('text') for block in content] == ['ONE', None, 'TWO']


def test_write_back_refuses_a_different_number_of_messages():
    request = MessagesRequest(_body())

    with pytest.raises(GatewayInternalError):
        request.write_back([])


def test_write_back_refuses_a_different_number_of_texts():
    request = MessagesRequest(_body())

    with pytest.raises(GatewayInternalError):
        request.write_back(
            [
                HumanMessage(
                    content=[
                        {'type': 'text', 'text': 'a'},
                        {'type': 'text', 'text': 'b'},
                    ]
                )
            ]
        )
