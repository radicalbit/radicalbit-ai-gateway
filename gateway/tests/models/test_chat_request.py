import pytest

from radicalbit_ai_gateway.llm.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from radicalbit_ai_gateway.models.chat_request import (
    convert_openai_messages,
    parse_tool_calls,
)
from radicalbit_ai_gateway.utils.exceptions import GatewayBadRequest


def _call(id_, name=None, arguments=None):
    function = {} if name is None else {'name': name}
    if arguments is not None:
        function['arguments'] = arguments
    return {'id': id_, 'type': 'function', 'function': function}


@pytest.mark.parametrize(
    ('tool_calls', 'expected'),
    [
        (
            [
                _call('c1', 'get_weather', '{"location": "Roma"}'),
                _call('c2', 'get_news', '{"topic": "tech"}'),
            ],
            [
                {'name': 'get_weather', 'args': {'location': 'Roma'}, 'id': 'c1'},
                {'name': 'get_news', 'args': {'topic': 'tech'}, 'id': 'c2'},
            ],
        ),
        ([], []),
        ([{'id': 'c3'}], [{'name': None, 'args': {}, 'id': 'c3'}]),
        ([_call('c4', 'no_args')], [{'name': 'no_args', 'args': {}, 'id': 'c4'}]),
    ],
    ids=['two_calls', 'none', 'no_function', 'no_arguments'],
)
def test_tool_calls_are_parsed_into_name_args_and_id(tool_calls, expected):
    assert parse_tool_calls(tool_calls) == expected


@pytest.mark.parametrize(
    ('message', 'kind', 'content'),
    [
        ({'role': 'system', 'content': 'Be brief'}, SystemMessage, 'Be brief'),
        (
            {'role': 'system', 'content': [{'type': 'text', 'text': 'Be brief'}]},
            SystemMessage,
            '[{"type": "text", "text": "Be brief"}]',
        ),
        ({'role': 'user', 'content': 'Ciao!'}, HumanMessage, 'Ciao!'),
        ({'role': 'developer', 'content': 'Rules'}, HumanMessage, 'Rules'),
        ({'role': 'assistant', 'content': 'Bene'}, AIMessage, 'Bene'),
        (
            {'role': 'tool', 'content': '{"t": "25C"}', 'tool_call_id': 'c1'},
            ToolMessage,
            '{"t": "25C"}',
        ),
    ],
    ids=['system', 'system_parts', 'user', 'developer', 'assistant', 'tool'],
)
def test_each_role_becomes_its_message_with_text_content(message, kind, content):
    [result] = convert_openai_messages([message])

    assert type(result) is kind
    assert result.content == content


def test_an_assistant_message_keeps_its_tool_calls():
    [result] = convert_openai_messages(
        [
            {
                'role': 'assistant',
                'content': 'Calling',
                'tool_calls': [_call('c1', 'get_weather', '{"location": "Milano"}')],
            }
        ]
    )

    assert result.tool_calls == [
        {
            'name': 'get_weather',
            'args': {'location': 'Milano'},
            'id': 'c1',
            'type': 'tool_call',
        }
    ]


@pytest.mark.parametrize(
    ('message', 'error'),
    [
        ({'role': 'tool', 'content': 'result'}, 'ToolMessage must have tool_call_id.'),
        ({'role': 'robot', 'content': 'Test'}, 'Unsupported role: robot'),
    ],
    ids=['tool_without_call_id', 'unsupported_role'],
)
def test_an_invalid_message_is_a_bad_request(message, error):
    with pytest.raises(GatewayBadRequest, match=error):
        convert_openai_messages([message])


@pytest.mark.parametrize(
    ('message', 'expected'),
    [
        ({'role': 'assistant', 'content': 'Paris.', 'reasoning_content': 'Geo'}, 'Geo'),
        ({'role': 'assistant', 'content': 'Hi'}, None),
        ({'role': 'user', 'content': 'Hello', 'reasoning_content': 'Geo'}, None),
    ],
    ids=['assistant', 'assistant_without', 'user_ignored'],
)
def test_only_an_assistant_keeps_its_reasoning_content(message, expected):
    [result] = convert_openai_messages([message])

    assert (getattr(result, 'additional_kwargs', None) or {}).get(
        'reasoning_content'
    ) == expected


def _image(mime, data):
    return {'type': 'image', 'source_type': 'base64', 'data': data, 'mime_type': mime}


def _file(mime, data, **extra):
    return {
        'type': 'file',
        'source_type': 'base64',
        'data': data,
        'mime_type': mime,
        **extra,
    }


@pytest.mark.parametrize(
    ('part', 'expected'),
    [
        ({'type': 'text', 'text': 'hi'}, [{'type': 'text', 'text': 'hi'}]),
        ({'type': 'text'}, [{'type': 'text', 'text': ''}]),
        (
            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AAA'}},
            [_image('image/png', 'AAA')],
        ),
        (
            {'type': 'image_url', 'image_url': {'url': 'https://x/a.png'}},
            [{'type': 'image_url', 'image_url': {'url': 'https://x/a.png'}}],
        ),
        (
            {'type': 'image_url', 'image_url': {'url': 'data:;base64,BBB'}},
            [_file('application/octet-stream', 'BBB')],
        ),
        (
            {
                'type': 'file',
                'file': {
                    'file_data': 'data:application/pdf;base64,CCC',
                    'filename': 'a.pdf',
                },
            },
            [_file('application/pdf', 'CCC', filename='a.pdf')],
        ),
        (
            {
                'type': 'file',
                'file': {'data': 'data:image/jpeg;base64,DDD', 'file_data': 'x'},
            },
            [_image('image/jpeg', 'DDD')],
        ),
        (
            {'type': 'file', 'file_data': 'EEE'},
            [_file('application/octet-stream', 'EEE')],
        ),
        (
            {'type': 'file', 'data': 'FFF', 'file_data': 'x'},
            [_file('application/octet-stream', 'FFF')],
        ),
        ({'type': 'file', 'file': {'filename': 'empty'}}, []),
        (
            {'type': 'input_audio', 'id': 1},
            [{'type': 'text', 'text': "{'type': 'input_audio', 'id': 1}"}],
        ),
    ],
    ids=[
        'text',
        'text_missing',
        'image_data_url',
        'image_http_url',
        'data_url_without_mime',
        'nested_file_data',
        'nested_data_wins',
        'flat_raw_base64',
        'flat_data_wins',
        'file_without_data_dropped',
        'unknown_type_as_text',
    ],
)
def test_user_parts_are_normalised_to_the_gateway_format(part, expected):
    [result] = convert_openai_messages([{'role': 'user', 'content': [part]}])

    assert result.content == expected
