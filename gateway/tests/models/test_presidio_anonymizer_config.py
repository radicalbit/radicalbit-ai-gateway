"""presidio_anonymizer has no behavior: a config that still sets one loads."""

import logging
from typing import Any

from pydantic import ValidationError
import pytest

from radicalbit_ai_gateway.models.gateway_config_out import (
    PresidioAnonymizerGuardrailOut,
)
from radicalbit_ai_gateway.models.guardrails import (
    GuardrailBehaviorType,
    GuardrailClass,
    PresidioAnalyzerGuardrail,
    PresidioAnonymizerGuardrail,
    guardrail_adapter,
)


def _anonymizer(**extra) -> dict[str, Any]:
    return {
        'name': 'redact_email',
        'type': 'presidio_anonymizer',
        'where': 'input',
        'parameters': {'entities': ['EMAIL_ADDRESS']},
        **extra,
    }


@pytest.mark.parametrize(
    'extra',
    [
        pytest.param({'behavior': 'block'}, id='behavior'),
        pytest.param({'behavior': 'soft_block'}, id='soft-block'),
        pytest.param({'response_message': 'No PII.'}, id='response-message'),
        pytest.param({'behavior': 'warn', 'response_message': 'No PII.'}, id='both'),
    ],
)
def test_an_anonymizer_with_a_behavior_loads_and_warns(caplog, extra):
    with caplog.at_level(logging.WARNING):
        guardrail = guardrail_adapter.validate_python(_anonymizer(**extra))

    assert isinstance(guardrail, PresidioAnonymizerGuardrail)
    assert guardrail == guardrail_adapter.validate_python(_anonymizer())
    assert 'redact_email: presidio_anonymizer ignores' in caplog.text
    for key in extra:
        assert key in caplog.text


def test_an_anonymizer_without_a_behavior_loads_without_a_warning(caplog):
    with caplog.at_level(logging.WARNING):
        guardrail = guardrail_adapter.validate_python(_anonymizer())

    assert isinstance(guardrail, PresidioAnonymizerGuardrail)
    assert 'ignores' not in caplog.text


def test_an_anonymizer_dump_has_no_behavior():
    guardrail = guardrail_adapter.validate_python(
        _anonymizer(behavior='block', response_message='No PII.')
    )

    dumped = guardrail.model_dump()
    assert 'behavior' not in dumped
    assert 'response_message' not in dumped
    assert guardrail_adapter.validate_python(dumped) == guardrail
    out = PresidioAnonymizerGuardrailOut.model_validate(dumped)
    assert 'behavior' not in out.model_dump(by_alias=True)
    assert 'responseMessage' not in out.model_dump(by_alias=True)


def test_an_anonymizer_is_a_redaction():
    guardrail = guardrail_adapter.validate_python(_anonymizer())

    assert guardrail.guardrail_class() == GuardrailClass.REDACT


def test_a_loaded_anonymizer_validates_as_itself():
    guardrail = guardrail_adapter.validate_python(_anonymizer())

    assert guardrail_adapter.validate_python(guardrail) == guardrail


def test_an_anonymizer_from_neither_a_dict_nor_a_guardrail_is_rejected():
    with pytest.raises(ValidationError, match='valid dictionary or instance'):
        PresidioAnonymizerGuardrail.model_validate(['presidio_anonymizer'])


def test_an_anonymizer_still_rejects_an_unknown_field():
    with pytest.raises(ValidationError):
        guardrail_adapter.validate_python(_anonymizer(foo='bar'))


def test_an_analyzer_keeps_its_behavior():
    guardrail = guardrail_adapter.validate_python(
        _anonymizer(
            type='presidio_analyzer', behavior='warn', response_message='No PII.'
        )
    )

    assert isinstance(guardrail, PresidioAnalyzerGuardrail)
    assert guardrail.behavior == GuardrailBehaviorType.WARN
    assert guardrail.model_dump()['response_message'] == 'No PII.'


@pytest.mark.parametrize(
    'extra',
    [
        pytest.param({'behavior': 'redact'}, id='redact'),
        pytest.param({'behavior': None}, id='null-behavior'),
        pytest.param({'behavior': 3}, id='number-behavior'),
        pytest.param({'response_message': 3}, id='number-response-message'),
    ],
)
def test_an_anonymizer_with_a_value_the_field_never_took_is_rejected(extra):
    # Dropped, but still checked: a config rejected before stays rejected.
    with pytest.raises(ValidationError, match='should be'):
        guardrail_adapter.validate_python(_anonymizer(**extra))
