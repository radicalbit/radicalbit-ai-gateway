"""POST /v1/systemone: Jev proxied through the gateway, Typesafe mocked with pook."""

from contextlib import nullcontext
from dataclasses import replace
import json
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import httpx
import pook
import pytest

from tests.common import db_mock
from tests.common.gateway_harness import build_routes, open_gateway

from radicalbit_ai_gateway.caching.gateway_cache import GatewayCache
from radicalbit_ai_gateway.caching.semantic_caching import SemanticCache
from radicalbit_ai_gateway.limiting.limits import RouteLimits
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
from radicalbit_ai_gateway.server import (
    app,
    group_service,
    key_service,
    project_budget_limit_dao,
)
from radicalbit_ai_gateway.utils.exceptions import KeyNotFoundError

ROUTE_KEY = 'proj/agent'
TYPESAFE_KEY = 'ts-upstream-secret'
TYPESAFE_URL = 'https://api.typesafe.ai/v1/systemone'

MODEL_INVOKER_EMIT = 'radicalbit_ai_gateway.invocation.recorder.emit_event'
SPAN = 'radicalbit_ai_gateway.invocation.decision_model_invoker.trace.get_current_span'

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
            'choice': 'refund',
            'confidence': 0.87,
            'probabilities': {'refund': 0.91, 'information': 0.04, 'complaint': 0.05},
        }
    },
    'usage': {'input_tokens': 312, 'output_tokens': 20},
}
# What the client gets: the gateway model-id replaces Typesafe's version.
CLIENT_BODY = {**TYPESAFE_BODY, 'model': 'jev'}


