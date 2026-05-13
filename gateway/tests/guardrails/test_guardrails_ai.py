import copy
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from langchain_core.messages import HumanMessage
import pytest

from tests.common.db_mock import API_KEY_UUID, GROUP_UUID, REQUEST_UUID
from tests.common.mocked_gateway_config_openai import get_default_gateway_openai

from radicalbit_ai_gateway.guardrails.guardrail_engine import GuardrailEngine
from radicalbit_ai_gateway.guardrails.judges.judge_engine import JudgeEngine
from radicalbit_ai_gateway.guardrails.presidio import PresidioEngine
from radicalbit_ai_gateway.models.guardrails import (
    Guardrail,
    GuardrailBehaviorType,
    GuardrailClass,
    GuardrailsAIParameter,
    GuardrailType,
    GuardrailWhereType,
)
from radicalbit_ai_gateway.models.soft_block_info import SoftBlockInfo
from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.exceptions import GuardrailBadRequest

gateway_config = get_default_gateway_openai()

GUARD_ID = 'guard-abc-123'
GUARD_NAME = 'toxic_language'


def _make_guardrail(
    behavior, where=GuardrailWhereType.INPUT, name='guardrails_ai_test'
):
    return Guardrail(
        name=name,
        type=GuardrailType.GUARDRAILS_AI,
        behavior=behavior,
        where=where,
        response_message='Guardrails-AI triggered',
        parameters=GuardrailsAIParameter(
            guard_name=GUARD_NAME,
            base_url='http://guardrails-api:8000',
        ),
    )


def _build_engine(guardrails):
    cost_service = MagicMock(spec_set=CostService)
    prompt_manager = MagicMock(spec_set=PromptManager)
    return GuardrailEngine(
        presidio_engine=PresidioEngine(),
        judge_engine=JudgeEngine(prompt_manager=prompt_manager),
        cost_service=cost_service,
        guardrails=guardrails,
    )


def _mock_guards_list_response():
    """Mock response for GET /guards returning a list with our guard."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = [{'name': GUARD_NAME, 'id': GUARD_ID}]
    resp.raise_for_status = MagicMock()
    return resp


def _mock_validate_response(*, validation_passed):
    """Mock response for POST /guards/{id}/validate."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = {'validationPassed': validation_passed}
    resp.raise_for_status = MagicMock()
    return resp


def _mock_client(*, validation_passed):
    """Build an AsyncMock httpx client that handles GET /guards + POST validate."""
    guards_resp = _mock_guards_list_response()
    validate_resp = _mock_validate_response(validation_passed=validation_passed)

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=guards_resp)
    client.post = AsyncMock(return_value=validate_resp)
    return client


class TestGuardrailsAIModel(unittest.TestCase):
    def test_guardrails_ai_parameter_valid(self):
        guardrail = _make_guardrail(GuardrailBehaviorType.BLOCK)
        assert guardrail.type == GuardrailType.GUARDRAILS_AI
        assert guardrail.parameters.guard_name == GUARD_NAME
        assert guardrail.parameters.base_url == 'http://guardrails-api:8000'
        assert guardrail.parameters.timeout == 10.0

    def test_guardrails_ai_guardrail_class_is_check(self):
        guardrail = _make_guardrail(GuardrailBehaviorType.BLOCK)
        assert guardrail.guardrail_class() == GuardrailClass.CHECK

    def test_guardrails_ai_parameter_defaults(self):
        guardrail = Guardrail(
            name='test_defaults',
            type=GuardrailType.GUARDRAILS_AI,
            behavior=GuardrailBehaviorType.BLOCK,
            where=GuardrailWhereType.INPUT,
            parameters=GuardrailsAIParameter(
                guard_name='pii_detection',
            ),
        )
        assert guardrail.parameters.guard_name == 'pii_detection'
        assert guardrail.parameters.base_url == 'http://guardrails-api:8000'
        assert guardrail.parameters.timeout == 10.0


