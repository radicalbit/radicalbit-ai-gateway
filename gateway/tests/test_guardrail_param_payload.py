from fastapi.encoders import jsonable_encoder

from radicalbit_ai_gateway.utils.exceptions import _guardrail_param_payload


class _WeirdGuardrail:
    """Object intentionally NOT JSON-friendly / robust, to validate fallback behavior."""

    @property
    def name(self):
        raise RuntimeError('boom')

    def __str__(self) -> str:
        raise RuntimeError('nope')

    @property
    def parameters(self):
        raise RuntimeError('boom-params')


class _ParamsModel:
    """Pydantic-like object: exposes model_dump()."""

    def model_dump(self, **kwargs):
        return {'a': 1, 'b': None}


class _GuardrailWithParamsModel:
    name = 'gr'
    type = 'regex'
    where = 'input'
    behavior = 'block'
    id = 'g1'
    parameters = _ParamsModel()


class _UnserializableParams:
    def __str__(self) -> str:
        raise RuntimeError('nope')


class _GuardrailWithUnserializableParams:
    name = 'gr2'
    parameters = _UnserializableParams()


class _EnumLike:
    def __init__(self, name: str):
        self.name = name


class _GuardrailWithEnumLikesAndEmptyFields:
    name = ''  # should be ignored
    type = _EnumLike('REGEX')
    where = _EnumLike('INPUT')
    behavior = _EnumLike('BLOCK')
    id = None  # should be ignored


def test_guardrail_param_payload_is_json_safe_on_weird_objects():
    payload = _guardrail_param_payload(_WeirdGuardrail())

    # Must always return something JSON-friendly (dict), never the raw object.
    assert isinstance(payload, dict)
    assert payload.get('class') == '_WeirdGuardrail'
    assert isinstance(payload.get('repr'), str)

    # And FastAPI must be able to encode it without blowing up.
    encoded = jsonable_encoder(payload)
    assert isinstance(encoded, dict)

    # If guardrail looks like a normal object with readable attributes, we extract a stable payload.
    payload2 = _guardrail_param_payload(_GuardrailWithParamsModel())
    assert isinstance(payload2, dict)
    assert payload2['name'] == 'gr'
    assert payload2['type'] == 'regex'
    assert payload2['where'] == 'input'
    assert payload2['behavior'] == 'block'
    assert payload2['id'] == 'g1'
    assert payload2['parameters'] == {'a': 1, 'b': None}
    assert isinstance(jsonable_encoder(payload2), dict)

    # If parameters are not serializable, we still return JSON-safe strings.
    payload3 = _guardrail_param_payload(_GuardrailWithUnserializableParams())
    assert isinstance(payload3, dict)
    assert payload3['name'] == 'gr2'
    assert isinstance(payload3['parameters'], str)
    assert isinstance(jsonable_encoder(payload3), dict)

    # Enum-like values should be normalized via their `.name`, and empty/None fields omitted.
    payload4 = _guardrail_param_payload(_GuardrailWithEnumLikesAndEmptyFields())
    assert isinstance(payload4, dict)
    assert 'name' not in payload4
    assert 'id' not in payload4
    assert payload4['type'] == 'REGEX'
    assert payload4['where'] == 'INPUT'
    assert payload4['behavior'] == 'BLOCK'
    assert isinstance(jsonable_encoder(payload4), dict)
