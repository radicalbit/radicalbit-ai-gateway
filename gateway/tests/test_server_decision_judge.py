"""Decision judge on chat input, through /v1/chat/completions.

Typesafe and OpenAI are mocked with pook.
"""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
import httpx
import pook
from starlette.requests import Request

from tests.common import db_mock
from tests.common.mocked_build_openai_chat_completion import (
    to_mock_openai_chat_completion,
)

from radicalbit_ai_gateway.auth.api_key_validator import ApiKeyValidator
from radicalbit_ai_gateway.guardrails.guardrail_engine import GuardrailEngine
from radicalbit_ai_gateway.guardrails.judges.decision_judge_engine import (
    DecisionJudgeEngine,
)
from radicalbit_ai_gateway.guardrails.judges.judge_engine import JudgeEngine
from radicalbit_ai_gateway.guardrails.presidio import PresidioEngine
from radicalbit_ai_gateway.limiter import InMemoryStorage
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.server import app, group_service, key_service
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.dependencies import get_request_uuid
from radicalbit_ai_gateway.utils.gateway_route_factory import (
    build_gateway_routes_from_config,
)

ROUTE_KEY = 'proj/chat'
TYPESAFE_KEY = 'ts-upstream-secret'
TYPESAFE_URL = 'https://api.typesafe.ai/v1/systemone'
OPENAI_URL = 'https://api.openai.com/v1/chat/completions'

MODEL_INVOKER_EMIT = 'radicalbit_ai_gateway.invocation.model_invoker.emit_event'
GATEWAY_EMIT = 'radicalbit_ai_gateway.ai_gateway.emit_event'
GUARDRAIL_EMIT = 'radicalbit_ai_gateway.guardrails.guardrail_check.emit_event'
REQUEST_EVENT_EMIT = (
    'radicalbit_ai_gateway.middleware.request_event_middleware.emit_request_event'
)
BACKOFF_SLEEP = 'radicalbit_ai_gateway.invocation.decision_model_invoker.asyncio.sleep'
CREDENTIAL_STORAGE = 'radicalbit_ai_gateway.limiting.credential_limiter.InMemoryStorage'
PROJECT_STORAGE = (
    'radicalbit_ai_gateway.limiting.project_budget_limiter.InMemoryStorage'
)

GPT = {
    'model_id': 'gpt',
    'model': 'openai/gpt-4o-mini',
    'credentials': {'api_key': 'sk-123'},
}
JEV = {
    'model_id': 'jev',
    'model': 'typesafe/jev-latest',
    'credentials': {'api_key': TYPESAFE_KEY},
}
JEV_BACKUP = {
    'model_id': 'jev-backup',
    'model': 'typesafe/jev-backup',
    'credentials': {'api_key': TYPESAFE_KEY},
}
INSTRUCTIONS = 'Is the user asking about something other than billing?'
CRITERIA = {'true': 'Not about billing', 'false': 'About billing'}
USER_TEXT = 'Tell me a joke about cats'


def _mock_request_uuid(request: Request):
    request.state.request_uuid = str(db_mock.REQUEST_UUID)
    return str(db_mock.REQUEST_UUID)


def _decision_judge(behavior: str = 'block', **parameters) -> dict:
    return {
        'name': f'off_topic_{behavior}',
        'type': 'decision_judge',
        'where': 'input',
        'behavior': behavior,
        'parameters': {'model_id': 'jev', 'instructions': INSTRUCTIONS, **parameters},
        'response_message': f'{behavior} by decision judge',
    }


