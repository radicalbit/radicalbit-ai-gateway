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


JEV_BACKUP = {
    'model_id': 'jev-backup',
    'model': 'typesafe/jev-backup',
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
            'embedding_models': [
                {'model_id': 'embed', 'model': 'openai/text-embedding-3-small'}
            ],
            'transcription_models': [
                {'model_id': 'whisper', 'model': 'openai/whisper-1'}
            ],
            'decision_models': [JEV, JEV_BACKUP],
            'guardrails': [guardrail],
            'routes': {'chat': {'chat_models': ['gpt'], 'guardrails': ['off_topic']}},
        }
    )


def test_decision_judge_loads_as_a_check_guardrail_with_defaults():
    guardrail = _config(_decision_judge()).guardrails[0]

    assert guardrail.type == GuardrailType.DECISION_JUDGE
    assert guardrail.guardrail_class() == GuardrailClass.CHECK
    assert isinstance(guardrail.parameters, DecisionJudgeParameter)
    assert guardrail.parameters.model_id == 'jev'
    assert guardrail.parameters.criteria is None
    assert guardrail.parameters.threshold == 0.5
    assert guardrail.parameters.fallback_model_id is None


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


@pytest.mark.parametrize('field', ['instructions', 'model_id'])
def test_required_parameters(field):
    guardrail = _decision_judge()
    del guardrail['parameters'][field]

    with pytest.raises(ValueError, match=field):
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
        'fallbackModelId': None,
        'instructions': 'Is the user asking about something other than billing?',
        'criteria': {'true': 'yes', 'false': 'no'},
        'threshold': 0.7,
    }


# Model references, checked at load


@pytest.mark.parametrize(
    ('overrides', 'match'),
    [
        pytest.param(
            {'model_id': 'missing'}, "'off_topic'.*'missing'", id='unknown-model'
        ),
        pytest.param(
            {'fallback_model_id': 'missing'},
            "'off_topic'.*'missing'",
            id='unknown-fallback-model',
        ),
        pytest.param(
            {'model_id': 'jev', 'fallback_model_id': 'jev'},
            "'off_topic'.*'jev'",
            id='fallback-equal-to-model',
        ),
    ],
)
def test_invalid_model_reference_is_rejected_naming_guardrail_and_id(overrides, match):
    with pytest.raises(ValueError, match=match):
        _config(_decision_judge(**overrides))


@pytest.mark.parametrize(
    ('field', 'label'),
    [('model_id', 'model'), ('fallback_model_id', 'fallback model')],
)
@pytest.mark.parametrize('model_id', ['gpt', 'embed', 'whisper'])
def test_non_decision_model_is_rejected(field, label, model_id):
    with pytest.raises(
        ValueError, match=f"'off_topic': decision judge {label} '{model_id}'"
    ):
        _config(_decision_judge(**{field: model_id}))


def test_decision_models_not_on_the_route_are_accepted():
    # The route lists only the chat model 'gpt'.
    guardrail = _config(
        _decision_judge(model_id='jev', fallback_model_id='jev-backup')
    ).guardrails[0]

    assert guardrail.parameters.model_id == 'jev'
    assert guardrail.parameters.fallback_model_id == 'jev-backup'
