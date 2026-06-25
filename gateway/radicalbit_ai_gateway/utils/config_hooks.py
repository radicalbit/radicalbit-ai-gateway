"""Generic registry for validating the route ``extension`` config.

A route's ``extension`` map is opaque to the core gateway. Plugins register a
validator at init time; ``GatewayRouteConfig`` runs every registered validator
against a route's ``extension`` during validation, so malformed plugin config is
rejected with the rest of the gateway config. The core carries no knowledge of
what the validators check.

A validator receives the route's ``extension`` value and must raise
``ValueError`` if it is invalid.
"""

from collections.abc import Callable

_extension_validators: list[Callable[[object], None]] = []


def register_extension_validator(validate: Callable[[object], None]) -> None:
    """Register a validator for a route's ``extension`` config."""
    _extension_validators.append(validate)


def get_extension_validators() -> list[Callable[[object], None]]:
    """Return the registered extension validators, in registration order."""
    return list(_extension_validators)
