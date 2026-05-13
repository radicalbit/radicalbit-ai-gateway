from unittest.mock import MagicMock, patch

from langchain_core.messages import HumanMessage
import pytest

from radicalbit_ai_gateway.guardrails.guardrail_check import GuardrailCheck
from radicalbit_ai_gateway.guardrails.judges.judge_engine import JudgeEngine
from radicalbit_ai_gateway.guardrails.presidio import PresidioEngine
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.models.guardrails import (
    CheckParameter,
    Guardrail,
    GuardrailBehaviorType,
    GuardrailType,
    GuardrailWhereType,
    JudgeParameter,
)
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.exceptions import GuardrailBadRequest


def _route_config_with_guardrails(names: list[str]) -> GatewayRouteConfig:
    return GatewayRouteConfig(
        route_name='test-route',
        chat_models=['m1'],
        embedding_models=None,
        guardrails=names,
    )


@pytest.mark.asyncio
async def test_reason_logged_for_starts_with():
    cost_service: CostService = MagicMock(spec_set=CostService)
    prompt_manager: PromptManager = MagicMock(spec_set=PromptManager)
    gr = Guardrail(
        name='gr_sw',
        type=GuardrailType.STARTS_WITH,
        where=GuardrailWhereType.INPUT,
        behavior=GuardrailBehaviorType.BLOCK,
        parameters=CheckParameter(values=['Hello']),
    )
    chk = GuardrailCheck(
        presidio_engine=PresidioEngine(),
        judge_engine=JudgeEngine(prompt_manager=prompt_manager),
        cost_service=cost_service,
        guardrails_by_name={'gr_sw': gr},
    )
    cfg = _route_config_with_guardrails(['gr_sw'])

    with (
        patch(
            'radicalbit_ai_gateway.guardrails.guardrail_check.emit_event',
            autospec=True,
        ),
        pytest.raises(GuardrailBadRequest) as exc,
    ):
        await chk.apply_guardrails(
            request_uuid='r',
            api_key_uuid='k',
            group_uuid='g',
            api_key_name='kn',
            group_name='gn',
            route_config=cfg,
            messages=[HumanMessage(content='Hello there')],
            where=GuardrailWhereType.INPUT,
        )

    assert '[GUARDRAIL TRIGGERED]' in str(exc.value)
    assert exc.value.reason is not None
    assert exc.value.reason['kind'] == 'starts_with'
    assert exc.value.reason['value'] == 'Hello'
    assert exc.value.reason['message_index'] == 0
    assert isinstance(exc.value.reason.get('context'), str)


@pytest.mark.asyncio
async def test_reason_logged_for_contains_case_insensitive():
    cost_service: CostService = MagicMock(spec_set=CostService)
    prompt_manager: PromptManager = MagicMock(spec_set=PromptManager)
    gr = Guardrail(
        name='gr_contains',
        type=GuardrailType.CONTAINS,
        where=GuardrailWhereType.INPUT,
        behavior=GuardrailBehaviorType.BLOCK,
        parameters=CheckParameter(values=['sensitive']),
    )
    chk = GuardrailCheck(
        presidio_engine=PresidioEngine(),
        judge_engine=JudgeEngine(prompt_manager=prompt_manager),
        cost_service=cost_service,
        guardrails_by_name={'gr_contains': gr},
    )
    cfg = _route_config_with_guardrails(['gr_contains'])

    with (
        patch(
            'radicalbit_ai_gateway.guardrails.guardrail_check.emit_event',
            autospec=True,
        ),
        pytest.raises(GuardrailBadRequest) as exc,
    ):
        await chk.apply_guardrails(
            request_uuid='r',
            api_key_uuid='k',
            group_uuid='g',
            api_key_name='kn',
            group_name='gn',
            route_config=cfg,
            messages=[HumanMessage(content='This has SenSiTive info')],
            where=GuardrailWhereType.INPUT,
        )

    assert '[GUARDRAIL TRIGGERED]' in str(exc.value)
    assert exc.value.reason is not None
    assert exc.value.reason['kind'] == 'contains'
    assert exc.value.reason['value'] == 'sensitive'
    assert exc.value.reason['message_index'] == 0
    assert isinstance(exc.value.reason.get('context'), str)


