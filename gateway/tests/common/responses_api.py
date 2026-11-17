"""Responses API test helpers shared by the tests of ``endpoints/responses``."""

import json

import httpx
from httpx_aiohttp import HttpxAiohttpClient
import openai

from radicalbit_ai_gateway.llm.chat_model import ChatModel
from radicalbit_ai_gateway.llm.factory import init_chat_model

# A turn as opencode sends it back: reasoning only the model can resume, a
# commentary message, two parallel calls and their outputs.
OPENCODE_TURN = [
    {
        'type': 'message',
        'role': 'user',
        'content': [{'type': 'input_text', 'text': 'Implement the task'}],
    },
    {
        'type': 'reasoning',
        'id': 'rs_0095a',
        'summary': [],
        'encrypted_content': 'gAAAAABq301x',
    },
    {
        'type': 'message',
        'id': 'msg_0095a',
        'role': 'assistant',
        'status': 'completed',
        'content': [{'type': 'output_text', 'text': 'I will read the files first.'}],
        'phase': 'commentary',
    },
    {
        'type': 'function_call',
        'id': 'fc_0095a',
        'call_id': 'call_A',
        'name': 'read',
        'arguments': '{"path":"a.py"}',
    },
    {
        'type': 'function_call',
        'id': 'fc_0095b',
        'call_id': 'call_B',
        'name': 'glob',
        'arguments': '{"pattern":"**/*.py"}',
    },
    {'type': 'function_call_output', 'call_id': 'call_A', 'output': 'print(1)'},
    {'type': 'function_call_output', 'call_id': 'call_B', 'output': 'a.py'},
]


def openai_model(**kwargs):
    """Return an OpenAI chat model, as the gateway builds one."""
    return init_chat_model(
        'openai:gpt-6-luna',
        api_key='sk',
        http_async_client=HttpxAiohttpClient(),
        **kwargs,
    )


class FakeChatModel(ChatModel):
    """A chat model that answers the Responses API with canned ``events``,
    records the bodies it is sent, and can fail (``error``) or break after
    ``fail_after`` events.
    """

    def __init__(self, native=True, events=(), error=None, fail_after=None):
        self.native = native
        self.events = events
        self.error = error
        self.fail_after = fail_after
        self.bodies = []

    def supports_native_responses(self):
        return self.native

    async def _astream_native_responses(self, body):
        self.bodies.append(body)
        if self.error:
            raise self.error
        for i, event in enumerate(self.events):
            if i == self.fail_after:
                raise RuntimeError('connection reset')
            yield event['type'], json.dumps(event)

    async def _ainvoke_native_responses(self, body):
        self.bodies.append(body)
        if self.error:
            raise self.error
        return self.events[-1]['response']

    async def _agenerate(self, messages, **kwargs):
        raise NotImplementedError

    async def _astream(self, messages, **kwargs):
        raise NotImplementedError
        yield


def status_error(status: int, body: dict):
    """Return the error the OpenAI SDK raises for an HTTP error ``status``."""
    request = httpx.Request('POST', 'https://api.openai.com/v1/responses')
    response = httpx.Response(status, json=body, request=request)
    return openai.APIStatusError(body['error']['message'], response=response, body=body)


def events_of(frames: list[str]) -> list[dict]:
    """Parse SSE frames, checking each one's ``event:`` line matches its type."""
    events = []
    for frame in frames:
        event_line, data_line = frame.strip('\n').split('\n')
        event = json.loads(data_line.removeprefix('data: '))
        assert event_line == f'event: {event["type"]}'
        events.append(event)
    return events
