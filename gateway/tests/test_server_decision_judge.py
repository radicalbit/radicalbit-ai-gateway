"""Decision judge through /v1/chat/completions (input and output),
/v1/embeddings and /v1/systemone.

Typesafe and OpenAI are mocked with pook.
"""

import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
import httpx
import pook
import pytest
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
from radicalbit_ai_gateway.models.credential_limiting import (
    CredentialLimitCategory,
    CredentialLimitOut,
)
from radicalbit_ai_gateway.models.event_payload import (
    FallbackEventPayload,
    InputTokenProcessedPayload,
    ModelInvocationPayload,
    OutputTokenProcessedPayload,
)
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.server import (
    app,
    group_service,
    key_service,
    project_budget_limit_dao,
)
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.dependencies import get_request_uuid
from radicalbit_ai_gateway.utils.gateway_route_factory import (
    build_gateway_routes_from_config,
)

CHAT_ROUTE_KEY = 'proj/chat'
EMBEDDING_ROUTE_KEY = 'proj/embed'
DECISION_ROUTE_KEY = 'proj/agent'
TYPESAFE_KEY = 'ts-upstream-secret'
TYPESAFE_URL = 'https://api.typesafe.ai/v1/systemone'
OPENAI_URL = 'https://api.openai.com/v1/chat/completions'
OPENAI_EMBEDDINGS_URL = 'https://api.openai.com/v1/embeddings'

