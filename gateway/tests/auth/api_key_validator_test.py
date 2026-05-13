import datetime
from unittest.mock import MagicMock
import uuid

import pytest

from radicalbit_ai_gateway.auth.api_key_validator import ApiKeyValidator
from radicalbit_ai_gateway.db.tables.group_table import Group
from radicalbit_ai_gateway.db.tables.key_table import Key
from radicalbit_ai_gateway.models.auth_dto import KeyDetails
from radicalbit_ai_gateway.services.commons.keyed_hash_algorithm import hash_key
from radicalbit_ai_gateway.utils.exceptions import InvalidApiKey, KeyNotFoundError

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
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_validate_token_returns_key_details():
    validator, key_service = _make_validator()
    group = _gw_group('team-a')
    key = _gw_key('alice', group)
    token = 'sk-rb-mytoken'
    key_service.get_key_by_hashed_key = MagicMock(return_value=key)

    result = await validator.validate_token(token)

    assert isinstance(result, KeyDetails)
    assert result.api_key_uuid == str(key.uuid)
    assert result.api_key_name == 'alice'
    assert result.hashed_api_key == hash_key(token)
    assert result.group_uuid == str(group.uuid)
    assert result.group_name == 'team-a'


async def test_validate_token_calls_key_service_with_hashed_token():
    validator, key_service = _make_validator()
    group = _gw_group()
    key = _gw_key('bob', group)
    token = 'sk-rb-secret'
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
    )
    key_service.get_key_by_hashed_key = MagicMock(return_value=key_without_group)

    with pytest.raises(InvalidApiKey) as exc_info:
        await validator.validate_token('sk-rb-orphan')

    assert 'group' in exc_info.value.client_message.lower()
