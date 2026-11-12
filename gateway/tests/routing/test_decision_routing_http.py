"""Decision routing through /v1/chat/completions.

Typesafe and OpenAI are mocked with pook.
"""

from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import httpx
import pook
import pytest

from tests.common import db_mock
from tests.common.decision_routing import (
    CHINESE,
    EMAILS,
    INSTRUCTIONS,
    JEV,
    JEV_BACKUP,
    QUESTION_ID,
    ROUTER_SPAN,
    TYPESAFE_KEY,
    TYPESAFE_URL,
    USER_TEXT,
)
from tests.common.gateway_harness import build_routes, open_gateway
from tests.common.mocked_build_openai_chat_completion import (
    to_mock_openai_chat_completion,
)

from radicalbit_ai_gateway.models.credential_limiting import (
    CredentialLimitCategory,
    CredentialLimitOut,
)
from radicalbit_ai_gateway.models.event_payload import (
    FallbackEventPayload,
    InputTokenProcessedPayload,
    ModelInvocationPayload,
    RoutingEventPayload,
)
from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.routing import DecisionRouter
from radicalbit_ai_gateway.server import app, key_service, project_budget_limit_dao

CHAT_ROUTE_KEY = 'proj/chat'
OPENAI_URL = 'https://api.openai.com/v1/chat/completions'

MODEL_INVOKER_EMIT = 'radicalbit_ai_gateway.invocation.recorder.emit_event'
GATEWAY_EMIT = 'radicalbit_ai_gateway.endpoints.chat_like.model_selection.emit_event'

SYSTEM_PROMPT = 'You are the configured system prompt.'
GPT_4O = {
    'model_id': 'gpt-4o',
    'model': 'openai/gpt-4o',
    'credentials': {'api_key': 'sk-123'},
    'prompt': SYSTEM_PROMPT,
}
GPT_5 = {
    'model_id': 'gpt-5',
    'model': 'openai/gpt-5',
    'credentials': {'api_key': 'sk-123'},
    'prompt': SYSTEM_PROMPT,
}


def _build_routes(
    *,
    decision_models: tuple[dict, ...] = (JEV, JEV_BACKUP),
    route: dict | None = None,
    top_level: dict | None = None,
    **routing,
) -> dict:
    """One chat route with decision routing between gpt-4o and gpt-5.

    `route` adds to the chat route's config, `top_level` to the gateway's.
    """
    return build_routes(
        {
            'chat_models': [GPT_4O, GPT_5],
            'decision_models': list(decision_models),
            'routing': [
                {
                    'name': 'by-task',
                    'type': 'decision',
                    'decision_model_id': 'jev',
                    'instructions': INSTRUCTIONS,
                    'default_model_id': 'gpt-4o',
                    'output_mapping': [
                        {'model_id': 'gpt-4o', 'description': EMAILS},
                        {'model_id': 'gpt-5', 'description': CHINESE},
                    ],
                    **routing,
                }
            ],
            'routes': {
                'chat': {
                    'chat_models': ['gpt-4o', 'gpt-5'],
                    'routing': 'by-task',
                    **(route or {}),
                }
            },
            **(top_level or {}),
        },
    )


def _choice_answer(probabilities: dict, input_tokens: int = 280) -> dict:
    """Jev's answer for these probabilities: the top option, its confidence."""
    top = max(probabilities, key=probabilities.get)
    return {
        'model': 'jev-1.13.0',
        'answers': {
            QUESTION_ID: {
                'type': 'choice',
                'choice': top,
                'confidence': probabilities[top],
                'probabilities': probabilities,
            }
        },
        'usage': {'input_tokens': input_tokens, 'output_tokens': 0},
    }


