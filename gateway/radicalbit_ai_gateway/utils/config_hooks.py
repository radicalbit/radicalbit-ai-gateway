from collections.abc import Callable

_extension_validators: list[Callable[[object], None]] = []


def register_extension_validator(validate: Callable[[object], None]) -> None:
    """Register a validator for a route's ``extension`` config."""
    _extension_validators.append(validate)


def get_extension_validators() -> list[Callable[[object], None]]:
    """Return the registered extension validators, in registration order."""
    return list(_extension_validators)
