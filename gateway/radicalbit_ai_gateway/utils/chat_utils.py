import json
from time import time
from typing import Literal
import uuid

from langchain_core.messages import AIMessage
from openai.types.chat.chat_completion import ChatCompletion, Choice
from openai.types.chat.chat_completion_message import ChatCompletionMessage
from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall,
    Function,
)
from openai.types.completion_usage import CompletionUsage


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
            reasoning_content = ai_message.additional_kwargs.get('reasoning_content')
            if reasoning_content:
                message_to_send.reasoning_content = reasoning_content
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
            reasoning_content = ai_message.additional_kwargs.get('reasoning_content')
            if reasoning_content:
                message_to_send.reasoning_content = reasoning_content
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
            usage=CompletionUsage(
                prompt_tokens=usage_metadata.get('input_tokens', 0),
                completion_tokens=usage_metadata.get('output_tokens', 0),
                total_tokens=usage_metadata.get('total_tokens', 0),
            )
            if usage_metadata
            else None,
        )
