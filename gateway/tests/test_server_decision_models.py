"""POST /v1/systemone: Jev proxied through the gateway, Typesafe mocked with pook."""

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

from radicalbit_ai_gateway.auth.api_key_validator import ApiKeyValidator
from radicalbit_ai_gateway.caching.gateway_cache import GatewayCache
from radicalbit_ai_gateway.caching.semantic_caching import SemanticCache
from radicalbit_ai_gateway.guardrails.guardrail_engine import GuardrailEngine
from radicalbit_ai_gateway.guardrails.judges.judge_engine import JudgeEngine
from radicalbit_ai_gateway.guardrails.presidio import PresidioEngine
from radicalbit_ai_gateway.limiter import InMemoryStorage
from radicalbit_ai_gateway.models.credential_limiting import (
    CredentialLimitCategory,
    CredentialLimitOut,
)
from radicalbit_ai_gateway.models.event_payload import (
    CacheEventPayload,
    FallbackEventPayload,
    InputTokenProcessedPayload,
    ModelInvocationPayload,
    OutputTokenProcessedPayload,
)
from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.request_event_type import RequestType
from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.server import (
    app,
    group_service,
    key_service,
    project_budget_limit_dao,
)
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.dependencies import get_request_uuid
from radicalbit_ai_gateway.utils.exceptions import KeyNotFoundError
from radicalbit_ai_gateway.utils.gateway_route_factory import (
    build_gateway_routes_from_config,
)

ROUTE_KEY = 'proj/agent'
TYPESAFE_KEY = 'ts-upstream-secret'
TYPESAFE_URL = 'https://api.typesafe.ai/v1/systemone'

MODEL_INVOKER_EMIT = 'radicalbit_ai_gateway.invocation.model_invoker.emit_event'
REQUEST_EVENT_EMIT = (
    'radicalbit_ai_gateway.middleware.request_event_middleware.emit_request_event'
)
SPAN = 'radicalbit_ai_gateway.invocation.decision_model_invoker.trace.get_current_span'
# Credential and project limiters are built per request. Redis shares their
# counters in production: one shared in-memory storage does it here.
CREDENTIAL_STORAGE = 'radicalbit_ai_gateway.limiting.credential_limiter.InMemoryStorage'
PROJECT_STORAGE = (
    'radicalbit_ai_gateway.limiting.project_budget_limiter.InMemoryStorage'
)
BACKOFF_SLEEP = 'radicalbit_ai_gateway.invocation.decision_model_invoker.asyncio.sleep'

STATE = {'ticket': 'My card was charged twice', 'customer': {'tier': 'gold'}}
QUESTIONS = {
    'intent': {
        'type': 'choice',
        'instructions': 'What does the customer want?',
        'criteria': {
            'refund': 'Wants money back',
            'information': 'Wants an explanation',
            'complaint': 'Wants to complain',
        },
    }
}
TYPESAFE_BODY = {
    'model': 'jev-1.13.0',
    'answers': {
        'intent': {
            'type': 'choice',
            'choice': {'refund': 0.91, 'information': 0.04, 'complaint': 0.05},
        }
    },
    'usage': {'input_tokens': 312, 'output_tokens': 20},
}


def _mock_request_uuid(request: Request):
    request.state.request_uuid = str(db_mock.REQUEST_UUID)
    return str(db_mock.REQUEST_UUID)


def _build_routes(
    *decision_models: dict,
    guardrails: list[dict] | None = None,
    top_level: dict | None = None,
    **route_config,
) -> dict:
    config = GatewayConfig.model_validate(
        {
            'decision_models': list(decision_models),
            'guardrails': guardrails,
            'routes': {
                'agent': {
                    'decision_models': [m['model_id'] for m in decision_models],
                    'guardrails': [g['name'] for g in guardrails or []],
                    **route_config,
                }
            },
            **(top_level or {}),
        }
    )
    cost_service = CostService(decision_models_by_id=config.decision_models_by_id)
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
    route = routes['agent']
    route.project_name = 'proj'
    return {ROUTE_KEY: route}


