from collections.abc import Callable, Iterable
from typing import Any

from pydantic import BaseModel, ConfigDict, create_model

_plugins_validators: list[Callable[[object], None]] = []
_known_plugin_keys: set[str] = set()


def register_plugins_validator(validate: Callable[[object], None]) -> None:
    """Register a validator for a route's ``plugins`` config."""
    _plugins_validators.append(validate)


def get_plugins_validators() -> list[Callable[[object], None]]:
    """Return the registered plugins validators, in registration order."""
    return list(_plugins_validators)


def get_known_plugin_keys() -> set[str]:
    """Return the ``plugins`` keys claimed by a registered plugin slice.

    A plugin declares a key by registering a slice validator/schema for it (see
    :func:`register_plugin_config_validator`). A route may only set keys in
    this set; see :func:`build_route_plugins_model`.
    """
    return set(_known_plugin_keys)


def build_route_plugins_model(keys: Iterable[str]) -> type[BaseModel]:
    """Build a model whose only allowed fields are *keys*.

    *keys* are the ``plugins`` keys plugins claimed via slice/schema
    registration. The returned model lists exactly those keys and sets
    ``extra='forbid'``, so a route ``plugins`` that names a key no plugin
    claims — a typo'd or stale plugin name — fails config validation instead of
    being silently ignored. Field contents stay permissive (``Any``); the
    per-slice validators validate each slice's contents.
    """
    fields: dict[str, Any] = dict.fromkeys(keys, (Any, None))
    return create_model(
        'RoutePlugins',
        __config__=ConfigDict(extra='forbid'),
        **fields,
    )


class PluginConfig(BaseModel):
    """Base schema for a plugin's ``plugins`` slice.

    Forbids unknown keys (``extra='forbid'``), so a route may only set the
    parameters a plugin declares. Subclass to add plugin-specific fields::

        class MyPluginConfig(PluginConfig):
            threshold: int = 5

    Secret-bearing fields (set via ``!secret KEY`` in YAML) must be typed as
    ``str`` (or ``SecretStr`` / ``str | None``): ``!secret`` resolves to a
    string before this schema runs, and during validation it is a placeholder
    string rather than the real value — so do not type such fields ``int``/
    ``bool`` or attach a format regex.
    """

    model_config = ConfigDict(extra='forbid')


def register_plugin_config_validator(
    key: str, validate_slice: Callable[[Any], object]
) -> None:
    """Register a validator scoped to one ``plugins`` key.

    Runs ``validate_slice`` on ``plugins[key]`` only when that key is present
    in a route's ``plugins``. Raise ``ValueError`` from *validate_slice* to
    fail config validation. Records *key* as a known ``plugins`` key (see
    :func:`build_route_plugins_model`), so a route may only set keys some
    plugin claims.
    """
    _known_plugin_keys.add(key)

    def _validate(plugins: object) -> None:
        if isinstance(plugins, dict):
            config = plugins.get(key)
            if config is not None:
                validate_slice(config)

    register_plugins_validator(_validate)
