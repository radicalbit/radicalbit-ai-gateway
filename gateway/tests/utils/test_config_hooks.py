import pytest

from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.utils import config_hooks
from radicalbit_ai_gateway.utils.config_hooks import (
    PluginConfig,
    register_plugin_config_validator,
    register_plugins_validator,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    config_hooks._plugins_validators.clear()
    config_hooks._known_plugin_keys.clear()
    yield
    config_hooks._plugins_validators.clear()
    config_hooks._known_plugin_keys.clear()


def _config(plugins):
    """Build a config the way it is loaded in production: validation of a
    route's ``plugins`` happens at GatewayConfig load time, not on bare
    GatewayRouteConfig construction.
    """
    return GatewayConfig(
        chat_models=[{'model_id': 'm', 'model': 'openai/gpt-4o'}],
        routes={'r': {'chat_models': ['m'], 'plugins': plugins}},
    )


def test_registered_validator_receives_extension():
    seen = []
    register_plugins_validator(seen.append)

    _config({'fake_enabled': True})

    assert seen == [{'fake_enabled': True}]


def test_validator_error_fails_config_validation():
    def validate(plugins):
        raise ValueError('bad plugin config')

    register_plugins_validator(validate)

    with pytest.raises(Exception) as exc_info:
        _config({'whatever': 1})
    assert 'bad plugin config' in str(exc_info.value)


def test_no_extension_is_a_noop():
    register_plugins_validator(lambda plugins: 1 / 0)

    _config(None)


class _MyConfig(PluginConfig):
    threshold: int = 5
    secret: str | None = None


def test_schema_validates_known_keys():
    register_plugin_config_validator('my_plugin', _MyConfig.model_validate)

    _config({'my_plugin': {'threshold': 3}})


def test_schema_rejects_unknown_key():
    register_plugin_config_validator('my_plugin', _MyConfig.model_validate)

    with pytest.raises(Exception) as exc_info:
        _config({'my_plugin': {'typo': 1}})
    assert 'typo' in str(exc_info.value)


def test_schema_rejects_bad_type():
    register_plugin_config_validator('my_plugin', _MyConfig.model_validate)

    with pytest.raises(Exception):
        _config({'my_plugin': {'threshold': 'not-an-int'}})


def test_unknown_key_is_rejected():
    register_plugin_config_validator('my_plugin', _MyConfig.model_validate)

    with pytest.raises(Exception) as exc_info:
        _config({'other_plugin': {'whatever': 1}})
    assert 'other_plugin' in str(exc_info.value)


def test_schema_accepts_secret_placeholder_for_str_field():
    # ``!secret`` resolves to a string before validation (a placeholder during
    # the validate pass); a str-typed field must accept it.
    register_plugin_config_validator('my_plugin', _MyConfig.model_validate)

    _config({'my_plugin': {'secret': '__secret_placeholder__'}})


def test_slice_validator_runs_only_when_key_present():
    seen = []
    register_plugin_config_validator('my_plugin', seen.append)

    # A different, unclaimed key is rejected rather than silently skipped.
    with pytest.raises(Exception) as exc_info:
        _config({'other_plugin': {'a': 1}})
    assert 'other_plugin' in str(exc_info.value)
    assert seen == []

    _config({'my_plugin': {'a': 1}})
    assert seen == [{'a': 1}]
