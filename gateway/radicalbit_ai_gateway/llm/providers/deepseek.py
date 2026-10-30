"""DeepSeek chat model, on the OpenAI SDK against DeepSeek's endpoint.

Replies carry the model's ``reasoning_content`` in ``additional_kwargs``; on
the way back, assistant messages send it again (DeepSeek's thinking mode
requires it within a tool-calling turn).
"""

import json
from typing import Any, ClassVar
from urllib.parse import urlparse

import openai
from pydantic import Field, SecretStr, model_validator

from radicalbit_ai_gateway.llm.messages import AIMessage, AIMessageChunk, BaseMessage
from radicalbit_ai_gateway.llm.providers.openai import (
    _BaseChatOpenAI,
    _env,
    is_openai_reasoning_blob,
)

DEFAULT_API_BASE = 'https://api.deepseek.com/v1'
# Stands in for reasoning another model did not share.
REASONING_PLACEHOLDER = 'Reasoning not available: this step came from another model.'


def _reasoning(text: str) -> dict:
    return {
        'type': 'reasoning',
        'summary': [],
        'content': [{'type': 'reasoning_text', 'text': text}],
    }


def _with_reasoning_before_current_calls(items: list) -> list:
    """Put reasoning before each tool call of the current turn that has none."""
    last_user = max(
        (
            index
            for index, item in enumerate(items)
            if isinstance(item, dict) and item.get('role') == 'user'
        ),
        default=-1,
    )
    adapted = items[: last_user + 1]
    reasoned = False
    for item in items[last_user + 1 :]:
        kind = item.get('type') if isinstance(item, dict) else None
        if kind == 'reasoning':
            reasoned = True
        elif kind == 'function_call_output':
            reasoned = False
        elif kind == 'function_call' and not reasoned:
            # DeepSeek in thinking mode rejects a tool call of the current turn
            # without non-empty reasoning before it.
            adapted.append(_reasoning(REASONING_PLACEHOLDER))
            reasoned = True
        adapted.append(item)
    return adapted


def _secret_env_deepseek() -> SecretStr | None:
    value = _env('DEEPSEEK_API_KEY')()
    return SecretStr(value) if value is not None else None


