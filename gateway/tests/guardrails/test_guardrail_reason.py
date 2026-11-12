from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tests.common.guardrails import apply_check

from radicalbit_ai_gateway.guardrails.guardrails import Guardrails
from radicalbit_ai_gateway.guardrails.judges.judge_engine import JudgeEngine
from radicalbit_ai_gateway.guardrails.presidio import PresidioEngine
from radicalbit_ai_gateway.llm.messages import HumanMessage
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.models.guardrails import (
    CheckParameter,
    Guardrail,
    GuardrailBehaviorType,
    GuardrailType,
    GuardrailWhereType,
    JudgeParameter,
    RedactParameter,
)
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.exceptions import GuardrailBadRequest


class _Judge:
    async def execute_judge(self, **kwargs):
        return SimpleNamespace(
            triggered=True,
            reasoning='disallowed context',
            violation_type='BUSINESS_CONTEXT',
        )


def _guardrail(kind, parameters):
    return Guardrail(
        name='gr',
        type=kind,
        where=GuardrailWhereType.INPUT,
        behavior=GuardrailBehaviorType.BLOCK,
        parameters=parameters,
    )


async def _blocked(guardrail, content, judge_engine=None):
    """Run ``guardrail`` on ``content`` under a recording span; return the
    error it raised and the span.
    """
    chk = Guardrails(
        presidio_engine=PresidioEngine(),
        judge_engine=judge_engine
        or JudgeEngine(prompt_manager=MagicMock(spec_set=PromptManager)),
        cost_service=MagicMock(spec_set=CostService),
        guardrails=[guardrail],
    )
    chk._check._chat_models_by_id = {
        'm1': Model(model_id='m1', model='mock/gateway', params={'latency_ms': 0})
    }
    span = MagicMock(**{'is_recording.return_value': True})
    with (
        patch('radicalbit_ai_gateway.guardrails.guardrail_check.emit_event'),
        patch(
            'radicalbit_ai_gateway.guardrails.guardrail_check.trace.get_current_span',
            return_value=span,
        ),
        pytest.raises(GuardrailBadRequest) as exc,
    ):
        await apply_check(
            chk,
            request_uuid='r',
            api_key_uuid='k',
            group_uuid='g',
            api_key_name='kn',
            group_name='gn',
            route_config=GatewayRouteConfig(
                route_name='test-route', chat_models=['m1'], guardrails=['gr']
            ),
            messages=[HumanMessage(content=content)],
            where=GuardrailWhereType.INPUT,
        )
    assert '[GUARDRAIL TRIGGERED]' in str(exc.value)
    return exc.value, span


@pytest.mark.parametrize(
    ('kind', 'parameters', 'content', 'reason', 'attribute'),
    [
        (
            GuardrailType.STARTS_WITH,
            CheckParameter(values=['Hello']),
            'Hello there',
            {'kind': 'starts_with', 'value': 'Hello'},
            ('guardrail.triggered.value', 'Hello'),
        ),
        (
            GuardrailType.CONTAINS,
            CheckParameter(values=['sensitive']),
            'this is very SenSiTive data indeed',
            {'kind': 'contains', 'value': 'sensitive'},
            ('guardrail.triggered.value', 'sensitive'),
        ),
        (
            GuardrailType.REGEX,
            CheckParameter(values=[r'\d+'], ignore_case=True),
            'value 123',
            {'kind': 'regex', 'pattern': r'\d+'},
            ('guardrail.triggered.pattern', r'\d+'),
        ),
        (
            GuardrailType.PRESIDIO_ANALYZER,
            RedactParameter(language='it', entities=['EMAIL_ADDRESS']),
            'write to test@radicalbit.io now',
            {'kind': 'presidio', 'entity_type': 'EMAIL_ADDRESS'},
            ('guardrail.triggered.entity_type', 'EMAIL_ADDRESS'),
        ),
    ],
    ids=['starts_with', 'contains_ignoring_case', 'regex', 'presidio'],
)
async def test_a_check_reports_what_matched_where(
    kind, parameters, content, reason, attribute
):
    error, span = await _blocked(_guardrail(kind, parameters), content)

    assert error.reason.items() >= {**reason, 'message_indices': [0]}.items()
    assert isinstance(error.reason['context'], str)
    span.set_attribute.assert_any_call(*attribute)
    span.set_attribute.assert_any_call('guardrail.triggered.message_indices', [0])


async def test_a_contains_reason_marks_the_match_in_its_context():
    error, _ = await _blocked(
        _guardrail(GuardrailType.CONTAINS, CheckParameter(values=['sensitive'])),
        'this is very sensitive data indeed',
    )

    assert '<<sensitive>>' in error.reason['context']


async def test_a_judge_reports_its_verdict_and_traces_it():
    error, span = await _blocked(
        _guardrail(
            GuardrailType.JUDGE,
            JudgeParameter(prompt_ref='business_context_check.md', model_id='m1'),
        ),
        'Some business context here',
        judge_engine=_Judge(),
    )

    assert error.reason['kind'] == 'judge'
    assert error.reason['value'] == 'BUSINESS_CONTEXT'
    assert error.reason['prompt_ref'] == 'business_context_check.md'
    assert error.reason['reasoning'] == 'disallowed context'
    for name, value in [
        ('guardrail.judge.violation_type', 'BUSINESS_CONTEXT'),
        ('guardrail.judge.reasoning', 'disallowed context'),
        ('guardrail.judge.prompt_ref', 'business_context_check.md'),
        ('guardrail.judge.model_id', 'm1'),
        ('guardrail.triggered.reasoning', 'disallowed context'),
    ]:
        span.set_attribute.assert_any_call(name, value)
