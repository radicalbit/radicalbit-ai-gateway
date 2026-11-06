import json
from time import time
from typing import Literal
import uuid

from openai.types.chat.chat_completion import ChatCompletion, Choice
from openai.types.chat.chat_completion_message import ChatCompletionMessage
from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall,
    Function,
)
from openai.types.completion_usage import CompletionUsage

from radicalbit_ai_gateway.llm.messages import (
    AIMessage,
    message_reasoning,
    usage_detail,
)


def completion_usage(usage_metadata: dict | None) -> CompletionUsage | None:
    """Translate the gateway's ``UsageMetadata`` into Chat Completions usage.

    The details (cached and reasoning tokens) appear only when the provider
    reported them.
    """
    if not usage_metadata:
        return None
    input_details = usage_metadata.get('input_token_details') or {}
    output_details = usage_metadata.get('output_token_details') or {}
    return CompletionUsage(
        prompt_tokens=usage_metadata.get('input_tokens', 0),
        completion_tokens=usage_metadata.get('output_tokens', 0),
        total_tokens=usage_metadata.get('total_tokens', 0),
        prompt_tokens_details={
            'cached_tokens': usage_detail(input_details, 'cache_read'),
            'audio_tokens': usage_detail(input_details, 'audio'),
        }
        if input_details
        else None,
        completion_tokens_details={
            'reasoning_tokens': usage_detail(output_details, 'reasoning'),
            'audio_tokens': usage_detail(output_details, 'audio'),
            'accepted_prediction_tokens': usage_detail(
                output_details, 'accepted_prediction'
            ),
            'rejected_prediction_tokens': usage_detail(
                output_details, 'rejected_prediction'
            ),
        }
        if output_details
        else None,
    )


# The names of the model's reasoning in a Chat Completions message or delta:
# DeepSeek's, and vLLM's, Ollama's and OpenRouter's.
_REASONING_FIELDS = ('reasoning_content', 'reasoning')


def reasoning_fields(reasoning: str) -> dict[str, str]:
    """Return the model's reasoning under each name it goes by."""
    return dict.fromkeys(_REASONING_FIELDS, reasoning)


def completion_reasoning(message: ChatCompletionMessage) -> str:
    """Return the model's reasoning in a Chat Completions message, or ''."""
    for name in _REASONING_FIELDS:
        if isinstance(value := getattr(message, name, None), str) and value:
            return value
    return ''


def _set_reasoning(message: ChatCompletionMessage, ai_message: AIMessage) -> None:
    """Put the model's reasoning on ``message``, under each name it goes by."""
    if reasoning := message_reasoning(ai_message):
        for name, value in reasoning_fields(reasoning).items():
            setattr(message, name, value)


class ChatUtils:
    @staticmethod
    def to_openai_chat_completion(
        ai_message: AIMessage, model_id_invoked: str, request_id: str | None = None
    ) -> ChatCompletion:
        response_metadata = ai_message.response_metadata or {}
        usage_metadata = ai_message.usage_metadata or {}

        message_to_send: ChatCompletionMessage
        finish_reason: Literal[
            'stop', 'length', 'tool_calls', 'content_filter', 'function_call'
        ]
        if ai_message.tool_calls:
            openai_tool_calls = [
                ChatCompletionMessageToolCall(
                    id=call['id'] or '',
                    function=Function(
                        name=call['name'], arguments=json.dumps(call['args'])
                    ),
                    type='function',
                )
                for call in ai_message.tool_calls
            ]
            message_to_send = ChatCompletionMessage(
                role='assistant',
                content=None,
                tool_calls=openai_tool_calls,
            )
            _set_reasoning(message_to_send, ai_message)
            finish_reason = 'tool_calls'
        else:
            content = ai_message.content
            if isinstance(content, list | dict):
                content = str(content)
            message_to_send = ChatCompletionMessage(
                role='assistant',
                content=content,
                tool_calls=None,
            )
            _set_reasoning(message_to_send, ai_message)
            # Normalize finish_reason to lowercase (Gemini returns uppercase like 'STOP')
            finish_reason_raw = response_metadata.get('finish_reason', 'stop')
            finish_reason = (
                finish_reason_raw.lower()
                if isinstance(finish_reason_raw, str)
                else 'stop'
            )
        return ChatCompletion(
            id=request_id
            if request_id
            else (ai_message.id if ai_message.id else f'chatcmpl-{uuid.uuid4()}'),
            object='chat.completion',
            created=int(time()),
            model=model_id_invoked,
            choices=[
                Choice(
                    index=0,
                    message=message_to_send,
                    finish_reason=finish_reason,
                )
            ],
            usage=completion_usage(usage_metadata),
        )
