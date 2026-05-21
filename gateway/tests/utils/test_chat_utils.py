from langchain_core.messages import AIMessage

from radicalbit_ai_gateway.utils.chat_utils import ChatUtils


def test_to_openai_chat_completion_with_reasoning_content():
    ai_message = AIMessage(
        content='Paris is the capital of France.',
        additional_kwargs={'reasoning_content': 'The user is asking about France...'},
        response_metadata={'finish_reason': 'stop'},
        usage_metadata={'input_tokens': 10, 'output_tokens': 8, 'total_tokens': 18},
    )
    result = ChatUtils.to_openai_chat_completion(
        ai_message, model_id_invoked='deepseek-reasoner', request_id='req-123'
    )
    msg = result.choices[0].message
    assert msg.content == 'Paris is the capital of France.'
    assert msg.reasoning_content == 'The user is asking about France...'


def test_to_openai_chat_completion_without_reasoning_content():
    ai_message = AIMessage(
        content='Paris is the capital of France.',
        response_metadata={'finish_reason': 'stop'},
        usage_metadata={'input_tokens': 10, 'output_tokens': 8, 'total_tokens': 18},
    )
    result = ChatUtils.to_openai_chat_completion(
        ai_message, model_id_invoked='gpt-4o', request_id='req-456'
    )
    msg = result.choices[0].message
    assert msg.content == 'Paris is the capital of France.'
    assert not hasattr(msg, 'reasoning_content') or msg.reasoning_content is None


def test_to_openai_chat_completion_reasoning_content_not_set_on_tool_calls():
    ai_message = AIMessage(
        content='',
        additional_kwargs={'reasoning_content': 'some reasoning'},
        tool_calls=[
            {
                'id': 'call_1',
                'name': 'get_weather',
                'args': {'city': 'Rome'},
                'type': 'tool_call',
            }
        ],
        response_metadata={'finish_reason': 'tool_calls'},
    )
    result = ChatUtils.to_openai_chat_completion(
        ai_message, model_id_invoked='deepseek-reasoner', request_id='req-789'
    )
    msg = result.choices[0].message
    assert msg.tool_calls is not None
    assert not hasattr(msg, 'reasoning_content') or msg.reasoning_content is None
