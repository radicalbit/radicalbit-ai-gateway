import datetime
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

from freezegun import freeze_time
import pytest
from sqlalchemy.exc import IntegrityError

from tests.common import db_mock

from radicalbit_ai_gateway.db.dao.group_dao import GroupDAO
from radicalbit_ai_gateway.db.dao.key_dao import KeyDAO
from radicalbit_ai_gateway.db.dao.key_limit_dao import KeyLimitDAO
from radicalbit_ai_gateway.models.auth_dto import (
    GroupFullOut,
    GroupOut,
    KeyFullOut,
    KeyGroupIn,
)
from radicalbit_ai_gateway.models.credential_limiting import (
    CredentialLimitCategory,
    CredentialLimitIn,
    CredentialLimitOut,
    CredentialLimitsIn,
    CredentialLimitValueIn,
)
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.models.group_limiting import GroupLimitOutcome, GroupLimitsIn
from radicalbit_ai_gateway.models.limiting import RateLimiting
from radicalbit_ai_gateway.services.api_key_security import ApiKeySecurity
from radicalbit_ai_gateway.services.key_service import KeyService
from radicalbit_ai_gateway.utils.exceptions import (
    CredentialLimitAlreadyExistsError,
    CredentialLimitNotFoundError,
    CredentialLimitValueError,
    KeyGroupAlreadyExistsError,
    KeyInternalError,
    KeyNotFoundError,
    KeyOperationNotAllowedError,
)


def _fake_insert_many(limits):
    """Mimics KeyLimitDAO.insert_many: a real DB flush assigns each row's
    default uuid, which a bare pass-through mock wouldn't.
    """
    for limit in limits:
        limit.uuid = uuid.uuid4()
    return limits


class KeyServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key_dao: KeyDAO = MagicMock(spec_set=KeyDAO)
        cls.group_dao: GroupDAO = MagicMock(spec_set=GroupDAO)
        cls.api_key_security: ApiKeySecurity = MagicMock(spec_set=ApiKeySecurity)
        cls.key_limit_dao: KeyLimitDAO = MagicMock(spec_set=KeyLimitDAO)
        cls.key_service = KeyService(
            key_dao=cls.key_dao,
            api_key_security=cls.api_key_security,
            group_dao=cls.group_dao,
            key_limit_dao=cls.key_limit_dao,
        )
        cls.mocks = [cls.key_dao, cls.group_dao, cls.key_limit_dao]

    def setUp(self):
        self.key_limit_dao.get_by_key_uuid = MagicMock(return_value=[])

    def test_create_key_ok(self):
        key = db_mock.get_sample_key()
        api_key_sec = db_mock.get_sample_api_key_sec()
        self.key_dao.insert = MagicMock(return_value=key)
        self.api_key_security.generate_key = MagicMock(return_value=api_key_sec)
        key_in = db_mock.get_sample_key_create_in()
        res = self.key_service.create_key(key_in)
        self.key_dao.insert.assert_called_once()
        assert res == KeyFullOut.from_key(key=key, plain_api_key=api_key_sec.plain_key)

    def test_get_all(self):
        group_one, group_two = uuid.uuid4(), uuid.uuid4()
        api_keys = [
            db_mock.get_sample_key(uuid=uuid.uuid4(), name='one', group_uuid=group_one),
            db_mock.get_sample_key(uuid=uuid.uuid4(), name='two'),
            db_mock.get_sample_key(
                uuid=uuid.uuid4(), name='three', group_uuid=group_two
            ),
        ]
        self.key_dao.get_all = MagicMock(return_value=api_keys)
        res = self.key_service.get_all(include_groups=False, only_unassigned=False)
        self.key_dao.get_all.assert_called_once()
        assert len(res) == 3

    def test_get_all_only_unassigned(self):
        api_keys = [
            db_mock.get_sample_key(uuid=uuid.uuid4(), name='one'),
            db_mock.get_sample_key(uuid=uuid.uuid4(), name='two'),
            db_mock.get_sample_key(uuid=uuid.uuid4(), name='three'),
        ]
        self.key_dao.get_all = MagicMock(return_value=api_keys)
        res = self.key_service.get_all(include_groups=False, only_unassigned=True)
        self.key_dao.get_all.assert_called_once()
        assert len(res) == 3

    def test_delete_key(self):
        key = db_mock.get_sample_key()
        self.key_dao.delete_by_uuid = MagicMock(return_value=1)
        self.key_dao.get_by_uuid = MagicMock(return_value=key)
        res = self.key_service.delete_key(key.uuid, include_groups=False)
        self.key_dao.get_by_uuid.assert_called_once_with(key.uuid)
        self.key_dao.delete_by_uuid.assert_called_once_with(key.uuid)
        assert res == KeyFullOut.from_key_obscured(key, include_groups=False)

    def test_delete_keycloak_key_raises(self):
        key = db_mock.get_sample_key()
        key.owner = 'keycloak'
        self.key_dao.get_by_uuid = MagicMock(return_value=key)
        self.key_dao.delete_by_uuid = MagicMock()
        pytest.raises(
            KeyOperationNotAllowedError,
            self.key_service.delete_key,
            key.uuid,
        )
        self.key_dao.delete_by_uuid.assert_not_called()

    def test_delete_key_ko(self):
        key = db_mock.get_sample_key()
        self.key_dao.delete_by_uuid = MagicMock(return_value=0)
        self.key_dao.get_by_uuid = MagicMock(return_value=key)
        pytest.raises(
            KeyInternalError,
            self.key_service.delete_key,
            key.uuid,
        )
        self.key_dao.get_by_uuid.assert_called_once_with(key.uuid)
        self.key_dao.delete_by_uuid.assert_called_once_with(key.uuid)

    def test_delete_missing_key(self):
        key = db_mock.get_sample_key()
        self.key_dao.get_by_uuid = MagicMock(return_value=None)
        pytest.raises(
            KeyNotFoundError,
            self.key_service.delete_key,
            key.uuid,
        )

    def test_get_key_by_uuid(self):
        key = db_mock.get_sample_key()
        self.key_dao.get_by_uuid = MagicMock(return_value=key)
        res = self.key_service.get_key_by_uuid(key.uuid, False)
        self.key_dao.get_by_uuid.assert_called_once_with(key.uuid)
        assert res == KeyFullOut.from_key_obscured(key)

    def test_get_missing_key_by_uuid(self):
        key = db_mock.get_sample_key()
        self.key_dao.get_by_uuid = MagicMock(return_value=None)
        pytest.raises(
            KeyNotFoundError,
            self.key_service.get_key_by_uuid,
            key.uuid,
            False,
        )

    def test_update_key_name(self):
        group_uuid = uuid.uuid4()
        key = db_mock.get_sample_key(group_uuid=group_uuid)
        group = db_mock.get_sample_group(uuid=group_uuid)
        key.group = group
        key_in = db_mock.get_sample_key_update_in()
        self.key_dao.get_by_uuid = MagicMock(return_value=key)
        self.key_dao.update_key_name = MagicMock(return_value=1)
        res = self.key_service.update_key_name(key.uuid, key_in)
        assert self.key_dao.get_by_uuid.call_count == 2
        self.key_dao.update_key_name.assert_called_once_with(key.uuid, key_in.name)
        assert res == KeyFullOut.from_key_obscured(key)

    def test_update_key_name_ko(self):
        key = db_mock.get_sample_key()
        key_in = db_mock.get_sample_key_update_in()
        self.key_dao.get_by_uuid = MagicMock(return_value=key)
        self.key_dao.update_key_name = MagicMock(return_value=0)
        pytest.raises(
            KeyInternalError,
            self.key_service.update_key_name,
            key.uuid,
            key_in,
        )
        self.key_dao.get_by_uuid.assert_called_once()
        self.key_dao.update_key_name.assert_called_once_with(key.uuid, key_in.name)

    def test_update_missing_key(self):
        key = db_mock.get_sample_key()
        key_in = db_mock.get_sample_key_update_in()
        self.key_dao.get_by_uuid = MagicMock(return_value=None)
        pytest.raises(
            KeyNotFoundError,
            self.key_service.update_key_name,
            key.uuid,
            key_in,
        )

    def test_add_group_to_key_success_with_groups(self):
        key_uuid = uuid.uuid4()
        group_uuid = uuid.uuid4()
        group = db_mock.get_sample_group(uuid=group_uuid)
        key = db_mock.get_sample_key(uuid=key_uuid)
        self.group_dao.get_by_uuid = MagicMock(return_value=group)
        self.key_dao.get_by_uuid = MagicMock(return_value=key)
        key.group = group
        self.key_dao.assign_group = MagicMock(return_value=key)
        key_groups_in = KeyGroupIn(group=group.uuid)
        result = self.key_service.add_group_to_key(
            key_uuid=key_uuid, key_group_in=key_groups_in, include_groups=True
        )
        self.key_dao.get_by_uuid.assert_called_once_with(key_uuid)
        assert result.uuid == key_uuid
        assert result.name == 'rb-key'
        assert result.group == GroupOut.from_group(group)

    def test_add_group_to_key_success_without_groups(self):
        key_uuid = uuid.uuid4()
        group = db_mock.get_sample_group()
        key = db_mock.get_sample_key(uuid=key_uuid)
        self.group_dao.get_by_uuid = MagicMock(return_value=group)
        self.key_dao.get_by_uuid = MagicMock(return_value=key)
        key.group = group
        self.key_dao.assign_group = MagicMock(return_value=key)
        key_groups_in = KeyGroupIn(group=group.uuid)
        result = self.key_service.add_group_to_key(
            key_uuid=key_uuid, key_group_in=key_groups_in, include_groups=False
        )
        self.key_dao.get_by_uuid.assert_called_once_with(key_uuid)
        assert result.uuid == key_uuid
        assert result.name == 'rb-key'
        assert result.group is None

    def test_add_group_to_key_already_exists(self):
        key_uuid, group_uuid = (uuid.uuid4(), uuid.uuid4())
        key = db_mock.get_sample_key(uuid=key_uuid, group_uuid=group_uuid)
        self.key_dao.insert(key)
        key_group_in = KeyGroupIn(group=group_uuid)
        pytest.raises(
            KeyGroupAlreadyExistsError,
            self.key_service.add_group_to_key,
            key_uuid=key_uuid,
            key_group_in=key_group_in,
            include_groups=False,
        )

    def test_add_group_to_key_owner_mismatch_raises(self):
        key_uuid = uuid.uuid4()
        group_uuid = uuid.uuid4()
        gateway_key = db_mock.get_sample_key(uuid=key_uuid)  # owner='gateway'
        keycloak_group = db_mock.get_sample_group(uuid=group_uuid)
        keycloak_group.owner = 'keycloak'
        self.key_dao.get_by_uuid = MagicMock(return_value=gateway_key)
        self.group_dao.get_by_uuid = MagicMock(return_value=keycloak_group)
        key_group_in = KeyGroupIn(group=group_uuid)
        pytest.raises(
            KeyOperationNotAllowedError,
            self.key_service.add_group_to_key,
            key_uuid=key_uuid,
            key_group_in=key_group_in,
            include_groups=False,
        )
        self.key_dao.assign_group.assert_not_called()

    def test_add_group_to_keycloak_key_raises(self):
        key_uuid = uuid.uuid4()
        group_uuid = uuid.uuid4()
        keycloak_key = db_mock.get_sample_key(uuid=key_uuid)
        keycloak_key.owner = 'keycloak'
        keycloak_group = db_mock.get_sample_group(uuid=group_uuid)
        keycloak_group.owner = 'keycloak'
        self.key_dao.get_by_uuid = MagicMock(return_value=keycloak_key)
        self.group_dao.get_by_uuid = MagicMock(return_value=keycloak_group)
        self.key_dao.assign_group = MagicMock()
        key_group_in = KeyGroupIn(group=group_uuid)
        pytest.raises(
            KeyOperationNotAllowedError,
            self.key_service.add_group_to_key,
            key_uuid=key_uuid,
            key_group_in=key_group_in,
            include_groups=False,
        )
        self.key_dao.assign_group.assert_not_called()

    def test_add_group_to_key_keycloak_key_to_gateway_group_raises(self):
        key_uuid = uuid.uuid4()
        group_uuid = uuid.uuid4()
        keycloak_key = db_mock.get_sample_key(uuid=key_uuid)
        keycloak_key.owner = 'keycloak'
        gateway_group = db_mock.get_sample_group(uuid=group_uuid)  # owner='gateway'
        self.key_dao.get_by_uuid = MagicMock(return_value=keycloak_key)
        self.group_dao.get_by_uuid = MagicMock(return_value=gateway_group)
        key_group_in = KeyGroupIn(group=group_uuid)
        pytest.raises(
            KeyOperationNotAllowedError,
            self.key_service.add_group_to_key,
            key_uuid=key_uuid,
            key_group_in=key_group_in,
            include_groups=False,
        )
        self.key_dao.assign_group.assert_not_called()

    def test_get_key_by_hashed_key(self):
        key = db_mock.get_sample_key_with_group()
        self.key_dao.get_key_by_hashed_key = MagicMock(return_value=key)
        res = self.key_service.get_key_by_hashed_key(db_mock.HASHED_KEY)
        self.key_dao.get_key_by_hashed_key.assert_called_once_with(
            hashed_api_key=db_mock.HASHED_KEY
        )
        assert res == KeyFullOut.from_key_obscured(
            key, include_groups=True, include_limits=True
        )

    def test_get_associable_groups_unassigned_key(self):
        key = db_mock.get_sample_key()
        groups = [
            db_mock.get_sample_group_plain(uuid=uuid.uuid4(), name='g1'),
            db_mock.get_sample_group_plain(uuid=uuid.uuid4(), name='g2'),
        ]
        self.key_dao.get_by_uuid = MagicMock(return_value=key)
        self.group_dao.get_all_by_owner = MagicMock(return_value=groups)
        res = self.key_service.get_associable_groups(key.uuid, False, False)
        self.key_dao.get_by_uuid.assert_called_once_with(key.uuid)
        self.group_dao.get_all_by_owner.assert_called_once_with(owner='gateway')
        assert len(res) == 2
        assert all(isinstance(g, GroupFullOut) for g in res)

    def test_get_associable_groups_assigned_key_returns_empty(self):
        key = db_mock.get_sample_key(group_uuid=uuid.uuid4())
        get_all_by_owner_mock = MagicMock()
        self.key_dao.get_by_uuid = MagicMock(return_value=key)
        self.group_dao.get_all_by_owner = get_all_by_owner_mock
        res = self.key_service.get_associable_groups(key.uuid, False, False)
        get_all_by_owner_mock.assert_not_called()
        assert res == []

    def test_get_associable_groups_keycloak_key_returns_empty(self):
        key = db_mock.get_sample_key()
        key.owner = 'keycloak'
        get_all_by_owner_mock = MagicMock()
        self.key_dao.get_by_uuid = MagicMock(return_value=key)
        self.group_dao.get_all_by_owner = get_all_by_owner_mock
        res = self.key_service.get_associable_groups(key.uuid, False, False)
        get_all_by_owner_mock.assert_not_called()
        assert res == []

    @freeze_time('2026-11-11 00:00:00')
    def test_get_associable_groups_expired_key_returns_empty(self):
        key = db_mock.get_sample_key(expires_on=datetime.date(2026, 11, 10))
        get_all_by_owner_mock = MagicMock()
        self.key_dao.get_by_uuid = MagicMock(return_value=key)
        self.group_dao.get_all_by_owner = get_all_by_owner_mock
        res = self.key_service.get_associable_groups(key.uuid, False, False)
        get_all_by_owner_mock.assert_not_called()
        assert res == []

    @freeze_time('2026-11-11 00:00:00')
    def test_get_associable_keys_leaves_out_expired_keys(self):
        group = db_mock.get_sample_group_plain(uuid=uuid.uuid4(), name='g1')
        expired = db_mock.get_sample_key(
            uuid=uuid.uuid4(), name='expired', expires_on=datetime.date(2026, 11, 10)
        )
        expiring = db_mock.get_sample_key(
            uuid=uuid.uuid4(), name='expiring', expires_on=datetime.date(2026, 11, 11)
        )
        never = db_mock.get_sample_key(uuid=uuid.uuid4(), name='never')
        self.group_dao.get_by_uuid = MagicMock(return_value=group)
        self.key_dao.get_all = MagicMock(return_value=[expired, expiring, never])
        res = self.key_service.get_associable_keys(group.uuid)
        assert [k.name for k in res] == ['expiring', 'never']

    def test_get_associable_groups_key_not_found(self):
        self.key_dao.get_by_uuid = MagicMock(return_value=None)
        pytest.raises(
            KeyNotFoundError,
            self.key_service.get_associable_groups,
            uuid.uuid4(),
            False,
            False,
        )

    def test_add_limits_to_key_ok(self):
        key_uuid = uuid.uuid4()
        key = db_mock.get_sample_key(uuid=key_uuid)
        limit = db_mock.get_sample_key_limit(key_uuid=key_uuid)
        key.limits = [limit]
        limits_in = db_mock.get_sample_credential_limits_in()
        self.key_dao.get_by_uuid = MagicMock(return_value=key)
        self.key_limit_dao.insert_many = MagicMock(return_value=[limit])
        res = self.key_service.add_limits_to_key(key_uuid, limits_in)
        self.key_limit_dao.insert_many.assert_called_once()
        assert res.key.limits == [CredentialLimitOut.from_key_limit(limit)]
        assert res.key == KeyFullOut.from_key_obscured(
            key, include_limits=True
        ).model_copy(update={'limit_warnings': []})

    def test_add_limits_to_key_with_groups(self):
        key_uuid = uuid.uuid4()
        group = db_mock.get_sample_group()
        key = db_mock.get_sample_key(uuid=key_uuid)
        key.group = group
        key.limits = []
        limits_in = db_mock.get_sample_credential_limits_in()
        self.key_dao.get_by_uuid = MagicMock(return_value=key)
        self.key_limit_dao.insert_many = MagicMock(return_value=[])
        res = self.key_service.add_limits_to_key(
            key_uuid, limits_in, include_groups=True
        )
        assert res.key.group == GroupOut.from_group(group)

    def test_add_limits_to_key_multiple_categories(self):
        key_uuid = uuid.uuid4()
        key = db_mock.get_sample_key(uuid=key_uuid)
        limits_in = db_mock.get_sample_credential_limits_in(
            limits=[
                db_mock.get_sample_credential_limit_in(
                    category=CredentialLimitCategory.RATE, window_size='1 hour'
                ),
                db_mock.get_sample_credential_limit_in(
                    category=CredentialLimitCategory.BUDGET, window_size='1 day'
                ),
            ]
        )
        self.key_dao.get_by_uuid = MagicMock(return_value=key)
        self.key_limit_dao.insert_many = MagicMock(return_value=[])
        self.key_service.add_limits_to_key(key_uuid, limits_in)
        inserted = self.key_limit_dao.insert_many.call_args[0][0]
        assert len(inserted) == 2
        assert {limit.category for limit in inserted} == {'request_rate', 'budget'}

    def test_add_limits_to_key_not_found(self):
        self.key_dao.get_by_uuid = MagicMock(return_value=None)
        self.key_limit_dao.insert_many = MagicMock()
        pytest.raises(
            KeyNotFoundError,
            self.key_service.add_limits_to_key,
            uuid.uuid4(),
            db_mock.get_sample_credential_limits_in(),
        )
        self.key_limit_dao.insert_many.assert_not_called()

    def test_add_limits_to_keycloak_key_ok(self):
        key_uuid = uuid.uuid4()
        key = db_mock.get_sample_key(uuid=key_uuid)
        key.owner = 'keycloak'
        limit = db_mock.get_sample_key_limit(key_uuid=key_uuid)
        key.limits = [limit]
        self.key_dao.get_by_uuid = MagicMock(return_value=key)
        self.key_limit_dao.insert_many = MagicMock(return_value=[limit])
        res = self.key_service.add_limits_to_key(
            key_uuid, db_mock.get_sample_credential_limits_in()
        )
        self.key_limit_dao.insert_many.assert_called_once()
        assert res.key == KeyFullOut.from_key_obscured(
            key, include_limits=True
        ).model_copy(update={'limit_warnings': []})

    def test_add_limits_to_key_any_owner_ok(self):
        key_uuid = uuid.uuid4()
        key = db_mock.get_sample_key(uuid=key_uuid)
        key.owner = 'some-other-idp'
        limit = db_mock.get_sample_key_limit(key_uuid=key_uuid)
        key.limits = [limit]
        self.key_dao.get_by_uuid = MagicMock(return_value=key)
        self.key_limit_dao.insert_many = MagicMock(return_value=[limit])
        res = self.key_service.add_limits_to_key(
            key_uuid, db_mock.get_sample_credential_limits_in()
        )
        self.key_limit_dao.insert_many.assert_called_once()
        assert res.key == KeyFullOut.from_key_obscured(
            key, include_limits=True
        ).model_copy(update={'limit_warnings': []})

    def test_add_limits_to_key_duplicate_individual_limit_raises(self):
        key_uuid = uuid.uuid4()
        key = db_mock.get_sample_key(uuid=key_uuid, name='my-credential')
        existing = db_mock.get_sample_key_limit(key_uuid=key_uuid)
        self.key_dao.get_by_uuid = MagicMock(return_value=key)
        self.key_limit_dao.get_by_key_uuid = MagicMock(return_value=[existing])
        self.key_limit_dao.insert_many = MagicMock()
        with pytest.raises(CredentialLimitAlreadyExistsError) as exc_info:
            self.key_service.add_limits_to_key(
                key_uuid, db_mock.get_sample_credential_limits_in()
            )
        # The message should reference the credential by name, not by UUID,
        # so it's actually readable to whoever hits this error.
        assert 'my-credential' in str(exc_info.value)
        assert str(key_uuid) not in str(exc_info.value)
        self.key_limit_dao.insert_many.assert_not_called()

    def test_add_limits_to_key_duplicate_written_in_another_unit_raises(self):
        key_uuid = uuid.uuid4()
        key = db_mock.get_sample_key(uuid=key_uuid, name='my-credential')
        existing = db_mock.get_sample_key_limit(key_uuid=key_uuid, window_size='1 day')
        self.key_dao.get_by_uuid = MagicMock(return_value=key)
        self.key_limit_dao.get_by_key_uuid = MagicMock(return_value=[existing])
        self.key_limit_dao.insert_many = MagicMock()
        limits_in = CredentialLimitsIn(
            limits=[
                CredentialLimitIn(
                    category=CredentialLimitCategory.BUDGET,
                    window_size='24 hours',
                    value=10,
                )
            ]
        )
        with pytest.raises(CredentialLimitAlreadyExistsError):
            self.key_service.add_limits_to_key(key_uuid, limits_in)
        self.key_limit_dao.insert_many.assert_not_called()

    def test_get_limits_for_key_ok(self):
        key_uuid = uuid.uuid4()
        key = db_mock.get_sample_key(uuid=key_uuid)
        limits = [db_mock.get_sample_key_limit(key_uuid=key_uuid)]
        self.key_dao.get_by_uuid = MagicMock(return_value=key)
        self.key_limit_dao.get_by_key_uuid = MagicMock(return_value=limits)
        res = self.key_service.get_limits_for_key(key_uuid)
        self.key_limit_dao.get_by_key_uuid.assert_called_once_with(key_uuid)
        assert res == [CredentialLimitOut.from_key_limit(limits[0])]

    def test_get_limits_for_key_not_found(self):
        self.key_dao.get_by_uuid = MagicMock(return_value=None)
        pytest.raises(
            KeyNotFoundError,
            self.key_service.get_limits_for_key,
            uuid.uuid4(),
        )


