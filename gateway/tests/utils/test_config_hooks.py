import pytest

from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.utils import config_hooks
from radicalbit_ai_gateway.utils.config_hooks import (
    ExtensionConfig,
    register_extension_schema,
    register_extension_slice_validator,
    register_extension_validator,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    config_hooks._extension_validators.clear()
    yield
    config_hooks._extension_validators.clear()


def _config(extension):
    """Build a config the way it is loaded in production: validation of a
    route's ``extension`` happens at GatewayConfig load time, not on bare
    GatewayRouteConfig construction.
    """
    return GatewayConfig(
        chat_models=[{'model_id': 'm', 'model': 'openai/gpt-4o'}],
        routes={'r': {'chat_models': ['m'], 'extension': extension}},
    )


def test_registered_validator_receives_extension():
    seen = []
    register_extension_validator(seen.append)

    _config({'fake_enabled': True})

    assert seen == [{'fake_enabled': True}]


def test_validator_error_fails_config_validation():
    def validate(extension):
        raise ValueError('bad plugin config')

    register_extension_validator(validate)

    with pytest.raises(Exception) as exc_info:
        _config({'whatever': 1})
    assert 'bad plugin config' in str(exc_info.value)


def test_no_extension_is_a_noop():
    register_extension_validator(lambda extension: 1 / 0)

    _config(None)


class _MyConfig(ExtensionConfig):
    threshold: int = 5
    secret: str | None = None


def test_schema_validates_known_keys():
    register_extension_schema('my_plugin', _MyConfig)

    _config({'my_plugin': {'threshold': 3}})


def test_schema_rejects_unknown_key():
    register_extension_schema('my_plugin', _MyConfig)

    with pytest.raises(Exception) as exc_info:
        _config({'my_plugin': {'typo': 1}})
    assert 'typo' in str(exc_info.value)


def test_schema_rejects_bad_type():
    register_extension_schema('my_plugin', _MyConfig)

    with pytest.raises(Exception):
        _config({'my_plugin': {'threshold': 'not-an-int'}})


def test_schema_noop_when_key_absent():
    register_extension_schema('my_plugin', _MyConfig)

    _config({'other_plugin': {'whatever': 1}})


def test_schema_accepts_secret_placeholder_for_str_field():
    # ``!secret`` resolves to a string before validation (a placeholder during
    # the validate pass); a str-typed field must accept it.
    register_extension_schema('my_plugin', _MyConfig)

    _config({'my_plugin': {'secret': '__secret_placeholder__'}})


def test_slice_validator_runs_only_when_key_present():
    seen = []
    register_extension_slice_validator('my_plugin', seen.append)

    _config({'other_plugin': {'a': 1}})
    assert seen == []

    _config({'my_plugin': {'a': 1}})
    assert seen == [{'a': 1}]
