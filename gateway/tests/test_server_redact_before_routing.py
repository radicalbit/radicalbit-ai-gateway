"""Redact guardrails run before routing: chat requests through real routes.

Providers and the text classifier are mocked over HTTP with pook.
"""

import json
import unittest

import pook

from tests.common.gateway_harness import build_routes, open_gateway
from tests.common.mocked_build_openai_chat_completion import (
    to_mock_openai_chat_completion,
)

from radicalbit_ai_gateway.server import app

ROUTE_KEY = 'proj/support'
OPENAI_URL = 'https://api.openai.com/v1/chat/completions'
OPENAI_RESPONSES_URL = 'https://api.openai.com/v1/responses'
CLASSIFIER_URL = 'http://text-classifier:8888'

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


def _build_routes(routing: dict, guardrails: list[dict] | None = None) -> dict:
    return build_routes(
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


def _sent(mock) -> dict:
    """Return the JSON body of the one request a pook mock matched."""
    return mock.matches[0].json


class TestRedactBeforeRouting(unittest.TestCase):
    def setUp(self):
        self.gateway = self.enterContext(open_gateway(use_pook=True))
        self.client = self.gateway.client
        self.headers = self.gateway.headers

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

    def _openai_response(self) -> dict:
        return {
            'id': 'resp_1',
            'object': 'response',
            'created_at': 1,
            'model': 'gpt-4o',
            'status': 'completed',
            'output': [
                {
                    'type': 'message',
                    'id': 'msg_1',
                    'role': 'assistant',
                    'status': 'completed',
                    'content': [
                        {'type': 'output_text', 'text': 'Done', 'annotations': []}
                    ],
                }
            ],
            'parallel_tool_calls': True,
            'tool_choice': 'auto',
            'tools': [],
            'usage': {
                'input_tokens': 10,
                'input_tokens_details': {'cached_tokens': 0},
                'output_tokens': 1,
                'output_tokens_details': {'reasoning_tokens': 0},
                'total_tokens': 11,
            },
        }

    def _mock_openai_responses(self):
        mock = pook.post(OPENAI_RESPONSES_URL).times(1)
        mock.reply(200).json(self._openai_response())
        return mock

    def _mock_openai_responses_stream(self):
        events = [
            {
                'type': 'response.output_text.delta',
                'item_id': 'msg_1',
                'output_index': 0,
                'content_index': 0,
                'delta': 'Done',
                'logprobs': [],
            },
            {'type': 'response.completed', 'response': self._openai_response()},
        ]
        body = ''.join(
            f'event: {event["type"]}\ndata: {json.dumps(event)}\n\n' for event in events
        )
        mock = pook.post(OPENAI_RESPONSES_URL).times(1)
        mock.reply(200).header('Content-Type', 'text/event-stream').body(body)
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
        openai = self._mock_openai_responses()

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
        openai = self._mock_openai_responses_stream()

        response = self._responses(stream=True)

        assert response.status_code == 200
        assert 'Done' in response.text
        assert classifier.isdone()
        assert _sent(openai)['model'] == 'gpt-4o'
