from openai.types.chat.chat_completion import ChatCompletion

from radicalbit_ai_gateway.endpoints.chat_completions.streaming import (
    build_soft_block_chunk,
    cached_response_to_chunk,
)


def _completion(content: str | None, refusal: str | None = None) -> ChatCompletion:
    return ChatCompletion.model_validate(
        {
            'id': 'chatcmpl-1',
            'object': 'chat.completion',
            'created': 0,
            'model': 'gpt',
            'choices': [
                {
                    'index': 0,
                    'finish_reason': 'stop',
                    'message': {
                        'role': 'assistant',
                        'content': content,
                        'refusal': refusal,
                    },
                }
            ],
            'usage': {'prompt_tokens': 3, 'completion_tokens': 0, 'total_tokens': 3},
        }
    )


def test_a_cached_reply_with_no_text_streams_as_a_chunk_with_no_content():
    chunk = cached_response_to_chunk(_completion(None), 'route')

    assert chunk.choices[0].delta.content is None
    assert chunk.choices[0].finish_reason == 'stop'
    assert chunk.usage is not None
    assert chunk.usage.prompt_tokens == 3


def test_a_cached_refusal_streams_its_refusal():
    chunk = cached_response_to_chunk(_completion(None, refusal='I cannot.'), 'route')

    assert chunk.choices[0].delta.content is None
    assert chunk.choices[0].delta.refusal == 'I cannot.'


def test_a_cached_reply_streams_its_text():
    chunk = cached_response_to_chunk(_completion('hi'), 'route')

    assert chunk.choices[0].delta.content == 'hi'
    assert chunk.model == 'route'


def test_a_soft_block_with_no_text_streams_as_a_chunk_with_no_content():
    chunk = build_soft_block_chunk(_completion(None), 'route')

    assert chunk.choices[0].delta.content is None
