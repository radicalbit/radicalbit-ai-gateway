import pytest

from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.utils import config_hooks
from radicalbit_ai_gateway.utils.config_hooks import register_extension_validator


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
