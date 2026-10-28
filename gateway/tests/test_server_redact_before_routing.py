"""Redact guardrails run before routing: chat requests through real routes.

Providers and the text classifier are mocked over HTTP with pook.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
import pook
from starlette.requests import Request

from tests.common import db_mock
from tests.common.mocked_build_openai_chat_completion import (
    to_mock_openai_chat_completion,
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

ROUTE_KEY = 'proj/support'
OPENAI_URL = 'https://api.openai.com/v1/chat/completions'
CLASSIFIER_URL = 'http://text-classifier:8888'

MODEL_INVOKER_EMIT = 'radicalbit_ai_gateway.invocation.model_invoker.emit_event'
GATEWAY_EMIT = 'radicalbit_ai_gateway.ai_gateway.emit_event'
GUARDRAIL_EMIT = 'radicalbit_ai_gateway.guardrails.guardrail_check.emit_event'
REDACT_EMIT = 'radicalbit_ai_gateway.guardrails.guardrail_redact.emit_event'
REQUEST_EVENT_EMIT = (
    'radicalbit_ai_gateway.middleware.request_event_middleware.emit_request_event'
)

EMAIL = 'john.smithson.longaddress@verylongcompanydomain.example.com'
USER_TEXT = f'Mail me at {EMAIL}'
REDACTED_TEXT = 'Mail me at <EMAIL_ADDRESS>'

# Each model has its own provider name and prompt, so the body sent to
# OpenAI tells which model served the request.
BILLING = {
    'model_id': 'billing',
    'model': 'openai/gpt-4o',
    'credentials': {'api_key': 'sk-123'},
    'prompt': f'You are billing. Escalate to {EMAIL}.',
}
GENERAL = {
    'model_id': 'general',
    'model': 'openai/gpt-4o-mini',
    'credentials': {'api_key': 'sk-123'},
    'prompt': 'You are general support.',
}

REDACT_EMAIL = {
    'name': 'redact_email',
    'type': 'presidio_anonymizer',
    'where': 'input',
    'parameters': {'language': 'en', 'entities': ['EMAIL_ADDRESS']},
}

TEXT_CLASSIFICATION = {
    'name': 'intent',
    'type': 'text_classification',
    'url': CLASSIFIER_URL,
    'default_model_id': 'general',
    'output_mapping': [{'model_id': 'billing', 'conditions': ['billing']}],
}
# Matches only the raw address, never the masked one.
KEYWORD = {
    'name': 'by_keyword',
    'type': 'deterministic',
    'rule': 'keyword',
    'default_model_id': 'general',
    'output_mapping': [{'model_id': 'billing', 'conditions': ['example.com']}],
}
# The raw text is 16 tokens, the redacted one 7.
TOKEN_LENGTH = {
    'name': 'by_length',
    'type': 'deterministic',
    'rule': 'token_length',
    'default_model_id': 'general',
    'output_mapping': [{'model_id': 'billing', 'conditions': {'gte': 12}}],
}


def _mock_request_uuid(request: Request):
    request.state.request_uuid = str(db_mock.REQUEST_UUID)
    return str(db_mock.REQUEST_UUID)


def _build_routes(routing: dict, guardrails: list[dict] | None = None) -> dict:
    config = GatewayConfig.model_validate(
        {
            'chat_models': [BILLING, GENERAL],
            'guardrails': guardrails,
            'routing': [routing],
            'routes': {
                'support': {
                    'chat_models': ['billing', 'general'],
                    'guardrails': [g['name'] for g in guardrails or []],
                    'routing': routing['name'],
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
    route = routes['support']
    route.project_name = 'proj'
    return {ROUTE_KEY: route}


def _sent(mock) -> dict:
    """Return the JSON body of the one request a pook mock matched."""
    return mock.matches[0].json


class TestRedactBeforeRouting(unittest.TestCase):
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
        # The TestClient talks httpx too: let only its own host through.
        pook.enable_network('testserver')
        self.addCleanup(pook.off)
        self.addCleanup(pook.disable_network)

    def _chat(self, stream: bool = False):
        return self.client.post(
            '/v1/chat/completions',
            json={
                'model': ROUTE_KEY,
                'messages': [{'role': 'user', 'content': USER_TEXT}],
                'stream': stream,
            },
            headers=self.headers,
        )

    def _responses(self, stream: bool = False):
        return self.client.post(
            '/v1/responses',
            json={'model': ROUTE_KEY, 'input': USER_TEXT, 'stream': stream},
            headers=self.headers,
        )

    def _mock_openai_stream(self):
        chunk = {
            'id': 'chatcmpl-1',
            'object': 'chat.completion.chunk',
            'created': 1,
            'model': 'gpt-4o',
            'choices': [
                {'index': 0, 'delta': {'content': 'Done'}, 'finish_reason': None}
            ],
        }
        done = {
            **chunk,
            'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}],
        }
        body = (
            f'data: {json.dumps(chunk)}\n\ndata: {json.dumps(done)}\n\ndata: [DONE]\n\n'
        )
        mock = pook.post(OPENAI_URL).times(1)
        mock.reply(200).header('Content-Type', 'text/event-stream').body(body)
        return mock

    def _mock_openai(self):
        mock = pook.post(OPENAI_URL).times(1)
        mock.reply(200).json(
            to_mock_openai_chat_completion(content='Done').model_dump()
        )
        return mock

    def _mock_classifier(self, text: str, label: str = 'billing'):
        mock = pook.post(f'{CLASSIFIER_URL}/invocations').json(
            {'dataframe_records': [{'inputs': text}]}
        )
        mock.reply(200).json({'predictions': [{'class': label}]})
        return mock

    def test_text_classifier_receives_the_redacted_last_human_message(self):
        app.state.routes = _build_routes(TEXT_CLASSIFICATION, [REDACT_EMAIL])
        classifier = self._mock_classifier(REDACTED_TEXT)
        openai = self._mock_openai()

        response = self._chat()

        assert response.status_code == 200
        assert classifier.isdone()
        assert _sent(openai)['model'] == 'gpt-4o'

    def test_keyword_rule_no_longer_matches_text_the_guardrail_masks(self):
        app.state.routes = _build_routes(KEYWORD, [REDACT_EMAIL])
        openai = self._mock_openai()

        response = self._chat()

        assert response.status_code == 200
        assert _sent(openai)['model'] == 'gpt-4o-mini'

    def test_keyword_rule_still_matches_without_a_redact_guardrail(self):
        app.state.routes = _build_routes(KEYWORD)
        openai = self._mock_openai()

        response = self._chat()

        assert response.status_code == 200
        assert _sent(openai)['model'] == 'gpt-4o'

    def test_token_length_rule_counts_the_redacted_text(self):
        app.state.routes = _build_routes(TOKEN_LENGTH, [REDACT_EMAIL])
        openai = self._mock_openai()

        response = self._chat()

        assert response.status_code == 200
        assert _sent(openai)['model'] == 'gpt-4o-mini'

    def test_token_length_rule_counts_the_raw_text_without_a_redact_guardrail(self):
        app.state.routes = _build_routes(TOKEN_LENGTH)
        openai = self._mock_openai()

        response = self._chat()

        assert response.status_code == 200
        assert _sent(openai)['model'] == 'gpt-4o'

    def test_model_gets_the_selected_models_prompt_then_the_redacted_message(self):
        app.state.routes = _build_routes(TEXT_CLASSIFICATION, [REDACT_EMAIL])
        self._mock_classifier(REDACTED_TEXT)
        openai = self._mock_openai()

        response = self._chat()

        assert response.status_code == 200
        # The prompt is added after redaction, so its address stays as written.
        assert _sent(openai)['messages'] == [
            {'role': 'system', 'content': BILLING['prompt']},
            {'role': 'user', 'content': REDACTED_TEXT},
        ]

    def test_check_guardrail_sees_the_redacted_message(self):
        block_email = {
            'name': 'block_email',
            'type': 'contains',
            'where': 'input',
            'behavior': 'block',
            'parameters': {'values': [EMAIL]},
            'response_message': 'blocked',
        }
        app.state.routes = _build_routes(KEYWORD, [REDACT_EMAIL, block_email])
        openai = self._mock_openai()

        response = self._chat()

        assert response.status_code == 200
        assert openai.isdone()

    def test_responses_endpoint_routes_on_the_redacted_message(self):
        app.state.routes = _build_routes(TEXT_CLASSIFICATION, [REDACT_EMAIL])
        classifier = self._mock_classifier(REDACTED_TEXT)
        openai = self._mock_openai()

        response = self._responses()

        assert response.status_code == 200
        assert classifier.isdone()
        assert _sent(openai)['model'] == 'gpt-4o'

    def test_streamed_chat_routes_on_the_redacted_message(self):
        app.state.routes = _build_routes(TEXT_CLASSIFICATION, [REDACT_EMAIL])
        classifier = self._mock_classifier(REDACTED_TEXT)
        openai = self._mock_openai_stream()

        response = self._chat(stream=True)

        assert response.status_code == 200
        assert 'Done' in response.text
        assert classifier.isdone()
        assert _sent(openai)['model'] == 'gpt-4o'

    def test_streamed_responses_route_on_the_redacted_message(self):
        app.state.routes = _build_routes(TEXT_CLASSIFICATION, [REDACT_EMAIL])
        classifier = self._mock_classifier(REDACTED_TEXT)
        openai = self._mock_openai_stream()

        response = self._responses(stream=True)

        assert response.status_code == 200
        assert 'Done' in response.text
        assert classifier.isdone()
        assert _sent(openai)['model'] == 'gpt-4o'
