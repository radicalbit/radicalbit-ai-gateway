from radicalbit_ai_gateway.llm.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from radicalbit_ai_gateway.llm.providers.deepseek import GatewayDeepSeekChatModel


def _payload(messages) -> dict:
    model = GatewayDeepSeekChatModel(model='deepseek-reasoner', api_key='test-key')
    return model._get_request_payload(messages)


def test_reasoning_content_injected_for_assistant_message():
    payload = _payload(
        [
            HumanMessage(content='What is 2+2?'),
            AIMessage(
                content='4.',
                additional_kwargs={'reasoning_content': 'Simple arithmetic: 2+2=4.'},
            ),
            HumanMessage(content='And 3+3?'),
        ]
    )

    assert payload['messages'][1]['reasoning_content'] == 'Simple arithmetic: 2+2=4.'
    assert 'reasoning_content' not in payload['messages'][0]
    assert 'reasoning_content' not in payload['messages'][2]


def test_reasoning_content_not_injected_when_absent():
    payload = _payload([HumanMessage(content='Hello'), AIMessage(content='Hi there!')])

    for msg in payload['messages']:
        assert 'reasoning_content' not in msg


def test_reasoning_content_injected_only_for_assistant_role():
    payload = _payload(
        [
            SystemMessage(content='You are helpful.'),
            HumanMessage(
                content='Hi', additional_kwargs={'reasoning_content': 'ignored'}
            ),
            AIMessage(
                content='Hello!',
                additional_kwargs={'reasoning_content': 'Greeting response.'},
            ),
        ]
    )

    assert 'reasoning_content' not in payload['messages'][0]
    assert 'reasoning_content' not in payload['messages'][1]
    assert payload['messages'][2]['reasoning_content'] == 'Greeting response.'


def test_multiple_assistant_messages_with_reasoning_content():
    payload = _payload(
        [
            HumanMessage(content='Turn 1'),
            AIMessage(content='A1', additional_kwargs={'reasoning_content': 'R1'}),
            HumanMessage(content='Turn 2'),
            AIMessage(content='A2', additional_kwargs={'reasoning_content': 'R2'}),
            HumanMessage(content='Turn 3'),
        ]
    )

    assert payload['messages'][1]['reasoning_content'] == 'R1'
    assert payload['messages'][3]['reasoning_content'] == 'R2'
    assert 'reasoning_content' not in payload['messages'][0]
    assert 'reasoning_content' not in payload['messages'][2]
    assert 'reasoning_content' not in payload['messages'][4]


def test_reasoning_content_injected_for_tool_call_assistant_message():
    payload = _payload(
        [
            HumanMessage(content="What's the weather in Paris?"),
            AIMessage(
                content='',
                tool_calls=[
                    {'id': 'call_1', 'name': 'get_weather', 'args': {'city': 'Paris'}}
                ],
                additional_kwargs={
                    'reasoning_content': 'I need to call the weather API to answer this.'
                },
            ),
            ToolMessage(content='Sunny, 22°C', tool_call_id='call_1'),
        ]
    )

    # reasoning_content must be injected on the assistant message with tool_calls
    assert payload['messages'][1] == {
        'content': None,
        'role': 'assistant',
        'tool_calls': [
            {
                'type': 'function',
                'id': 'call_1',
                'function': {'name': 'get_weather', 'arguments': '{"city": "Paris"}'},
            }
        ],
        'reasoning_content': 'I need to call the weather API to answer this.',
    }
    # user and tool messages must not carry reasoning_content
    assert 'reasoning_content' not in payload['messages'][0]
    assert 'reasoning_content' not in payload['messages'][2]