def _build_routes(
    *decision_models: dict,
    guardrails: list[dict] | None = None,
    top_level: dict | None = None,
    **route_config,
) -> dict:
    return build_routes(
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


CACHE_EMIT = 'radicalbit_ai_gateway.caching.route_cache.emit_event'
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
    def setUp(self):
        self.emitted = []
        self.guardrail_events = []
        self.cache_events = []
        self.span = MagicMock()
        self.span.is_recording.return_value = True
        gateway = self.enterContext(
            open_gateway(
                _build_routes(JEV),
                use_pook=True,
                patches=[
                    patch(MODEL_INVOKER_EMIT, side_effect=self.emitted.append),
                    patch(SPAN, return_value=self.span),
                    patch(GUARDRAIL_EMIT, side_effect=self.guardrail_events.append),
                    patch(REDACT_EMIT, side_effect=self.guardrail_events.append),
                    patch(CACHE_EMIT, side_effect=self.cache_events.append),
                ],
            )
        )
        self.client = gateway.client
        self.headers = gateway.headers
        self.api_key = gateway.api_key
        self.request_events = gateway.request_events

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

    def test_success_reaches_the_client_and_is_recorded_billed_and_traced(self):
        self._mock_typesafe()

        response = self._post()

        assert response.status_code == 200
        assert response.json() == CLIENT_BODY
        assert pook.isdone()
        assert [e.request_type for e in self.request_events] == [
            RequestType.DECISION_MODEL
        ]
        # Cost: input tokens times the input price; output adds zero.
        [invocation] = [
            e for e in self.emitted if isinstance(e, ModelInvocationPayload)
        ]
        [input_tokens] = [
            e for e in self.emitted if isinstance(e, InputTokenProcessedPayload)
        ]
        [output_tokens] = [
            e for e in self.emitted if isinstance(e, OutputTokenProcessedPayload)
        ]
        assert (invocation.model_id, invocation.model_type) == ('jev', 'decision_model')
        assert input_tokens.value == 312
        assert input_tokens.cost == pytest.approx(312 * 0.042 / 1_000_000)
        assert (output_tokens.value, output_tokens.cost) == (0, 0)
        attributes = self._span_attributes()
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
        # The trace shows all usage, though only input is billed.
        assert attributes['gen_ai.usage.input_tokens'] == 312
        assert attributes['gen_ai.usage.output_tokens'] == 20
        assert attributes['gen_ai.usage.total_tokens'] == 332

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

    def test_client_error_is_not_retried(self):
        error = {'detail': 'bad question'}
        self._mock_typesafe(status=400, body=error)
        retry = self._mock_typesafe()

        response = self._post()

        assert response.status_code == 400
        assert response.json() == error
        assert not retry.isdone()

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
        # The model that answered, not the target.
        assert response.json() == {**TYPESAFE_BODY, 'model': 'jev-eu'}
        assert pook.isdone()
        attributes = self._span_attributes()
        assert attributes['decision.response.fallback_triggered'] is True
        assert attributes['decision.response.model_id'] == 'jev-eu'
        [fallback] = [e for e in self.emitted if isinstance(e, FallbackEventPayload)]
        assert (fallback.target, fallback.fallback) == ('jev', 'jev-eu')

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
        attributes = self._span_attributes()
        assert attributes['decision.response.fallback_triggered'] is True
        assert attributes['decision.response.model_id'] == 'jev-eu'

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

    def test_span_records_no_fallback_when_the_target_answers(self):
        self._route_with_fallback()
        self._mock_typesafe()

        self._post()

        assert self._span_attributes()['decision.response.fallback_triggered'] is False

    # Limits

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

    # 312 tokens at 1000 per million cost 0.312, over a 0.1 budget.
    PRICEY_JEV = {**JEV, 'input_cost_per_million_tokens': 1000}

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
        route.route_limits = RouteLimits.from_config(config.routes['agent'], '')
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
            questions={
                'mail': {
                    'type': 'choice',
                    'instructions': 'Is <EMAIL_ADDRESS> the sender?',
                    'criteria': {'yes': 'Yes', 'no': 'No'},
                }
            },
        )

        response = self._post_state(state, questions=questions)

        assert response.status_code == 200
        assert pook.isdone()

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

    def test_body_with_no_string_leaves_is_forwarded_unchanged(self):
        app.state.routes = _build_routes(
            JEV, guardrails=[_check_guardrail('block', 'refund')]
        )
        state = {'amount': 42.5, 'refunded': False, 'note': None}
        typesafe = (
            pook.post(TYPESAFE_URL)
            .json({'state': state, 'model': 'jev-latest'})
            .times(1)
        )
        typesafe.reply(200).json(TYPESAFE_BODY)

        response = self.client.post(
            '/v1/systemone',
            json={'state': state, 'model': ROUTE_KEY},
            headers=self.headers,
        )

        assert response.status_code == 200
        assert pook.isdone()

    # Exact cache

    def test_same_request_in_any_key_order_is_served_from_cache(self):
        app.state.routes = _build_routes(JEV, **EXACT_CACHE)
        typesafe = self._spy_on_typesafe()
        reordered_state = dict(reversed(list(STATE.items())))
        reordered_questions = {
            'intent': dict(reversed(list(QUESTIONS['intent'].items())))
        }

        first = self._post_state(STATE)
        second = self._post_state(reordered_state, questions=reordered_questions)

        assert typesafe.calls == 1
        assert second.status_code == 200
        assert second.content == first.content
        assert second.headers['content-type'] == first.headers['content-type']

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

    def test_hit_is_rejected_when_limits_are_full(self):
        # Limits are checked before the cache: over a limit means a 429,
        # even when the answer is cached.
        app.state.routes = _build_routes(
            JEV, token_limiting={'input': {'max_tokens': 100}}, **EXACT_CACHE
        )
        self._spy_on_typesafe()

        first = self._post()
        hit = self._post()

        assert (first.status_code, hit.status_code) == (200, 429)

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
        route = app.state.routes[ROUTE_KEY]
        route.gateway_cache = GatewayCache(semantic_cache)
        route.cache = replace(route.cache, backend=route.gateway_cache)
        typesafe = self._spy_on_typesafe().times(2)

        self._post()
        self._post()

        assert typesafe.calls == 2
        semantic_cache.get.assert_not_called()
        semantic_cache.set.assert_not_called()


@pytest.fixture
def decision_case():
    """Set up a TestDecisionModelEndpoint as for its own tests, for parametrized functions."""
    case = TestDecisionModelEndpoint()
    case.setUp()
    yield case
    case.doCleanups()


LIMITS = {
    'route-rate': {
        'route': {'rate_limiting': {'max_requests': 1, 'window_size': '1 minute'}}
    },
    'credential-rate': {'credential': (CredentialLimitCategory.RATE, 1)},
    'route-input-tokens': {'route': {'token_limiting': {'input': {'max_tokens': 100}}}},
    'route-budget': {'pricey': True, 'route': {'budget_limiting': {'max_budget': 0.1}}},
    'credential-input-tokens': {
        'credential': (CredentialLimitCategory.TOKEN_INPUT, 100)
    },
    'credential-budget': {
        'pricey': True,
        'credential': (CredentialLimitCategory.BUDGET, 0.1),
    },
    'project-budget': {'pricey': True, 'project_budget': True},
}


@pytest.mark.parametrize('limit', LIMITS.values(), ids=LIMITS.keys())
def test_usage_counts_against_the_limits_and_blocks_when_full(decision_case, limit):
    pricey = decision_case.PRICEY_JEV if limit.get('pricey') else JEV
    app.state.routes = _build_routes(pricey, **limit.get('route', {}))
    if limit.get('credential'):
        decision_case._limit_credential(*limit['credential'])
    budgets = nullcontext()
    if limit.get('project_budget'):
        app.state.routes[ROUTE_KEY].project_uuid = str(db_mock.RANDOM_UUID)
        budget = db_mock.get_sample_project_budget_limit(
            window_size='1 minute', max_value=0.1
        )
        budgets = patch.object(
            project_budget_limit_dao,
            'get_by_project_uuid',
            MagicMock(return_value=[budget]),
        )

    with budgets:
        decision_case._assert_second_request_blocked_before_typesafe()


