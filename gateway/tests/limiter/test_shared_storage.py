import pytest

from radicalbit_ai_gateway.limiter.storage.memory import InMemoryStorage
from radicalbit_ai_gateway.limiter.storage.redis import RedisStorage
from radicalbit_ai_gateway.limiter.storage.shared import (
    close_limit_storage,
    get_limit_storage,
)
from radicalbit_ai_gateway.limiting.limits import ADMISSION, RouteLimits, shared_limits
from radicalbit_ai_gateway.models.credential_limiting import (
    CredentialLimitCategory,
    CredentialLimitOut,
)
from radicalbit_ai_gateway.models.limiting import LimitingAlgorithmType
from radicalbit_ai_gateway.models.request_identity import RequestIdentity
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import RequestRateLimitExceeded

_IDENTITY = RequestIdentity(
    request_uuid='req-1',
    route_name='my-route',
    api_key_uuid='cred-1',
    api_key_name='my-cred',
    group_uuid='grp-1',
    group_name='my-group',
)


def _rate_limit_of_one() -> CredentialLimitOut:
    return CredentialLimitOut(
        uuid='00000000-0000-4000-8000-000000000001',
        category=CredentialLimitCategory.RATE,
        algorithm=LimitingAlgorithmType.FIXED_WINDOW,
        window_size='1 minute',
        value=1,
        created_at='2026-01-01 00:00:00',
        updated_at='2026-01-01 00:00:00',
    )


def test_one_storage_per_process():
    assert get_limit_storage() is get_limit_storage()


def test_in_memory_without_a_redis_url():
    assert isinstance(get_limit_storage(), InMemoryStorage)


@pytest.mark.asyncio
async def test_redis_with_a_redis_url(monkeypatch):
    monkeypatch.setattr(
        get_app_config().redis_config, 'redis_url', 'redis://localhost:6379/0'
    )
    storage = get_limit_storage()
    assert isinstance(storage, RedisStorage)
    await close_limit_storage()
    assert get_limit_storage() is not storage


@pytest.mark.asyncio
async def test_in_memory_credential_counters_outlive_the_request():
    """Each request resolves its own credential limits: the counter it fills
    must still be there for the next request.
    """
    first_request = shared_limits.resolve(
        _IDENTITY, RouteLimits(), [_rate_limit_of_one()]
    )
    await first_request.check(ADMISSION)

    second_request = shared_limits.resolve(
        _IDENTITY, RouteLimits(), [_rate_limit_of_one()]
    )
    with pytest.raises(RequestRateLimitExceeded):
        await second_request.check(ADMISSION)