class TestDeleteLimitFromKey:
    def _make_service(self):
        key_dao = MagicMock(spec_set=KeyDAO)
        key_limit_dao = MagicMock(spec_set=KeyLimitDAO)
        service = KeyService(
            key_dao=key_dao,
            api_key_security=MagicMock(spec_set=ApiKeySecurity),
            group_dao=MagicMock(spec_set=GroupDAO),
            key_limit_dao=key_limit_dao,
        )
        return service, key_dao, key_limit_dao

    @pytest.mark.asyncio
    async def test_ok(self):
        service, key_dao, key_limit_dao = self._make_service()
        key_uuid = uuid.uuid4()
        limit_uuid = uuid.uuid4()
        key = db_mock.get_sample_key(uuid=key_uuid)
        limit = db_mock.get_sample_key_limit(uuid=limit_uuid, key_uuid=key_uuid)
        key_dao.get_by_uuid = MagicMock(return_value=key)
        key_limit_dao.get_by_uuid = MagicMock(return_value=limit)
        key_limit_dao.delete_by_uuid = MagicMock(return_value=1)

        with patch(
            'radicalbit_ai_gateway.services.key_service.clear_limit_counter',
            new=AsyncMock(),
        ) as mock_clear:
            res = await service.delete_limit_from_key(key_uuid, limit_uuid)

        key_limit_dao.delete_by_uuid.assert_called_once_with(limit_uuid)
        mock_clear.assert_awaited_once_with(
            credential_uuid=str(key_uuid),
            category=limit.category,
            algorithm=limit.algorithm,
            window_size=limit.window_size,
        )
        assert res == CredentialLimitOut.from_key_limit(limit)

    @pytest.mark.asyncio
    async def test_key_not_found(self):
        service, key_dao, key_limit_dao = self._make_service()
        key_dao.get_by_uuid = MagicMock(return_value=None)

        with pytest.raises(KeyNotFoundError):
            await service.delete_limit_from_key(uuid.uuid4(), uuid.uuid4())
        key_limit_dao.delete_by_uuid.assert_not_called()

    @pytest.mark.asyncio
    async def test_limit_not_found(self):
        service, key_dao, key_limit_dao = self._make_service()
        key_uuid = uuid.uuid4()
        key_dao.get_by_uuid = MagicMock(
            return_value=db_mock.get_sample_key(uuid=key_uuid)
        )
        key_limit_dao.get_by_uuid = MagicMock(return_value=None)

        with pytest.raises(CredentialLimitNotFoundError):
            await service.delete_limit_from_key(key_uuid, uuid.uuid4())
        key_limit_dao.delete_by_uuid.assert_not_called()

    @pytest.mark.asyncio
    async def test_limit_belongs_to_a_different_key(self):
        service, key_dao, key_limit_dao = self._make_service()
        key_uuid = uuid.uuid4()
        limit_uuid = uuid.uuid4()
        key_dao.get_by_uuid = MagicMock(
            return_value=db_mock.get_sample_key(uuid=key_uuid)
        )
        key_limit_dao.get_by_uuid = MagicMock(
            return_value=db_mock.get_sample_key_limit(
                uuid=limit_uuid, key_uuid=uuid.uuid4()
            )
        )

        with pytest.raises(CredentialLimitNotFoundError):
            await service.delete_limit_from_key(key_uuid, limit_uuid)
        key_limit_dao.delete_by_uuid.assert_not_called()

    @pytest.mark.asyncio
    async def test_redis_clear_failure_does_not_fail_the_request(self):
        """A Redis-side error clearing the counter must not undo the delete."""
        service, key_dao, key_limit_dao = self._make_service()
        key_uuid = uuid.uuid4()
        limit_uuid = uuid.uuid4()
        key = db_mock.get_sample_key(uuid=key_uuid)
        limit = db_mock.get_sample_key_limit(uuid=limit_uuid, key_uuid=key_uuid)
        key_dao.get_by_uuid = MagicMock(return_value=key)
        key_limit_dao.get_by_uuid = MagicMock(return_value=limit)
        key_limit_dao.delete_by_uuid = MagicMock(return_value=1)

        with patch(
            'radicalbit_ai_gateway.services.key_service.clear_limit_counter',
            new=AsyncMock(side_effect=ConnectionError('redis unreachable')),
        ):
            res = await service.delete_limit_from_key(key_uuid, limit_uuid)

        key_limit_dao.delete_by_uuid.assert_called_once_with(limit_uuid)
        assert res == CredentialLimitOut.from_key_limit(limit)


