"""The base class of every generated model (``models.py``).

Responses from a newer gateway can carry what this SDK does not know yet: a
value outside a field's ``Literal`` (a new project status) or a field that is
not in the model. Rejecting them would break a working program on a gateway
upgrade, so both are kept:

- an unknown value comes through as the API sent it (``'ARCHIVED'``);
- an unknown field is kept as the API named it, in ``model_extra``
  (``project.model_extra['newField']``).

Any other problem (a number that is not a number, a missing field) still
raises: only the closed sets of values are open to new members.
"""

from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
    ValidatorFunctionWrapHandler,
    field_validator,
)

# Pydantic's error types for a value outside a Literal or an Enum
_UNKNOWN_VALUE_ERRORS = frozenset({'literal_error', 'enum'})


class GatewayModel(BaseModel):
    """A model of the API: tolerant of values and fields added by newer gateways."""

    model_config = ConfigDict(extra='allow')

    @field_validator('*', mode='wrap')
    @classmethod
    def _keep_unknown_values(
        cls, value: Any, handler: ValidatorFunctionWrapHandler
    ) -> Any:
        try:
            return handler(value)
        except ValidationError as error:
            if all(e['type'] in _UNKNOWN_VALUE_ERRORS for e in error.errors()):
                return value
            raise
