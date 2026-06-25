import pytest

from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.utils import config_hooks
from radicalbit_ai_gateway.utils.config_hooks import register_extension_validator


@pytest.fixture(autouse=True)
def _clean_registry():
    config_hooks._extension_validators.clear()
    yield
    config_hooks._extension_validators.clear()


def _route(extension):
    return GatewayRouteConfig(route_name='r', chat_models=['m'], extension=extension)


def test_registered_validator_receives_extension():
    seen = []
    register_extension_validator(seen.append)

    _route({'fake_enabled': True})

    assert seen == [{'fake_enabled': True}]


def test_validator_error_fails_config_validation():
    def validate(extension):
        raise ValueError('bad plugin config')

    register_extension_validator(validate)

    with pytest.raises(Exception) as exc_info:
        _route({'whatever': 1})
    assert 'bad plugin config' in str(exc_info.value)


def test_no_extension_is_a_noop():
    register_extension_validator(lambda extension: 1 / 0)

    _route(None)