class GatewayDeepSeekChatModel(_BaseChatOpenAI):
    """DeepSeek chat model."""

    _gen_ai_provider: ClassVar[str] = 'deepseek'

    model_name: str = Field(alias='model')
    api_key: SecretStr | None = Field(default_factory=_secret_env_deepseek)
    api_base: str = Field(
        alias='base_url',
        default_factory=_env('DEEPSEEK_API_BASE', default=DEFAULT_API_BASE),
    )

    @model_validator(mode='after')
    def _build_client(self) -> 'GatewayDeepSeekChatModel':
        if self.api_base == DEFAULT_API_BASE and not (
            self.api_key and self.api_key.get_secret_value()
        ):
            raise ValueError('If using default api base, DEEPSEEK_API_KEY must be set.')
        client_params = {
            k: v
            for k, v in {
                'api_key': self.api_key.get_secret_value() if self.api_key else None,
                'base_url': self.api_base,
                'timeout': self.request_timeout,
                'max_retries': self.max_retries,
                'default_headers': self.default_headers,
                'default_query': self.default_query,
            }.items()
            if v is not None
        }
        self._client = openai.AsyncOpenAI(
            **client_params, http_client=self.http_async_client
        )
        return self

    @property
    def _is_azure_endpoint(self) -> bool:
        hostname = urlparse(self.api_base or '').hostname or ''
        return hostname == 'azure.com' or hostname.endswith('.azure.com')

    def _structured_method(self) -> str:
        return 'function_calling'

    def supports_native_responses(self) -> bool:
        return True

    def adapt_responses_input(self, items: list) -> list:
        adapted = []
        for item in items:
            if not (
                isinstance(item, dict)
                and item.get('type') == 'reasoning'
                and is_openai_reasoning_blob(item.get('encrypted_content'))
            ):
                adapted.append(item)
                continue
            # OpenAI's summary is the only part of its reasoning another model
            # can read; DeepSeek takes it as plain-text reasoning ``content``.
            summary = '\n\n'.join(
                part['text']
                for part in item.get('summary') or []
                if isinstance(part, dict) and part.get('text')
            )
            if summary:
                adapted.append(_reasoning(summary))
        return _with_reasoning_before_current_calls(adapted)

    def _get_request_payload(self, messages: list[BaseMessage], **kwargs: Any) -> dict:
        payload = super()._get_request_payload(messages, **kwargs)
        for message in payload['messages']:
            if message['role'] == 'tool' and isinstance(message['content'], list):
                message['content'] = json.dumps(message['content'])
            elif message['role'] == 'assistant' and isinstance(
                message['content'], list
            ):
                # DeepSeek expects assistant content as a string.
                text_parts = [
                    block.get('text', '')
                    for block in message['content']
                    if isinstance(block, dict) and block.get('type') == 'text'
                ]
                message['content'] = ''.join(text_parts) if text_parts else ''
        # Azure-hosted DeepSeek only accepts string tool_choice values.
        if self._is_azure_endpoint and isinstance(payload.get('tool_choice'), dict):
            payload['tool_choice'] = 'required'
        for message_dict, message in zip(payload['messages'], messages, strict=False):
            if (
                isinstance(message, AIMessage)
                and message_dict.get('role') == 'assistant'
                and message.additional_kwargs.get('reasoning_content')
            ):
                message_dict['reasoning_content'] = message.additional_kwargs[
                    'reasoning_content'
                ]
        return payload

    def _chat_result(
        self, response: Any, generation_info: dict | None = None
    ) -> tuple[list[tuple[AIMessage, dict]], dict]:
        generations, llm_output = super()._chat_result(response, generation_info)
        if not isinstance(response, openai.BaseModel):
            return generations, llm_output
        for message, _ in generations:
            message.response_metadata['model_provider'] = 'deepseek'
        choices = getattr(response, 'choices', None)
        if choices and hasattr(choices[0].message, 'reasoning_content'):
            generations[0][0].additional_kwargs['reasoning_content'] = choices[
                0
            ].message.reasoning_content
        # OpenRouter sends the reasoning as ``reasoning``.
        elif choices and isinstance(
            model_extra := choices[0].message.model_extra, dict
        ):
            if reasoning := model_extra.get('reasoning'):
                generations[0][0].additional_kwargs['reasoning_content'] = reasoning
        return generations, llm_output

    def _convert_chunk(
        self, chunk: dict, base_generation_info: dict
    ) -> tuple[AIMessageChunk, dict | None] | None:
        converted = super()._convert_chunk(chunk, base_generation_info)
        if (choices := chunk.get('choices')) and converted:
            message, _ = converted
            message.response_metadata = {
                **message.response_metadata,
                'model_provider': 'deepseek',
            }
            delta = choices[0].get('delta', {})
            if (reasoning_content := delta.get('reasoning_content')) is not None:
                message.additional_kwargs['reasoning_content'] = reasoning_content
            elif (reasoning := delta.get('reasoning')) is not None:
                message.additional_kwargs['reasoning_content'] = reasoning
        return converted

    async def _agenerate(self, messages: list[BaseMessage], **kwargs: Any) -> AIMessage:
        try:
            return await super()._agenerate(messages, **kwargs)
        except json.JSONDecodeError as e:
            raise json.JSONDecodeError(
                'DeepSeek API returned an invalid response. '
                'Please check the API status and try again.',
                e.doc,
                e.pos,
            ) from e


def build_chat_model(model_name: str, **kwargs: Any) -> GatewayDeepSeekChatModel:
    return GatewayDeepSeekChatModel(model=model_name, **kwargs)