def _build_routes(*guardrails: dict, prompt_manager=None) -> dict:
    config = GatewayConfig.model_validate(
        {
            'chat_models': [GPT],
            'decision_models': [JEV, JEV_BACKUP],
            'guardrails': list(guardrails),
            'routes': {
                'chat': {
                    'chat_models': ['gpt'],
                    'guardrails': [g['name'] for g in guardrails],
                }
            },
        }
    )
    cost_service = CostService(
        chat_models_by_id=config.chat_models_by_id,
        decision_models_by_id=config.decision_models_by_id,
    )
    guardrail_engine = GuardrailEngine(
        presidio_engine=PresidioEngine(),
        judge_engine=JudgeEngine(
            prompt_manager=prompt_manager or MagicMock(spec_set=PromptManager)
        ),
        decision_judge_engine=DecisionJudgeEngine(
            decision_models=config.decision_models,
            cost_service=cost_service,
        ),
        cost_service=cost_service,
        guardrails=config.guardrails,
        chat_models_by_id=config.chat_models_by_id,
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


def _noul_answer(noul) -> dict:
    return {
        'model': 'jev-1.13.0',
        'answers': {'decision_judge': {'type': 'noul', 'noul': noul}},
        'usage': {'input_tokens': 40, 'output_tokens': 1},
    }


class TestDecisionJudgeOnChatInput(unittest.TestCase):
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

        self.guardrail_events = []
        for patcher in (
            patch(MODEL_INVOKER_EMIT),
            patch(GATEWAY_EMIT),
            patch(REQUEST_EVENT_EMIT),
            patch(GUARDRAIL_EMIT, side_effect=self.guardrail_events.append),
            patch(BACKOFF_SLEEP, new=AsyncMock()),
            patch(CREDENTIAL_STORAGE, return_value=InMemoryStorage()),
            patch(PROJECT_STORAGE, return_value=InMemoryStorage()),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        pook.on()
        # The TestClient talks httpx too: let only its own host through.
        pook.enable_network('testserver')
        self.addCleanup(pook.off)
        self.addCleanup(pook.disable_network)

    def _chat(self, messages: list[dict] | None = None, stream: bool = False):
        return self.client.post(
            '/v1/chat/completions',
            json={
                'model': ROUTE_KEY,
                'messages': messages or [{'role': 'user', 'content': USER_TEXT}],
                'stream': stream,
            },
            headers=self.headers,
        )

    def _mock_typesafe(
        self,
        noul=None,
        body=None,
        question=None,
        state: str = USER_TEXT,
        status: int = 200,
        times: int = 1,
        raw_body: str | None = None,
        model: str = 'jev-latest',
    ):
        expected_question = question or {
            'type': 'noul',
            'instructions': INSTRUCTIONS,
        }
        mock = (
            pook.post(TYPESAFE_URL)
            .header('Authorization', f'Bearer {TYPESAFE_KEY}')
            .json(
                {
                    'model': model,
                    'state': state,
                    'questions': {'decision_judge': expected_question},
                }
            )
            .times(times)
        )
        if raw_body is not None:
            mock.reply(status).body(raw_body)
        else:
            mock.reply(status).json(body if body is not None else _noul_answer(noul))
        return mock

    def _assert_fails_closed(self, response, openai):
        assert response.status_code == 500
        assert response.json()['error']['code'] == 'judge_internal_error'
        assert not openai.isdone()

    def _mock_openai(self):
        mock = pook.post(OPENAI_URL).times(1)
        mock.reply(200).json(
            to_mock_openai_chat_completion(content='Paris').model_dump()
        )
        return mock

    def test_noul_above_threshold_blocks_before_the_chat_model(self):
        app.state.routes = _build_routes(_decision_judge(threshold=0.7))
        self._mock_typesafe(noul=0.9)
        openai = self._mock_openai()

        response = self._chat()

        assert response.status_code == 400
        assert response.json()['error']['message'] == 'block by decision judge'
        assert not openai.isdone()

    def test_noul_at_threshold_triggers(self):
        app.state.routes = _build_routes(_decision_judge(threshold=0.7))
        self._mock_typesafe(noul=0.7)
        openai = self._mock_openai()

        response = self._chat()

        assert response.status_code == 400
        assert not openai.isdone()

    def test_noul_below_threshold_passes(self):
        app.state.routes = _build_routes(_decision_judge(threshold=0.7))
        self._mock_typesafe(noul=0.69)
        self._mock_openai()

        response = self._chat()

        assert response.status_code == 200
        assert response.json()['choices'][0]['message']['content'] == 'Paris'
        assert pook.isdone()

    def test_default_threshold_is_one_half(self):
        app.state.routes = _build_routes(_decision_judge())
        self._mock_typesafe(noul=0.5)
        openai = self._mock_openai()

        response = self._chat()

        assert response.status_code == 400
        assert not openai.isdone()

    def test_request_carries_text_as_state_and_one_noul_question(self):
        app.state.routes = _build_routes(_decision_judge(criteria=CRITERIA))
        typesafe = self._mock_typesafe(
            noul=0.1,
            question={
                'type': 'noul',
                'instructions': INSTRUCTIONS,
                'criteria': CRITERIA,
            },
        )
        self._mock_openai()

        response = self._chat()

        assert response.status_code == 200
        assert typesafe.isdone()

    # Behaviors

    def test_soft_block_returns_the_usual_chat_refusal(self):
        app.state.routes = _build_routes(_decision_judge('soft_block'))
        self._mock_typesafe(noul=0.9)
        openai = self._mock_openai()

        response = self._chat()

        assert response.status_code == 200
        assert response.headers['X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED'] == 'true'
        content = response.json()['choices'][0]['message']['content']
        assert content == 'soft_block by decision judge'
        assert not openai.isdone()

    def test_warn_lets_the_request_through(self):
        app.state.routes = _build_routes(_decision_judge('warn'))
        self._mock_typesafe(noul=0.9)
        self._mock_openai()

        response = self._chat()

        assert response.status_code == 200
        assert response.json()['choices'][0]['message']['content'] == 'Paris'
        assert pook.isdone()

    def test_trigger_emits_the_guardrail_event(self):
        app.state.routes = _build_routes(_decision_judge())
        self._mock_typesafe(noul=0.9)
        self._mock_openai()

        self._chat()

        [event] = self.guardrail_events
        assert event.name == 'off_topic_block'
        assert event.type == 'DECISION_JUDGE'
        assert event.where == 'INPUT'
        assert event.behavior == 'BLOCK'

    # Text sent as state

    def test_by_default_only_user_messages_are_sent(self):
        app.state.routes = _build_routes(_decision_judge())
        typesafe = self._mock_typesafe(noul=0.1)
        self._mock_openai()

        response = self._chat(
            [
                {'role': 'system', 'content': 'You are a billing assistant'},
                {'role': 'user', 'content': USER_TEXT},
            ]
        )

        assert response.status_code == 200
        assert typesafe.isdone()

    def test_message_roles_change_what_is_sent(self):
        guardrail = _decision_judge()
        guardrail['message_roles'] = ['system', 'user']
        app.state.routes = _build_routes(guardrail)
        typesafe = self._mock_typesafe(
            noul=0.1, state=f'You are a billing assistant\n{USER_TEXT}'
        )
        self._mock_openai()

        response = self._chat(
            [
                {'role': 'system', 'content': 'You are a billing assistant'},
                {'role': 'user', 'content': USER_TEXT},
            ]
        )

        assert response.status_code == 200
        assert typesafe.isdone()

    # Retries and fail closed

    def test_transient_error_is_retried(self):
        app.state.routes = _build_routes(_decision_judge())
        self._mock_typesafe(status=503, body={'detail': 'busy'})
        self._mock_typesafe(noul=0.1)
        self._mock_openai()

        response = self._chat()

        assert response.status_code == 200
        assert pook.isdone()

    def test_exhausted_retries_fail_closed(self):
        app.state.routes = _build_routes(_decision_judge())
        # retry_attempts defaults to 3: one call plus three retries.
        typesafe = self._mock_typesafe(status=503, body={'detail': 'busy'}, times=4)
        openai = self._mock_openai()

        response = self._chat()

        self._assert_fails_closed(response, openai)
        assert typesafe.isdone()

    def test_client_error_is_not_retried_and_fails_closed(self):
        app.state.routes = _build_routes(_decision_judge())
        typesafe = self._mock_typesafe(status=422, body={'detail': 'bad'})
        openai = self._mock_openai()

        response = self._chat()

        self._assert_fails_closed(response, openai)
        assert typesafe.isdone()

    def test_answer_without_noul_fails_closed(self):
        app.state.routes = _build_routes(_decision_judge())
        self._mock_typesafe(body={'answers': {}, 'usage': {'input_tokens': 40}})
        openai = self._mock_openai()

        self._assert_fails_closed(self._chat(), openai)

    def _assert_noul_fails_closed(self, noul):
        app.state.routes = _build_routes(_decision_judge())
        self._mock_typesafe(noul=noul)
        openai = self._mock_openai()

        self._assert_fails_closed(self._chat(), openai)

    def test_string_noul_fails_closed(self):
        self._assert_noul_fails_closed('high')

    def test_boolean_noul_fails_closed(self):
        self._assert_noul_fails_closed(True)

    def test_null_noul_fails_closed(self):
        self._assert_noul_fails_closed(None)

    def test_non_json_answer_fails_closed(self):
        app.state.routes = _build_routes(_decision_judge())
        self._mock_typesafe(raw_body='<html>oops</html>')
        openai = self._mock_openai()

        self._assert_fails_closed(self._chat(), openai)

    def test_rate_limited_answer_is_retried(self):
        app.state.routes = _build_routes(_decision_judge())
        self._mock_typesafe(status=429, body={'detail': 'slow down'})
        self._mock_typesafe(noul=0.1)
        self._mock_openai()

        response = self._chat()

        assert response.status_code == 200
        assert pook.isdone()

    def test_network_error_is_retried(self):
        app.state.routes = _build_routes(_decision_judge())
        pook.post(TYPESAFE_URL).times(1).error(httpx.ConnectError('refused'))
        self._mock_typesafe(noul=0.1)
        self._mock_openai()

        response = self._chat()

        assert response.status_code == 200
        assert pook.isdone()

    def test_timeout_is_retried(self):
        app.state.routes = _build_routes(_decision_judge())
        pook.post(TYPESAFE_URL).times(1).error(httpx.ReadTimeout('too slow'))
        self._mock_typesafe(noul=0.1)
        self._mock_openai()

        response = self._chat()

        assert response.status_code == 200
        assert pook.isdone()

    # Fallback

    def _mock_backup(self, **kwargs):
        return self._mock_typesafe(model='jev-backup', **kwargs)

    def test_fallback_answers_when_the_primary_is_exhausted(self):
        app.state.routes = _build_routes(
            _decision_judge(threshold=0.7, fallback_model_id='jev-backup')
        )
        self._mock_typesafe(status=503, body={'detail': 'busy'}, times=4)
        backup = self._mock_backup(noul=0.9)
        openai = self._mock_openai()

        response = self._chat()

        assert response.status_code == 400
        assert response.json()['error']['message'] == 'block by decision judge'
        assert backup.isdone()
        assert not openai.isdone()

    def test_fallback_noul_below_threshold_passes(self):
        app.state.routes = _build_routes(
            _decision_judge(threshold=0.7, fallback_model_id='jev-backup')
        )
        self._mock_typesafe(status=503, body={'detail': 'busy'}, times=4)
        self._mock_backup(noul=0.2)
        self._mock_openai()

        response = self._chat()

        assert response.status_code == 200
        assert pook.isdone()

    def test_primary_and_fallback_exhausted_fail_closed(self):
        app.state.routes = _build_routes(
            _decision_judge(fallback_model_id='jev-backup')
        )
        self._mock_typesafe(status=503, body={'detail': 'busy'}, times=4)
        backup = self._mock_backup(status=503, body={'detail': 'busy'}, times=4)
        openai = self._mock_openai()

        response = self._chat()

        self._assert_fails_closed(response, openai)
        assert backup.isdone()

    def test_fallback_is_not_called_when_the_primary_answers(self):
        app.state.routes = _build_routes(
            _decision_judge(fallback_model_id='jev-backup')
        )
        self._mock_typesafe(noul=0.1)
        backup = self._mock_backup(noul=0.9)
        self._mock_openai()

        response = self._chat()

        assert response.status_code == 200
        assert not backup.isdone()

    def test_primary_client_error_fails_closed_without_the_fallback(self):
        app.state.routes = _build_routes(
            _decision_judge(fallback_model_id='jev-backup')
        )
        typesafe = self._mock_typesafe(status=422, body={'detail': 'bad'})
        backup = self._mock_backup(noul=0.1)
        openai = self._mock_openai()

        response = self._chat()

        self._assert_fails_closed(response, openai)
        assert typesafe.isdone()
        assert not backup.isdone()

    def test_primary_rate_limited_after_retries_moves_to_the_fallback(self):
        app.state.routes = _build_routes(
            _decision_judge(fallback_model_id='jev-backup')
        )
        self._mock_typesafe(status=429, body={'detail': 'slow down'}, times=4)
        backup = self._mock_backup(noul=0.9)
        openai = self._mock_openai()

        response = self._chat()

        assert response.status_code == 400
        assert backup.isdone()
        assert not openai.isdone()

    def test_primary_unreachable_moves_to_the_fallback(self):
        app.state.routes = _build_routes(
            _decision_judge(fallback_model_id='jev-backup')
        )
        pook.post(TYPESAFE_URL).times(4).error(httpx.ConnectError('refused'))
        backup = self._mock_backup(noul=0.9)
        openai = self._mock_openai()

        response = self._chat()

        assert response.status_code == 400
        assert backup.isdone()
        assert not openai.isdone()

    def test_primary_answer_without_noul_moves_to_the_fallback(self):
        app.state.routes = _build_routes(
            _decision_judge(fallback_model_id='jev-backup')
        )
        self._mock_typesafe(body={'answers': {}, 'usage': {'input_tokens': 40}})
        backup = self._mock_backup(noul=0.9)
        openai = self._mock_openai()

        response = self._chat()

        assert response.status_code == 400
        assert backup.isdone()
        assert not openai.isdone()

    def test_primary_invalid_noul_moves_to_the_fallback(self):
        app.state.routes = _build_routes(
            _decision_judge(fallback_model_id='jev-backup')
        )
        self._mock_typesafe(noul='high')
        backup = self._mock_backup(noul=0.9)
        openai = self._mock_openai()

        response = self._chat()

        assert response.status_code == 400
        assert backup.isdone()
        assert not openai.isdone()

    # LLM judge

    def test_llm_judge_failure_is_a_judge_internal_error(self):
        prompt_manager = MagicMock(spec_set=PromptManager)
        llm_judge = {
            'name': 'llm_off_topic',
            'type': 'judge',
            'where': 'input',
            'parameters': {'prompt': 'Is this off topic?', 'model_id': 'gpt'},
        }
        app.state.routes = _build_routes(llm_judge, prompt_manager=prompt_manager)
        # The SDK does not retry a 400: the judge call fails at once.
        judge_call = pook.post(OPENAI_URL).times(1)
        judge_call.reply(400).json({'error': {'message': 'bad request'}})
        chat_call = self._mock_openai()

        response = self._chat()

        self._assert_fails_closed(response, chat_call)
        assert judge_call.isdone()

    # Streaming

    def _mock_openai_stream(self):
        chunk = {
            'id': 'chatcmpl-mock',
            'object': 'chat.completion.chunk',
            'created': 1234567890,
            'model': 'gpt-4o-mini',
            'choices': [
                {
                    'index': 0,
                    'delta': {'role': 'assistant', 'content': 'Paris'},
                    'finish_reason': None,
                }
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

    def test_streamed_request_is_blocked_before_the_chat_model(self):
        app.state.routes = _build_routes(_decision_judge())
        self._mock_typesafe(noul=0.9)
        openai = self._mock_openai_stream()

        response = self._chat(stream=True)

        assert response.status_code == 400
        assert response.json()['error']['message'] == 'block by decision judge'
        assert not openai.isdone()

    def test_streamed_request_below_threshold_streams_the_answer(self):
        app.state.routes = _build_routes(_decision_judge())
        self._mock_typesafe(noul=0.1)
        self._mock_openai_stream()

        response = self._chat(stream=True)

        assert response.status_code == 200
        assert 'Paris' in response.text
        assert pook.isdone()
