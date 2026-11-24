from pydantic import ValidationError
import pytest

from radicalbit_ai_gateway.models.guardrails import (
    CheckGuardrail,
    GuardrailBehaviorType,
    GuardrailHistory,
    GuardrailType,
    GuardrailWhereType,
    guardrail_adapter,
)


def _guardrail(**overrides):
    data = {
        'name': 'g',
        'type': 'contains',
        'where': 'input',
        'behavior': 'block',
        'parameters': {'values': ['x']},
        **overrides,
    }
    return guardrail_adapter.validate_python(data)


def test_lower_case_enum_values_are_accepted():
    guardrail = _guardrail(history='last')

    assert guardrail.type == GuardrailType.CONTAINS
    assert guardrail.where == GuardrailWhereType.INPUT
    assert guardrail.behavior == GuardrailBehaviorType.BLOCK
    assert guardrail.history == GuardrailHistory.LAST


@pytest.mark.parametrize('field', ['type', 'where', 'behavior', 'history'])
@pytest.mark.parametrize('value', [None, 3])
def test_non_string_enum_value_is_a_validation_error(field, value):
    with pytest.raises(ValidationError) as exc_info:
        _guardrail(**{field: value})

    errors = exc_info.value.errors()
    if field == 'type':
        # The type picks the guardrail class: a bad one fails the guardrail.
        assert [error['type'] for error in errors] == ['guardrail_type']
    else:
        assert any(error['loc'] == ('CHECK', field) for error in errors)


def test_an_unknown_type_is_a_guardrail_type_error():
    with pytest.raises(ValidationError) as exc_info:
        _guardrail(type='not_a_guardrail')

    assert [error['type'] for error in exc_info.value.errors()] == ['guardrail_type']


def test_behavior_defaults_to_block():
    data = {'name': 'g', 'type': 'contains', 'parameters': {'values': ['x']}}

    guardrail = guardrail_adapter.validate_python(data)

    assert isinstance(guardrail, CheckGuardrail)
    assert guardrail.behavior == GuardrailBehaviorType.BLOCK