class TestUpdateLimitValue:
    def _make_service(self):
        key_dao = MagicMock(spec_set=KeyDAO)
        key_limit_dao = MagicMock(spec_set=KeyLimitDAO)
        service = KeyService(
            key_dao=key_dao,
            api_key_security=MagicMock(spec_set=ApiKeySecurity),
            group_dao=MagicMock(spec_set=GroupDAO),
            key_limit_dao=key_limit_dao,
        )
        return service, key_dao, key_limit_dao

    def _stub(self, key_dao, key_limit_dao, *, key=None, limit=None):
        key_dao.get_by_uuid = MagicMock(return_value=key)
        key_limit_dao.get_by_uuid = MagicMock(return_value=limit)
        key_limit_dao.save_many = MagicMock()

    def test_saves_the_new_max_on_the_same_row_and_returns_the_previous_one(self):
        service, key_dao, key_limit_dao = self._make_service()
        key = db_mock.get_sample_key(uuid=uuid.uuid4())
        limit = db_mock.get_sample_key_limit(
            uuid=uuid.uuid4(), key_uuid=key.uuid, max_value=10.0
        )
        self._stub(key_dao, key_limit_dao, key=key, limit=limit)

        res = service.update_limit_value(
            key.uuid, limit.uuid, CredentialLimitValueIn(value=25.0)
        )

        _, to_update = key_limit_dao.save_many.call_args.args
        assert [(row.uuid, row.max_value) for row in to_update] == [(limit.uuid, 25.0)]
        assert res.uuid == limit.uuid
        assert res.value == 25.0
        assert res.previous_value == 10.0
        assert res.window_size == limit.window_size

    def test_key_not_found(self):
        service, key_dao, key_limit_dao = self._make_service()
        self._stub(key_dao, key_limit_dao)

        with pytest.raises(KeyNotFoundError):
            service.update_limit_value(
                uuid.uuid4(), uuid.uuid4(), CredentialLimitValueIn(value=5)
            )
        key_limit_dao.save_many.assert_not_called()

    def test_limit_of_another_key_is_not_found(self):
        service, key_dao, key_limit_dao = self._make_service()
        key = db_mock.get_sample_key(uuid=uuid.uuid4())
        limit = db_mock.get_sample_key_limit(uuid=uuid.uuid4(), key_uuid=uuid.uuid4())
        self._stub(key_dao, key_limit_dao, key=key, limit=limit)

        with pytest.raises(CredentialLimitNotFoundError):
            service.update_limit_value(
                key.uuid, limit.uuid, CredentialLimitValueIn(value=5)
            )
        key_limit_dao.save_many.assert_not_called()

    @freeze_time('2026-11-11 00:00:00')
    def test_expired_key_is_refused(self):
        service, key_dao, key_limit_dao = self._make_service()
        key = db_mock.get_sample_key(
            uuid=uuid.uuid4(), expires_on=datetime.date(2026, 11, 10)
        )
        limit = db_mock.get_sample_key_limit(uuid=uuid.uuid4(), key_uuid=key.uuid)
        self._stub(key_dao, key_limit_dao, key=key, limit=limit)

        with pytest.raises(KeyOperationNotAllowedError):
            service.update_limit_value(
                key.uuid, limit.uuid, CredentialLimitValueIn(value=5)
            )
        key_limit_dao.save_many.assert_not_called()

    def test_a_request_limit_must_stay_a_whole_number(self):
        service, key_dao, key_limit_dao = self._make_service()
        key = db_mock.get_sample_key(uuid=uuid.uuid4())
        limit = db_mock.get_sample_key_limit(
            uuid=uuid.uuid4(),
            key_uuid=key.uuid,
            category=CredentialLimitCategory.RATE.value,
            window_size='1 minute',
        )
        self._stub(key_dao, key_limit_dao, key=key, limit=limit)

        with pytest.raises(CredentialLimitValueError):
            service.update_limit_value(
                key.uuid, limit.uuid, CredentialLimitValueIn(value=2.5)
            )
        key_limit_dao.save_many.assert_not_called()


