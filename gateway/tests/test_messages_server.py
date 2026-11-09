"""POST /v1/messages through a real route: the Anthropic Messages API, passed through.

The route is built from a published configuration, the Anthropic provider and
its SDK are real, and Anthropic is mocked over HTTP with pook. The tests check
only what the client and the provider see.
"""

import asyncio
import datetime
import json
import socket
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
import pook
import pytest
from starlette.requests import Request

from tests.common import db_mock, provider_responses as canned

from radicalbit_ai_gateway.auth.api_key_validator import ApiKeyValidator
from radicalbit_ai_gateway.guardrails.guardrails import Guardrails
from radicalbit_ai_gateway.guardrails.judges.judge_engine import JudgeEngine
from radicalbit_ai_gateway.guardrails.presidio import PresidioEngine
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.request_event_type import RequestStatus, RequestType
from radicalbit_ai_gateway.models.request_identity import RequestIdentity
from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.server import app, group_service, key_service
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.dependencies import get_request_uuid
from radicalbit_ai_gateway.utils.exceptions import (
    KeyNotFoundError,
    ModelInvokerBadRequest,
)
from radicalbit_ai_gateway.utils.gateway_route_factory import (
    build_gateway_routes_from_config,
)

ROUTE_KEY = 'proj/assistant'
# What the answer's ``model`` shows, as on the Responses API.
ROUTE_NAME = 'assistant'
ANTHROPIC_URL = 'https://api.anthropic.com/v1/messages'
CONFIGURED_KEY = 'sk-ant-configured'

MODEL_INVOKER_EMIT = 'radicalbit_ai_gateway.invocation.recorder.emit_event'
GATEWAY_EMIT = 'radicalbit_ai_gateway.pipeline.conversation.emit_event'
REQUEST_EVENT_EMIT = (
    'radicalbit_ai_gateway.middleware.request_event_middleware.emit_request_event'
)

MISTRAL = {
    'model_id': 'mistral',
    'model': 'mistralai/mistral-large-latest',
    'credentials': {'api_key': 'mistral-key'},
}

CLAUDE = {
    'model_id': 'claude',
    'model': 'anthropic/claude-sonnet-4-5',
    'credentials': {'api_key': CONFIGURED_KEY},
}

GPT = {
    'model_id': 'gpt',
    'model': 'openai/gpt-4o-mini',
    'credentials': {'api_key': 'sk-openai'},
}

# Every upstream a test route could call.
UPSTREAM_URLS = (
    ANTHROPIC_URL,
    'https://api.openai.com/v1/chat/completions',
    'https://api.openai.com/v1/responses',
    'https://api.mistral.ai/v1/chat/completions',
)

EMBEDDING = {
    'model_id': 'emb',
    'model': 'openai/text-embedding-3-small',
    'credentials': {'api_key': 'sk-openai'},
}

HAIKU = {
    'model_id': 'haiku',
    'model': 'anthropic/claude-haiku-4-5',
    'credentials': {'api_key': CONFIGURED_KEY},
}

# What a Messages client sends, with a field no SDK knows yet.
BODY = {
    'model': ROUTE_KEY,
    'max_tokens': 1024,
    'system': 'You are terse.',
    'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': 'Hi'}]}],
    'future_field': {'kept': True},
}


def _mock_request_uuid(request: Request):
    request.state.request_uuid = str(db_mock.REQUEST_UUID)
    return str(db_mock.REQUEST_UUID)


def _build_routes(
    models: list[dict],
    route_models: list[str] | None = None,
    fallbacks: list[str] | None = None,
    routing: dict | None = None,
) -> dict:
    route_models = route_models or [models[0]['model_id']]
    route: dict = {'chat_models': route_models}
    if fallbacks:
        route['fallback'] = [{'target': route_models[0], 'fallbacks': fallbacks}]
    if routing:
        route['routing'] = routing['name']
    return _routes_from(
        {
            'chat_models': models,
            'routing': [routing] if routing else None,
            'routes': {'assistant': route},
        }
    )


def _routes_from(config_data: dict) -> dict:
    """Build the ``assistant`` route of a configuration, as the server holds it."""
    config = GatewayConfig.model_validate(config_data)
    cost_service = CostService()
    project_guardrails = Guardrails(
        presidio_engine=PresidioEngine(),
        judge_engine=JudgeEngine(prompt_manager=MagicMock(spec_set=PromptManager)),
        cost_service=cost_service,
        guardrails=config.guardrails,
    )
    routes = build_gateway_routes_from_config(
        config,
        project_guardrails,
        redis_client=None,
        cost_service=cost_service,
        httpx_client=None,
        project_uuid='',
    )
    built = routes['assistant']
    built.project_name = 'proj'
    return {ROUTE_KEY: built}


