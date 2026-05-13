from openai.types.chat.chat_completion import ChatCompletion, Choice
from openai.types.chat.chat_completion_message import ChatCompletionMessage


def to_mock_openai_chat_completion(content: str) -> ChatCompletion:
    return ChatCompletion(
        id='chatcmpl-mock',
        object='chat.completion',
        created=1234567890,
        model='test-model',
        choices=[
            Choice(
                index=0,
                message=ChatCompletionMessage(
                    role='assistant',
                    content=content,
                ),
                finish_reason='stop',
            )
        ],
        usage=None,
    )