def _make_limits_service():
    key_dao = MagicMock(spec_set=KeyDAO)
    key_limit_dao = MagicMock(spec_set=KeyLimitDAO)
    service = KeyService(
        key_dao=key_dao,
        api_key_security=MagicMock(spec_set=ApiKeySecurity),
        group_dao=MagicMock(spec_set=GroupDAO),
        key_limit_dao=key_limit_dao,
    )
    return service, key_dao, key_limit_dao


def _group_limits_in(limits=None, skip=None) -> GroupLimitsIn:
    return GroupLimitsIn.model_validate(
        {
            'limits': limits
            or [
                {
                    'category': 'request_rate',
                    'algorithm': 'FIXED_WINDOW',
                    'windowSize': '1 minute',
                    'value': 42,
                }
            ],
            'skip': skip or [],
        }
    )


class TestApplyLimitsToKeys:
    def test_adds_onto_every_member_with_no_existing_limits(self):
        service, _, key_limit_dao = _make_limits_service()
        key_a = db_mock.get_sample_key(uuid=uuid.uuid4(), name='a')
        key_b = db_mock.get_sample_key(uuid=uuid.uuid4(), name='b')
        key_limit_dao.get_all_by_key_uuids = MagicMock(return_value=[])

        members = service.apply_limits_to_keys([key_a, key_b], _group_limits_in())

        key_limit_dao.get_all_by_key_uuids.assert_called_once_with(
            [key_a.uuid, key_b.uuid]
        )
        to_insert, to_update = key_limit_dao.save_many.call_args.args
        assert {limit.key_uuid for limit in to_insert} == {key_a.uuid, key_b.uuid}
        assert all(limit.window_size == '1 minute' for limit in to_insert)
        assert to_update == []
        assert [m.key_name for m in members] == ['a', 'b']
        assert all(
            m.limits[0].outcome == GroupLimitOutcome.ADDED
            and m.limits[0].previous_value is None
            and m.limits[0].new_value == 42
            for m in members
        )

    def test_overwrites_the_max_of_a_conflict_not_listed_in_skip(self):
        service, _, key_limit_dao = _make_limits_service()
        key = db_mock.get_sample_key(uuid=uuid.uuid4())
        existing = db_mock.get_sample_key_limit(
            uuid=uuid.uuid4(),
            key_uuid=key.uuid,
            category=CredentialLimitCategory.RATE.value,
            window_size='1 minute',
            max_value=10,
        )
        key_limit_dao.get_all_by_key_uuids = MagicMock(return_value=[existing])

        [member] = service.apply_limits_to_keys([key], _group_limits_in())

        key_limit_dao.save_many.assert_called_once_with([], [existing])
        # Same row, so the counter, keyed by the signature, is kept
        assert existing.max_value == 42
        [result] = member.limits
        assert result.outcome == GroupLimitOutcome.OVERWRITTEN
        assert result.previous_value == 10
        assert result.new_value == 42

    def test_the_same_window_in_another_unit_is_a_conflict(self):
        service, _, key_limit_dao = _make_limits_service()
        key = db_mock.get_sample_key(uuid=uuid.uuid4())
        existing = db_mock.get_sample_key_limit(
            uuid=uuid.uuid4(),
            key_uuid=key.uuid,
            category=CredentialLimitCategory.RATE.value,
            window_size='1 minute',
        )
        key_limit_dao.get_all_by_key_uuids = MagicMock(return_value=[existing])
        limits = [
            {
                'category': 'request_rate',
                'algorithm': 'FIXED_WINDOW',
                'windowSize': '60 seconds',
                'value': 42,
            }
        ]

        [member] = service.apply_limits_to_keys([key], _group_limits_in(limits))

        key_limit_dao.save_many.assert_called_once_with([], [existing])
        assert member.limits[0].outcome == GroupLimitOutcome.OVERWRITTEN

    def test_leaves_a_conflict_listed_in_skip_as_it_is(self):
        service, _, key_limit_dao = _make_limits_service()
        key = db_mock.get_sample_key(uuid=uuid.uuid4())
        existing = db_mock.get_sample_key_limit(
            uuid=uuid.uuid4(),
            key_uuid=key.uuid,
            category=CredentialLimitCategory.RATE.value,
            window_size='1 minute',
            max_value=10,
        )
        key_limit_dao.get_all_by_key_uuids = MagicMock(return_value=[existing])
        skip = [
            {
                'keyUuid': str(key.uuid),
                'category': 'request_rate',
                'algorithm': 'FIXED_WINDOW',
                # Another unit for the same window
                'windowSize': '60 seconds',
            }
        ]

        [member] = service.apply_limits_to_keys([key], _group_limits_in(skip=skip))

        key_limit_dao.save_many.assert_called_once_with([], [])
        assert existing.max_value == 10
        [result] = member.limits
        assert result.outcome == GroupLimitOutcome.SKIPPED
        assert result.previous_value == 10
        assert result.new_value == 42

    def test_a_skip_on_another_member_does_not_skip_this_one(self):
        service, _, key_limit_dao = _make_limits_service()
        key = db_mock.get_sample_key(uuid=uuid.uuid4())
        existing = db_mock.get_sample_key_limit(
            uuid=uuid.uuid4(),
            key_uuid=key.uuid,
            category=CredentialLimitCategory.RATE.value,
            window_size='1 minute',
        )
        key_limit_dao.get_all_by_key_uuids = MagicMock(return_value=[existing])
        skip = [
            {
                'keyUuid': str(uuid.uuid4()),
                'category': 'request_rate',
                'algorithm': 'FIXED_WINDOW',
                'windowSize': '1 minute',
            }
        ]

        [member] = service.apply_limits_to_keys([key], _group_limits_in(skip=skip))

        assert member.limits[0].outcome == GroupLimitOutcome.OVERWRITTEN

    def test_another_window_or_window_type_is_not_a_conflict(self):
        service, _, key_limit_dao = _make_limits_service()
        key = db_mock.get_sample_key(uuid=uuid.uuid4())
        key_limit_dao.get_all_by_key_uuids = MagicMock(
            return_value=[
                db_mock.get_sample_key_limit(
                    key_uuid=key.uuid,
                    category=CredentialLimitCategory.RATE.value,
                    window_size='1 hour',
                ),
                db_mock.get_sample_key_limit(
                    key_uuid=key.uuid,
                    category=CredentialLimitCategory.RATE.value,
                    algorithm='ALIGNED_FIXED_WINDOW',
                    window_size='1 minute',
                ),
            ]
        )

        [member] = service.apply_limits_to_keys([key], _group_limits_in())

        assert member.limits[0].outcome == GroupLimitOutcome.ADDED

    def test_expired_members_are_written_and_marked_expired(self):
        service, _, key_limit_dao = _make_limits_service()
        key = db_mock.get_sample_key(uuid=uuid.uuid4())
        key.expires_on = datetime.date(2020, 1, 1)
        key_limit_dao.get_all_by_key_uuids = MagicMock(return_value=[])

        [member] = service.apply_limits_to_keys([key], _group_limits_in())

        [inserted], _ = key_limit_dao.save_many.call_args.args
        assert inserted.key_uuid == key.uuid
        assert member.expired is True

    def test_a_limit_added_meanwhile_is_a_conflict_error(self):
        service, _, key_limit_dao = _make_limits_service()
        key = db_mock.get_sample_key(uuid=uuid.uuid4())
        key_limit_dao.get_all_by_key_uuids = MagicMock(return_value=[])
        key_limit_dao.save_many = MagicMock(
            side_effect=IntegrityError(
                'INSERT',
                {},
                Exception('uq_key_limit_KEY_UUID_CATEGORY_ALGORITHM_WINDOW_SIZE'),
            )
        )

        with pytest.raises(CredentialLimitAlreadyExistsError):
            service.apply_limits_to_keys([key], _group_limits_in())


