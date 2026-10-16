import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
import uuid

from freezegun import freeze_time
import pytest

from tests.common import db_mock

from radicalbit_ai_gateway.auth.api_key_validator import ApiKeyValidator
from radicalbit_ai_gateway.db.tables.group_table import Group
from radicalbit_ai_gateway.db.tables.key_table import Key
from radicalbit_ai_gateway.models.auth_dto import KeyDetails
from radicalbit_ai_gateway.models.credential_limiting import CredentialLimitOut
from radicalbit_ai_gateway.services.commons.keyed_hash_algorithm import hash_key
from radicalbit_ai_gateway.utils.exceptions import (
    ApiKeyError,
    ExpiredApiKey,
    InvalidApiKey,
    KeyNotFoundError,
)

_UTC = getattr(datetime, 'UTC', datetime.timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_validator():
    key_service = MagicMock()
    return ApiKeyValidator(key_service=key_service), key_service


def _gw_group(name: str = 'team-a') -> Group:
    now = datetime.datetime.now(tz=_UTC)
    return Group(
        uuid=uuid.uuid4(),
        name=name,
        owner='gateway',
        group_metadata='{}',
        created_at=now,
        updated_at=now,
        keys=[],
    )


def _gw_key(name: str, group: Group) -> Key:
    now = datetime.datetime.now(tz=_UTC)
    return Key(
        uuid=uuid.uuid4(),
        name=name,
        owner='gateway',
        key_metadata=None,
        hashed_key=hash_key(f'sk-rb-{name}'),
        obscured_key='sk-rb-***',
        created_at=now,
        updated_at=now,
        group_uuid=group.uuid,
        group=group,
        expires_on=None,
        previous_hashed_key=None,
        grace_ends_at=None,
        last_rotated_at=None,
        # unset .limits on a transient instance can hang (SQLAlchemy lazy-load)
        limits=[],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_validate_token_returns_key_details():
    validator, key_service = _make_validator()
    group = _gw_group('team-a')
    key = _gw_key('alice', group)
    token = 'sk-rb-alice'
    key_service.get_key_by_hashed_key = MagicMock(return_value=key)

    result = await validator.validate_token(token)

    assert isinstance(result, KeyDetails)
    assert result.api_key_uuid == str(key.uuid)
    assert result.api_key_name == 'alice'
    assert result.hashed_api_key == hash_key(token)
    assert result.group_uuid == str(group.uuid)
    assert result.group_name == 'team-a'
    assert result.limits == []


async def test_validate_token_propagates_limits_from_key_record():
    validator, key_service = _make_validator()
    group = _gw_group('team-a')
    limit_out = CredentialLimitOut.from_key_limit(db_mock.get_sample_key_limit())
    key = SimpleNamespace(
        uuid=uuid.uuid4(),
        name='alice',
        hashed_key=hash_key('sk-rb-mytoken'),
        group=group,
        limits=[limit_out],
        expires_on=None,
    )
    key_service.get_key_by_hashed_key = MagicMock(return_value=key)

    result = await validator.validate_token('sk-rb-mytoken')

    assert result.limits == [limit_out]


async def test_validate_token_calls_key_service_with_hashed_token():
    validator, key_service = _make_validator()
    group = _gw_group()
    key = _gw_key('bob', group)
    token = 'sk-rb-bob'
    key_service.get_key_by_hashed_key = MagicMock(return_value=key)

    await validator.validate_token(token)

    key_service.get_key_by_hashed_key.assert_called_once_with(hash_key(token))


async def test_validate_token_raises_invalid_api_key_when_not_found():
    validator, key_service = _make_validator()
    key_service.get_key_by_hashed_key = MagicMock(
        side_effect=KeyNotFoundError('not found')
    )

    with pytest.raises(InvalidApiKey) as exc_info:
        await validator.validate_token('sk-rb-unknown')

    assert 'incorrect' in exc_info.value.client_message.lower()


async def test_validate_token_raises_invalid_api_key_when_key_has_no_group():
    validator, key_service = _make_validator()
    now = datetime.datetime.now(tz=_UTC)
    key_without_group = Key(
        uuid=uuid.uuid4(),
        name='orphan',
        owner='gateway',
        key_metadata=None,
        hashed_key=hash_key('sk-rb-orphan'),
        obscured_key='sk-rb-***',
        created_at=now,
        updated_at=now,
        group_uuid=None,
        group=None,
        expires_on=None,
        previous_hashed_key=None,
        grace_ends_at=None,
        last_rotated_at=None,
    )
    key_service.get_key_by_hashed_key = MagicMock(return_value=key_without_group)

    with pytest.raises(InvalidApiKey) as exc_info:
        await validator.validate_token('sk-rb-orphan')

    assert 'group' in exc_info.value.client_message.lower()


# ---------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------


def _key_expiring_on(expires_on: datetime.date | None) -> Key:
    key = _gw_key('alice', _gw_group('team-a'))
    key.expires_on = expires_on
    return key


@freeze_time('2026-11-11 00:00:00')
async def test_validate_token_rejects_an_expired_key():
    validator, key_service = _make_validator()
    key_service.get_key_by_hashed_key = MagicMock(
        return_value=_key_expiring_on(datetime.date(2026, 11, 10))
    )

    with pytest.raises(ExpiredApiKey) as exc_info:
        await validator.validate_token('sk-rb-alice')

    assert isinstance(exc_info.value, ApiKeyError)
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == 'key_expired_unauthorized'
    assert exc_info.value.client_message == 'API key has expired.'


@freeze_time('2026-11-10 23:59:59')
async def test_validate_token_authenticates_an_expiring_key():
    validator, key_service = _make_validator()
    key = _key_expiring_on(datetime.date(2026, 11, 10))
    key_service.get_key_by_hashed_key = MagicMock(return_value=key)

    result = await validator.validate_token('sk-rb-alice')

    assert result.api_key_uuid == str(key.uuid)


async def test_validate_token_authenticates_a_key_without_expiry_date():
    validator, key_service = _make_validator()
    key = _key_expiring_on(None)
    key_service.get_key_by_hashed_key = MagicMock(return_value=key)

    result = await validator.validate_token('sk-rb-alice')

    assert result.api_key_uuid == str(key.uuid)


# ---------------------------------------------------------------------------
# Rotation (ADR 0008)
# ---------------------------------------------------------------------------

PREVIOUS = 'sk-rb-previous'
CURRENT = 'sk-rb-current'
GRACE_ENDS_AT = datetime.datetime(2026, 11, 5, 12, tzinfo=_UTC)


def _rotated_key(grace_ends_at=GRACE_ENDS_AT, expires_on=None) -> SimpleNamespace:
    # A plain record: the ORM `limits` relationship only takes KeyLimit rows
    return SimpleNamespace(
        uuid=uuid.uuid4(),
        name='alice',
        group=_gw_group('team-a'),
        limits=[CredentialLimitOut.from_key_limit(db_mock.get_sample_key_limit())],
        hashed_key=hash_key(CURRENT),
        previous_hashed_key=hash_key(PREVIOUS) if grace_ends_at else None,
        grace_ends_at=grace_ends_at,
        expires_on=expires_on,
    )


def _validator_over(key: SimpleNamespace):
    """Build a validator whose lookup finds the credential by either stored value."""
    validator, key_service = _make_validator()

    def lookup(hashed):
        if hashed in (key.hashed_key, key.previous_hashed_key):
            return key
        raise KeyNotFoundError('not found')

    key_service.get_key_by_hashed_key = MagicMock(side_effect=lookup)
    return validator


@freeze_time('2026-11-05 11:59:59')
async def test_during_the_grace_period_both_values_are_the_same_credential():
    key = _rotated_key()
    validator = _validator_over(key)

    previous = await validator.validate_token(PREVIOUS)
    current = await validator.validate_token(CURRENT)

    assert previous.api_key_uuid == current.api_key_uuid == str(key.uuid)
    assert previous.group_uuid == current.group_uuid == str(key.group.uuid)
    assert previous.limits == current.limits == key.limits


@pytest.mark.parametrize(
    ('grace_ends_at', 'now'),
    [
        pytest.param(GRACE_ENDS_AT, '2026-11-05 12:00:00', id='at the grace end'),
        pytest.param(GRACE_ENDS_AT, '2026-11-20 00:00:00', id='after the grace end'),
        pytest.param(None, '2026-11-04 12:00:00', id='no grace period, or ended early'),
    ],
)
async def test_the_previous_value_is_a_wrong_credential_once_the_grace_period_is_over(
    grace_ends_at, now
):
    validator = _validator_over(_rotated_key(grace_ends_at=grace_ends_at))
    with freeze_time(now):
        with pytest.raises(InvalidApiKey) as exc_info:
            await validator.validate_token(PREVIOUS)
        assert exc_info.value.code == 'key_invalid_unauthorized'
        assert exc_info.value.client_message == 'Incorrect API key provided.'
        assert (await validator.validate_token(CURRENT)).api_key_name == 'alice'


@freeze_time('2026-11-07 00:00:00')
async def test_after_expiry_a_stale_previous_value_still_looks_wrong_not_expired():
    # The grace period ended before the expiry and its hash was never cleared:
    # "expired" would confirm the old value was once real (ADR 0008)
    key = _rotated_key(expires_on=datetime.date(2026, 11, 6))
    validator = _validator_over(key)

    with pytest.raises(InvalidApiKey) as previous:
        await validator.validate_token(PREVIOUS)
    with pytest.raises(ExpiredApiKey) as current:
        await validator.validate_token(CURRENT)

    assert previous.value.code == 'key_invalid_unauthorized'
    assert current.value.code == 'key_expired_unauthorized'
