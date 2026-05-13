import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from openai import AuthenticationError, RateLimitError

request = httpx.Request('GET', '/')
response = httpx.Response(200, request=request)
error = RateLimitError('rate limit', response=response, body='')


class FailingChatModel(BaseChatModel):
    def _generate(self, messages: list[BaseMessage], *args, **kwargs):
        raise RuntimeError('This model is designed to fail.')

    @property
    def _llm_type(self) -> str:
        return 'failing-chat-model'


class WorkingChatModel(BaseChatModel):
    def _generate(self, messages: list[BaseMessage], *args, **kwargs):
        response_message = AIMessage(
            content='This is a successful response from the WorkingChatModel.'
        )
        generation = ChatGeneration(message=response_message)
        return ChatResult(generations=[generation])

    @property
    def _llm_type(self) -> str:
        return 'working-chat-model'


class RateLimitedChatModel(BaseChatModel):
    def _generate(self, messages: list[BaseMessage], *args, **kwargs) -> ChatResult:
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

    @property
    def _llm_type(self) -> str:
        """A required property that returns a unique name for the model class."""
        return 'rate-limited-chat-model'


class UnauthorizedChatModel(BaseChatModel):
    def _generate(self, messages: list[BaseMessage], *args, **kwargs) -> ChatResult:
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

    @property
    def _llm_type(self) -> str:
        """A required property that returns a unique name for the model class."""
        return 'rate-limited-chat-model'