class TestGroupMembershipLeavesLimitsAlone:
    def test_joining_a_group_writes_no_limit(self):
        service, key_dao, key_limit_dao = _make_limits_service()
        key = db_mock.get_sample_key(uuid=uuid.uuid4())
        group = db_mock.get_sample_group(uuid=uuid.uuid4())
        service.group_dao.get_by_uuid = MagicMock(return_value=group)
        key_dao.get_by_uuid = MagicMock(return_value=key)
        key_dao.assign_group = MagicMock(return_value=key)

        service.add_group_to_key(
            key_uuid=key.uuid,
            key_group_in=KeyGroupIn(group=group.uuid),
            include_groups=False,
        )

        assert key_limit_dao.method_calls == []

    @pytest.mark.asyncio
    async def test_leaving_a_group_keeps_limits_and_counters(self):
        service, key_dao, key_limit_dao = _make_limits_service()
        group_uuid = uuid.uuid4()
        key = db_mock.get_sample_key(uuid=uuid.uuid4(), group_uuid=group_uuid)
        key.group = db_mock.get_sample_group(uuid=group_uuid)
        key_dao.get_by_uuid = MagicMock(return_value=key)
        key_dao.remove_group = MagicMock(return_value=1)

        with patch(
            'radicalbit_ai_gateway.services.key_service.clear_limit_counter',
            new=AsyncMock(),
        ) as mock_clear:
            await service.remove_group_from_key(key.uuid, group_uuid)

        key_dao.remove_group.assert_called_once_with(key_uuid=key.uuid)
        assert key_limit_dao.method_calls == []
        mock_clear.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_keycloak_key_cannot_leave_its_group(self):
        service, key_dao, _ = _make_limits_service()
        group_uuid = uuid.uuid4()
        key = db_mock.get_sample_key(uuid=uuid.uuid4(), group_uuid=group_uuid)
        key.owner = 'keycloak'
        key_dao.get_by_uuid = MagicMock(return_value=key)
        key_dao.remove_group = MagicMock()
        with pytest.raises(KeyOperationNotAllowedError):
            await service.remove_group_from_key(key.uuid, group_uuid)
        key_dao.remove_group.assert_not_called()


