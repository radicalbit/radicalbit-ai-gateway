from pydantic import ValidationError
import pytest

from tests.common.mocked_gateway_config import get_default_fallback, get_default_gateway


def test_fallback_target_error():
    fallback = get_default_fallback('claude')
    with pytest.raises(ValidationError) as exc:
        _ = get_default_gateway(fallback_one=fallback)

    msg = exc.value.errors()[0]['msg']
    assert 'Route rb-gateway:' in msg
    assert f'Target model {fallback.target}' in msg
    assert 'must be present in the chat models' in msg


def test_fallbacks_error():
    fallback = get_default_fallback(fallback_two='claude')
    with pytest.raises(ValidationError) as exc:
        _ = get_default_gateway(fallback_two=fallback)

    msg = exc.value.errors()[0]['msg']
    assert 'Route rb-gateway:' in msg
    assert f'All fallback models for target {fallback.target}' in msg
    assert 'must be present in the chat models' in msg
