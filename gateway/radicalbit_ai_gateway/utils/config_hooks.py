from collections.abc import Callable, Iterable
from typing import Any

from pydantic import BaseModel, ConfigDict, create_model

_extension_validators: list[Callable[[object], None]] = []
_known_extension_keys: set[str] = set()


def register_extension_validator(validate: Callable[[object], None]) -> None:
    """Register a validator for a route's ``extension`` config."""
    _extension_validators.append(validate)


def get_extension_validators() -> list[Callable[[object], None]]:
    """Return the registered extension validators, in registration order."""
    return list(_extension_validators)


def get_known_extension_keys() -> set[str]:
    """Return the ``extension`` keys claimed by a registered plugin slice.

    A plugin declares a key by registering a slice validator/schema for it (see
    :func:`register_extension_slice_validator`). A route may only set keys in
    this set; see :func:`build_route_extension_model`.
    """
    return set(_known_extension_keys)


def build_route_extension_model(keys: Iterable[str]) -> type[BaseModel]:
    """Build a model whose only allowed fields are *keys*.

    *keys* are the ``extension`` keys plugins claimed via slice/schema
    registration. The returned model lists exactly those keys and sets
    ``extra='forbid'``, so a route ``extension`` that names a key no plugin
    claims — a typo'd or stale plugin name — fails config validation instead of
    being silently ignored. Field contents stay permissive (``Any``); the
    per-slice validators validate each slice's contents.
    """
    fields: dict[str, Any] = dict.fromkeys(keys, (Any, None))
    return create_model(
        'RouteExtension',
        __config__=ConfigDict(extra='forbid'),
        **fields,
    )


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
    key: str, validate_slice: Callable[[Any], object]
) -> None:
    """Register a validator scoped to one ``extension`` key.

    Runs ``validate_slice`` on ``extension[key]`` only when that key is present
    in a route's ``extension``. Raise ``ValueError`` from *validate_slice* to
    fail config validation. Records *key* as a known ``extension`` key (see
    :func:`build_route_extension_model`), so a route may only set keys some
    plugin claims.
    """
    _known_extension_keys.add(key)

    def _validate(extension: object) -> None:
        if isinstance(extension, dict):
            config = extension.get(key)
            if config is not None:
                validate_slice(config)

    register_extension_validator(_validate)