class TestRouteLimitWarnings:
    """The credential's group reaches `proj/chat`, capped at 50 requests a minute."""

    ROUTES = {
        'proj/chat': GatewayRouteConfig(
            route_name='chat',
            rate_limiting=RateLimiting(max_requests=50, window_size='1 minute'),
        ),
        # Served, but not reached by the group
        'proj/other': GatewayRouteConfig(
            route_name='other',
            rate_limiting=RateLimiting(max_requests=1, window_size='1 minute'),
        ),
    }

    @staticmethod
    def _service_with_group_routes(route_names):
        service, key_dao, key_limit_dao = _make_limits_service()
        service.group_dao.get_route_names_by_group_uuid = MagicMock(
            return_value=route_names
        )
        return service, key_dao, key_limit_dao

    @staticmethod
    def _rate_limits_in(value) -> CredentialLimitsIn:
        return CredentialLimitsIn(
            limits=[
                CredentialLimitIn(
                    category=CredentialLimitCategory.RATE,
                    window_size='1 minute',
                    value=value,
                )
            ]
        )

    def test_adding_a_looser_limit_saves_it_and_warns(self):
        service, key_dao, key_limit_dao = self._service_with_group_routes(
            ['proj/chat', 'proj/gone']
        )
        group_uuid = uuid.uuid4()
        key = db_mock.get_sample_key(uuid=uuid.uuid4(), group_uuid=group_uuid)
        key_dao.get_by_uuid = MagicMock(return_value=key)
        key_limit_dao.get_by_key_uuid = MagicMock(return_value=[])
        limits_in = self._rate_limits_in(100)
        # The credential read back after the insert holds the new limit
        key.limits = _fake_insert_many(limits_in.to_key_limits(key.uuid))

        res = service.add_limits_to_key(key.uuid, limits_in, route_configs=self.ROUTES)

        key_limit_dao.insert_many.assert_called_once()
        service.group_dao.get_route_names_by_group_uuid.assert_called_once_with(
            group_uuid
        )
        assert res.key.uuid == key.uuid
        assert [
            (w.route_name, w.credential_value, w.route_value) for w in res.warnings
        ] == [('proj/chat', 100, 50)]

    def test_adding_a_stricter_limit_does_not_warn(self):
        service, key_dao, key_limit_dao = self._service_with_group_routes(['proj/chat'])
        key = db_mock.get_sample_key(uuid=uuid.uuid4(), group_uuid=uuid.uuid4())
        key_dao.get_by_uuid = MagicMock(return_value=key)
        key_limit_dao.get_by_key_uuid = MagicMock(return_value=[])

        res = service.add_limits_to_key(
            key.uuid, self._rate_limits_in(50), route_configs=self.ROUTES
        )

        assert res.warnings == []

    def test_a_credential_without_a_group_reaches_no_route(self):
        service, key_dao, key_limit_dao = self._service_with_group_routes(['proj/chat'])
        key = db_mock.get_sample_key(uuid=uuid.uuid4(), group_uuid=None)
        key_dao.get_by_uuid = MagicMock(return_value=key)
        key_limit_dao.get_by_key_uuid = MagicMock(return_value=[])
        limits_in = self._rate_limits_in(100)
        # The credential read back after the insert holds the new limit
        key.limits = _fake_insert_many(limits_in.to_key_limits(key.uuid))

        res = service.add_limits_to_key(key.uuid, limits_in, route_configs=self.ROUTES)

        assert res.warnings == []
        service.group_dao.get_route_names_by_group_uuid.assert_not_called()

    def test_raising_a_max_above_a_route_warns(self):
        service, key_dao, key_limit_dao = self._service_with_group_routes(['proj/chat'])
        key = db_mock.get_sample_key(uuid=uuid.uuid4(), group_uuid=uuid.uuid4())
        limit = db_mock.get_sample_key_limit(
            uuid=uuid.uuid4(),
            key_uuid=key.uuid,
            category=CredentialLimitCategory.RATE.value,
            window_size='1 minute',
            max_value=40,
        )
        key_dao.get_by_uuid = MagicMock(return_value=key)
        key_limit_dao.get_by_uuid = MagicMock(return_value=limit)

        res = service.update_limit_value(
            key.uuid,
            limit.uuid,
            CredentialLimitValueIn(value=80),
            route_configs=self.ROUTES,
        )

        assert res.value == 80
        assert [(w.route_name, w.credential_value) for w in res.warnings] == [
            ('proj/chat', 80)
        ]

    def test_bulk_assignment_warns_each_member_on_what_it_received(self):
        service, _, key_limit_dao = self._service_with_group_routes(['proj/chat'])
        group_uuid = uuid.uuid4()
        key_a = db_mock.get_sample_key(
            uuid=uuid.uuid4(), name='a', group_uuid=group_uuid
        )
        key_b = db_mock.get_sample_key(
            uuid=uuid.uuid4(), name='b', group_uuid=group_uuid
        )
        # b already has the limit and skips it: it keeps its own max, no warning
        key_limit_dao.get_all_by_key_uuids = MagicMock(
            return_value=[
                db_mock.get_sample_key_limit(
                    uuid=uuid.uuid4(),
                    key_uuid=key_b.uuid,
                    category=CredentialLimitCategory.RATE.value,
                    window_size='1 minute',
                )
            ]
        )
        limits = [
            {
                'category': 'request_rate',
                'algorithm': 'FIXED_WINDOW',
                'windowSize': '1 minute',
                'value': 100,
            }
        ]
        skip = [
            {
                'keyUuid': str(key_b.uuid),
                'category': 'request_rate',
                'algorithm': 'FIXED_WINDOW',
                'windowSize': '1 minute',
            }
        ]

        member_a, member_b = service.apply_limits_to_keys(
            [key_a, key_b],
            _group_limits_in(limits, skip),
            route_configs=self.ROUTES,
        )

        assert [w.route_name for w in member_a.warnings] == ['proj/chat']
        assert member_b.warnings == []
        # One lookup for the group, not one per member
        service.group_dao.get_route_names_by_group_uuid.assert_called_once_with(
            group_uuid
        )


