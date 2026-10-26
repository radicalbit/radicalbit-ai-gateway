import httpx
from openai import AuthenticationError, RateLimitError

from radicalbit_ai_gateway.llm.chat_model import ChatModel
from radicalbit_ai_gateway.llm.messages import AIMessage, AIMessageChunk, BaseMessage

request = httpx.Request('GET', '/')
response = httpx.Response(200, request=request)
error = RateLimitError('rate limit', response=response, body='')


class _MockChatModel(ChatModel):
    """Streams by yielding the complete reply as a single chunk."""

    async def _astream(self, messages: list[BaseMessage], **kwargs):
        message = await self._agenerate(messages, **kwargs)
        yield AIMessageChunk(**message.model_dump(exclude={'type'}))


class FailingChatModel(_MockChatModel):
    async def _agenerate(self, messages: list[BaseMessage], **kwargs):
        raise RuntimeError('This model is designed to fail.')


class WorkingChatModel(_MockChatModel):
    async def _agenerate(self, messages: list[BaseMessage], **kwargs):
        return AIMessage(
            content='This is a successful response from the WorkingChatModel.'
        )


class RateLimitedChatModel(_MockChatModel):
    async def _agenerate(self, messages: list[BaseMessage], **kwargs):
        error_body = {
            'error': {
                'message': 'You exceeded your current quota, please check your plan and billing details.',
                'type': 'insufficient_quota',
                'code': 'rate_limit_exceeded',
            }
        }
        request = httpx.Request(
            method='POST',
            url='https://api.openai.com/v1/chat/completions',
            json={
                'model': 'gpt-4.1',
                'messages': [
                    {'role': 'developer', 'content': 'You are a helpful assistant.'},
                    {'role': 'user', 'content': 'Hello!'},
                ],
            },
        )
        _ = httpx.Response(
            status_code=429,
            request=request,
            json=error_body,
        )
        raise RateLimitError(
            'You exceeded your current quota, please check your plan and billing details.',
            response=response,
            body=error_body,
        )


class UnauthorizedChatModel(_MockChatModel):
    async def _agenerate(self, messages: list[BaseMessage], **kwargs):
        error_body = {
            'error': {
                'message': 'Incorrect API key provided: sk-123. You can find your API key at https://platform.openai.com/account/api-keys.',
                'type': 'invalid_request_error',
                'param': None,
                'code': 'invalid_api_key',
            }
        }
        request = httpx.Request(
            method='POST',
            url='https://api.openai.com/v1/chat/completions',
            json={
                'model': 'gpt-4.1',
                'messages': [
                    {'role': 'developer', 'content': 'You are a helpful assistant.'},
                    {'role': 'user', 'content': 'Hello!'},
                ],
            },
        )
        _ = httpx.Response(
            status_code=401,
            request=request,
            json=error_body,
        )
        raise AuthenticationError(
            'Unauthorized request, please check your API key and permissions.',
            response=response,
            body=error_body,
        )
