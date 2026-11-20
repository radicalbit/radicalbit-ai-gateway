"""Building the chunks of a chat completions stream: the model's reasoning,
the usage, and a reply the output guardrails rewrote.
"""

from radicalbit_ai_gateway.endpoints.chat_completions import streaming
from radicalbit_ai_gateway.llm.messages import AIMessage, AIMessageChunk
from radicalbit_ai_gateway.utils.chat_utils import ChatUtils

USAGE_WITH_DETAILS = {
    'input_tokens': 25,
    'output_tokens': 535,
    'total_tokens': 560,
    'input_token_details': {'cache_read': 24},
    'output_token_details': {'reasoning': 530},
}


def test_streamed_reasoning_goes_out_under_both_names():
    chunk = streaming.to_openai_chat_completion_chunk(
        AIMessageChunk(content='', additional_kwargs={'reasoning_content': 'Hm'}),
        model_id_invoked='qwen3',
    )
    delta = chunk.choices[0].delta
    assert delta.reasoning_content == 'Hm'
    assert delta.reasoning == 'Hm'


def test_non_streaming_and_streaming_usage_match():
    chunk = streaming.build_usage_chunk(
        final_usage=USAGE_WITH_DETAILS, model_id_invoked='m', request_id='r'
    )
    assert (
        ChatUtils.to_openai_chat_completion(
            AIMessage(content='391', usage_metadata=USAGE_WITH_DETAILS),
            model_id_invoked='m',
        ).usage
        == chunk.usage
    )


def test_with_text_puts_the_whole_text_and_reasoning_in_their_first_chunks():
    chunks = [
        AIMessageChunk(content='', additional_kwargs={'reasoning_content': 'a@'}),
        AIMessageChunk(content='', additional_kwargs={'reasoning_content': 'b.com'}),
        AIMessageChunk(content='Hi '),
        AIMessageChunk(
            content='there',
            tool_call_chunks=[{'name': 'f', 'args': '{}', 'id': 'c1', 'index': 0}],
        ),
        AIMessageChunk(content='', response_metadata={'finish_reason': 'stop'}),
    ]

    out = streaming.with_text(chunks, 'Hi <X>', '<EMAIL>')

    assert [c.additional_kwargs.get('reasoning_content') for c in out] == [
        '<EMAIL>',
        None,
        None,
        None,
        None,
    ]
    assert [c.content for c in out] == ['', '', 'Hi <X>', '', '']
    assert out[3].tool_call_chunks[0]['id'] == 'c1'
    assert out[4].response_metadata == {'finish_reason': 'stop'}


def test_with_text_keeps_a_tool_call_reply_with_no_text():
    chunks = [
        AIMessageChunk(content='', additional_kwargs={'reasoning_content': 'a@b'}),
        AIMessageChunk(
            content='',
            tool_call_chunks=[{'name': 'f', 'args': '{}', 'id': 'c1', 'index': 0}],
        ),
    ]

    out = streaming.with_text(chunks, None, '<EMAIL>')

    assert out[0].additional_kwargs == {'reasoning_content': '<EMAIL>'}
    assert out[1] is chunks[1]