class TestSavedLimitWarnings:
    """Read time: limits saved before a stricter route was served still warn."""

    ROUTES = TestRouteLimitWarnings.ROUTES

    @staticmethod
    def _key_with_rate_limit(value, group_uuid):
        key = db_mock.get_sample_key(uuid=uuid.uuid4(), group_uuid=group_uuid)
        key.limits = [
            db_mock.get_sample_key_limit(
                uuid=uuid.uuid4(),
                key_uuid=key.uuid,
                category=CredentialLimitCategory.RATE.value,
                window_size='1 minute',
                max_value=value,
            )
        ]
        return key

    def test_a_credential_read_with_its_limits_carries_their_warnings(self):
        service, key_dao, _ = _make_limits_service()
        service.group_dao.get_route_names_by_group_uuid = MagicMock(
            return_value=['proj/chat']
        )
        key = self._key_with_rate_limit(100, uuid.uuid4())
        key_dao.get_by_uuid = MagicMock(return_value=key)

        res = service.get_key_by_uuid(
            key.uuid, False, include_limits=True, route_configs=self.ROUTES
        )

        assert [(w.route_name, w.credential_value) for w in res.limit_warnings] == [
            ('proj/chat', 100)
        ]

    def test_without_limits_there_are_no_warnings_to_compute(self):
        service, key_dao, _ = _make_limits_service()
        key = self._key_with_rate_limit(100, uuid.uuid4())
        key_dao.get_by_uuid = MagicMock(return_value=key)

        res = service.get_key_by_uuid(key.uuid, False, route_configs=self.ROUTES)

        assert res.limit_warnings is None
        service.group_dao.get_route_names_by_group_uuid.assert_not_called()

    def test_the_list_looks_up_each_group_once(self):
        service, key_dao, _ = _make_limits_service()
        service.group_dao.get_route_names_by_group_uuid = MagicMock(
            return_value=['proj/chat']
        )
        group_uuid = uuid.uuid4()
        looser = self._key_with_rate_limit(100, group_uuid)
        stricter = self._key_with_rate_limit(10, group_uuid)
        solo = self._key_with_rate_limit(100, None)
        key_dao.get_all = MagicMock(return_value=[looser, stricter, solo])

        res = service.get_all(
            False, False, include_limits=True, route_configs=self.ROUTES
        )

        assert [len(key.limit_warnings) for key in res] == [1, 0, 0]
        service.group_dao.get_route_names_by_group_uuid.assert_called_once_with(
            group_uuid
        )