def _reject_unknown_route():
    return {'model': 'proj/missing'}


def _reject_missing_credential():
    return {'headers': {}}


def _reject_wrong_credential():
    key_service.get_key_by_hashed_key = MagicMock(
        side_effect=KeyNotFoundError('no such key')
    )
    return {}


def _reject_foreign_credential():
    group_service.check_key_uuid_for_route = MagicMock(return_value=False)
    return {}


@pytest.mark.parametrize(
    ('arrange', 'status'),
    [
        pytest.param(_reject_unknown_route, 400, id='unknown-route'),
        pytest.param(_reject_missing_credential, 401, id='missing-credential'),
        pytest.param(_reject_wrong_credential, 401, id='wrong-credential'),
        pytest.param(_reject_foreign_credential, 401, id='credential-not-on-route'),
    ],
)
def test_request_is_rejected(decision_case, arrange, status):
    typesafe = decision_case._spy_on_typesafe()

    response = decision_case._post(**arrange())

    assert response.status_code == status
    assert not typesafe.calls


def _fail_with_status(status: int, detail: str):
    return lambda case: case._mock_typesafe(status=status, body={'detail': detail})


def _fail_with_error(error: Exception):
    return lambda case: pook.post(TYPESAFE_URL).times(1).error(error)


@pytest.mark.parametrize(
    'fail_once',
    [
        pytest.param(_fail_with_status(503, 'busy'), id='server-error'),
        pytest.param(_fail_with_status(429, 'slow down'), id='rate-limited'),
        pytest.param(_fail_with_error(httpx.ConnectError('refused')), id='network'),
        pytest.param(_fail_with_error(httpx.ReadTimeout('too slow')), id='timeout'),
    ],
)
def test_transient_failure_is_retried_and_the_later_success_returned(
    decision_case, fail_once
):
    fail_once(decision_case)
    decision_case._mock_typesafe()

    response = decision_case._post()

    assert response.status_code == 200
    assert response.json() == CLIENT_BODY
    assert pook.isdone()


@pytest.mark.parametrize(
    ('guardrail', 'state', 'status'),
    [
        # 'charged twice' is in the state's ticket.
        pytest.param(
            _check_guardrail('block', 'charged twice'), STATE, 400, id='state-checked'
        ),
        # 'customer want' is only in the question's instructions.
        pytest.param(
            _check_guardrail('block', 'customer want'),
            STATE,
            400,
            id='questions-checked',
        ),
        # 'refund' starts only the second leaf, not the state as a whole.
        pytest.param(
            {**_check_guardrail('block', 'refund'), 'type': 'starts_with'},
            {'ticket': 'Hello', 'notes': ['refund now']},
            400,
            id='each-string-leaf-is-one-text',
        ),
        pytest.param(
            _check_guardrail('block', 'refund'),
            {'ticket': 'Hello'},
            200,
            id='criterion-names-are-keys-never-checked',
        ),
    ],
)
def test_block_guardrail_reads_state_and_questions(
    decision_case, guardrail, state, status
):
    app.state.routes = _build_routes(JEV, guardrails=[guardrail])
    typesafe = decision_case._spy_on_typesafe()

    response = decision_case._post_state(state)

    assert response.status_code == status
    if status == 400:
        assert response.json()['error']['message'] == 'block by policy'
    assert typesafe.calls == (0 if status == 400 else 1)


_CHANGED_CRITERIA = {**QUESTIONS['intent']['criteria'], 'refund': 'Wants a refund'}


@pytest.mark.parametrize(
    ('state', 'questions'),
    [
        pytest.param(
            STATE,
            {'intent': {**QUESTIONS['intent'], 'instructions': 'Why?'}},
            id='instruction',
        ),
        pytest.param(
            STATE,
            {'intent': {**QUESTIONS['intent'], 'criteria': _CHANGED_CRITERIA}},
            id='criterion',
        ),
        pytest.param({**STATE, 'ticket': 'Where is my parcel?'}, QUESTIONS, id='state'),
    ],
)
def test_a_changed_request_misses_the_cache(decision_case, state, questions):
    app.state.routes = _build_routes(JEV, **EXACT_CACHE)
    typesafe = decision_case._spy_on_typesafe().times(2)

    decision_case._post_state(STATE)
    decision_case._post_state(state, questions=questions)

    assert typesafe.calls == 2
