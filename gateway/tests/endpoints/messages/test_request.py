import pytest

from radicalbit_ai_gateway.endpoints.chat_like.limits import chat_demand
from radicalbit_ai_gateway.endpoints.messages.request import MessagesRequest
from radicalbit_ai_gateway.llm.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.utils.exceptions import GatewayInternalError
from radicalbit_ai_gateway.utils.token_encoding import count_tokens

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


def _tool_result(content, **fields) -> dict:
    return {
        'type': 'tool_result',
        'tool_use_id': 'toolu_1',
        'content': content,
        **fields,
    }


def test_a_tool_result_text_is_read_as_a_tool_message():
    body = _body(
        messages=[{'role': 'user', 'content': [_tool_result('18 degrees in Milan')]}]
    )

    assert MessagesRequest(body).messages() == [
        ToolMessage(content='18 degrees in Milan', tool_call_id='toolu_1')
    ]


def test_text_blocks_of_a_tool_result_are_read_as_one_tool_message():
    result = _tool_result(
        [
            {'type': 'text', 'text': 'stdout'},
            {'type': 'image', 'source': {'type': 'url', 'url': 'x'}},
            {'type': 'text', 'text': 'stderr'},
        ]
    )
    body = _body(messages=[{'role': 'user', 'content': [result]}])

    assert MessagesRequest(body).messages() == [
        ToolMessage(
            content=[
                {'type': 'text', 'text': 'stdout'},
                {'type': 'text', 'text': 'stderr'},
            ],
            tool_call_id='toolu_1',
        )
    ]


def test_texts_and_tool_results_of_a_message_are_read_in_block_order():
    body = _body(
        messages=[
            {
                'role': 'user',
                'content': [
                    _tool_result('first result'),
                    _tool_result('second result', tool_use_id='toolu_2'),
                    {'type': 'text', 'text': 'What now?'},
                ],
            }
        ]
    )

    assert MessagesRequest(body).messages() == [
        ToolMessage(content='first result', tool_call_id='toolu_1'),
        ToolMessage(content='second result', tool_call_id='toolu_2'),
        HumanMessage(content='What now?'),
    ]


def test_blocks_without_text_are_not_read():
    body = _body(
        messages=[
            {
                'role': 'assistant',
                'content': [
                    {'type': 'thinking', 'thinking': 'hm', 'signature': 's'},
                    {'type': 'redacted_thinking', 'data': 'secret'},
                    {'type': 'text', 'text': 'Let me check.'},
                    {
                        'type': 'tool_use',
                        'id': 'toolu_1',
                        'name': 'weather',
                        'input': {'city': 'Milan'},
                    },
                ],
            },
            {
                'role': 'user',
                'content': [
                    _tool_result(
                        [{'type': 'image', 'source': {'type': 'url', 'url': 'x'}}]
                    ),
                    _tool_result(None, tool_use_id='toolu_2'),
                    {'type': 'image', 'source': {'type': 'url', 'url': 'y'}},
                    {
                        'type': 'document',
                        'source': {
                            'type': 'text',
                            'media_type': 'text/plain',
                            'data': 'a document',
                        },
                    },
                ],
            },
        ]
    )

    assert MessagesRequest(body).messages() == [AIMessage(content='Let me check.')]


def test_a_changed_tool_result_text_is_written_back_in_place():
    content = [
        {'type': 'text', 'text': 'Here it is.'},
        _tool_result(
            'mail: ada@example.com',
            is_error=False,
            cache_control={'type': 'ephemeral'},
        ),
        {'type': 'image', 'source': {'type': 'url', 'url': 'x'}},
    ]
    request = MessagesRequest(_body(messages=[{'role': 'user', 'content': content}]))

    request.write_back(
        [
            HumanMessage(content='Here it is.'),
            ToolMessage(content='mail: [EMAIL]', tool_call_id='toolu_1'),
        ]
    )

    assert request.body['messages'][0]['content'] == [
        {'type': 'text', 'text': 'Here it is.'},
        {
            'type': 'tool_result',
            'tool_use_id': 'toolu_1',
            'content': 'mail: [EMAIL]',
            'is_error': False,
            'cache_control': {'type': 'ephemeral'},
        },
        {'type': 'image', 'source': {'type': 'url', 'url': 'x'}},
    ]


def test_changed_text_blocks_of_a_tool_result_are_written_back_in_place():
    result = _tool_result(
        [
            {'type': 'text', 'text': 'ada@example.com'},
            {'type': 'image', 'source': {'type': 'url', 'url': 'x'}},
            {
                'type': 'text',
                'text': 'bob@example.com',
                'cache_control': {'type': 'ephemeral'},
            },
        ]
    )
    request = MessagesRequest(_body(messages=[{'role': 'user', 'content': [result]}]))

    request.write_back(
        [
            ToolMessage(
                content=[
                    {'type': 'text', 'text': '[EMAIL]'},
                    {'type': 'text', 'text': '[EMAIL]'},
                ],
                tool_call_id='toolu_1',
            )
        ]
    )

    assert request.body['messages'][0]['content'] == [
        {
            'type': 'tool_result',
            'tool_use_id': 'toolu_1',
            'content': [
                {'type': 'text', 'text': '[EMAIL]'},
                {'type': 'image', 'source': {'type': 'url', 'url': 'x'}},
                {
                    'type': 'text',
                    'text': '[EMAIL]',
                    'cache_control': {'type': 'ephemeral'},
                },
            ],
        }
    ]


def test_the_input_token_estimate_counts_the_tool_result_text():
    body = _body(
        system='Be brief.',
        messages=[
            {'role': 'user', 'content': 'Weather?'},
            {'role': 'user', 'content': [_tool_result('18 degrees in Milan')]},
        ],
    )

    model = Model(model_id='claude', model='anthropic/claude-sonnet-4-5')

    estimate = chat_demand(MessagesRequest(body).messages(), model).input

    assert estimate.text == 'Be brief. Weather? 18 degrees in Milan'
    assert count_tokens(estimate.text, estimate.model) == 10