class TestDecisionRoutingEndpoint(unittest.TestCase):
    def setUp(self):
        self.span = MagicMock()
        self.span.is_recording.return_value = True
        self.emitted = []
        self.gateway_events = []
        gateway = self.enterContext(
            open_gateway(
                use_pook=True,
                patches=[
                    patch(MODEL_INVOKER_EMIT, side_effect=self.emitted.append),
                    patch(GATEWAY_EMIT, side_effect=self.gateway_events.append),
                    patch(ROUTER_SPAN, return_value=self.span),
                ],
            )
        )
        self.client = gateway.client
        self.headers = gateway.headers
        self.api_key = gateway.api_key

    def _chat(self, messages: list[dict] | None = None):
        return self.client.post(
            '/v1/chat/completions',
            json={
                'model': CHAT_ROUTE_KEY,
                'messages': messages or [{'role': 'user', 'content': USER_TEXT}],
            },
            headers=self.headers,
        )

    def _mock_typesafe(
        self,
        choice=None,
        *,
        body=None,
        state: str = USER_TEXT,
        status: int = 200,
        times: int = 1,
        model: str = 'jev-latest',
    ):
        mock = (
            pook.post(TYPESAFE_URL)
            .header('Authorization', f'Bearer {TYPESAFE_KEY}')
            .json(
                {
                    'model': model,
                    'state': state,
                    'questions': {
                        QUESTION_ID: {
                            'type': 'choice',
                            'instructions': INSTRUCTIONS,
                            'criteria': {'option_1': EMAILS, 'option_2': CHINESE},
                        }
                    },
                }
            )
            .times(times)
        )
        mock.reply(status).json(body if body is not None else _choice_answer(choice))
        return mock

    def _mock_openai(self, model_name: str):
        # Matches only a call for `model_name`: done means that model served.
        mock = (
            pook.post(OPENAI_URL)
            .jsonschema(
                {
                    'type': 'object',
                    'properties': {'model': {'const': model_name}},
                    'required': ['model'],
                }
            )
            .times(1)
        )
        mock.reply(200).json(
            to_mock_openai_chat_completion(content='Ohayou').model_dump()
        )
        return mock

    def _routing_event(self) -> RoutingEventPayload:
        [event] = [e for e in self.gateway_events if isinstance(e, RoutingEventPayload)]
        return event

    def _attributes(self) -> dict:
        return {c.args[0]: c.args[1] for c in self.span.set_attribute.call_args_list}

    def _assert_served(self, response, model_id: str, openai):
        assert response.status_code == 200
        assert openai.isdone()
        event = self._routing_event()
        assert event.routing_name == 'by-task'
        assert event.selected_model_id == model_id

    def test_the_route_is_built_with_a_decision_router(self):
        routes = _build_routes()

        assert isinstance(routes[CHAT_ROUTE_KEY].router, DecisionRouter)

    def test_the_request_is_served_by_the_model_jev_chose(self):
        app.state.routes = _build_routes()
        typesafe = self._mock_typesafe({'option_1': 0.1, 'option_2': 0.9})
        openai = self._mock_openai('gpt-5')

        response = self._chat()

        assert typesafe.isdone()
        self._assert_served(response, 'gpt-5', openai)
        attributes = self._attributes()
        assert attributes['routing.decision.chosen_model_id'] == 'gpt-5'
        assert attributes['routing.decision.default_used'] is False
        assert attributes['routing.decision.state'] == USER_TEXT

    def test_the_routing_event_has_the_same_shape_as_for_other_routers(self):
        app.state.routes = _build_routes()
        self._mock_typesafe({'option_1': 0.1, 'option_2': 0.9})
        self._mock_openai('gpt-5')

        self._chat()

        assert self._routing_event() == RoutingEventPayload(
            value=1.0,
            request_uuid=str(db_mock.REQUEST_UUID),
            event_type=EventType.ROUTING,
            route_name='chat',
            api_key_uuid=str(self.api_key.uuid),
            api_key_name=self.api_key.name,
            group_uuid=str(self.api_key.group.uuid),
            group_name=self.api_key.group.name,
            project_uuid='',
            project_name='proj',
            routing_name='by-task',
            selected_model_id='gpt-5',
        )

    def test_history_all_sends_the_conversation_without_system_messages(self):
        app.state.routes = _build_routes(history='all')
        # The body match proves no system prompt and no client system message.
        typesafe = self._mock_typesafe(
            {'option_1': 0.1, 'option_2': 0.9},
            state='Hello\nHi, how can I help?\n' + USER_TEXT,
        )
        openai = self._mock_openai('gpt-5')

        response = self._chat(
            [
                {'role': 'system', 'content': 'client system message'},
                {'role': 'user', 'content': 'Hello'},
                {'role': 'assistant', 'content': 'Hi, how can I help?'},
                {'role': 'user', 'content': USER_TEXT},
            ]
        )

        assert typesafe.isdone()
        self._assert_served(response, 'gpt-5', openai)

    def test_history_all_with_message_roles_sends_only_those_roles(self):
        app.state.routes = _build_routes(
            history='all', message_roles=['system', 'user']
        )
        typesafe = self._mock_typesafe(
            {'option_1': 0.9, 'option_2': 0.1},
            state='client system message\nHello\n' + USER_TEXT,
        )
        openai = self._mock_openai('gpt-4o')

        response = self._chat(
            [
                {'role': 'system', 'content': 'client system message'},
                {'role': 'user', 'content': 'Hello'},
                {'role': 'assistant', 'content': 'Hi, how can I help?'},
                {'role': 'user', 'content': USER_TEXT},
            ]
        )

        assert typesafe.isdone()
        self._assert_served(response, 'gpt-4o', openai)

    def test_an_error_after_retries_serves_the_default(self):
        app.state.routes = _build_routes()
        typesafe = self._mock_typesafe(body={'error': 'busy'}, status=503, times=4)
        openai = self._mock_openai('gpt-4o')

        response = self._chat()

        assert typesafe.isdone()
        self._assert_served(response, 'gpt-4o', openai)
        assert self._attributes()['routing.decision.default_reason'] == 'error'

    def test_the_fallback_choice_serves_the_request(self):
        app.state.routes = _build_routes(fallback_model_id='jev-backup')
        pook.post(TYPESAFE_URL).times(4).error(httpx.ReadTimeout('slow'))
        fallback = self._mock_typesafe(
            {'option_1': 0.2, 'option_2': 0.8}, model='jev-backup'
        )
        openai = self._mock_openai('gpt-5')

        response = self._chat()

        assert fallback.isdone()
        self._assert_served(response, 'gpt-5', openai)
        assert self._attributes()['routing.decision.fallback_used'] is True

    def test_a_failing_fallback_serves_the_default(self):
        app.state.routes = _build_routes(fallback_model_id='jev-backup')
        self._mock_typesafe(body={'error': 'busy'}, status=503, times=4)
        fallback = self._mock_typesafe(
            body={'error': 'busy'}, status=503, times=4, model='jev-backup'
        )
        openai = self._mock_openai('gpt-4o')

        response = self._chat()

        assert fallback.isdone()
        self._assert_served(response, 'gpt-4o', openai)

    def test_a_non_retriable_4xx_goes_to_the_fallback(self):
        app.state.routes = _build_routes(fallback_model_id='jev-backup')
        self._mock_typesafe(body={'error': 'bad'}, status=400)
        fallback = self._mock_typesafe(
            {'option_1': 0.2, 'option_2': 0.8}, model='jev-backup'
        )
        openai = self._mock_openai('gpt-5')

        response = self._chat()

        assert fallback.isdone()
        self._assert_served(response, 'gpt-5', openai)

    def test_an_unknown_option_serves_the_default(self):
        app.state.routes = _build_routes()
        self._mock_typesafe({'gpt-5': 0.9, 'option_2': 0.1})
        openai = self._mock_openai('gpt-4o')

        response = self._chat()

        self._assert_served(response, 'gpt-4o', openai)
        assert self._attributes()['routing.decision.default_reason'] == (
            'unknown_option'
        )

    def test_a_malformed_answer_serves_the_default(self):
        app.state.routes = _build_routes()
        self._mock_typesafe(body={'model': 'jev-1.13.0', 'answers': {}})
        openai = self._mock_openai('gpt-4o')

        response = self._chat()

        self._assert_served(response, 'gpt-4o', openai)

    def test_no_text_serves_the_default_without_calling_typesafe(self):
        app.state.routes = _build_routes()
        typesafe = self._mock_typesafe({'option_1': 0.1, 'option_2': 0.9})
        openai = self._mock_openai('gpt-4o')

        response = self._chat([{'role': 'assistant', 'content': 'Hi there'}])

        assert not typesafe.isdone()
        self._assert_served(response, 'gpt-4o', openai)
        assert self._attributes()['routing.decision.default_reason'] == 'no_text'

    def test_low_confidence_serves_the_default(self):
        app.state.routes = _build_routes(min_confidence=0.7)
        self._mock_typesafe({'option_1': 0.35, 'option_2': 0.65})
        openai = self._mock_openai('gpt-4o')

        response = self._chat()

        self._assert_served(response, 'gpt-4o', openai)
        assert self._attributes()['routing.decision.default_reason'] == (
            'low_confidence'
        )

    # Cost and limits

    # 312 routing tokens fill a 100 token limit on their own.
    ROUTING_TOKENS = 312
    # 312 tokens at 1000 per million cost 0.312, over a 0.1 budget.
    PRICEY_JEV = {**JEV, 'input_cost_per_million_tokens': 1000}
    PRICEY_BACKUP = {**JEV_BACKUP, 'input_cost_per_million_tokens': 2000}
    CHOOSE_GPT_5 = {'option_1': 0.1, 'option_2': 0.9}

    def _routing_events(self, payload_type: type) -> list:
        return [e for e in self.emitted if isinstance(e, payload_type) and e.is_routing]

    def test_the_routing_call_emits_cost_events_flagged_as_routing(self):
        app.state.routes = _build_routes(decision_models=(self.PRICEY_JEV, JEV_BACKUP))
        self._mock_typesafe(
            body=_choice_answer(self.CHOOSE_GPT_5, input_tokens=self.ROUTING_TOKENS)
        )
        self._mock_openai('gpt-5')

        self._chat()

        [invocation] = self._routing_events(ModelInvocationPayload)
        [input_tokens] = self._routing_events(InputTokenProcessedPayload)
        assert (invocation.model_id, invocation.model_type) == ('jev', 'decision_model')
        assert input_tokens.model_type == 'decision_model'
        assert input_tokens.is_judge is False
        assert input_tokens.value == self.ROUTING_TOKENS
        assert input_tokens.cost == pytest.approx(0.312)
        assert self._routing_events(FallbackEventPayload) == []

    def test_a_failing_routing_cost_event_does_not_fail_the_request(self):
        app.state.routes = _build_routes()
        self._mock_typesafe(body=_choice_answer(self.CHOOSE_GPT_5))
        openai = self._mock_openai('gpt-5')

        def emit(event):
            if getattr(event, 'is_routing', False):
                raise RuntimeError('event queue is down')
            self.emitted.append(event)

        with patch(MODEL_INVOKER_EMIT, side_effect=emit):
            response = self._chat()

        # Routing never fails a request: Jev's choice still serves it.
        self._assert_served(response, 'gpt-5', openai)

    def _assert_routing_usage_blocks_the_next_request(self):
        # Only routing is counted: the chat reply carries no usage. Its 312
        # tokens (or their cost) fill the counter, so the second request is
        # rejected before routing.
        typesafe = self._mock_typesafe(
            body=_choice_answer(self.CHOOSE_GPT_5, input_tokens=self.ROUTING_TOKENS)
        )
        self._mock_openai('gpt-5')

        first = self._chat()
        second = self._chat()

        assert (first.status_code, second.status_code) == (200, 429)
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

    def test_fallback_answer_is_costed_at_the_fallback_price(self):
        app.state.routes = _build_routes(
            fallback_model_id='jev-backup',
            decision_models=(self.PRICEY_JEV, self.PRICEY_BACKUP),
        )
        self._mock_typesafe(body={'error': 'busy'}, status=503, times=4)
        self._mock_typesafe(
            body=_choice_answer(self.CHOOSE_GPT_5, input_tokens=self.ROUTING_TOKENS),
            model='jev-backup',
        )
        self._mock_openai('gpt-5')

        self._chat()

        [invocation] = self._routing_events(ModelInvocationPayload)
        [input_tokens] = self._routing_events(InputTokenProcessedPayload)
        [fallback] = self._routing_events(FallbackEventPayload)
        assert invocation.model_id == 'jev-backup'
        assert input_tokens.model_id == 'jev-backup'
        assert input_tokens.cost == pytest.approx(0.624)
        assert (fallback.target, fallback.fallback) == ('jev', 'jev-backup')

    def test_a_routing_call_failed_without_usage_counts_nothing(self):
        app.state.routes = _build_routes(
            route={'token_limiting': {'input': {'max_tokens': 100}}}
        )
        typesafe = self._mock_typesafe(body={'error': 'busy'}, status=503, times=8)
        self._mock_openai('gpt-4o')
        self._mock_openai('gpt-4o')

        first = self._chat()
        second = self._chat()

        # Nothing was counted: the second request is routed again.
        assert (first.status_code, second.status_code) == (200, 200)
        assert typesafe.isdone()
        assert self._routing_events(InputTokenProcessedPayload) == []

    def test_an_answer_without_a_choice_still_counts_its_usage(self):
        # A bad answer still spent tokens.
        app.state.routes = _build_routes(
            route={'token_limiting': {'input': {'max_tokens': 100}}}
        )
        self._mock_typesafe(
            body={'answers': {}, 'usage': {'input_tokens': self.ROUTING_TOKENS}}
        )
        openai = self._mock_openai('gpt-4o')

        first = self._chat()
        second = self._chat()

        assert openai.isdone()
        assert (first.status_code, second.status_code) == (200, 429)

    def test_a_cache_hit_still_pays_for_its_routing_call(self):
        app.state.routes = _build_routes(
            decision_models=(self.PRICEY_JEV, JEV_BACKUP),
            route={'caching': {'type': 'exact'}},
            top_level={'cache': {'redis_host': 'localhost', 'redis_port': 6379}},
        )
        # Routing runs before the cache lookup: both requests ask Jev.
        typesafe = self._mock_typesafe(
            body=_choice_answer(self.CHOOSE_GPT_5, input_tokens=self.ROUTING_TOKENS),
            times=2,
        )
        openai = self._mock_openai('gpt-5')

        first = self._chat()
        second = self._chat()

        assert (first.status_code, second.status_code) == (200, 200)
        # A cache hit is stamped with the time it is served: across a second
        # boundary `created` differs, the rest is the cached answer
        first_body, second_body = first.json(), second.json()
        assert second_body.pop('created') >= first_body.pop('created')
        assert second_body == first_body
        assert typesafe.isdone()
        assert openai.isdone()
        # One routing call per request, never more.
        assert [
            (e.model_id, e.cost)
            for e in self._routing_events(InputTokenProcessedPayload)
        ] == [('jev', pytest.approx(0.312))] * 2


@pytest.fixture
def routing_case():
    """Set up a TestDecisionRoutingEndpoint as for its own tests, for parametrized functions."""
    case = TestDecisionRoutingEndpoint()
    case.setUp()
    yield case
    case.doCleanups()


LIMITS = {
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
def test_routing_usage_counts_against_the_limits(routing_case, limit):
    pricey = routing_case.PRICEY_JEV if limit.get('pricey') else JEV
    app.state.routes = _build_routes(
        decision_models=(pricey, JEV_BACKUP), route=limit.get('route')
    )
    if limit.get('credential'):
        routing_case._limit_credential(*limit['credential'])
    budgets = nullcontext()
    if limit.get('project_budget'):
        app.state.routes[CHAT_ROUTE_KEY].project_uuid = str(db_mock.RANDOM_UUID)
        budget = db_mock.get_sample_project_budget_limit(
            window_size='1 minute', max_value=0.1
        )
        budgets = patch.object(
            project_budget_limit_dao,
            'get_by_project_uuid',
            MagicMock(return_value=[budget]),
        )

    with budgets:
        routing_case._assert_routing_usage_blocks_the_next_request()