def _sent(mock, index: int = 0) -> dict:
    """Return the JSON body of a request a pook mock matched."""
    return mock.matches[index].json


def _messages_error(error_type: str) -> dict:
    """Return the shape of a Messages API error, its message left out."""
    return {'type': 'error', 'error': {'type': error_type}}


def _shape(body: dict) -> dict:
    return {'type': body['type'], 'error': {'type': body['error']['type']}}


def _frames(text: str) -> list[tuple[str, dict]]:
    """Return the ``(event, data)`` pairs of an SSE body."""
    frames = []
    for block in text.strip().split('\n\n'):
        lines = dict(line.split(': ', 1) for line in block.splitlines())
        frames.append((lines['event'], json.loads(lines['data'])))
    return frames


def _blocked(*args, **kwargs):
    raise AssertionError('Real network access attempted')


class MessagesTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.dependency_overrides[get_request_uuid] = _mock_request_uuid
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides = {}

    def setUp(self):
        self.addCleanup(
            setattr, app.state, 'token_validator', app.state.token_validator
        )
        self.addCleanup(
            setattr, app.state, 'routes', getattr(app.state, 'routes', None)
        )
        app.state.token_validator = ApiKeyValidator(key_service=key_service)
        api_key = db_mock.get_sample_key_with_group(group_uuid=db_mock.GROUP_UUID)
        key_service.get_key_by_hashed_key = MagicMock(return_value=api_key)
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)
        app.state.routes = _build_routes([CLAUDE])

        request_events = patch(REQUEST_EVENT_EMIT)
        self.emit_request_event = request_events.start()
        self.addCleanup(request_events.stop)
        for patcher in (
            patch(MODEL_INVOKER_EMIT),
            patch(GATEWAY_EMIT),
            # As in the provider recorder: a missed mock fails loudly.
            patch.object(socket.socket, 'connect', _blocked),
            patch.object(socket.socket, 'connect_ex', _blocked),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        pook.on()
        # The TestClient talks httpx too: let only its own host through.
        pook.enable_network('testserver')
        self.addCleanup(pook.off)
        self.addCleanup(pook.disable_network)

    def _messages(self, body: dict | None = None, headers: dict | None = None):
        return self.client.post(
            '/v1/messages',
            json=body or BODY,
            headers={'x-api-key': db_mock.PLAIN_KEY} if headers is None else headers,
        )

    def _mock_anthropic_stream(self, sse_text: str | None = None):
        mock = pook.post(ANTHROPIC_URL).times(1)
        mock.reply(200).header('Content-Type', 'text/event-stream').body(
            sse_text or canned.anthropic_stream().sse_text()
        )
        return mock

    def _mock_every_upstream(self) -> list:
        """Mock every upstream, to check later that none was called."""
        mocks = []
        for url in UPSTREAM_URLS:
            mock = pook.post(url).times(1)
            mock.reply(500).json({})
            mocks.append(mock)
        return mocks

    def _mock_anthropic(self, reply: dict | None = None, url: str = ANTHROPIC_URL):
        mock = pook.post(url).times(1)
        mock.reply(200).json(reply or canned.anthropic_message().json_body)
        return mock


class TestMessagesRoundTrip(MessagesTestCase):
    def test_body_goes_upstream_as_sent_and_comes_back_with_the_route_name(self):
        reply = {
            **canned.anthropic_message().json_body,
            'future_field': {'kept': True},
        }
        upstream = self._mock_anthropic(reply)

        response = self._messages()

        assert response.status_code == 200
        assert _sent(upstream) == {**BODY, 'model': 'claude-sonnet-4-5'}
        assert response.json() == {**reply, 'model': ROUTE_NAME}

    def test_anthropic_headers_go_upstream_with_the_configured_key(self):
        upstream = self._mock_anthropic()

        response = self._messages(
            headers={
                'x-api-key': db_mock.PLAIN_KEY,
                'anthropic-version': '2023-06-01',
                'anthropic-beta': 'interleaved-thinking-2025-05-14',
            }
        )

        assert response.status_code == 200
        sent = upstream.matches[0].headers
        assert sent['anthropic-version'] == '2023-06-01'
        assert sent['anthropic-beta'] == 'interleaved-thinking-2025-05-14'
        assert sent['x-api-key'] == CONFIGURED_KEY
        assert db_mock.PLAIN_KEY not in json.dumps(dict(sent))

    def test_a_default_anthropic_version_is_sent_when_the_client_sets_none(self):
        upstream = self._mock_anthropic()

        response = self._messages()

        assert response.status_code == 200
        assert upstream.matches[0].headers['anthropic-version'] == '2023-06-01'
        assert 'anthropic-beta' not in upstream.matches[0].headers

    def test_a_model_with_a_custom_base_url_gets_the_request_there(self):
        app.state.routes = _build_routes(
            [{**CLAUDE, 'params': {'base_url': 'https://claude.example.com'}}]
        )
        upstream = self._mock_anthropic(url='https://claude.example.com/v1/messages')

        response = self._messages()

        assert response.status_code == 200
        assert upstream.isdone()

    def test_config_params_are_not_merged_into_the_body(self):
        app.state.routes = _build_routes(
            [{**CLAUDE, 'params': {'temperature': 0.1, 'max_tokens': 9}}]
        )
        upstream = self._mock_anthropic()

        response = self._messages()

        assert response.status_code == 200
        assert _sent(upstream) == {**BODY, 'model': 'claude-sonnet-4-5'}

    def test_configured_prompt_goes_first_in_the_system_prompt(self):
        app.state.routes = _build_routes([{**CLAUDE, 'prompt': 'Be kind.'}])
        upstream = self._mock_anthropic()

        response = self._messages()

        assert response.status_code == 200
        assert _sent(upstream)['system'] == [
            {'type': 'text', 'text': 'Be kind.'},
            {'type': 'text', 'text': 'You are terse.'},
        ]
        assert _sent(upstream)['messages'] == BODY['messages']

    def test_configured_prompt_goes_before_a_cached_system_prompt(self):
        # Claude Code sends its system prompt as blocks, the last one cached.
        system = [
            {'type': 'text', 'text': 'You are Claude Code.'},
            {
                'type': 'text',
                'text': 'Project rules.',
                'cache_control': {'type': 'ephemeral'},
            },
        ]
        app.state.routes = _build_routes([{**CLAUDE, 'prompt': 'Be kind.'}])
        upstream = self._mock_anthropic()

        response = self._messages({**BODY, 'system': system})

        assert response.status_code == 200
        assert _sent(upstream)['system'] == [
            {'type': 'text', 'text': 'Be kind.'},
            *system,
        ]

    def test_configured_prompt_is_the_system_prompt_when_the_client_sends_none(
        self,
    ):
        app.state.routes = _build_routes([{**CLAUDE, 'prompt': 'Be kind.'}])
        upstream = self._mock_anthropic()
        body = {key: value for key, value in BODY.items() if key != 'system'}

        response = self._messages(body)

        assert response.status_code == 200
        assert _sent(upstream)['system'] == 'Be kind.'

    def test_blocks_without_text_pass_through_unchanged(self):
        body = {
            **BODY,
            'thinking': {'type': 'enabled', 'budget_tokens': 2048},
            'tools': [{'name': 'get_weather', 'input_schema': {'type': 'object'}}],
            'messages': [
                {
                    'role': 'user',
                    'content': [
                        {
                            'type': 'image',
                            'source': {
                                'type': 'base64',
                                'media_type': 'image/png',
                                'data': 'iVBORw0KGgo=',
                            },
                        },
                        {
                            'type': 'text',
                            'text': 'What is this?',
                            'cache_control': {'type': 'ephemeral'},
                        },
                    ],
                },
                {
                    'role': 'assistant',
                    'content': [
                        {'type': 'thinking', 'thinking': 'Hm.', 'signature': 'sig'},
                        {
                            'type': 'tool_use',
                            'id': 'toolu_1',
                            'name': 'get_weather',
                            'input': {'city': 'Paris'},
                        },
                    ],
                },
                {
                    'role': 'user',
                    'content': [
                        {
                            'type': 'tool_result',
                            'tool_use_id': 'toolu_1',
                            'content': 'Sunny',
                        }
                    ],
                },
            ],
        }
        upstream = self._mock_anthropic()

        response = self._messages(body)

        assert response.status_code == 200
        assert _sent(upstream) == {**body, 'model': 'claude-sonnet-4-5'}


class TestMessagesAuth(MessagesTestCase):
    def test_bearer_credential_is_accepted(self):
        self._mock_anthropic()

        response = self._messages(
            headers={'Authorization': f'Bearer {db_mock.PLAIN_KEY}'}
        )

        assert response.status_code == 200

    def test_missing_credential_is_refused(self):
        response = self._messages(headers={})

        assert response.status_code == 401
        assert _shape(response.json()) == _messages_error('authentication_error')

    def test_wrong_credential_is_refused(self):
        key_service.get_key_by_hashed_key = MagicMock(
            side_effect=KeyNotFoundError('no such key')
        )

        response = self._messages(headers={'x-api-key': 'sk-rb-wrong'})

        assert response.status_code == 401
        assert _shape(response.json()) == _messages_error('authentication_error')

    def test_expired_credential_is_told_it_expired(self):
        expired = db_mock.get_sample_key_with_group(group_uuid=db_mock.GROUP_UUID)
        expired.expires_on = datetime.date(2020, 1, 1)
        key_service.get_key_by_hashed_key = MagicMock(return_value=expired)

        response = self._messages()

        assert response.status_code == 401
        assert response.json()['error']['message'] == 'API key has expired.'

    def test_credential_without_access_to_the_route_is_refused(self):
        group_service.check_key_uuid_for_route = MagicMock(return_value=False)

        response = self._messages()

        assert response.status_code == 401
        assert _shape(response.json()) == _messages_error('authentication_error')


class TestMessagesErrors(MessagesTestCase):
    def test_unknown_route_is_a_bad_request_naming_it(self):
        response = self._messages({**BODY, 'model': 'proj/nowhere'})

        assert response.status_code == 400
        body = response.json()
        assert _shape(body) == _messages_error('invalid_request_error')
        assert 'proj/nowhere' in body['error']['message']

    def test_route_without_chat_models_is_a_bad_request_naming_it(self):
        app.state.routes = _routes_from(
            {
                'embedding_models': [EMBEDDING],
                'routes': {'assistant': {'embedding_models': ['emb']}},
            }
        )
        upstreams = self._mock_every_upstream()

        response = self._messages()

        assert response.status_code == 400
        body = response.json()
        assert _shape(body) == _messages_error('invalid_request_error')
        assert body['error']['message'] == (
            'Route assistant has no chat models defined'
        )
        assert not any(upstream.matched for upstream in upstreams)

    def test_malformed_body_is_a_bad_request_in_the_messages_shape(self):
        body = {key: value for key, value in BODY.items() if key != 'max_tokens'}

        response = self._messages(body)

        assert response.status_code == 400
        body = response.json()
        assert _shape(body) == _messages_error('invalid_request_error')
        assert 'max_tokens' in body['error']['message']

    def test_body_that_is_not_json_is_a_bad_request(self):
        response = self.client.post(
            '/v1/messages',
            content=b'{not json',
            headers={
                'x-api-key': db_mock.PLAIN_KEY,
                'content-type': 'application/json',
            },
        )

        assert response.status_code == 400
        assert _shape(response.json()) == _messages_error('invalid_request_error')

    def test_unknown_sub_path_is_not_found(self):
        response = self.client.post(
            '/v1/messages/count_tokens',
            json=BODY,
            headers={'x-api-key': db_mock.PLAIN_KEY},
        )

        assert response.status_code == 404
        assert _shape(response.json()) == _messages_error('not_found_error')

    def test_unknown_sub_path_is_not_found_whatever_the_method(self):
        response = self.client.put(
            '/v1/messages/batches/msgbatch_1',
            json={},
            headers={'x-api-key': db_mock.PLAIN_KEY},
        )

        assert response.status_code == 404
        assert _shape(response.json()) == _messages_error('not_found_error')

    def _assert_refused_before_any_upstream_call(self, model: dict):
        app.state.routes = _build_routes([model])
        upstreams = self._mock_every_upstream()

        response = self._messages()

        assert response.status_code == 400
        body = response.json()
        assert _shape(body) == _messages_error('invalid_request_error')
        assert body['error']['message'] == (
            f'Model {model["model_id"]} of route assistant '
            'does not serve the Messages API'
        )
        assert not any(upstream.matched for upstream in upstreams)

    def test_mistral_model_is_refused_before_any_upstream_call(self):
        self._assert_refused_before_any_upstream_call(MISTRAL)

    def test_openai_model_is_refused_before_any_upstream_call(self):
        self._assert_refused_before_any_upstream_call(GPT)

    def test_upstream_refusal_reaches_the_client_as_sent(self):
        for status, error_type in (
            (400, 'invalid_request_error'),
            (404, 'not_found_error'),
        ):
            refusal = {
                'type': 'error',
                'error': {'type': error_type, 'message': 'upstream says no'},
                'request_id': 'req_1',
            }
            pook.post(ANTHROPIC_URL).times(1).reply(status).json(refusal)

            response = self._messages()

            assert response.status_code == status
            assert response.json() == refusal

    def test_the_sdk_does_not_retry(self):
        upstream = pook.post(ANTHROPIC_URL).times(3)
        upstream.reply(529).json(
            {'type': 'error', 'error': {'type': 'overloaded_error', 'message': 'busy'}}
        )

        response = self._messages()

        assert response.status_code == 500
        assert len(upstream.matches) == 1

    def test_upstream_server_error_without_fallback_is_an_api_error(self):
        pook.post(ANTHROPIC_URL).times(1).reply(500).json(
            {'type': 'error', 'error': {'type': 'api_error', 'message': 'boom'}}
        )

        response = self._messages()

        assert response.status_code == 500
        assert _shape(response.json()) == _messages_error('api_error')


class TestMessagesStreaming(MessagesTestCase):
    def test_stream_is_relayed_in_order_with_the_route_name(self):
        upstream_events = canned.anthropic_stream().sse_events
        upstream = self._mock_anthropic_stream()

        response = self._messages({**BODY, 'stream': True})

        assert response.status_code == 200
        assert response.headers['content-type'].startswith('text/event-stream')
        assert _sent(upstream) == {**BODY, 'stream': True, 'model': 'claude-sonnet-4-5'}
        start = upstream_events[0]
        expected = [
            {**start, 'message': {**start['message'], 'model': ROUTE_NAME}},
            *upstream_events[1:],
        ]
        assert _frames(response.text) == [(e['type'], e) for e in expected]

    def test_upstream_refusal_before_streaming_is_an_http_error(self):
        refusal = {
            'type': 'error',
            'error': {'type': 'invalid_request_error', 'message': 'no'},
        }
        pook.post(ANTHROPIC_URL).times(1).reply(400).json(refusal)

        response = self._messages({**BODY, 'stream': True})

        assert response.status_code == 400
        assert response.json() == refusal

    def test_failure_before_streaming_is_an_http_error_in_the_messages_shape(self):
        pook.post(ANTHROPIC_URL).times(1).reply(500).json(
            {'type': 'error', 'error': {'type': 'api_error', 'message': 'boom'}}
        )

        response = self._messages({**BODY, 'stream': True})

        assert response.status_code == 500
        assert _shape(response.json()) == _messages_error('api_error')

    def test_failure_after_the_first_event_ends_with_an_error_event(self):
        start = canned.anthropic_stream().sse_events[0]
        broken = (
            f'event: message_start\ndata: {json.dumps(start)}\n\ndata: {{broken\n\n'
        )
        self._mock_anthropic_stream(broken)

        response = self._messages({**BODY, 'stream': True})

        assert response.status_code == 200
        frames = _frames(response.text)
        assert [event for event, _ in frames] == ['message_start', 'error']
        assert frames[-1][1] == {
            'type': 'error',
            'error': {'type': 'api_error', 'message': 'Internal server error'},
        }

    def test_upstream_error_event_after_the_first_event_reaches_the_client(self):
        start = canned.anthropic_stream().sse_events[0]
        overloaded = {
            'type': 'error',
            'error': {'type': 'overloaded_error', 'message': 'Overloaded'},
        }
        self._mock_anthropic_stream(
            f'event: message_start\ndata: {json.dumps(start)}\n\n'
            f'event: error\ndata: {json.dumps(overloaded)}\n\n'
        )

        response = self._messages({**BODY, 'stream': True})

        assert response.status_code == 200
        assert _frames(response.text)[-1] == ('error', overloaded)


class TestMessagesFallback(MessagesTestCase):
    def _fail_once(self, status: int = 529):
        pook.post(ANTHROPIC_URL).times(1).reply(status).json(
            {'type': 'error', 'error': {'type': 'overloaded_error', 'message': 'busy'}}
        )

    def test_server_error_falls_back_to_the_next_model(self):
        app.state.routes = _build_routes(
            [CLAUDE, HAIKU], ['claude', 'haiku'], fallbacks=['haiku']
        )
        self._fail_once()
        upstream = self._mock_anthropic()

        response = self._messages()

        assert response.status_code == 200
        assert _sent(upstream)['model'] == 'claude-haiku-4-5'
        assert response.json()['model'] == ROUTE_NAME

    def test_client_error_does_not_fall_back(self):
        app.state.routes = _build_routes(
            [CLAUDE, HAIKU], ['claude', 'haiku'], fallbacks=['haiku']
        )
        refusal = {
            'type': 'error',
            'error': {'type': 'invalid_request_error', 'message': 'bad'},
        }
        pook.post(ANTHROPIC_URL).times(1).reply(400).json(refusal)
        unused = self._mock_anthropic()

        response = self._messages()

        assert response.status_code == 400
        assert response.json() == refusal
        assert not unused.matched

    def test_refusal_by_the_fallback_reaches_the_client_as_sent(self):
        app.state.routes = _build_routes(
            [CLAUDE, HAIKU], ['claude', 'haiku'], fallbacks=['haiku']
        )
        self._fail_once()
        refusal = {
            'type': 'error',
            'error': {'type': 'invalid_request_error', 'message': 'haiku says no'},
        }
        pook.post(ANTHROPIC_URL).times(1).reply(400).json(refusal)

        response = self._messages()

        assert response.status_code == 400
        assert response.json() == refusal

    def test_upstream_access_refusal_falls_back_to_the_next_model(self):
        app.state.routes = _build_routes(
            [CLAUDE, HAIKU], ['claude', 'haiku'], fallbacks=['haiku']
        )
        pook.post(ANTHROPIC_URL).times(1).reply(401).json(
            {
                'type': 'error',
                'error': {'type': 'authentication_error', 'message': 'bad key'},
            }
        )
        upstream = self._mock_anthropic()

        response = self._messages()

        assert response.status_code == 200
        assert _sent(upstream)['model'] == 'claude-haiku-4-5'

    def test_upstream_access_refusal_at_the_end_is_an_api_error(self):
        app.state.routes = _build_routes(
            [CLAUDE, HAIKU], ['claude', 'haiku'], fallbacks=['haiku']
        )
        self._fail_once()
        pook.post(ANTHROPIC_URL).times(1).reply(401).json(
            {
                'type': 'error',
                'error': {'type': 'authentication_error', 'message': 'bad key'},
            }
        )

        response = self._messages()

        assert response.status_code >= 500
        assert _shape(response.json()) == _messages_error('api_error')

    def test_upstream_permission_refusal_without_fallback_is_an_api_error(self):
        pook.post(ANTHROPIC_URL).times(1).reply(403).json(
            {
                'type': 'error',
                'error': {'type': 'permission_error', 'message': 'not allowed'},
            }
        )

        response = self._messages()

        assert response.status_code >= 500
        assert _shape(response.json()) == _messages_error('api_error')

    def test_fallback_to_a_model_without_messages_api_fails_naming_it(self):
        app.state.routes = _build_routes(
            [CLAUDE, MISTRAL], ['claude', 'mistral'], fallbacks=['mistral']
        )
        self._fail_once()

        response = self._messages()

        assert response.status_code == 400
        body = response.json()
        assert _shape(body) == _messages_error('invalid_request_error')
        assert body['error']['message'] == (
            'Model mistral of route assistant does not serve the Messages API'
        )

    def test_stream_falls_back_before_the_first_event(self):
        app.state.routes = _build_routes(
            [CLAUDE, HAIKU], ['claude', 'haiku'], fallbacks=['haiku']
        )
        self._fail_once()
        upstream = self._mock_anthropic_stream()

        response = self._messages({**BODY, 'stream': True})

        assert response.status_code == 200
        assert _sent(upstream)['model'] == 'claude-haiku-4-5'
        assert [event for event, _ in _frames(response.text)][-1] == 'message_stop'

    def test_stream_fallback_to_a_model_without_messages_api_fails(self):
        app.state.routes = _build_routes(
            [CLAUDE, MISTRAL], ['claude', 'mistral'], fallbacks=['mistral']
        )
        self._fail_once()

        response = self._messages({**BODY, 'stream': True})

        assert response.status_code == 400
        assert 'mistral' in response.json()['error']['message']


class TestMessagesRouting(MessagesTestCase):
    """Routing picks the model first; then the gateway checks it serves Messages."""

    # Requests that mention code go to Claude, any other to Mistral.
    BY_KEYWORD = {
        'name': 'by_keyword',
        'type': 'deterministic',
        'rule': 'keyword',
        'default_model_id': 'mistral',
        'output_mapping': [{'model_id': 'claude', 'conditions': ['code']}],
    }

    def setUp(self):
        super().setUp()
        app.state.routes = _build_routes(
            [MISTRAL, CLAUDE], ['mistral', 'claude'], routing=self.BY_KEYWORD
        )

    def _ask(self, text: str):
        return self._messages({**BODY, 'messages': [{'role': 'user', 'content': text}]})

    def test_request_routed_to_an_anthropic_model_is_served(self):
        upstream = self._mock_anthropic()

        response = self._ask('Review my code')

        assert response.status_code == 200
        assert upstream.isdone()

    def test_request_routed_to_a_model_without_messages_api_is_refused(self):
        response = self._ask('Tell me a joke')

        assert response.status_code == 400
        assert response.json()['error']['message'] == (
            'Model mistral of route assistant does not serve the Messages API'
        )


class TestMixedRoute(MessagesTestCase):
    """A route whose models speak different APIs, without fallback."""

    def setUp(self):
        super().setUp()
        app.state.routes = _build_routes([CLAUDE, MISTRAL], ['claude', 'mistral'])

    def test_messages_request_is_served_by_the_selected_anthropic_model(self):
        upstream = self._mock_anthropic()

        response = self._messages()

        assert response.status_code == 200
        assert upstream.isdone()

    def test_chat_completions_to_the_anthropic_model_still_translate(self):
        upstream = self._mock_anthropic()

        response = self.client.post(
            '/v1/chat/completions',
            json={
                'model': ROUTE_KEY,
                'messages': [{'role': 'user', 'content': 'Hi'}],
            },
            headers={'Authorization': f'Bearer {db_mock.PLAIN_KEY}'},
        )

        assert response.status_code == 200
        assert response.json()['choices'][0]['message']['content'] == (
            'Hello from the model'
        )
        assert _sent(upstream)['messages'] == [{'role': 'user', 'content': 'Hi'}]


class TestMessagesRequestEvents(MessagesTestCase):
    def _event(self):
        self.emit_request_event.assert_called_once()
        return self.emit_request_event.call_args.args[0]

    def test_served_request_leaves_a_successful_chat_event(self):
        self._mock_anthropic()

        self._messages()

        event = self._event()
        assert event.route_name == ROUTE_NAME
        assert event.request_type == RequestType.CHAT_COMPLETIONS
        assert event.status == RequestStatus.SUCCESS
        assert event.http_status_code == 200
        assert event.is_streaming is False

    def test_streamed_request_leaves_a_streaming_event(self):
        self._mock_anthropic_stream()

        self._messages({**BODY, 'stream': True})

        event = self._event()
        assert event.status == RequestStatus.SUCCESS
        assert event.is_streaming is True

    def test_refused_request_leaves_a_failed_event(self):
        self._messages(headers={})

        event = self._event()
        assert event.status == RequestStatus.HANDLED_ERROR
        assert event.http_status_code == 401


# What Anthropic says when a thinking block was signed by another provider.
SIGNATURE_REFUSAL = {
    'type': 'error',
    'error': {
        'type': 'invalid_request_error',
        'message': 'messages.1.content.0: Invalid `signature` in `thinking` block',
    },
    'request_id': 'req_1',
}

FOREIGN_THINKING = {'type': 'thinking', 'thinking': 'Hm.', 'signature': 'deepseek'}
ANSWER = {'type': 'text', 'text': 'Hello'}

# A conversation another provider answered with thinking.
FOREIGN_HISTORY = {
    **BODY,
    'messages': [
        {'role': 'user', 'content': 'Hi'},
        {'role': 'assistant', 'content': [FOREIGN_THINKING, ANSWER]},
        {'role': 'user', 'content': 'And now?'},
    ],
}


class TestMessagesForeignThinking(MessagesTestCase):
    """A thinking block another provider signed: retried once without it."""

    def _refuse(self, refusal: dict | None = None):
        mock = pook.post(ANTHROPIC_URL).times(1)
        mock.reply(400).json(refusal or SIGNATURE_REFUSAL)
        return mock

    def test_signature_refusal_is_retried_without_the_old_thinking(self):
        first = self._refuse()
        retry = self._mock_anthropic()

        response = self._messages(FOREIGN_HISTORY)

        assert response.status_code == 200
        assert _sent(first)['messages'] == FOREIGN_HISTORY['messages']
        assert _sent(retry)['messages'] == [
            {'role': 'user', 'content': 'Hi'},
            {'role': 'assistant', 'content': [ANSWER]},
            {'role': 'user', 'content': 'And now?'},
        ]
        assert _sent(retry)['model'] == 'claude-sonnet-4-5'

    def test_thinking_of_a_running_tool_loop_stays_on_retry(self):
        tool_use = {
            'type': 'tool_use',
            'id': 'toolu_1',
            'name': 'get_weather',
            'input': {'city': 'Paris'},
        }
        own_thinking = {'type': 'thinking', 'thinking': 'Tool.', 'signature': 'own'}
        tool_loop = [
            {'role': 'assistant', 'content': [own_thinking, tool_use]},
            {
                'role': 'user',
                'content': [
                    {'type': 'tool_result', 'tool_use_id': 'toolu_1', 'content': 'Sun'}
                ],
            },
        ]
        body = {**FOREIGN_HISTORY, 'messages': FOREIGN_HISTORY['messages'] + tool_loop}
        self._refuse()
        retry = self._mock_anthropic()

        response = self._messages(body)

        assert response.status_code == 200
        assert _sent(retry)['messages'] == [
            {'role': 'user', 'content': 'Hi'},
            {'role': 'assistant', 'content': [ANSWER]},
            {'role': 'user', 'content': 'And now?'},
            *tool_loop,
        ]

    def test_other_refusal_is_relayed_without_retry(self):
        refusal = {
            'type': 'error',
            'error': {'type': 'invalid_request_error', 'message': 'max_tokens: bad'},
        }
        self._refuse(refusal)
        unused = self._mock_anthropic()

        response = self._messages(FOREIGN_HISTORY)

        assert response.status_code == 400
        assert response.json() == refusal
        assert not unused.matched

    def test_signature_refusal_with_nothing_to_strip_is_relayed_without_retry(self):
        only_thinking = {
            **BODY,
            'messages': [
                {'role': 'user', 'content': 'Hi'},
                {'role': 'assistant', 'content': [FOREIGN_THINKING]},
                {'role': 'user', 'content': 'And now?'},
            ],
        }
        self._refuse()
        unused = self._mock_anthropic()

        response = self._messages(only_thinking)

        assert response.status_code == 400
        assert response.json() == SIGNATURE_REFUSAL
        assert not unused.matched

    def test_refused_retry_is_relayed_as_sent(self):
        self._refuse()
        refusal = {
            'type': 'error',
            'error': {'type': 'invalid_request_error', 'message': 'still no'},
        }
        retry = self._refuse(refusal)
        unused = self._mock_anthropic()

        response = self._messages(FOREIGN_HISTORY)

        assert response.status_code == 400
        assert response.json() == refusal
        assert retry.matched
        assert not unused.matched

    def test_signature_refusal_of_a_stream_is_retried_without_the_old_thinking(self):
        self._refuse()
        retry = self._mock_anthropic_stream()

        response = self._messages({**FOREIGN_HISTORY, 'stream': True})

        assert response.status_code == 200
        assert _sent(retry)['messages'][1] == {
            'role': 'assistant',
            'content': [ANSWER],
        }
        assert [event for event, _ in _frames(response.text)][-1] == 'message_stop'

    def test_refused_stream_retry_is_an_http_error_as_sent(self):
        self._refuse()
        retry = self._refuse()

        response = self._messages({**FOREIGN_HISTORY, 'stream': True})

        assert response.status_code == 400
        assert response.json() == SIGNATURE_REFUSAL
        assert retry.matched


class TestMessagesInvokerGuards(unittest.TestCase):
    """The invoker's own checks, behind the route's support check."""

    def test_a_model_the_route_does_not_hold_does_not_serve_messages(self):
        invoker = _build_routes([CLAUDE])[ROUTE_KEY].chat_invoker

        assert not invoker.supports_messages('nowhere')

    def test_the_invoker_refuses_a_model_without_messages_api(self):
        invoker = _build_routes([MISTRAL])[ROUTE_KEY].chat_invoker

        with pytest.raises(ModelInvokerBadRequest) as refused:
            asyncio.run(
                invoker.complete_messages(
                    identity=RequestIdentity(
                        request_uuid='r',
                        api_key_uuid='k',
                        group_uuid='g',
                        api_key_name='key',
                        group_name='group',
                        route_name=ROUTE_NAME,
                    ),
                    body=BODY,
                    headers={},
                    model_id='mistral',
                )
            )
        assert refused.value.client_message == (
            'Chat model mistral does not serve the Messages API'
        )
