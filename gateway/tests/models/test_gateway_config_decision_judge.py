import pytest

from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.gateway_config_out import GuardrailOut
from radicalbit_ai_gateway.models.guardrails import (
    DecisionJudgeParameter,
    GuardrailClass,
    GuardrailType,
)

JEV = {
    'model_id': 'jev',
    'model': 'typesafe/jev-latest',
    'credentials': {'api_key': 'ts-dummy'},
}


def _decision_judge(**parameters) -> dict:
    return {
        'name': 'off_topic',
        'type': 'decision_judge',
        'where': 'input',
        'parameters': {
            'model_id': 'jev',
            'instructions': 'Is the user asking about something other than billing?',
            **parameters,
        },
    }


def _config(guardrail: dict) -> GatewayConfig:
    return GatewayConfig.model_validate(
        {
            'chat_models': [{'model_id': 'gpt', 'model': 'openai/gpt-4o-mini'}],
            'decision_models': [JEV],
            'guardrails': [guardrail],
            'routes': {'chat': {'chat_models': ['gpt'], 'guardrails': ['off_topic']}},
        }
    )


def test_decision_judge_loads_as_a_check_guardrail():
    guardrail = _config(_decision_judge()).guardrails[0]

    assert guardrail.type == GuardrailType.DECISION_JUDGE
    assert guardrail.guardrail_class() == GuardrailClass.CHECK
    assert isinstance(guardrail.parameters, DecisionJudgeParameter)
    assert guardrail.parameters.model_id == 'jev'
    assert guardrail.parameters.criteria is None


def test_threshold_defaults_to_one_half():
    guardrail = _config(_decision_judge()).guardrails[0]

    assert guardrail.parameters.threshold == 0.5


@pytest.mark.parametrize('threshold', [0, 0.2, 1])
def test_threshold_inside_zero_one_is_accepted(threshold):
    guardrail = _config(_decision_judge(threshold=threshold)).guardrails[0]

    assert guardrail.parameters.threshold == threshold


@pytest.mark.parametrize('threshold', [-0.1, 1.01])
def test_threshold_outside_zero_one_is_rejected(threshold):
    with pytest.raises(ValueError, match='threshold'):
        _config(_decision_judge(threshold=threshold))


def test_criteria_keep_their_true_and_false_descriptions():
    guardrail = _config(
        _decision_judge(criteria={'true': 'Off topic', 'false': 'About billing'})
    ).guardrails[0]

    assert guardrail.parameters.criteria.model_dump() == {
        'true': 'Off topic',
        'false': 'About billing',
    }


def test_instructions_are_required():
    guardrail = _decision_judge()
    del guardrail['parameters']['instructions']

    with pytest.raises(ValueError, match='instructions'):
        _config(guardrail)


@pytest.mark.parametrize(
    'llm_judge_field',
    ['prompt_ref', 'temperature', 'max_tokens', 'include_reasoning', 'include_media'],
)
def test_llm_judge_fields_are_rejected(llm_judge_field):
    with pytest.raises(ValueError, match=llm_judge_field):
        _config(_decision_judge(**{llm_judge_field: 'x'}))


def test_decision_judge_is_shown_in_the_config_out():
    guardrail = _config(
        _decision_judge(threshold=0.7, criteria={'true': 'yes', 'false': 'no'})
    ).guardrails[0]

    out = GuardrailOut.model_validate(guardrail.model_dump())

    assert out.parameters.model_dump(by_alias=True) == {
        'type': 'DECISION_JUDGE',
        'modelId': 'jev',
        'instructions': 'Is the user asking about something other than billing?',
        'criteria': {'true': 'yes', 'false': 'no'},
        'threshold': 0.7,
    }
