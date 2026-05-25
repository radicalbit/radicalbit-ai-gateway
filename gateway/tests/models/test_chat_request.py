from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
import pytest

from radicalbit_ai_gateway.models.chat_request import (
    convert_openai_messages,
    parse_tool_calls,
)
from radicalbit_ai_gateway.utils.exceptions import GatewayBadRequest


def test_parse_tool_calls_ok():
    tool_calls = [
        {
            'id': 'call_123',
            'type': 'function',
            'function': {
                'name': 'get_weather',
                'arguments': '{"location": "Roma"}',
            },
        },
        {
            'id': 'call_456',
            'type': 'function',
            'function': {
                'name': 'get_news',
                'arguments': '{"topic": "tech"}',
            },
        },
    ]
    expected = [
        {
            'name': 'get_weather',
            'args': {'location': 'Roma'},
            'id': 'call_123',
        },
        {
            'name': 'get_news',
            'args': {'topic': 'tech'},
            'id': 'call_456',
        },
    ]
    assert parse_tool_calls(tool_calls) == expected


def test_parse_tool_calls_empty():
    assert parse_tool_calls([]) == []


def test_parse_tool_calls_invalid_input():
    tool_calls = [{'id': 'call_789'}]
    expected = [
        {
            'name': None,
            'args': {},
            'id': 'call_789',
        }
    ]
    assert parse_tool_calls(tool_calls) == expected


def test_parse_tool_calls_con_invalid_args_or_empty():
    tool_calls = [
        {
            'id': 'call_abc',
            'type': 'function',
            'function': {
                'name': 'tool_wo_args',
                'arguments': '{}',
            },
        },
        {
            'id': 'call_def',
            'type': 'function',
            'function': {'name': 'tool_w_args'},
        },
    ]
    expected = [
        {'name': 'tool_wo_args', 'args': {}, 'id': 'call_abc'},
        {'name': 'tool_w_args', 'args': {}, 'id': 'call_def'},
    ]
    assert parse_tool_calls(tool_calls) == expected


def test_convert_message_system():
    messages = [{'role': 'system', 'content': 'You are an helpful assistant'}]
    result = convert_openai_messages(messages)
    assert len(result) == 1
    assert isinstance(result[0], SystemMessage)
    assert result[0].content == 'You are an helpful assistant'


def test_convert_message_human():
    messages = [{'role': 'user', 'content': 'Ciao!'}]
    result = convert_openai_messages(messages)
    assert len(result) == 1
    assert isinstance(result[0], HumanMessage)
    assert result[0].content == 'Ciao!'


def test_convert_messagges_assistant_tool_calls():
    messages = [
        {
            'role': 'assistant',
            'content': "Of course, I'll execute the func",
            'tool_calls': [
                {
                    'id': 'call_123',
                    'type': 'function',
                    'function': {
                        'name': 'get_weather',
                        'arguments': '{"location": "Milano"}',
                    },
                }
            ],
        }
    ]
    result = convert_openai_messages(messages)
    assert len(result) == 1
    assert isinstance(result[0], AIMessage)
    assert result[0].content == "Of course, I'll execute the func"
    assert len(result[0].tool_calls) == 1
    assert result[0].tool_calls[0] == {
        'name': 'get_weather',
        'args': {'location': 'Milano'},
        'id': 'call_123',
        'type': 'tool_call',
    }


def test_convert_message_tool():
    messages = [
        {
            'role': 'tool',
            'content': '{"temperature": "25C"}',
            'tool_call_id': 'call_123',
        }
    ]
    result = convert_openai_messages(messages)
    assert len(result) == 1
    assert isinstance(result[0], ToolMessage)
    assert result[0].content == '{"temperature": "25C"}'
    assert result[0].tool_call_id == 'call_123'


def test_error_no_tool_call_id():
    messages = [{'role': 'tool', 'content': 'result tool'}]
    with pytest.raises(GatewayBadRequest, match='ToolMessage must have tool_call_id.'):
        convert_openai_messages(messages)


def test_error_unsupported_role():
    messages = [{'role': 'unsupported_role', 'content': 'Test'}]
    with pytest.raises(GatewayBadRequest, match='Unsupported role: unsupported_role'):
        convert_openai_messages(messages)


def test_convert_messages():
    messages = [
        {'role': 'system', 'content': 'Inizia la conversazione.'},
        {'role': 'user', 'content': 'Come stai?'},
        {'role': 'assistant', 'content': 'Bene, grazie!'},
    ]
    result = convert_openai_messages(messages)
    assert len(result) == 3
    assert isinstance(result[0], SystemMessage)
    assert isinstance(result[1], HumanMessage)
    assert isinstance(result[2], AIMessage)


def test_convert_openai_messages_assistant_with_reasoning_content():
    messages = [
        {'role': 'user', 'content': 'What is the capital of France?'},
        {
            'role': 'assistant',
            'content': 'Paris.',
            'reasoning_content': 'The user is asking a geography question...',
        },
    ]
    result = convert_openai_messages(messages)
    assert len(result) == 2
    ai_msg = result[1]
    assert isinstance(ai_msg, AIMessage)
    assert ai_msg.content == 'Paris.'
    assert ai_msg.additional_kwargs.get('reasoning_content') == (
        'The user is asking a geography question...'
    )


def test_convert_openai_messages_assistant_without_reasoning_content():
    messages = [
        {'role': 'user', 'content': 'Hello'},
        {'role': 'assistant', 'content': 'Hi there!'},
    ]
    result = convert_openai_messages(messages)
    ai_msg = result[1]
    assert isinstance(ai_msg, AIMessage)
    assert 'reasoning_content' not in ai_msg.additional_kwargs


def test_convert_openai_messages_reasoning_content_ignored_for_non_assistant():
    messages = [
        {'role': 'user', 'content': 'Hello', 'reasoning_content': 'should be ignored'},
    ]
    result = convert_openai_messages(messages)
    assert isinstance(result[0], HumanMessage)
    assert not hasattr(result[0], 'additional_kwargs') or 'reasoning_content' not in (
        result[0].additional_kwargs or {}
    )
