from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from radicalbit_ai_gateway.models.model import GatewayDeepSeekChatModel


def _make_model() -> GatewayDeepSeekChatModel:
    return GatewayDeepSeekChatModel(model='deepseek-reasoner', api_key='test-key')


def _base_payload(messages: list[dict]) -> dict:
    return {'model': 'deepseek-reasoner', 'messages': messages}


def test_reasoning_content_injected_for_assistant_message():
    model = _make_model()
    input_messages = [
        HumanMessage(content='What is 2+2?'),
        AIMessage(
            content='4.',
            additional_kwargs={'reasoning_content': 'Simple arithmetic: 2+2=4.'},
        ),
        HumanMessage(content='And 3+3?'),
    ]
    base_payload = _base_payload(
        [
            {'role': 'user', 'content': '什么是2+2?'},
            {'role': 'assistant', 'content': '4.'},
            {'role': 'user', 'content': '和3+3?'},
        ]
    )
    with patch.object(
        GatewayDeepSeekChatModel.__bases__[0],
        '_get_request_payload',
        return_value=base_payload,
    ):
        payload = model._get_request_payload(input_messages)

    assert payload['messages'][1]['reasoning_content'] == 'Simple arithmetic: 2+2=4.'
    assert 'reasoning_content' not in payload['messages'][0]
    assert 'reasoning_content' not in payload['messages'][2]


def test_reasoning_content_not_injected_when_absent():
    model = _make_model()
    input_messages = [
        HumanMessage(content='Hello'),
        AIMessage(content='Hi there!'),
    ]
    base_payload = _base_payload(
        [
            {'role': 'user', 'content': 'Hello'},
            {'role': 'assistant', 'content': 'Hi there!'},
        ]
    )
    with patch.object(
        GatewayDeepSeekChatModel.__bases__[0],
        '_get_request_payload',
        return_value=base_payload,
    ):
        payload = model._get_request_payload(input_messages)

    for msg in payload['messages']:
        assert 'reasoning_content' not in msg


def test_reasoning_content_injected_only_for_assistant_role():
    model = _make_model()
    input_messages = [
        SystemMessage(content='You are helpful.'),
        HumanMessage(content='Hi'),
        AIMessage(
            content='Hello!',
            additional_kwargs={'reasoning_content': 'Greeting response.'},
        ),
    ]
    base_payload = _base_payload(
        [
            {'role': 'system', 'content': 'You are helpful.'},
            {'role': 'user', 'content': 'Hi'},
            {'role': 'assistant', 'content': 'Hello!'},
        ]
    )
    with patch.object(
        GatewayDeepSeekChatModel.__bases__[0],
        '_get_request_payload',
        return_value=base_payload,
    ):
        payload = model._get_request_payload(input_messages)

    assert 'reasoning_content' not in payload['messages'][0]
    assert 'reasoning_content' not in payload['messages'][1]
    assert payload['messages'][2]['reasoning_content'] == 'Greeting response.'


def test_multiple_assistant_messages_with_reasoning_content():
    model = _make_model()
    input_messages = [
        HumanMessage(content='Turn 1'),
        AIMessage(content='A1', additional_kwargs={'reasoning_content': 'R1'}),
        HumanMessage(content='Turn 2'),
        AIMessage(content='A2', additional_kwargs={'reasoning_content': 'R2'}),
        HumanMessage(content='Turn 3'),
    ]
    base_payload = _base_payload(
        [
            {'role': 'user', 'content': 'Turn 1'},
            {'role': 'assistant', 'content': 'A1'},
            {'role': 'user', 'content': 'Turn 2'},
            {'role': 'assistant', 'content': 'A2'},
            {'role': 'user', 'content': 'Turn 3'},
        ]
    )
    with patch.object(
        GatewayDeepSeekChatModel.__bases__[0],
        '_get_request_payload',
        return_value=base_payload,
    ):
        payload = model._get_request_payload(input_messages)

    assert payload['messages'][1]['reasoning_content'] == 'R1'
    assert payload['messages'][3]['reasoning_content'] == 'R2'
    assert 'reasoning_content' not in payload['messages'][0]
    assert 'reasoning_content' not in payload['messages'][2]
    assert 'reasoning_content' not in payload['messages'][4]


def test_reasoning_content_injected_for_tool_call_assistant_message():
    model = _make_model()
    input_messages = [
        HumanMessage(content="What's the weather in Paris?"),
        AIMessage(
            content='',
            tool_calls=[
                {
                    'id': 'call_1',
                    'name': 'get_weather',
                    'args': {'city': 'Paris'},
                    'type': 'tool_call',
                }
            ],
            additional_kwargs={
                'reasoning_content': 'I need to call the weather API to answer this.'
            },
        ),
        ToolMessage(content='Sunny, 22°C', tool_call_id='call_1'),
    ]
    base_payload = _base_payload(
        [
            {'role': 'user', 'content': "What's the weather in Paris?"},
            {
                'role': 'assistant',
                'content': '',
                'tool_calls': [
                    {
                        'id': 'call_1',
                        'function': {
                            'name': 'get_weather',
                            'arguments': '{"city": "Paris"}',
                        },
                        'type': 'function',
                    }
                ],
            },
            {'role': 'tool', 'content': 'Sunny, 22°C', 'tool_call_id': 'call_1'},
        ]
    )
    with patch.object(
        GatewayDeepSeekChatModel.__bases__[0],
        '_get_request_payload',
        return_value=base_payload,
    ):
        payload = model._get_request_payload(input_messages)

    # reasoning_content must be injected on the assistant message with tool_calls
    assert (
        payload['messages'][1]['reasoning_content']
        == 'I need to call the weather API to answer this.'
    )
    # user and tool messages must not carry reasoning_content
    assert 'reasoning_content' not in payload['messages'][0]
    assert 'reasoning_content' not in payload['messages'][2]