MODEL_INVOKER_EMIT = 'radicalbit_ai_gateway.invocation.model_invoker.emit_event'
GATEWAY_EMIT = 'radicalbit_ai_gateway.ai_gateway.emit_event'
GUARDRAIL_EMIT = 'radicalbit_ai_gateway.guardrails.guardrail_check.emit_event'
REQUEST_EVENT_EMIT = (
    'radicalbit_ai_gateway.middleware.request_event_middleware.emit_request_event'
)
JUDGE_SPAN = (
    'radicalbit_ai_gateway.guardrails.judges.decision_judge_engine'
    '.trace.get_current_span'
)
GUARDRAIL_SPAN = (
    'radicalbit_ai_gateway.guardrails.guardrail_check.trace.get_current_span'
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
EMBEDDING = {
    'model_id': 'emb',
    'model': 'openai/text-embedding-3-small',
    'credentials': {'api_key': 'sk-123'},
}
JEV_BACKUP = {
    'model_id': 'jev-backup',
    'model': 'typesafe/jev-backup',
    'credentials': {'api_key': TYPESAFE_KEY},
}
INSTRUCTIONS = 'Is the user asking about something other than billing?'
CRITERIA = {'true': 'Not about billing', 'false': 'About billing'}
USER_TEXT = 'Tell me a joke about cats'
EMBEDDING_TEXTS = ['first text', 'second text']
EMBEDDING_RESPONSE = {
    'object': 'list',
    'data': [
        {'object': 'embedding', 'index': i, 'embedding': [0.1, 0.2, 0.3]}
        for i in range(len(EMBEDDING_TEXTS))
    ],
    'model': 'text-embedding-3-small',
    'usage': {'prompt_tokens': 4, 'total_tokens': 4},
}
DECISION_STATE = {'ticket': 'My card was charged twice', 'customer': {'tier': 'gold'}}
DECISION_QUESTIONS = {
    'intent': {
        'type': 'choice',
        'instructions': 'What does the customer want?',
        'criteria': {'refund': 'Wants money back', 'complaint': 'Wants to complain'},
    }
}
# Decision guardrails read every string leaf of state and questions, in order.
DECISION_TEXT = '\n'.join(
    [
        'My card was charged twice',
        'gold',
        'choice',
        'What does the customer want?',
        'Wants money back',
        'Wants to complain',
    ]
)
DECISION_ANSWER = {
    'model': 'jev-1.13.0',
    'answers': {
        'intent': {'type': 'choice', 'choice': {'refund': 0.9, 'complaint': 0.1}}
    },
    'usage': {'input_tokens': 312, 'output_tokens': 20},
}


def _mock_request_uuid(request: Request):
    request.state.request_uuid = str(db_mock.REQUEST_UUID)
    return str(db_mock.REQUEST_UUID)


def _decision_judge(
    behavior: str = 'block', where: str = 'input', **parameters
) -> dict:
    return {
        'name': f'off_topic_{behavior}',
        'type': 'decision_judge',
        'where': where,
        'behavior': behavior,
        'parameters': {'model_id': 'jev', 'instructions': INSTRUCTIONS, **parameters},
        'response_message': f'{behavior} by decision judge',
    }


def _build_routes(
    *guardrails: dict,
    prompt_manager=None,
    decision_models: tuple[dict, ...] = (JEV, JEV_BACKUP),
    **chat_route,
) -> dict:
    """One chat, one embedding and one decision route, each with `guardrails`.

    Output guardrails go on the chat route only: a route without chat models
    rejects them at load. `chat_route` adds to the chat route's config.
    """
    names = [g['name'] for g in guardrails]
    input_names = [g['name'] for g in guardrails if g.get('where') != 'output']
    config = GatewayConfig.model_validate(
        {
            'chat_models': [GPT],
            'embedding_models': [EMBEDDING],
            'decision_models': list(decision_models),
            'guardrails': list(guardrails),
            'routes': {
                'chat': {'chat_models': ['gpt'], 'guardrails': names, **chat_route},
                'embed': {'embedding_models': ['emb'], 'guardrails': input_names},
                'agent': {'decision_models': ['jev'], 'guardrails': input_names},
            },
        }
    )
    cost_service = CostService(
        chat_models_by_id=config.chat_models_by_id,
        embedding_models_by_id=config.embedding_models_by_id,
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
    for route in routes.values():
        route.project_name = 'proj'
    return {f'proj/{name}': route for name, route in routes.items()}


def _noul_answer(noul, input_tokens: int = 40) -> dict:
    return {
        'model': 'jev-1.13.0',
        'answers': {'decision_judge': {'type': 'noul', 'noul': noul}},
        'usage': {'input_tokens': input_tokens, 'output_tokens': 1},
    }


class TestDecisionJudgeEndpoints(unittest.TestCase):
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
        self.api_key = db_mock.get_sample_key_with_group(group_uuid=db_mock.GROUP_UUID)
        key_service.get_key_by_hashed_key = MagicMock(return_value=self.api_key)
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)

        self.emitted = []
        self.guardrail_events = []
        for patcher in (
            patch(MODEL_INVOKER_EMIT, side_effect=self.emitted.append),
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
                'model': CHAT_ROUTE_KEY,
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

    # Cost and limits

    # 312 judge tokens fill a 100 token limit on their own.
    JUDGE_TOKENS = 312
    # 312 tokens at 1000 per million cost 0.312, over a 0.1 budget.
    PRICEY_JEV = {**JEV, 'input_cost_per_million_tokens': 1000}
    PRICEY_BACKUP = {**JEV_BACKUP, 'input_cost_per_million_tokens': 2000}

    def _judge_events(self, payload_type: type) -> list:
        return [e for e in self.emitted if isinstance(e, payload_type) and e.is_judge]

    def test_judge_call_emits_cost_events_flagged_as_judge(self):
        app.state.routes = _build_routes(
            _decision_judge(), decision_models=(self.PRICEY_JEV, JEV_BACKUP)
        )
        self._mock_typesafe(body=_noul_answer(0.1, input_tokens=self.JUDGE_TOKENS))
        self._mock_openai()

        self._chat()

        [invocation] = self._judge_events(ModelInvocationPayload)
        [input_tokens] = self._judge_events(InputTokenProcessedPayload)
        [output_tokens] = self._judge_events(OutputTokenProcessedPayload)
        assert (invocation.model_id, invocation.model_type) == ('jev', 'decision_model')
        assert input_tokens.model_type == 'decision_model'
        assert input_tokens.value == self.JUDGE_TOKENS
        assert input_tokens.cost == pytest.approx(0.312)
        assert (output_tokens.value, output_tokens.cost) == (0, 0)

    def test_fallback_answer_is_costed_at_the_fallback_price(self):
        app.state.routes = _build_routes(
            _decision_judge(fallback_model_id='jev-backup'),
            decision_models=(self.PRICEY_JEV, self.PRICEY_BACKUP),
        )
        self._mock_typesafe(status=503, body={'detail': 'busy'}, times=4)
        self._mock_backup(body=_noul_answer(0.1, input_tokens=self.JUDGE_TOKENS))
        self._mock_openai()

        self._chat()

        [invocation] = self._judge_events(ModelInvocationPayload)
        [input_tokens] = self._judge_events(InputTokenProcessedPayload)
        [fallback] = self._judge_events(FallbackEventPayload)
        assert invocation.model_id == 'jev-backup'
        assert input_tokens.model_id == 'jev-backup'
        assert input_tokens.cost == pytest.approx(0.624)
        assert (fallback.target, fallback.fallback) == ('jev', 'jev-backup')

    def test_judge_call_failed_without_usage_counts_nothing(self):
        app.state.routes = _build_routes(
            _decision_judge(), token_limiting={'input': {'max_tokens': 100}}
        )
        self._mock_typesafe(status=503, body={'detail': 'busy'}, times=8)

        first = self._chat()
        second = self._chat()

        # Nothing was counted: the second request reaches the judge again.
        assert (first.status_code, second.status_code) == (500, 500)
        assert self._judge_events(InputTokenProcessedPayload) == []
        assert pook.isdone()

    def test_answer_without_noul_still_counts_its_usage(self):
        # A bad answer still spent tokens.
        app.state.routes = _build_routes(
            _decision_judge(), token_limiting={'input': {'max_tokens': 100}}
        )
        self._mock_typesafe(
            body={'answers': {}, 'usage': {'input_tokens': self.JUDGE_TOKENS}}
        )

        first = self._chat()
        second = self._chat()

        assert (first.status_code, second.status_code) == (500, 429)

    def _assert_judge_usage_blocks_the_next_request(self):
        # The judge blocks the first request before the chat model, so only
        # the judge's usage is counted. Nothing is estimated: the call passes
        # though its 312 tokens (or their cost) exceed the limit. They fill
        # the counter, so the second request is rejected before the judge.
        typesafe = self._mock_typesafe(
            body=_noul_answer(0.9, input_tokens=self.JUDGE_TOKENS)
        )

        first = self._chat()
        second = self._chat()

        assert (first.status_code, second.status_code) == (400, 429)
        assert typesafe.isdone()

    def _limit_credential(self, category: CredentialLimitCategory, value: float):
        # A plain record: the ORM `limits` relationship only takes KeyLimit rows.
        limit = db_mock.get_sample_key_limit(
            category=category.value, window_size='1 minute', max_value=value
        )
        key_record = SimpleNamespace(
            uuid=self.api_key.uuid,
            name=self.api_key.name,
            hashed_key=self.api_key.hashed_key,
            group=self.api_key.group,
            limits=[CredentialLimitOut.from_key_limit(limit)],
            expires_on=None,
        )
        key_service.get_key_by_hashed_key = MagicMock(return_value=key_record)

    def test_route_input_token_limit_counts_judge_usage(self):
        app.state.routes = _build_routes(
            _decision_judge(), token_limiting={'input': {'max_tokens': 100}}
        )

        self._assert_judge_usage_blocks_the_next_request()

    def test_route_budget_counts_judge_cost(self):
        app.state.routes = _build_routes(
            _decision_judge(),
            decision_models=(self.PRICEY_JEV, JEV_BACKUP),
            budget_limiting={'max_budget': 0.1},
        )

        self._assert_judge_usage_blocks_the_next_request()

    def test_credential_input_token_limit_counts_judge_usage(self):
        app.state.routes = _build_routes(_decision_judge())
        self._limit_credential(CredentialLimitCategory.TOKEN_INPUT, 100)

        self._assert_judge_usage_blocks_the_next_request()

    def test_credential_budget_counts_judge_cost(self):
        app.state.routes = _build_routes(
            _decision_judge(), decision_models=(self.PRICEY_JEV, JEV_BACKUP)
        )
        self._limit_credential(CredentialLimitCategory.BUDGET, 0.1)

        self._assert_judge_usage_blocks_the_next_request()

    def test_project_budget_counts_judge_cost(self):
        app.state.routes = _build_routes(
            _decision_judge(), decision_models=(self.PRICEY_JEV, JEV_BACKUP)
        )
        app.state.routes[CHAT_ROUTE_KEY].project_uuid = str(db_mock.RANDOM_UUID)
        dao = MagicMock(
            return_value=[
                db_mock.get_sample_project_budget_limit(
                    window_size='1 minute', max_value=0.1
                )
            ]
        )
        with patch.object(project_budget_limit_dao, 'get_by_project_uuid', dao):
            self._assert_judge_usage_blocks_the_next_request()

    # Tracing

    def _record_span(self) -> MagicMock:
        """One recording span for the judge and the triggered guardrail."""
        span = MagicMock()
        span.is_recording.return_value = True
        for target in (JUDGE_SPAN, GUARDRAIL_SPAN):
            patcher = patch(target, return_value=span)
            patcher.start()
            self.addCleanup(patcher.stop)
        return span

    @staticmethod
    def _span_attributes(span: MagicMock) -> dict:
        return {c.args[0]: c.args[1] for c in span.set_attribute.call_args_list}

    @staticmethod
    def _question_with_criteria() -> dict:
        return {'type': 'noul', 'instructions': INSTRUCTIONS, 'criteria': CRITERIA}

    def _assert_judge_recorded(self, attributes: dict, noul: float):
        assert attributes['guardrail.decision_judge.model_id'] == 'jev'
        assert attributes['guardrail.decision_judge.instructions'] == INSTRUCTIONS
        assert json.loads(attributes['guardrail.decision_judge.criteria']) == CRITERIA
        assert attributes['guardrail.decision_judge.threshold'] == 0.7
        assert attributes['guardrail.decision_judge.noul'] == noul
        assert attributes['guardrail.decision_judge.state'] == USER_TEXT

    def test_passing_call_records_the_judge_on_the_span(self):
        span = self._record_span()
        app.state.routes = _build_routes(
            _decision_judge(threshold=0.7, criteria=CRITERIA)
        )
        self._mock_typesafe(noul=0.2, question=self._question_with_criteria())
        self._mock_openai()

        response = self._chat()

        assert response.status_code == 200
        attributes = self._span_attributes(span)
        self._assert_judge_recorded(attributes, noul=0.2)
        assert attributes['guardrail.decision_judge.answered_model_id'] == 'jev'
        assert attributes['guardrail.decision_judge.fallback_triggered'] is False
        assert 'guardrail.triggered.name' not in attributes

    def test_triggering_call_records_the_judge_and_the_triggered_guardrail(self):
        span = self._record_span()
        app.state.routes = _build_routes(
            _decision_judge(threshold=0.7, criteria=CRITERIA)
        )
        self._mock_typesafe(noul=0.9, question=self._question_with_criteria())
        self._mock_openai()

        response = self._chat()

        assert response.status_code == 400
        attributes = self._span_attributes(span)
        self._assert_judge_recorded(attributes, noul=0.9)
        assert attributes['guardrail.decision_judge.answered_model_id'] == 'jev'
        assert attributes['guardrail.decision_judge.fallback_triggered'] is False
        assert attributes['guardrail.triggered.name'] == 'off_topic_block'
        assert attributes['guardrail.triggered.type'] == 'DECISION_JUDGE'
        assert attributes['guardrail.triggered.where'] == 'INPUT'
        assert attributes['guardrail.triggered.behavior'] == 'BLOCK'

    def test_fallback_answer_is_recorded_on_the_span(self):
        span = self._record_span()
        app.state.routes = _build_routes(
            _decision_judge(
                threshold=0.7, criteria=CRITERIA, fallback_model_id='jev-backup'
            )
        )
        question = self._question_with_criteria()
        self._mock_typesafe(
            status=503, body={'detail': 'busy'}, times=4, question=question
        )
        self._mock_backup(noul=0.9, question=question)
        self._mock_openai()

        self._chat()

        attributes = self._span_attributes(span)
        self._assert_judge_recorded(attributes, noul=0.9)
        assert attributes['guardrail.decision_judge.answered_model_id'] == 'jev-backup'
        assert attributes['guardrail.decision_judge.fallback_triggered'] is True

    def test_state_lives_under_one_dedicated_key(self):
        span = self._record_span()
        app.state.routes = _build_routes(_decision_judge())
        self._mock_typesafe(noul=0.2)
        self._mock_openai()

        self._chat()

        attributes = self._span_attributes(span)
        # The EE privacy plugin drops this one key: nothing else may hold it.
        assert [k for k in attributes if 'state' in k] == [
            'guardrail.decision_judge.state'
        ]
        assert 'guardrail.decision_judge.criteria' not in attributes

    def test_span_errors_do_not_break_the_judge(self):
        span = self._record_span()
        span.set_attribute.side_effect = RuntimeError('exporter down')
        app.state.routes = _build_routes(_decision_judge(threshold=0.7))
        self._mock_typesafe(noul=0.9)
        openai = self._mock_openai()

        response = self._chat()

        # Tracing is best effort: the judge still blocks.
        assert response.status_code == 400
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

    # Chat output

    def test_output_judge_blocks_on_the_last_assistant_message(self):
        app.state.routes = _build_routes(_decision_judge(where='output'))
        typesafe = self._mock_typesafe(noul=0.9, state='Paris')
        self._mock_openai()

        response = self._chat()

        assert response.status_code == 400
        assert response.json()['error']['message'] == 'block by decision judge'
        assert typesafe.isdone()

    def test_output_judge_below_threshold_returns_the_response_unchanged(self):
        app.state.routes = _build_routes(_decision_judge(where='output'))
        self._mock_typesafe(noul=0.1, state='Paris')
        self._mock_openai()

        response = self._chat()

        assert response.status_code == 200
        assert response.json()['choices'][0]['message']['content'] == 'Paris'
        assert pook.isdone()

    def test_output_soft_block_replaces_the_answer(self):
        app.state.routes = _build_routes(_decision_judge('soft_block', where='output'))
        self._mock_typesafe(noul=0.9, state='Paris')
        self._mock_openai()

        response = self._chat()

        assert response.status_code == 200
        assert response.headers['X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED'] == 'true'
        content = response.json()['choices'][0]['message']['content']
        assert content == 'soft_block by decision judge'

    def test_output_warn_returns_the_response_unchanged(self):
        app.state.routes = _build_routes(_decision_judge('warn', where='output'))
        self._mock_typesafe(noul=0.9, state='Paris')
        self._mock_openai()

        response = self._chat()

        assert response.status_code == 200
        assert response.json()['choices'][0]['message']['content'] == 'Paris'
        assert [e.behavior for e in self.guardrail_events] == ['WARN']

    def test_output_trigger_emits_an_output_guardrail_event(self):
        app.state.routes = _build_routes(_decision_judge(where='output'))
        self._mock_typesafe(noul=0.9, state='Paris')
        self._mock_openai()

        self._chat()

        [event] = self.guardrail_events
        assert event.type == 'DECISION_JUDGE'
        assert event.where == 'OUTPUT'

    def test_io_judge_reads_the_input_then_the_output(self):
        app.state.routes = _build_routes(_decision_judge(where='io'))
        on_input = self._mock_typesafe(noul=0.1)
        on_output = self._mock_typesafe(noul=0.1, state='Paris')
        self._mock_openai()

        response = self._chat()

        assert response.status_code == 200
        assert on_input.isdone()
        assert on_output.isdone()

    def test_streamed_output_judge_blocks_the_buffered_stream(self):
        app.state.routes = _build_routes(_decision_judge(where='output'))
        typesafe = self._mock_typesafe(noul=0.9, state='Paris')
        self._mock_openai_stream()

        response = self._chat(stream=True)

        assert response.status_code == 400
        assert response.json()['error']['message'] == 'block by decision judge'
        assert typesafe.isdone()

    def test_streamed_output_judge_below_threshold_replays_the_chunks(self):
        app.state.routes = _build_routes(_decision_judge(where='output'))
        self._mock_typesafe(noul=0.1, state='Paris')
        self._mock_openai_stream()

        response = self._chat(stream=True)

        assert response.status_code == 200
        assert 'Paris' in response.text
        assert response.text.rstrip().endswith('data: [DONE]')
        assert pook.isdone()

    # Embeddings input

    def _embed(self):
        return self.client.post(
            '/v1/embeddings',
            json={'model': EMBEDDING_ROUTE_KEY, 'input': EMBEDDING_TEXTS},
            headers=self.headers,
        )

    def _mock_openai_embeddings(self):
        mock = pook.post(OPENAI_EMBEDDINGS_URL).times(1)
        mock.reply(200).json(EMBEDDING_RESPONSE)
        return mock

    def _mock_typesafe_on_embedding_texts(self, noul):
        return self._mock_typesafe(noul=noul, state='\n'.join(EMBEDDING_TEXTS))

    def test_embeddings_judge_blocks_before_the_embedding_model(self):
        app.state.routes = _build_routes(_decision_judge())
        typesafe = self._mock_typesafe_on_embedding_texts(noul=0.9)
        openai = self._mock_openai_embeddings()

        response = self._embed()

        assert response.status_code == 400
        assert response.json()['error']['message'] == 'block by decision judge'
        assert typesafe.isdone()
        assert not openai.isdone()

    def test_embeddings_soft_block_returns_no_vectors(self):
        app.state.routes = _build_routes(_decision_judge('soft_block'))
        self._mock_typesafe_on_embedding_texts(noul=0.9)
        openai = self._mock_openai_embeddings()

        response = self._embed()

        assert response.status_code == 200
        assert response.json()['data'] == []
        assert response.json()['error'] == 'soft_block by decision judge'
        assert not openai.isdone()

    def test_embeddings_warn_lets_the_request_through(self):
        app.state.routes = _build_routes(_decision_judge('warn'))
        self._mock_typesafe_on_embedding_texts(noul=0.9)
        self._mock_openai_embeddings()

        response = self._embed()

        assert response.status_code == 200
        assert len(response.json()['data']) == len(EMBEDDING_TEXTS)
        assert pook.isdone()
        assert [e.behavior for e in self.guardrail_events] == ['WARN']

    def test_embeddings_judge_below_threshold_passes(self):
        app.state.routes = _build_routes(_decision_judge())
        self._mock_typesafe_on_embedding_texts(noul=0.1)
        self._mock_openai_embeddings()

        response = self._embed()

        assert response.status_code == 200
        assert pook.isdone()

    def test_io_judge_reads_embeddings_input(self):
        app.state.routes = _build_routes(_decision_judge(where='io'))
        judge = self._mock_typesafe_on_embedding_texts(noul=0.9)
        openai = self._mock_openai_embeddings()

        response = self._embed()

        assert response.status_code == 400
        assert judge.isdone()
        assert not openai.isdone()

    def test_embeddings_judge_failure_is_a_judge_internal_error(self):
        app.state.routes = _build_routes(_decision_judge())
        self._mock_typesafe(
            status=422, body={'detail': 'bad'}, state='\n'.join(EMBEDDING_TEXTS)
        )
        openai = self._mock_openai_embeddings()

        self._assert_fails_closed(self._embed(), openai)

    # Decision input

    def _decide(self):
        return self.client.post(
            '/v1/systemone',
            json={
                'model': DECISION_ROUTE_KEY,
                'state': DECISION_STATE,
                'questions': DECISION_QUESTIONS,
            },
            headers=self.headers,
        )

    def _mock_decision_model(self):
        mock = (
            pook.post(TYPESAFE_URL)
            .json(
                {
                    'model': 'jev-latest',
                    'state': DECISION_STATE,
                    'questions': DECISION_QUESTIONS,
                }
            )
            .times(1)
        )
        mock.reply(200).json(DECISION_ANSWER)
        return mock

    def test_decision_judge_blocks_before_the_decision_model(self):
        app.state.routes = _build_routes(_decision_judge())
        judge = self._mock_typesafe(noul=0.9, state=DECISION_TEXT)
        decision_model = self._mock_decision_model()

        response = self._decide()

        assert response.status_code == 400
        assert response.json()['error']['message'] == 'block by decision judge'
        assert judge.isdone()
        assert not decision_model.isdone()

    def test_decision_soft_block_returns_400_without_the_decision_model(self):
        app.state.routes = _build_routes(_decision_judge('soft_block'))
        self._mock_typesafe(noul=0.9, state=DECISION_TEXT)
        decision_model = self._mock_decision_model()

        response = self._decide()

        assert response.status_code == 400
        assert response.json()['error']['message'] == 'soft_block by decision judge'
        assert not decision_model.isdone()
        assert [e.behavior for e in self.guardrail_events] == ['SOFT_BLOCK']

    def test_decision_judge_below_threshold_returns_the_answer(self):
        app.state.routes = _build_routes(_decision_judge())
        self._mock_typesafe(noul=0.1, state=DECISION_TEXT)
        self._mock_decision_model()

        response = self._decide()

        assert response.status_code == 200
        assert response.json() == DECISION_ANSWER
        assert pook.isdone()

    def test_io_judge_reads_decision_input(self):
        app.state.routes = _build_routes(_decision_judge(where='io'))
        judge = self._mock_typesafe(noul=0.9, state=DECISION_TEXT)
        decision_model = self._mock_decision_model()

        response = self._decide()

        assert response.status_code == 400
        assert judge.isdone()
        assert not decision_model.isdone()
