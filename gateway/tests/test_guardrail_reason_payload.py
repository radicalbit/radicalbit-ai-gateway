import json
from unittest.mock import MagicMock

from radicalbit_ai_gateway.models.guardrails import (
    CheckParameter,
    Guardrail,
    GuardrailBehaviorType,
    GuardrailType,
    GuardrailWhereType,
    JudgeParameter,
)
from radicalbit_ai_gateway.utils.exceptions import (
    GuardrailBadRequest,
    guardrail_exception_handler,
)


def _mock_request():
    """Create a mock request with state attribute."""
    request = MagicMock()
    request.state = MagicMock()
    return request


def test_guardrail_reason_is_included_in_error_param_payload():
    gr = Guardrail(
        name='gr_contains',
        type=GuardrailType.CONTAINS,
        where=GuardrailWhereType.INPUT,
        behavior=GuardrailBehaviorType.BLOCK,
        parameters=CheckParameter(values=['sensitive']),
    )

    err = GuardrailBadRequest(
        'blocked',
        guardrail=gr,
        log_message='[GUARDRAIL TRIGGERED]',
        reason={
            'kind': 'contains',
            'value': 'sensitive',
            'message_index': 0,
            'context': '… very <<sensitive>> data …',
        },
    )

    resp = guardrail_exception_handler(_mock_request(), err)
    payload = json.loads(resp.body.decode('utf-8'))
    assert payload['error']['type'] == 'guardrail_error'
    assert payload['error']['param']['name'] == 'gr_contains'
    assert payload['error']['param']['reason']['kind'] == 'contains'
    assert 'context' in payload['error']['param']['reason']


def test_guardrail_judge_reason_does_not_expose_prompt_or_model_in_response():
    gr = Guardrail(
        name='gr_judge',
        type=GuardrailType.JUDGE,
        where=GuardrailWhereType.INPUT,
        behavior=GuardrailBehaviorType.BLOCK,
        parameters=JudgeParameter(
            prompt_ref='business_context_check.md', model_id='m1'
        ),
    )
    err = GuardrailBadRequest(
        'blocked',
        guardrail=gr,
        log_message='[GUARDRAIL TRIGGERED]',
        reason={
            'kind': 'judge',
            'value': 'BUSINESS_CONTEXT',
            'message_index': 0,
            'context': 'Some excerpt',
            'prompt_ref': 'business_context_check.md',
            'model_id': 'gpt-4o-mini',
        },
    )

    resp = guardrail_exception_handler(_mock_request(), err)
    payload = json.loads(resp.body.decode('utf-8'))
    reason = payload['error']['param']['reason']
    assert reason['kind'] == 'judge'
    assert reason['value'] == 'BUSINESS_CONTEXT'
    assert 'prompt_ref' not in reason
    assert 'model_id' not in reason
