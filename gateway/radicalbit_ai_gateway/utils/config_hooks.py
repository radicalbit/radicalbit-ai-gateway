from collections.abc import Callable

from pydantic import BaseModel, ConfigDict

_extension_validators: list[Callable[[object], None]] = []


def register_extension_validator(validate: Callable[[object], None]) -> None:
    """Register a validator for a route's ``extension`` config."""
    _extension_validators.append(validate)


def get_extension_validators() -> list[Callable[[object], None]]:
    """Return the registered extension validators, in registration order."""
    return list(_extension_validators)


class ExtensionConfig(BaseModel):
    """Base schema for a plugin's ``extension`` slice.

    Forbids unknown keys (``extra='forbid'``), so a route may only set the
    parameters a plugin declares. Subclass to add plugin-specific fields::

        class MyPluginConfig(ExtensionConfig):
            threshold: int = 5

    Secret-bearing fields (set via ``!secret KEY`` in YAML) must be typed as
    ``str`` (or ``SecretStr`` / ``str | None``): ``!secret`` resolves to a
    string before this schema runs, and during validation it is a placeholder
    string rather than the real value — so do not type such fields ``int``/
    ``bool`` or attach a format regex.
    """

    model_config = ConfigDict(extra='forbid')


def register_extension_slice_validator(
    key: str, validate_slice: Callable[[dict], object]
) -> None:
    """Register a validator scoped to one ``extension`` key.

    Runs ``validate_slice`` on ``extension[key]`` only when that key is present
    in a route's ``extension``. Raise ``ValueError`` from *validate_slice* to
    fail config validation.
    """

    def _validate(extension: dict) -> None:
        config = extension.get(key)
        if config is not None:
            validate_slice(config)

    register_extension_validator(_validate)


def register_extension_schema(key: str, schema: type[ExtensionConfig]) -> None:
    """Validate the ``extension[key]`` slice against *schema* at config-load time.

    The one-call path for any plugin that needs extra config fields: define an
    :class:`ExtensionConfig` subclass and register it under the plugin's key.
    Unknown keys and invalid types are rejected.
    """
    register_extension_slice_validator(key, schema.model_validate)
