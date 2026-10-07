"""POST /v1/systemone: Jev proxied through the gateway, Typesafe mocked with pook."""

import json
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
import pook
import pytest
from starlette.requests import Request

from tests.common import db_mock

from radicalbit_ai_gateway.guardrails.guardrail_engine import GuardrailEngine
from radicalbit_ai_gateway.guardrails.judges.judge_engine import JudgeEngine
from radicalbit_ai_gateway.guardrails.presidio import PresidioEngine
from radicalbit_ai_gateway.models.event_payload import (
    InputTokenProcessedPayload,
    ModelInvocationPayload,
    OutputTokenProcessedPayload,
)
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.request_event_type import RequestType
from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.server import app, group_service, key_service
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


def _build_routes(decision_model: dict) -> dict:
    config = GatewayConfig.model_validate(
        {
            'decision_models': [decision_model],
            'routes': {'agent': {'decision_models': [decision_model['model_id']]}},
        }
    )
    cost_service = CostService(decision_models_by_id=config.decision_models_by_id)
    guardrail_engine = GuardrailEngine(
        presidio_engine=PresidioEngine(),
        judge_engine=JudgeEngine(prompt_manager=MagicMock(spec_set=PromptManager)),
        cost_service=cost_service,
        guardrails=[],
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
        self.api_key = db_mock.get_sample_key_with_group(group_uuid=db_mock.GROUP_UUID)
        key_service.get_key_by_hashed_key = MagicMock(return_value=self.api_key)
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)

        self.emitted = []
        self.request_events = []
        self.span = MagicMock()
        self.span.is_recording.return_value = True
        for patcher in (
            patch(MODEL_INVOKER_EMIT, side_effect=self.emitted.append),
            patch(REQUEST_EVENT_EMIT, side_effect=self.request_events.append),
            patch(SPAN, return_value=self.span),
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
        return (
            pook.post(url)
            .header('Authorization', f'Bearer {TYPESAFE_KEY}')
            .json({'state': STATE, 'model': 'jev-latest', 'questions': QUESTIONS})
            .times(1)
            .reply(status)
            .json(TYPESAFE_BODY if body is None else body)
        )

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
