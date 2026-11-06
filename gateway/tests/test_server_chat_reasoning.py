"""The model's reasoning in a chat request's history, through the real endpoint.

A client sends it back on assistant messages, as ``reasoning_content``
(DeepSeek) or ``reasoning`` (vLLM, Ollama, OpenRouter). The endpoint keeps it:
DeepSeek gets it back, and an input guardrail with read_reasoning reads it.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
import pook

from tests.common import db_mock
from tests.common.mocked_build_openai_chat_completion import (
    to_mock_openai_chat_completion,
)
from tests.test_server_redact_before_routing import (
    GATEWAY_EMIT,
    GUARDRAIL_EMIT,
    MODEL_INVOKER_EMIT,
    OPENAI_URL,
    REDACT_EMIT,
    REQUEST_EVENT_EMIT,
    _mock_request_uuid,
    _sent,
)

from radicalbit_ai_gateway.auth.api_key_validator import ApiKeyValidator
from radicalbit_ai_gateway.guardrails.guardrail_engine import GuardrailEngine
from radicalbit_ai_gateway.guardrails.judges.judge_engine import JudgeEngine
from radicalbit_ai_gateway.guardrails.presidio import PresidioEngine
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.server import app, group_service, key_service
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.dependencies import get_request_uuid
from radicalbit_ai_gateway.utils.gateway_route_factory import (
    build_gateway_routes_from_config,
)

ROUTE_KEY = 'proj/chat'
DEEPSEEK_URL = 'https://api.deepseek.com/v1/chat/completions'
BAD = 'banana'

OPENAI = {
    'model_id': 'gpt',
    'model': 'openai/gpt-4o-mini',
    'credentials': {'api_key': 'sk-123'},
}
DEEPSEEK = {
    'model_id': 'ds',
    'model': 'deepseek/deepseek-reasoner',
    'credentials': {'api_key': 'sk-123'},
}


def _guardrail(read_reasoning: bool) -> dict:
    return {
        'name': 'no_banana',
        'type': 'contains',
        'where': 'input',
        'behavior': 'block',
        'read_reasoning': read_reasoning,
        'parameters': {'values': [BAD]},
    }


def _build_routes(model: dict, guardrails: list[dict] | None = None) -> dict:
    config = GatewayConfig.model_validate(
        {
            'chat_models': [model],
            'guardrails': guardrails,
            'routes': {
                'chat': {
                    'chat_models': [model['model_id']],
                    'guardrails': [g['name'] for g in guardrails or []],
                }
            },
        }
    )
    cost_service = CostService()
    guardrail_engine = GuardrailEngine(
        presidio_engine=PresidioEngine(),
        judge_engine=JudgeEngine(prompt_manager=MagicMock(spec_set=PromptManager)),
        cost_service=cost_service,
        guardrails=config.guardrails,
    )
    routes = build_gateway_routes_from_config(
        config,
        guardrail_engine,
        redis_client=None,
        cost_service=cost_service,
        httpx_client=None,
        project_uuid='',
    )
    route = routes['chat']
    route.project_name = 'proj'
    return {ROUTE_KEY: route}


def _history(field: str) -> list[dict]:
    return [
        {'role': 'user', 'content': 'Name a fruit'},
        {'role': 'assistant', 'content': 'OK', field: f'I thought of a {BAD}.'},
        {'role': 'user', 'content': 'Thanks'},
    ]


class _ChatCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.dependency_overrides[get_request_uuid] = _mock_request_uuid
        cls.client = TestClient(app)
        cls.headers = {'Authorization': f'Bearer {db_mock.PLAIN_KEY}'}

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides = {}

    def setUp(self):
        self.addCleanup(
            setattr, app.state, 'token_validator', app.state.token_validator
        )
        app.state.token_validator = ApiKeyValidator(key_service=key_service)
        api_key = db_mock.get_sample_key_with_group(group_uuid=db_mock.GROUP_UUID)
        key_service.get_key_by_hashed_key = MagicMock(return_value=api_key)
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)

        for patcher in (
            patch(MODEL_INVOKER_EMIT),
            patch(GATEWAY_EMIT),
            patch(GUARDRAIL_EMIT),
            patch(REDACT_EMIT),
            patch(REQUEST_EVENT_EMIT),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        pook.on()
        pook.enable_network('testserver')
        self.addCleanup(pook.off)
        self.addCleanup(pook.disable_network)

    def _chat(self, routes: dict, messages: list[dict]):
        app.state.routes = routes
        return self.client.post(
            '/v1/chat/completions',
            json={'model': ROUTE_KEY, 'messages': messages},
            headers=self.headers,
        )

    def _mock(self, url: str):
        mock = pook.post(url).times(1)
        mock.reply(200).json(
            to_mock_openai_chat_completion(content='Done').model_dump()
        )
        return mock


class TestChatReasoningHistory(_ChatCase):
    def test_deepseek_gets_the_reasoning_back_under_either_name(self):
        for field in ('reasoning_content', 'reasoning'):
            with self.subTest(field=field):
                mock = self._mock(DEEPSEEK_URL)
                response = self._chat(_build_routes(DEEPSEEK), _history(field))
                assert response.status_code == 200, response.text
                assert _sent(mock)['messages'][1]['reasoning_content'] == (
                    f'I thought of a {BAD}.'
                )

    def test_input_guardrail_reads_history_reasoning_with_the_flag(self):
        for field in ('reasoning_content', 'reasoning'):
            with self.subTest(field=field):
                routes = _build_routes(OPENAI, [_guardrail(read_reasoning=True)])
                response = self._chat(routes, _history(field))
                assert response.status_code == 400, response.text
                assert response.json()['error']['param']['name'] == 'no_banana'

    def test_input_guardrail_ignores_history_reasoning_without_the_flag(self):
        mock = self._mock(OPENAI_URL)
        routes = _build_routes(OPENAI, [_guardrail(read_reasoning=False)])
        response = self._chat(routes, _history('reasoning'))
        assert response.status_code == 200, response.text
        # OpenAI never gets reasoning back.
        assert 'reasoning_content' not in _sent(mock)['messages'][1]


REDACT_REASONING = {
    'name': 'redact_email',
    'type': 'presidio_anonymizer',
    'where': 'output',
    'read_reasoning': True,
    'parameters': {'language': 'en', 'entities': ['EMAIL_ADDRESS']},
}


class TestChatReasoningOutput(_ChatCase):
    """An output redact guardrail with read_reasoning, on a non-streaming chat."""

    def _mock_reasoning(self, reasoning: str):
        body = to_mock_openai_chat_completion(content='Done').model_dump()
        body['choices'][0]['message']['reasoning_content'] = reasoning
        pook.post(DEEPSEEK_URL).times(1).reply(200).json(body)

    def test_output_reasoning_is_redacted(self):
        self._mock_reasoning('Mail john@example.com')
        routes = _build_routes(DEEPSEEK, [REDACT_REASONING])
        response = self._chat(routes, [{'role': 'user', 'content': 'Hi'}])
        assert response.status_code == 200, response.text
        message = response.json()['choices'][0]['message']
        assert message['content'] == 'Done'
        assert message['reasoning_content'] == 'Mail <EMAIL_ADDRESS>'
        assert message['reasoning'] == 'Mail <EMAIL_ADDRESS>'

    def test_output_reasoning_without_pii_is_left_alone(self):
        self._mock_reasoning('Just thinking')
        routes = _build_routes(DEEPSEEK, [REDACT_REASONING])
        response = self._chat(routes, [{'role': 'user', 'content': 'Hi'}])
        assert response.status_code == 200, response.text
        message = response.json()['choices'][0]['message']
        assert message['reasoning_content'] == 'Just thinking'


REDACT_ANSWER = {
    **REDACT_REASONING,
    'name': 'redact_answer',
    'read_reasoning': False,
}


def _sse(deltas: list[dict]) -> str:
    chunks = [
        {
            'id': 'chatcmpl-1',
            'object': 'chat.completion.chunk',
            'created': 0,
            'model': 'deepseek-reasoner',
            'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}],
        }
        for delta in deltas
    ]
    chunks.append(
        {
            'id': 'chatcmpl-1',
            'object': 'chat.completion.chunk',
            'created': 0,
            'model': 'deepseek-reasoner',
            'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 5, 'completion_tokens': 7, 'total_tokens': 12},
        }
    )
    return ''.join(f'data: {json.dumps(c)}\n\n' for c in chunks) + 'data: [DONE]\n\n'


class TestStreamedChatRedaction(_ChatCase):
    """A streamed chat is buffered when the route has output guardrails: the
    redact ones rewrite it, as on a non-streamed chat. An email split across
    two chunks is still masked.
    """

    def _stream(self, routes: dict):
        pook.post(DEEPSEEK_URL).times(1).reply(200).header(
            'Content-Type', 'text/event-stream'
        ).body(
            _sse(
                [
                    {'role': 'assistant', 'reasoning_content': 'Mail john@exa'},
                    {'reasoning_content': 'mple.com'},
                    {'content': 'Write to jane@exa'},
                    {'content': 'mple.com'},
                ]
            )
        )
        app.state.routes = routes
        response = self.client.post(
            '/v1/chat/completions',
            json={
                'model': ROUTE_KEY,
                'messages': [{'role': 'user', 'content': 'Hi'}],
                'stream': True,
            },
            headers=self.headers,
        )
        deltas = [
            json.loads(line[len('data: ') :])['choices']
            for line in response.text.splitlines()
            if line.startswith('data: {')
        ]
        joined = {
            name: ''.join(c[0]['delta'].get(name) or '' for c in deltas if c)
            for name in ('reasoning_content', 'reasoning', 'content')
        }
        return response, joined

    def test_reasoning_and_answer_are_redacted_with_the_flag(self):
        response, joined = self._stream(_build_routes(DEEPSEEK, [REDACT_REASONING]))
        assert response.status_code == 200, response.text
        assert joined == {
            'reasoning_content': 'Mail <EMAIL_ADDRESS>',
            'reasoning': 'Mail <EMAIL_ADDRESS>',
            'content': 'Write to <EMAIL_ADDRESS>',
        }
        assert response.headers['X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-WARN'] == 'true'

    def test_only_the_answer_is_redacted_without_the_flag(self):
        response, joined = self._stream(_build_routes(DEEPSEEK, [REDACT_ANSWER]))
        assert response.status_code == 200, response.text
        assert joined['reasoning_content'] == 'Mail john@example.com'
        assert joined['content'] == 'Write to <EMAIL_ADDRESS>'