@pytest.mark.asyncio
async def test_reason_logged_for_regex():
    cost_service: CostService = MagicMock(spec_set=CostService)
    prompt_manager: PromptManager = MagicMock(spec_set=PromptManager)
    gr = Guardrail(
        name='gr_re',
        type=GuardrailType.REGEX,
        where=GuardrailWhereType.INPUT,
        behavior=GuardrailBehaviorType.BLOCK,
        parameters=CheckParameter(values=[r'\d+'], ignore_case=True),
    )
    chk = GuardrailCheck(
        presidio_engine=PresidioEngine(),
        judge_engine=JudgeEngine(prompt_manager=prompt_manager),
        cost_service=cost_service,
        guardrails_by_name={'gr_re': gr},
    )
    cfg = _route_config_with_guardrails(['gr_re'])

    with (
        patch(
            'radicalbit_ai_gateway.guardrails.guardrail_check.emit_event',
            autospec=True,
        ),
        pytest.raises(GuardrailBadRequest) as exc,
    ):
        await chk.apply_guardrails(
            request_uuid='r',
            api_key_uuid='k',
            group_uuid='g',
            api_key_name='kn',
            group_name='gn',
            route_config=cfg,
            messages=[HumanMessage(content='value 123')],
            where=GuardrailWhereType.INPUT,
        )

    assert '[GUARDRAIL TRIGGERED]' in str(exc.value)
    assert exc.value.reason is not None
    assert exc.value.reason['kind'] == 'regex'
    assert exc.value.reason['pattern'] == r'\d+'
    assert exc.value.reason['message_index'] == 0
    assert isinstance(exc.value.reason.get('context'), str)


@pytest.mark.asyncio
async def test_reason_includes_context_when_debug_mode_enabled():
    cost_service: CostService = MagicMock(spec_set=CostService)
    prompt_manager: PromptManager = MagicMock(spec_set=PromptManager)
    gr = Guardrail(
        name='gr_contains_ctx',
        type=GuardrailType.CONTAINS,
        where=GuardrailWhereType.INPUT,
        behavior=GuardrailBehaviorType.BLOCK,
        parameters=CheckParameter(values=['sensitive']),
    )
    chk = GuardrailCheck(
        presidio_engine=PresidioEngine(),
        judge_engine=JudgeEngine(prompt_manager=prompt_manager),
        cost_service=cost_service,
        guardrails_by_name={'gr_contains_ctx': gr},
    )
    cfg = _route_config_with_guardrails(['gr_contains_ctx'])

    with (
        patch(
            'radicalbit_ai_gateway.guardrails.guardrail_check.emit_event',
            autospec=True,
        ),
        pytest.raises(GuardrailBadRequest) as exc,
    ):
        await chk.apply_guardrails(
            request_uuid='r',
            api_key_uuid='k',
            group_uuid='g',
            api_key_name='kn',
            group_name='gn',
            route_config=cfg,
            messages=[HumanMessage(content='this is very sensitive data indeed')],
            where=GuardrailWhereType.INPUT,
        )

    assert exc.value.reason is not None
    assert '<<sensitive>>' in exc.value.reason.get('context', '')


@pytest.mark.asyncio
async def test_reason_is_available_for_judge_guardrail():
    class _DummyJudgeEngine:
        async def execute_judge(self, **kwargs):
            class _R:
                triggered = True
                reasoning = 'The prompt contains disallowed business context.'
                violation_type = 'BUSINESS_CONTEXT'

            return _R()

    gr = Guardrail(
        name='gr_judge',
        type=GuardrailType.JUDGE,
        where=GuardrailWhereType.INPUT,
        behavior=GuardrailBehaviorType.BLOCK,
        parameters=JudgeParameter(
            prompt_ref='business_context_check.md', model_id='m1'
        ),
    )

    cost_service: CostService = MagicMock(spec_set=CostService)
    chk = GuardrailCheck(
        presidio_engine=PresidioEngine(),
        judge_engine=_DummyJudgeEngine(),
        cost_service=cost_service,
        guardrails_by_name={'gr_judge': gr},
    )

    m1 = Model(
        model_id='m1',
        model='mock/gateway',
        credentials=None,
        params={'latency_ms': 0},
    )

    chk._chat_models_by_id = {'m1': m1}

    cfg = _route_config_with_guardrails(['gr_judge'])

    with (
        patch(
            'radicalbit_ai_gateway.guardrails.guardrail_check.emit_event',
            autospec=True,
        ),
        pytest.raises(GuardrailBadRequest) as exc,
    ):
        await chk.apply_guardrails(
            request_uuid='r',
            api_key_uuid='k',
            group_uuid='g',
            api_key_name='kn',
            group_name='gn',
            route_config=cfg,
            messages=[HumanMessage(content='Some business context here')],
            where=GuardrailWhereType.INPUT,
        )

    assert exc.value.reason is not None
    assert exc.value.reason['kind'] == 'judge'
    assert exc.value.reason['value'] == 'BUSINESS_CONTEXT'
    assert 'business_context_check.md' in (exc.value.reason.get('prompt_ref') or '')
    assert isinstance(exc.value.reason.get('reasoning'), str)
