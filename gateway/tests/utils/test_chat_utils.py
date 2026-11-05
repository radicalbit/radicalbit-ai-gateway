from radicalbit_ai_gateway.llm.messages import AIMessage, AIMessageChunk
from radicalbit_ai_gateway.utils.chat_utils import ChatUtils
from radicalbit_ai_gateway.utils.streaming_utils import StreamingUtils


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


def test_to_openai_chat_completion_reasoning_content_set_on_tool_calls():
    """DeepSeek requires reasoning_content echoed back in multi-turn tool call flows.
    The gateway must include it in Turn 1 tool_call responses so the client can send
    it back in Turn 2.
    """
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
    assert msg.reasoning_content == 'some reasoning'


def test_reasoning_goes_out_under_both_names():
    """DeepSeek's reasoning_content, and vLLM's, Ollama's and OpenRouter's reasoning."""
    ai_message = AIMessage(
        content='OK',
        additional_kwargs={'reasoning_content': 'Thinking.'},
        response_metadata={'finish_reason': 'stop'},
    )
    msg = (
        ChatUtils.to_openai_chat_completion(
            ai_message, model_id_invoked='qwen3', request_id='req-1'
        )
        .choices[0]
        .message
    )
    assert msg.reasoning_content == 'Thinking.'
    assert msg.reasoning == 'Thinking.'


def test_streamed_reasoning_goes_out_under_both_names():
    chunk = StreamingUtils.to_openai_chat_completion_chunk(
        AIMessageChunk(content='', additional_kwargs={'reasoning_content': 'Hm'}),
        model_id_invoked='qwen3',
    )
    delta = chunk.choices[0].delta
    assert delta.reasoning_content == 'Hm'
    assert delta.reasoning == 'Hm'


USAGE_WITH_DETAILS = {
    'input_tokens': 25,
    'output_tokens': 535,
    'total_tokens': 560,
    'input_token_details': {'cache_read': 24},
    'output_token_details': {'reasoning': 530},
}


def _completion(usage_metadata):
    message = AIMessage(content='391', usage_metadata=usage_metadata)
    return ChatUtils.to_openai_chat_completion(message, model_id_invoked='m')


def test_non_streaming_usage_carries_reasoning_and_cached_tokens():
    usage = _completion(USAGE_WITH_DETAILS).usage
    assert usage.completion_tokens == 535
    assert usage.completion_tokens_details.reasoning_tokens == 530
    assert usage.prompt_tokens_details.cached_tokens == 24


def test_non_streaming_and_streaming_usage_match():
    chunk = StreamingUtils.build_usage_chunk(
        final_usage=USAGE_WITH_DETAILS, model_id_invoked='m', request_id='r'
    )
    assert _completion(USAGE_WITH_DETAILS).usage == chunk.usage


def test_usage_reads_the_service_tier_names():
    usage = _completion(
        {
            'input_tokens': 100,
            'output_tokens': 50,
            'total_tokens': 150,
            'input_token_details': {'priority_cache_read': 40, 'priority': 60},
            'output_token_details': {'priority_reasoning': 30, 'priority': 20},
        }
    ).usage
    assert usage.completion_tokens_details.reasoning_tokens == 30
    assert usage.prompt_tokens_details.cached_tokens == 40


def test_usage_has_no_details_when_the_provider_sent_none():
    usage = _completion(
        {'input_tokens': 10, 'output_tokens': 8, 'total_tokens': 18}
    ).usage
    assert usage.total_tokens == 18
    assert usage.prompt_tokens_details is None
    assert usage.completion_tokens_details is None
