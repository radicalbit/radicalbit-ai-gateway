"""A redaction guardrail reports the phase it evaluated, so alert rules match."""

import copy
from unittest.mock import MagicMock, patch
import uuid

from langchain_core.messages import HumanMessage
import pytest

from tests.common.mocked_gateway_config_openai import get_default_gateway_openai

from radicalbit_ai_gateway.events.events_processor import _dispatch_alert_if_matching
from radicalbit_ai_gateway.guardrails.guardrail_engine import GuardrailEngine
from radicalbit_ai_gateway.guardrails.judges.judge_engine import JudgeEngine
from radicalbit_ai_gateway.guardrails.presidio import PresidioEngine
from radicalbit_ai_gateway.models.guardrails import (
    Guardrail,
    GuardrailBehaviorType,
    GuardrailType,
    GuardrailWhereType,
    RedactParameter,
)
from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.services.cost_service import CostService


@pytest.fixture(scope='module')
def guardrail_engine():
    io_guardrail = Guardrail(
        name='redact_email',
        type=GuardrailType.PRESIDIO_ANONYMIZER,
        behavior=GuardrailBehaviorType.BLOCK,
        where=GuardrailWhereType.IO,
        parameters=RedactParameter(language='it', entities=['EMAIL_ADDRESS']),
    )
    return GuardrailEngine(
        presidio_engine=PresidioEngine(),
        judge_engine=JudgeEngine(prompt_manager=MagicMock(spec_set=PromptManager)),
        cost_service=MagicMock(spec_set=CostService),
        guardrails=[io_guardrail],
    )


async def _redact(guardrail_engine, where):
    route_config = copy.deepcopy(get_default_gateway_openai().routes['rb-gateway'])
    route_config.guardrails = ['redact_email']
    with patch(
        'radicalbit_ai_gateway.guardrails.guardrail_redact.emit_event', autospec=True
    ) as emit_event:
        await guardrail_engine.guardrail_redact.apply_guardrails(
            request_uuid=str(uuid.uuid4()),
            api_key_uuid=str(uuid.uuid4()),
            group_uuid=str(uuid.uuid4()),
            api_key_name='fake-name',
            group_name='test-group',
            route_config=route_config,
            messages=[HumanMessage(content='This is my email test@radicalbit.io')],
            where=where,
            project_uuid=str(uuid.uuid4()),
            project_name='test-project',
        )
    emit_event.assert_called_once()
    return emit_event.call_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('where', 'expected'),
    [(GuardrailWhereType.INPUT, 'INPUT'), (GuardrailWhereType.OUTPUT, 'OUTPUT')],
)
async def test_an_io_redaction_reports_the_phase_it_evaluated(
    guardrail_engine, where, expected
):
    event = await _redact(guardrail_engine, where)

    assert event.where == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('where', 'expected'),
    [
        (GuardrailWhereType.INPUT, 'guardrail-input-redact_email'),
        (GuardrailWhereType.OUTPUT, 'guardrail-output-redact_email'),
    ],
)
async def test_an_io_redaction_reaches_the_alert_rule_for_its_phase(
    guardrail_engine, where, expected
):
    event = await _redact(guardrail_engine, where)
    alert_service = MagicMock()

    _dispatch_alert_if_matching(alert_service, event)

    alert_service.dispatch_event_notification.assert_called_once()
    assert (
        alert_service.dispatch_event_notification.call_args.kwargs['event_name']
        == expected
    )
