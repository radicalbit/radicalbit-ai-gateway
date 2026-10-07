"""A model with no price entry: the request succeeds and is costed at 0 (AG-998)."""

import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
import pook
from starlette.requests import Request

from tests.common import db_mock

from radicalbit_ai_gateway.guardrails.guardrail_engine import GuardrailEngine
from radicalbit_ai_gateway.guardrails.judges.judge_engine import JudgeEngine
from radicalbit_ai_gateway.guardrails.presidio import PresidioEngine
from radicalbit_ai_gateway.models.event_payload import InputTokenProcessedPayload
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.server import app, group_service, key_service
from radicalbit_ai_gateway.services.cost_service import (
    CostService,
    logger as cost_service_logger,
)
from radicalbit_ai_gateway.utils.dependencies import get_request_uuid
from radicalbit_ai_gateway.utils.gateway_route_factory import (
    build_gateway_routes_from_config,
)

MODEL_INVOKER_EMIT = 'radicalbit_ai_gateway.invocation.model_invoker.emit_event'

CHAT_RESPONSE = {
    'id': 'chatcmpl-mock',
    'object': 'chat.completion',
    'created': 1234567890,
    'model': 'gpt-4o-mini',
    'choices': [
        {
            'index': 0,
            'message': {'role': 'assistant', 'content': 'Paris'},
            'finish_reason': 'stop',
        }
    ],
    'usage': {'prompt_tokens': 12, 'completion_tokens': 3, 'total_tokens': 15},
}
EMBEDDING_RESPONSE = {
    'object': 'list',
    'data': [{'object': 'embedding', 'index': 0, 'embedding': [0.1, 0.2, 0.3]}],
    'model': 'text-embedding-3-small',
    'usage': {'prompt_tokens': 4, 'total_tokens': 4},
}


def _mock_request_uuid(request: Request):
    request.state.request_uuid = str(db_mock.REQUEST_UUID)
    return str(db_mock.REQUEST_UUID)


def _build_routes_without_prices() -> dict:
    config = GatewayConfig.model_validate(
        {
            'chat_models': [
                {
                    'model_id': 'gpt',
                    'model': 'openai/gpt-4o-mini',
                    'credentials': {'api_key': 'sk-dummy'},
                }
            ],
            'embedding_models': [
                {
                    'model_id': 'emb',
                    'model': 'openai/text-embedding-3-small',
                    'credentials': {'api_key': 'sk-dummy'},
                }
            ],
            'routes': {'r': {'chat_models': ['gpt'], 'embedding_models': ['emb']}},
        }
    )
    # A cost service that knows no model: every lookup misses its price entry.
    cost_service = CostService()
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
    route = routes['r']
    route.project_name = 'proj'
    return {'proj/r': route}


class TestModelWithoutPrice(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.dependency_overrides[get_request_uuid] = _mock_request_uuid
        cls.client = TestClient(app)
        cls.headers = {'Authorization': f'Bearer {db_mock.PLAIN_KEY}'}

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides = {}

    def setUp(self):
        app.state.routes = _build_routes_without_prices()
        key_service.get_key_by_hashed_key = MagicMock(
            return_value=db_mock.get_sample_key_with_group(
                group_uuid=db_mock.GROUP_UUID
            )
        )
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)

        self.emitted = []
        patcher = patch(MODEL_INVOKER_EMIT, side_effect=self.emitted.append)
        patcher.start()
        self.addCleanup(patcher.stop)
        pook.on()
        # The TestClient talks httpx too: let only its own host through.
        pook.enable_network('testserver')
        self.addCleanup(pook.off)
        self.addCleanup(pook.disable_network)

    def _input_costs(self) -> list:
        return [
            e.cost for e in self.emitted if isinstance(e, InputTokenProcessedPayload)
        ]

    def test_chat_request_succeeds_and_is_costed_at_zero(self):
        pook.post('https://api.openai.com/v1/chat/completions').reply(200).json(
            CHAT_RESPONSE
        )

        with self.assertLogs(cost_service_logger, level='WARNING') as logs:
            response = self.client.post(
                '/v1/chat/completions',
                json={
                    'model': 'proj/r',
                    'messages': [{'role': 'user', 'content': 'Capital of France?'}],
                },
                headers=self.headers,
            )

        assert response.status_code == 200
        assert response.json()['choices'][0]['message']['content'] == 'Paris'
        assert self._input_costs() == [0]
        assert any('gpt' in line for line in logs.output)

    def test_embedding_request_succeeds_and_is_costed_at_zero(self):
        pook.post('https://api.openai.com/v1/embeddings').reply(200).json(
            EMBEDDING_RESPONSE
        )

        with self.assertLogs(cost_service_logger, level='WARNING') as logs:
            response = self.client.post(
                '/v1/embeddings',
                json={'model': 'proj/r', 'input': 'hello'},
                headers=self.headers,
            )

        assert response.status_code == 200
        assert self._input_costs() == [0]
        assert any('emb' in line for line in logs.output)