JEV = {
    'model_id': 'jev',
    'model': 'typesafe/jev-latest',
    'credentials': {'api_key': TYPESAFE_KEY},
}
TYPESAFE_EU_URL = 'https://typesafe.eu.example.com/v1/systemone'
JEV_EU = {
    'model_id': 'jev-eu',
    'model': 'typesafe/jev-latest',
    'credentials': {
        'api_key': TYPESAFE_KEY,
        'base_url': 'https://typesafe.eu.example.com',
    },
}
JEV_TO_JEV_EU = [{'target': 'jev', 'fallbacks': ['jev-eu'], 'type': 'decision'}]


CACHE_EMIT = 'radicalbit_ai_gateway.ai_gateway.emit_event'
# No Redis client in these tests: an exact cache falls back to in-memory.
EXACT_CACHE = {
    'caching': {'type': 'exact'},
    'top_level': {'cache': {'redis_host': 'localhost', 'redis_port': 6379}},
}

GUARDRAIL_EMIT = 'radicalbit_ai_gateway.guardrails.guardrail_check.emit_event'
REDACT_EMIT = 'radicalbit_ai_gateway.guardrails.guardrail_redact.emit_event'


def _check_guardrail(behavior: str, value: str) -> dict:
    return {
        'name': f'{behavior}_check',
        'type': 'contains',
        'where': 'input',
        'behavior': behavior,
        'parameters': {'values': [value]},
        'response_message': f'{behavior} by policy',
    }


REDACT_EMAIL = {
    'name': 'redact_email',
    'type': 'presidio_anonymizer',
    'where': 'input',
    'parameters': {'language': 'en', 'entities': ['EMAIL_ADDRESS']},
}


class TestDecisionModelEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.dependency_overrides[get_request_uuid] = _mock_request_uuid
        cls.client = TestClient(app)
        cls.headers = {'Authorization': f'Bearer {db_mock.PLAIN_KEY}'}

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides = {}

    def setUp(self):
        app.state.routes = _build_routes(JEV)
        # Other test modules swap the validator: use the real one, which reads
        # the credential's limits from the key.
        self.addCleanup(
            setattr, app.state, 'token_validator', app.state.token_validator
        )
        app.state.token_validator = ApiKeyValidator(key_service=key_service)
        self.api_key = db_mock.get_sample_key_with_group(group_uuid=db_mock.GROUP_UUID)
        key_service.get_key_by_hashed_key = MagicMock(return_value=self.api_key)
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)

        self.emitted = []
        self.request_events = []
        self.guardrail_events = []
        self.cache_events = []
        self.span = MagicMock()
        self.span.is_recording.return_value = True
        for patcher in (
            patch(MODEL_INVOKER_EMIT, side_effect=self.emitted.append),
            patch(REQUEST_EVENT_EMIT, side_effect=self.request_events.append),
            patch(SPAN, return_value=self.span),
            patch(BACKOFF_SLEEP, new=AsyncMock()),
            patch(CREDENTIAL_STORAGE, return_value=InMemoryStorage()),
            patch(PROJECT_STORAGE, return_value=InMemoryStorage()),
            patch(GUARDRAIL_EMIT, side_effect=self.guardrail_events.append),
            patch(REDACT_EMIT, side_effect=self.guardrail_events.append),
            patch(CACHE_EMIT, side_effect=self.cache_events.append),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        pook.on()
        # The TestClient talks httpx too: let only its own host through.
        pook.enable_network('testserver')
        self.addCleanup(pook.off)
        self.addCleanup(pook.disable_network)

    def _post(self, model: str = ROUTE_KEY, headers: dict | None = None):
        return self.client.post(
            '/v1/systemone',
            json={'state': STATE, 'model': model, 'questions': QUESTIONS},
            headers=self.headers if headers is None else headers,
        )

    def _mock_typesafe(self, url: str = TYPESAFE_URL, status: int = 200, body=None):
        mock = (
            pook.post(url)
            .header('Authorization', f'Bearer {TYPESAFE_KEY}')
            .json({'state': STATE, 'model': 'jev-latest', 'questions': QUESTIONS})
            .times(1)
        )
        mock.reply(status).json(TYPESAFE_BODY if body is None else body)
        return mock

    def test_success_body_and_status_reach_the_client_unchanged(self):
        self._mock_typesafe()

        response = self._post()

        assert response.status_code == 200
        assert response.json() == TYPESAFE_BODY
        assert pook.isdone()

    def test_upstream_client_error_is_returned_unchanged(self):
        error = {'detail': 'question intent: options must not be empty'}
        self._mock_typesafe(status=422, body=error)

        response = self._post()

        assert response.status_code == 422
        assert response.json() == error

    def test_base_url_overrides_the_typesafe_default(self):
        app.state.routes = _build_routes(
            {
                **JEV,
                'credentials': {
                    'api_key': TYPESAFE_KEY,
                    'base_url': 'https://typesafe.eu.example.com',
                },
            }
        )
        self._mock_typesafe(url='https://typesafe.eu.example.com/v1/systemone')

        response = self._post()

        assert response.status_code == 200
        assert pook.isdone()

    def test_unknown_route_is_rejected(self):
        response = self._post(model='proj/missing')

        assert response.status_code == 400

    def test_missing_credential_is_rejected(self):
        response = self._post(headers={})

        assert response.status_code == 401

    def test_wrong_credential_is_rejected(self):
        key_service.get_key_by_hashed_key = MagicMock(
            side_effect=KeyNotFoundError('no such key')
        )

        response = self._post()

        assert response.status_code == 401

    def test_credential_not_belonging_to_the_route_is_rejected(self):
        group_service.check_key_uuid_for_route = MagicMock(return_value=False)

        response = self._post()

        assert response.status_code == 401

    def test_request_is_recorded_as_decision_model(self):
        self._mock_typesafe()

        self._post()

        assert [e.request_type for e in self.request_events] == [
            RequestType.DECISION_MODEL
        ]

    def test_cost_is_input_tokens_times_input_price_and_output_adds_zero(self):
        self._mock_typesafe()

        self._post()

        [invocation] = [
            e for e in self.emitted if isinstance(e, ModelInvocationPayload)
        ]
        [input_tokens] = [
            e for e in self.emitted if isinstance(e, InputTokenProcessedPayload)
        ]
        [output_tokens] = [
            e for e in self.emitted if isinstance(e, OutputTokenProcessedPayload)
        ]
        assert invocation.model_id == 'jev'
        assert invocation.model_type == 'decision_model'
        assert input_tokens.value == 312
        assert input_tokens.cost == pytest.approx(312 * 0.042 / 1_000_000)
        assert output_tokens.value == 0
        assert output_tokens.cost == 0

    def test_span_carries_decision_request_and_response(self):
        self._mock_typesafe()

        self._post()

        attributes = {
            c.args[0]: c.args[1] for c in self.span.set_attribute.call_args_list
        }
        assert json.loads(attributes['decision.request.state']) == STATE
        assert json.loads(attributes['decision.request.questions']) == QUESTIONS
        assert attributes['decision.request.model_id'] == 'jev'
        assert (
            json.loads(attributes['decision.response.answers'])
            == TYPESAFE_BODY['answers']
        )
        assert (
            json.loads(attributes['decision.response.usage']) == TYPESAFE_BODY['usage']
        )
        assert attributes['decision.response.model_id'] == 'jev'

    def test_server_error_is_retried_and_the_later_success_is_returned(self):
        self._mock_typesafe(status=503, body={'detail': 'busy'})
        self._mock_typesafe()

        response = self._post()

        assert response.status_code == 200
        assert response.json() == TYPESAFE_BODY
        assert pook.isdone()

    def test_rate_limited_response_is_retried(self):
        self._mock_typesafe(status=429, body={'detail': 'slow down'})
        self._mock_typesafe()

        response = self._post()

        assert response.status_code == 200
        assert pook.isdone()

    def test_network_error_is_retried(self):
        pook.post(TYPESAFE_URL).times(1).error(httpx.ConnectError('refused'))
        self._mock_typesafe()

        response = self._post()

        assert response.status_code == 200
        assert pook.isdone()

    def test_client_error_is_not_retried(self):
        error = {'detail': 'bad question'}
        self._mock_typesafe(status=400, body=error)
        retry = self._mock_typesafe()

        response = self._post()

        assert response.status_code == 400
        assert response.json() == error
        assert not retry.isdone()

    def test_timeout_is_retried(self):
        pook.post(TYPESAFE_URL).times(1).error(httpx.ReadTimeout('too slow'))
        self._mock_typesafe()

        response = self._post()

        assert response.status_code == 200
        assert pook.isdone()

    def _route_with_fallback(self):
        app.state.routes = _build_routes(
            {**JEV, 'retry_attempts': 1},
            {**JEV_EU, 'retry_attempts': 0},
            fallback=JEV_TO_JEV_EU,
        )

    def _span_attributes(self) -> dict:
        return {c.args[0]: c.args[1] for c in self.span.set_attribute.call_args_list}

    def test_exhausted_retries_fall_back_to_the_next_decision_model(self):
        self._route_with_fallback()
        self._mock_typesafe(status=503, body={'detail': 'busy'})
        self._mock_typesafe(status=503, body={'detail': 'busy'})
        self._mock_typesafe(url=TYPESAFE_EU_URL)

        response = self._post()

        assert response.status_code == 200
        assert response.json() == TYPESAFE_BODY
        assert pook.isdone()

    def test_client_error_does_not_fall_back(self):
        self._route_with_fallback()
        error = {'detail': 'bad question'}
        self._mock_typesafe(status=400, body=error)
        fallback = self._mock_typesafe(url=TYPESAFE_EU_URL)

        response = self._post()

        assert response.status_code == 400
        assert response.json() == error
        assert not fallback.isdone()

    def test_exhausted_chain_returns_the_last_upstream_status_and_body(self):
        self._route_with_fallback()
        self._mock_typesafe(status=503, body={'detail': 'busy'})
        self._mock_typesafe(status=500, body={'detail': 'broken'})
        self._mock_typesafe(
            url=TYPESAFE_EU_URL, status=429, body={'detail': 'slow down'}
        )

        response = self._post()

        assert response.status_code == 429
        assert response.json() == {'detail': 'slow down'}
        assert pook.isdone()

    def test_exhausted_chain_with_no_upstream_response_returns_502(self):
        app.state.routes = _build_routes(
            {**JEV, 'retry_attempts': 0},
            {**JEV_EU, 'retry_attempts': 0},
            fallback=JEV_TO_JEV_EU,
        )
        pook.post(TYPESAFE_URL).times(1).error(httpx.ConnectError('refused'))
        pook.post(TYPESAFE_EU_URL).times(1).error(httpx.ReadTimeout('too slow'))

        response = self._post()

        assert response.status_code == 502
        assert pook.isdone()

    def test_span_records_the_fallback_that_served_the_request(self):
        self._route_with_fallback()
        self._mock_typesafe(status=503, body={'detail': 'busy'})
        self._mock_typesafe(status=503, body={'detail': 'busy'})
        self._mock_typesafe(url=TYPESAFE_EU_URL)

        self._post()

        attributes = self._span_attributes()
        assert attributes['decision.response.fallback_triggered'] is True
        assert attributes['decision.response.model_id'] == 'jev-eu'
        [fallback] = [e for e in self.emitted if isinstance(e, FallbackEventPayload)]
        assert (fallback.target, fallback.fallback) == ('jev', 'jev-eu')

    def test_span_records_no_fallback_when_the_target_answers(self):
        self._route_with_fallback()
        self._mock_typesafe()

        self._post()

        assert self._span_attributes()['decision.response.fallback_triggered'] is False

    def test_span_records_the_fallback_on_an_exhausted_chain(self):
        self._route_with_fallback()
        self._mock_typesafe(status=503, body={'detail': 'busy'})
        self._mock_typesafe(status=503, body={'detail': 'busy'})
        self._mock_typesafe(url=TYPESAFE_EU_URL, status=503, body={'detail': 'busy'})

        self._post()

        attributes = self._span_attributes()
        assert attributes['decision.response.fallback_triggered'] is True
        assert attributes['decision.response.model_id'] == 'jev-eu'

    # Limits (AG-1000)

    def test_route_rate_limit_applies(self):
        app.state.routes = _build_routes(
            JEV, rate_limiting={'max_requests': 1, 'window_size': '1 minute'}
        )
        self._mock_typesafe()

        first = self._post()
        second = self._post()

        assert first.status_code == 200
        assert second.status_code == 429

    def _limit_credential(self, category: CredentialLimitCategory, value: float):
        # A plain record: the ORM `limits` relationship only takes KeyLimit rows.
        limit = db_mock.get_sample_key_limit(
            category=category.value, window_size='1 minute', max_value=value
        )
        key_record = SimpleNamespace(
            uuid=self.api_key.uuid,
            name=self.api_key.name,
            group=self.api_key.group,
            limits=[CredentialLimitOut.from_key_limit(limit)],
        )
        key_service.get_key_by_hashed_key = MagicMock(return_value=key_record)

    def test_credential_rate_limit_applies(self):
        self._limit_credential(CredentialLimitCategory.RATE, 1)
        self._mock_typesafe()

        first = self._post()
        second = self._post()

        assert first.status_code == 200
        assert second.status_code == 429

    def _assert_second_request_blocked_before_typesafe(self):
        # The first call passes though its 312 input tokens (or their cost)
        # exceed the limit: nothing is estimated. Its usage fills the counter,
        # so the second call is rejected without reaching Typesafe.
        self._mock_typesafe()

        first = self._post()
        second = self._post()

        assert first.status_code == 200
        assert second.status_code == 429
        assert pook.isdone()

    def test_route_input_token_limit_counts_usage_and_blocks_when_full(self):
        app.state.routes = _build_routes(
            JEV, token_limiting={'input': {'max_tokens': 100}}
        )

        self._assert_second_request_blocked_before_typesafe()

    def test_credential_input_token_limit_counts_usage_and_blocks_when_full(self):
        self._limit_credential(CredentialLimitCategory.TOKEN_INPUT, 100)

        self._assert_second_request_blocked_before_typesafe()

    # 312 tokens at 1000 per million cost 0.312, over a 0.1 budget.
    PRICEY_JEV = {**JEV, 'input_cost_per_million_tokens': 1000}

    def test_route_budget_counts_input_cost_and_blocks_when_spent(self):
        app.state.routes = _build_routes(
            self.PRICEY_JEV, budget_limiting={'max_budget': 0.1}
        )

        self._assert_second_request_blocked_before_typesafe()

    def test_credential_budget_counts_input_cost_and_blocks_when_spent(self):
        app.state.routes = _build_routes(self.PRICEY_JEV)
        self._limit_credential(CredentialLimitCategory.BUDGET, 0.1)

        self._assert_second_request_blocked_before_typesafe()

    def test_project_budget_counts_input_cost_and_blocks_when_spent(self):
        app.state.routes = _build_routes(self.PRICEY_JEV)
        route = app.state.routes[ROUTE_KEY]
        route.project_uuid = str(db_mock.RANDOM_UUID)
        dao = MagicMock(
            return_value=[
                db_mock.get_sample_project_budget_limit(
                    window_size='1 minute', max_value=0.1
                )
            ]
        )
        with patch.object(project_budget_limit_dao, 'get_by_project_uuid', dao):
            self._assert_second_request_blocked_before_typesafe()

    def test_output_token_limits_get_nothing(self):
        # Typesafe's usage reports 20 output tokens. Counting them would fill
        # these limits of 10 and block the second call.
        config = GatewayConfig.model_validate(
            {
                'chat_models': [{'model_id': 'gpt', 'model': 'openai/gpt-4o-mini'}],
                'decision_models': [JEV],
                'routes': {
                    'agent': {
                        'chat_models': ['gpt'],
                        'decision_models': ['jev'],
                        'token_limiting': {'output': {'max_tokens': 10}},
                    }
                },
            }
        )
        route = app.state.routes[ROUTE_KEY]
        route.token_limiter = config.routes['agent'].get_token_limiter('')
        self._limit_credential(CredentialLimitCategory.TOKEN_OUTPUT, 10)
        self._mock_typesafe().times(2)

        first = self._post()
        second = self._post()

        assert (first.status_code, second.status_code) == (200, 200)

    def test_span_names_the_model_whose_response_is_returned(self):
        self._route_with_fallback()
        self._mock_typesafe(status=503, body={'detail': 'busy'})
        self._mock_typesafe(status=503, body={'detail': 'busy'})
        pook.post(TYPESAFE_EU_URL).times(1).error(httpx.ConnectError('refused'))

        response = self._post()

        assert response.status_code == 503
        attributes = self._span_attributes()
        assert attributes['decision.response.fallback_triggered'] is True
        assert attributes['decision.response.model_id'] == 'jev'

    def _post_state(self, state, questions=QUESTIONS):
        return self.client.post(
            '/v1/systemone',
            json={'state': state, 'model': ROUTE_KEY, 'questions': questions},
            headers=self.headers,
        )

    def _expect_typesafe_body(self, state, questions=QUESTIONS):
        mock = (
            pook.post(TYPESAFE_URL)
            .json({'state': state, 'model': 'jev-latest', 'questions': questions})
            .times(1)
        )
        mock.reply(200).json(TYPESAFE_BODY)
        return mock

    def _spy_on_typesafe(self):
        typesafe = pook.post(TYPESAFE_URL).times(1)
        typesafe.reply(200).json(TYPESAFE_BODY)
        return typesafe

    def test_redact_rewrites_string_leaves_and_keeps_the_structure(self):
        app.state.routes = _build_routes(JEV, guardrails=[REDACT_EMAIL])
        state = {
            'ticket': 'Write to ada@example.com please',
            'ada@example.com': 'key stays',
            'amount': 42.5,
            'refunded': False,
            'customer': {'contacts': ['bob@example.com', 3, None]},
        }
        questions = {
            'mail': {
                'type': 'choice',
                'instructions': 'Is ada@example.com the sender?',
                'criteria': {'yes': 'Yes', 'no': 'No'},
            }
        }
        self._expect_typesafe_body(
            {
                'ticket': 'Write to <EMAIL_ADDRESS> please',
                'ada@example.com': 'key stays',
                'amount': 42.5,
                'refunded': False,
                'customer': {'contacts': ['<EMAIL_ADDRESS>', 3, None]},
            },
            questions=questions,
        )

        response = self._post_state(state, questions=questions)

        assert response.status_code == 200
        assert pook.isdone()

    def test_each_string_leaf_is_checked_as_one_text(self):
        guardrail = {**_check_guardrail('block', 'refund'), 'type': 'starts_with'}
        app.state.routes = _build_routes(JEV, guardrails=[guardrail])
        typesafe = self._spy_on_typesafe()

        # 'refund' starts only the second leaf, not the state as a whole.
        response = self._post_state({'ticket': 'Hello', 'notes': ['refund now']})

        assert response.status_code == 400
        assert not typesafe.calls

    def test_block_returns_400_without_calling_typesafe(self):
        app.state.routes = _build_routes(
            JEV, guardrails=[_check_guardrail('block', 'charged twice')]
        )
        typesafe = self._spy_on_typesafe()

        response = self._post()

        assert response.status_code == 400
        assert response.json()['error']['message'] == 'block by policy'
        assert not typesafe.calls

    def test_soft_block_returns_400_and_is_recorded_as_soft_block(self):
        app.state.routes = _build_routes(
            JEV, guardrails=[_check_guardrail('soft_block', 'charged twice')]
        )
        typesafe = self._spy_on_typesafe()

        response = self._post()

        assert response.status_code == 400
        assert response.json()['error']['message'] == 'soft_block by policy'
        assert not typesafe.calls
        assert [e.behavior for e in self.guardrail_events] == ['SOFT_BLOCK']

    def test_questions_are_not_checked(self):
        app.state.routes = _build_routes(
            JEV, guardrails=[_check_guardrail('block', 'customer want')]
        )
        self._mock_typesafe()

        response = self._post()

        assert response.status_code == 200

    # Exact cache (AG-1002)

    def test_identical_request_is_served_from_cache_without_calling_typesafe(self):
        app.state.routes = _build_routes(JEV, **EXACT_CACHE)
        typesafe = self._spy_on_typesafe()

        first = self._post()
        second = self._post()

        assert typesafe.calls == 1
        assert second.status_code == 200
        assert second.content == first.content
        assert second.headers['content-type'] == first.headers['content-type']

    def test_key_order_does_not_matter(self):
        app.state.routes = _build_routes(JEV, **EXACT_CACHE)
        typesafe = self._spy_on_typesafe()
        reordered_state = dict(reversed(list(STATE.items())))
        reordered_questions = {
            'intent': dict(reversed(list(QUESTIONS['intent'].items())))
        }

        self._post_state(STATE)
        response = self._post_state(reordered_state, questions=reordered_questions)

        assert response.status_code == 200
        assert typesafe.calls == 1

    def _changed_question(self, field: str, value) -> dict:
        return {'intent': {**QUESTIONS['intent'], field: value}}

    def test_changed_instruction_misses(self):
        app.state.routes = _build_routes(JEV, **EXACT_CACHE)
        typesafe = self._spy_on_typesafe().times(2)

        self._post_state(STATE)
        self._post_state(
            STATE, questions=self._changed_question('instructions', 'Why?')
        )

        assert typesafe.calls == 2

    def test_changed_criterion_misses(self):
        app.state.routes = _build_routes(JEV, **EXACT_CACHE)
        typesafe = self._spy_on_typesafe().times(2)
        criteria = {**QUESTIONS['intent']['criteria'], 'refund': 'Wants a refund'}

        self._post_state(STATE)
        self._post_state(STATE, questions=self._changed_question('criteria', criteria))

        assert typesafe.calls == 2

    def test_changed_state_misses(self):
        app.state.routes = _build_routes(JEV, **EXACT_CACHE)
        typesafe = self._spy_on_typesafe().times(2)

        self._post_state(STATE)
        self._post_state({**STATE, 'ticket': 'Where is my parcel?'})

        assert typesafe.calls == 2

    def test_key_uses_the_outbound_state_after_redaction(self):
        app.state.routes = _build_routes(JEV, guardrails=[REDACT_EMAIL], **EXACT_CACHE)
        typesafe = self._spy_on_typesafe()

        # Both redact to the same outbound state.
        self._post_state({'ticket': 'Write to ada@example.com'})
        response = self._post_state({'ticket': 'Write to bob@example.com'})

        assert response.status_code == 200
        assert typesafe.calls == 1

    def test_upstream_error_is_not_cached(self):
        app.state.routes = _build_routes(JEV, **EXACT_CACHE)
        self._mock_typesafe(status=400, body={'detail': 'bad question'})
        self._mock_typesafe()

        first = self._post()
        second = self._post()

        assert (first.status_code, second.status_code) == (400, 200)
        assert pook.isdone()

    def test_hit_is_recorded_as_cache_hit_with_cached_tokens_at_zero_cost(self):
        app.state.routes = _build_routes(self.PRICEY_JEV, **EXACT_CACHE)
        self._spy_on_typesafe()

        self._post()
        assert self.cache_events == []
        self._post()

        assert all(isinstance(e, CacheEventPayload) for e in self.cache_events)
        by_type = {e.event_type: e for e in self.cache_events}
        hit = by_type[EventType.CACHE_HIT]
        cached_input = by_type[EventType.CACHE_INPUT_TOKENS]
        assert (hit.model_id, hit.cost) == ('jev', 0)
        assert (cached_input.model_id, cached_input.value) == ('jev', 312)
        assert cached_input.cost == 0
        assert EventType.CACHE_OUTPUT_TOKENS not in by_type

    def test_hit_touches_no_token_or_budget_counter(self):
        # One call uses 312 tokens costing 0.312. A counted hit would push
        # both counters over their limit and block the next miss.
        app.state.routes = _build_routes(
            self.PRICEY_JEV,
            token_limiting={'input': {'max_tokens': 400}},
            budget_limiting={'max_budget': 0.5},
            **EXACT_CACHE,
        )
        self._spy_on_typesafe().times(2)

        first = self._post()
        hit = self._post()
        miss = self._post_state({**STATE, 'ticket': 'Where is my parcel?'})

        assert (first.status_code, hit.status_code, miss.status_code) == (200,) * 3

    def test_hit_is_served_even_when_limits_are_full(self):
        app.state.routes = _build_routes(
            JEV, token_limiting={'input': {'max_tokens': 100}}, **EXACT_CACHE
        )
        self._spy_on_typesafe()

        first = self._post()
        hit = self._post()

        assert (first.status_code, hit.status_code) == (200, 200)

    def test_semantic_cache_route_leaves_decision_requests_uncached(self):
        app.state.routes = _build_routes(
            JEV,
            embedding_models=['emb'],
            caching={'type': 'semantic', 'embedding_model_id': 'emb'},
            top_level={
                'embedding_models': [
                    {
                        'model_id': 'emb',
                        'model': 'openai/text-embedding-3-small',
                        'credentials': {'api_key': 'sk-test'},
                    }
                ],
                'cache': {'redis_host': 'localhost', 'redis_port': 6379},
            },
        )
        semantic_cache = MagicMock(spec=SemanticCache)
        app.state.routes[ROUTE_KEY].gateway_cache = GatewayCache(semantic_cache)
        typesafe = self._spy_on_typesafe().times(2)

        self._post()
        self._post()

        assert typesafe.calls == 2
        semantic_cache.get.assert_not_called()
        semantic_cache.set.assert_not_called()