class TestGuardrailsAICheck(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.guardrails_block = [
            _make_guardrail(GuardrailBehaviorType.BLOCK, name='block_guardrails_ai')
        ]
        cls.guardrails_soft_block = [
            _make_guardrail(
                GuardrailBehaviorType.SOFT_BLOCK, name='soft_block_guardrails_ai'
            )
        ]
        cls.guardrails_warn = [
            _make_guardrail(GuardrailBehaviorType.WARN, name='warn_guardrails_ai')
        ]

        cls.engine_block = _build_engine(cls.guardrails_block)
        cls.engine_soft_block = _build_engine(cls.guardrails_soft_block)
        cls.engine_warn = _build_engine(cls.guardrails_warn)

        cls.route_config_block = copy.deepcopy(gateway_config.routes['rb-gateway'])
        cls.route_config_block.guardrails = [g.name for g in cls.guardrails_block]

        cls.route_config_soft_block = copy.deepcopy(gateway_config.routes['rb-gateway'])
        cls.route_config_soft_block.guardrails = [
            g.name for g in cls.guardrails_soft_block
        ]

        cls.route_config_warn = copy.deepcopy(gateway_config.routes['rb-gateway'])
        cls.route_config_warn.guardrails = [g.name for g in cls.guardrails_warn]

        cls.emit_event_patcher = patch(
            'radicalbit_ai_gateway.guardrails.guardrail_check.emit_event',
            autospec=True,
        )
        cls.emit_event_patcher.start()

    @classmethod
    def tearDownClass(cls):
        cls.emit_event_patcher.stop()

    @pytest.mark.asyncio
    async def test_not_triggered_when_validation_passes(self):
        client = _mock_client(validation_passed=True)

        with patch(
            'radicalbit_ai_gateway.guardrails.guardrail_check.httpx.AsyncClient',
            return_value=client,
        ):
            result = await self.engine_block.guardrail_check.apply_guardrails(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                group_name='test-group',
                messages=[HumanMessage(content='A normal message')],
                route_config=self.route_config_block,
                where=GuardrailWhereType.INPUT,
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_block_triggered_when_validation_fails(self):
        client = _mock_client(validation_passed=False)

        with patch(
            'radicalbit_ai_gateway.guardrails.guardrail_check.httpx.AsyncClient',
            return_value=client,
        ):
            with pytest.raises(GuardrailBadRequest) as exc_info:
                await self.engine_block.guardrail_check.apply_guardrails(
                    request_uuid=str(REQUEST_UUID),
                    api_key_uuid=str(API_KEY_UUID),
                    group_uuid=str(GROUP_UUID),
                    api_key_name='fake-name',
                    group_name='test-group',
                    messages=[HumanMessage(content='You are toxic')],
                    route_config=self.route_config_block,
                    where=GuardrailWhereType.INPUT,
                )
            msg = str(exc_info.value)
            assert '[GUARDRAIL TRIGGERED]' in msg
            assert '[type=GUARDRAILS_AI]' in msg
            assert '[behavior=BLOCK]' in msg
            assert exc_info.value.guardrail.name == 'block_guardrails_ai'

    @pytest.mark.asyncio
    async def test_soft_block_triggered_when_validation_fails(self):
        client = _mock_client(validation_passed=False)

        with patch(
            'radicalbit_ai_gateway.guardrails.guardrail_check.httpx.AsyncClient',
            return_value=client,
        ):
            result = await self.engine_soft_block.guardrail_check.apply_guardrails(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                group_name='test-group',
                messages=[HumanMessage(content='You are toxic')],
                route_config=self.route_config_soft_block,
                where=GuardrailWhereType.INPUT,
            )
        assert isinstance(result, SoftBlockInfo)
        assert result.guardrail.name == 'soft_block_guardrails_ai'

    @pytest.mark.asyncio
    async def test_warn_triggered_when_validation_fails(self):
        client = _mock_client(validation_passed=False)

        with patch(
            'radicalbit_ai_gateway.guardrails.guardrail_check.httpx.AsyncClient',
            return_value=client,
        ):
            result = await self.engine_warn.guardrail_check.apply_guardrails(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                group_name='test-group',
                messages=[HumanMessage(content='You are toxic')],
                route_config=self.route_config_warn,
                where=GuardrailWhereType.INPUT,
            )
        assert result is None  # WARN does not return SoftBlockInfo

    @pytest.mark.asyncio
    async def test_empty_messages_not_triggered(self):
        """Empty messages should short-circuit without calling the API."""
        with patch(
            'radicalbit_ai_gateway.guardrails.guardrail_check.httpx.AsyncClient'
        ):
            result = await self.engine_block.guardrail_check.apply_guardrails(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                group_name='test-group',
                messages=[HumanMessage(content='')],
                route_config=self.route_config_block,
                where=GuardrailWhereType.INPUT,
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_timeout_propagates(self):
        client = AsyncMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.get = AsyncMock(side_effect=httpx.ReadTimeout('timeout'))

        with (
            patch(
                'radicalbit_ai_gateway.guardrails.guardrail_check.httpx.AsyncClient',
                return_value=client,
            ),
            pytest.raises(httpx.TimeoutException),
        ):
            await self.engine_block.guardrail_check.apply_guardrails(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                group_name='test-group',
                messages=[HumanMessage(content='test message')],
                route_config=self.route_config_block,
                where=GuardrailWhereType.INPUT,
            )

    @pytest.mark.asyncio
    async def test_http_error_propagates(self):
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            'Server Error', request=MagicMock(), response=mock_response
        )

        client = AsyncMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.get = AsyncMock(return_value=mock_response)

        with (
            patch(
                'radicalbit_ai_gateway.guardrails.guardrail_check.httpx.AsyncClient',
                return_value=client,
            ),
            pytest.raises(httpx.HTTPStatusError),
        ):
            await self.engine_block.guardrail_check.apply_guardrails(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                group_name='test-group',
                messages=[HumanMessage(content='test message')],
                route_config=self.route_config_block,
                where=GuardrailWhereType.INPUT,
            )

    @pytest.mark.asyncio
    async def test_not_triggered_on_output_when_where_is_input(self):
        """A guardrail with where=INPUT should not be evaluated on OUTPUT."""
        with patch(
            'radicalbit_ai_gateway.guardrails.guardrail_check.httpx.AsyncClient'
        ) as mock_cls:
            result = await self.engine_block.guardrail_check.apply_guardrails(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                group_name='test-group',
                messages=[HumanMessage(content='You are toxic')],
                route_config=self.route_config_block,
                where=GuardrailWhereType.OUTPUT,
            )
        assert result is None
        mock_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_api_called_with_correct_url_and_payload(self):
        client = _mock_client(validation_passed=True)

        with patch(
            'radicalbit_ai_gateway.guardrails.guardrail_check.httpx.AsyncClient',
            return_value=client,
        ):
            await self.engine_block.guardrail_check.apply_guardrails(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                group_name='test-group',
                messages=[HumanMessage(content='Hello world')],
                route_config=self.route_config_block,
                where=GuardrailWhereType.INPUT,
            )

        client.get.assert_called_once_with(
            'http://guardrails-api:8000/guards',
        )
        client.post.assert_called_once_with(
            f'http://guardrails-api:8000/guards/{GUARD_ID}/validate',
            json={'llm_output': 'Hello world'},
        )
