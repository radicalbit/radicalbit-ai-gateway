import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest

from tests.common import db_mock

from radicalbit_ai_gateway.db.dao.group_dao import GroupDAO
from radicalbit_ai_gateway.db.dao.group_limit_dao import GroupLimitDAO
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
    CredentialLimitOut,
)
from radicalbit_ai_gateway.services.api_key_security import ApiKeySecurity
from radicalbit_ai_gateway.services.key_service import KeyService
from radicalbit_ai_gateway.utils.exceptions import (
    CredentialLimitAlreadyExistsError,
    CredentialLimitNotFoundError,
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
        cls.group_limit_dao: GroupLimitDAO = MagicMock(spec_set=GroupLimitDAO)
        cls.key_service = KeyService(
            key_dao=cls.key_dao,
            api_key_security=cls.api_key_security,
            group_dao=cls.group_dao,
            key_limit_dao=cls.key_limit_dao,
            group_limit_dao=cls.group_limit_dao,
        )
        cls.mocks = [cls.key_dao, cls.group_dao, cls.key_limit_dao, cls.group_limit_dao]

    def setUp(self):
        self.group_limit_dao.get_by_group_uuid = MagicMock(return_value=[])
        self.key_limit_dao.get_by_key_uuid = MagicMock(return_value=[])

    def test_create_key_ok(self):
        key = db_mock.get_sample_key()
        api_key_sec = db_mock.get_sample_api_key_sec()
        self.key_dao.insert = MagicMock(return_value=key)
        self.api_key_security.generate_key = MagicMock(return_value=api_key_sec)
        key_in = db_mock.get_sample_key_in()
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
        key_in = db_mock.get_sample_key_in()
        self.key_dao.get_by_uuid = MagicMock(return_value=key)
        self.key_dao.update_key_name = MagicMock(return_value=1)
        res = self.key_service.update_key_name(key.uuid, key_in)
        assert self.key_dao.get_by_uuid.call_count == 2
        self.key_dao.update_key_name.assert_called_once_with(key.uuid, key_in.name)
        assert res == KeyFullOut.from_key_obscured(key)

    def test_update_key_name_ko(self):
        key = db_mock.get_sample_key()
        key_in = db_mock.get_sample_key_in()
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
        key_in = db_mock.get_sample_key_in()
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
        assert res.limits == [CredentialLimitOut.from_key_limit(limit)]
        assert res == KeyFullOut.from_key_obscured(key, include_limits=True)

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
        assert res.group == GroupOut.from_group(group)

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

    def test_add_limits_to_keycloak_key_raises(self):
        key_uuid = uuid.uuid4()
        key = db_mock.get_sample_key(uuid=key_uuid)
        key.owner = 'keycloak'
        self.key_dao.get_by_uuid = MagicMock(return_value=key)
        self.key_limit_dao.insert_many = MagicMock()
        pytest.raises(
            KeyOperationNotAllowedError,
            self.key_service.add_limits_to_key,
            key_uuid,
            db_mock.get_sample_credential_limits_in(),
        )
        self.key_limit_dao.insert_many.assert_not_called()

    def test_add_limits_to_key_duplicate_individual_limit_raises(self):
        """A duplicate of an existing *individually-set* limit is still
        rejected — only a group-derived one gets overwritten.
        """
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

    def test_add_limits_to_key_overwrites_a_group_derived_limit(self):
        key_uuid = uuid.uuid4()
        key = db_mock.get_sample_key(uuid=key_uuid)
        existing = db_mock.get_sample_key_limit(
            key_uuid=key_uuid, group_limit_uuid=uuid.uuid4()
        )
        limits_in = db_mock.get_sample_credential_limits_in()
        self.key_dao.get_by_uuid = MagicMock(return_value=key)
        self.key_limit_dao.get_by_key_uuid = MagicMock(return_value=[existing])
        self.key_limit_dao.insert_many = MagicMock()
        self.key_limit_dao.update_many = MagicMock(side_effect=lambda limits: limits)

        self.key_service.add_limits_to_key(key_uuid, limits_in)

        self.key_limit_dao.insert_many.assert_not_called()
        self.key_limit_dao.update_many.assert_called_once_with([existing])
        assert existing.group_limit_uuid is None
        assert existing.max_value == limits_in.limits[0].value

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
            group_limit_dao=MagicMock(spec_set=GroupLimitDAO),
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


class TestPropagateGroupLimits:
    def _make_service(self):
        key_limit_dao = MagicMock(spec_set=KeyLimitDAO)
        service = KeyService(
            key_dao=MagicMock(spec_set=KeyDAO),
            api_key_security=MagicMock(spec_set=ApiKeySecurity),
            group_dao=MagicMock(spec_set=GroupDAO),
            key_limit_dao=key_limit_dao,
            group_limit_dao=MagicMock(spec_set=GroupLimitDAO),
        )
        return service, key_limit_dao

    def test_no_group_limits_or_no_keys_is_a_noop(self):
        service, key_limit_dao = self._make_service()
        key = db_mock.get_sample_key()
        assert service.propagate_group_limits(group_limits=[], keys=[key]) == ([], [])
        group_limit = db_mock.get_sample_group_limit()
        assert service.propagate_group_limits(group_limits=[group_limit], keys=[]) == (
            [],
            [],
        )
        key_limit_dao.get_all_by_key_uuids.assert_not_called()

    def test_propagates_onto_every_member_with_no_existing_limits(self):
        service, key_limit_dao = self._make_service()
        key_a, key_b = (
            db_mock.get_sample_key(uuid=uuid.uuid4()),
            db_mock.get_sample_key(uuid=uuid.uuid4()),
        )
        group_limit = db_mock.get_sample_group_limit()
        key_limit_dao.get_all_by_key_uuids = MagicMock(return_value=[])
        key_limit_dao.insert_many = MagicMock(side_effect=_fake_insert_many)

        applied, overwritten = service.propagate_group_limits(
            group_limits=[group_limit], keys=[key_a, key_b]
        )

        inserted = key_limit_dao.insert_many.call_args[0][0]
        assert {limit.key_uuid for limit in inserted} == {key_a.uuid, key_b.uuid}
        assert all(limit.group_limit_uuid == group_limit.uuid for limit in inserted)
        assert len(applied) == 2
        assert overwritten == []

    def test_overwrites_a_conflicting_individual_limit(self):
        service, key_limit_dao = self._make_service()
        key_uuid = uuid.uuid4()
        key = db_mock.get_sample_key(uuid=key_uuid, name='has-own-limit')
        group_limit = db_mock.get_sample_group_limit(
            category=CredentialLimitCategory.RATE.value,
            algorithm='FIXED_WINDOW',
            window_size='1 minute',
            max_value=42.0,
        )
        existing = db_mock.get_sample_key_limit(
            key_uuid=key_uuid,
            category=CredentialLimitCategory.RATE.value,
            algorithm='FIXED_WINDOW',
            window_size='1 minute',
        )
        key_limit_dao.get_all_by_key_uuids = MagicMock(return_value=[existing])
        key_limit_dao.update_many = MagicMock(side_effect=lambda limits: limits)

        applied, overwritten = service.propagate_group_limits(
            group_limits=[group_limit], keys=[key]
        )

        key_limit_dao.insert_many.assert_not_called()
        key_limit_dao.update_many.assert_called_once_with([existing])
        assert existing.max_value == 42.0
        assert existing.group_limit_uuid == group_limit.uuid
        assert len(applied) == 1
        assert len(overwritten) == 1
        assert overwritten[0].key_uuid == key_uuid
        assert overwritten[0].key_name == 'has-own-limit'

    def test_different_window_on_same_category_is_not_overwritten(self):
        service, key_limit_dao = self._make_service()
        key_uuid = uuid.uuid4()
        key = db_mock.get_sample_key(uuid=key_uuid)
        group_limit = db_mock.get_sample_group_limit(
            category=CredentialLimitCategory.RATE.value, window_size='1 hour'
        )
        existing = db_mock.get_sample_key_limit(
            key_uuid=key_uuid,
            category=CredentialLimitCategory.RATE.value,
            window_size='1 minute',
        )
        key_limit_dao.get_all_by_key_uuids = MagicMock(return_value=[existing])
        key_limit_dao.insert_many = MagicMock(side_effect=_fake_insert_many)

        applied, overwritten = service.propagate_group_limits(
            group_limits=[group_limit], keys=[key]
        )

        assert len(applied) == 1
        assert overwritten == []


class TestClearPropagatedLimitCounters:
    def _make_service(self):
        key_limit_dao = MagicMock(spec_set=KeyLimitDAO)
        service = KeyService(
            key_dao=MagicMock(spec_set=KeyDAO),
            api_key_security=MagicMock(spec_set=ApiKeySecurity),
            group_dao=MagicMock(spec_set=GroupDAO),
            key_limit_dao=key_limit_dao,
            group_limit_dao=MagicMock(spec_set=GroupLimitDAO),
        )
        return service, key_limit_dao

    @pytest.mark.asyncio
    async def test_clears_every_propagated_copy(self):
        service, key_limit_dao = self._make_service()
        group_limit_uuid = uuid.uuid4()
        propagated = [
            db_mock.get_sample_key_limit(
                key_uuid=uuid.uuid4(), group_limit_uuid=group_limit_uuid
            ),
            db_mock.get_sample_key_limit(
                key_uuid=uuid.uuid4(), group_limit_uuid=group_limit_uuid
            ),
        ]
        key_limit_dao.get_by_group_limit_uuid = MagicMock(return_value=propagated)

        with patch(
            'radicalbit_ai_gateway.services.key_service.clear_limit_counter',
            new=AsyncMock(),
        ) as mock_clear:
            await service.clear_propagated_limit_counters(group_limit_uuid)

        key_limit_dao.get_by_group_limit_uuid.assert_called_once_with(group_limit_uuid)
        assert mock_clear.await_count == 2

    @pytest.mark.asyncio
    async def test_redis_failure_on_one_does_not_stop_the_others(self):
        service, key_limit_dao = self._make_service()
        group_limit_uuid = uuid.uuid4()
        propagated = [
            db_mock.get_sample_key_limit(
                key_uuid=uuid.uuid4(), group_limit_uuid=group_limit_uuid
            ),
            db_mock.get_sample_key_limit(
                key_uuid=uuid.uuid4(), group_limit_uuid=group_limit_uuid
            ),
        ]
        key_limit_dao.get_by_group_limit_uuid = MagicMock(return_value=propagated)

        with patch(
            'radicalbit_ai_gateway.services.key_service.clear_limit_counter',
            new=AsyncMock(side_effect=ConnectionError('redis unreachable')),
        ) as mock_clear:
            await service.clear_propagated_limit_counters(group_limit_uuid)

        assert mock_clear.await_count == 2


class TestAddGroupToKeyPropagatesLimits:
    def _make_service(self):
        key_dao = MagicMock(spec_set=KeyDAO)
        group_dao = MagicMock(spec_set=GroupDAO)
        key_limit_dao = MagicMock(spec_set=KeyLimitDAO)
        group_limit_dao = MagicMock(spec_set=GroupLimitDAO)
        service = KeyService(
            key_dao=key_dao,
            api_key_security=MagicMock(spec_set=ApiKeySecurity),
            group_dao=group_dao,
            key_limit_dao=key_limit_dao,
            group_limit_dao=group_limit_dao,
        )
        return service, key_dao, group_dao, key_limit_dao, group_limit_dao

    def test_joining_key_inherits_existing_group_limits(self):
        service, key_dao, group_dao, key_limit_dao, group_limit_dao = (
            self._make_service()
        )
        key_uuid, group_uuid = uuid.uuid4(), uuid.uuid4()
        key = db_mock.get_sample_key(uuid=key_uuid)
        group = db_mock.get_sample_group(uuid=group_uuid)
        group_limit = db_mock.get_sample_group_limit(group_uuid=group_uuid)
        key_dao.get_by_uuid = MagicMock(return_value=key)
        group_dao.get_by_uuid = MagicMock(return_value=group)
        key_dao.assign_group = MagicMock(return_value=key)
        group_limit_dao.get_by_group_uuid = MagicMock(return_value=[group_limit])
        key_limit_dao.get_all_by_key_uuids = MagicMock(return_value=[])
        key_limit_dao.insert_many = MagicMock(side_effect=_fake_insert_many)

        service.add_group_to_key(
            key_uuid=key_uuid,
            key_group_in=KeyGroupIn(group=group_uuid),
            include_groups=False,
        )

        group_limit_dao.get_by_group_uuid.assert_called_once_with(group_uuid)
        inserted = key_limit_dao.insert_many.call_args[0][0]
        assert len(inserted) == 1
        assert inserted[0].key_uuid == key_uuid
        assert inserted[0].group_limit_uuid == group_limit.uuid

    def test_joining_key_with_no_group_limits_inserts_nothing(self):
        service, key_dao, group_dao, key_limit_dao, group_limit_dao = (
            self._make_service()
        )
        key_uuid, group_uuid = uuid.uuid4(), uuid.uuid4()
        key = db_mock.get_sample_key(uuid=key_uuid)
        group = db_mock.get_sample_group(uuid=group_uuid)
        key_dao.get_by_uuid = MagicMock(return_value=key)
        group_dao.get_by_uuid = MagicMock(return_value=group)
        key_dao.assign_group = MagicMock(return_value=key)
        group_limit_dao.get_by_group_uuid = MagicMock(return_value=[])

        service.add_group_to_key(
            key_uuid=key_uuid,
            key_group_in=KeyGroupIn(group=group_uuid),
            include_groups=False,
        )

        key_limit_dao.insert_many.assert_not_called()


class TestRemoveGroupFromKey:
    def _make_service(self):
        key_dao = MagicMock(spec_set=KeyDAO)
        key_limit_dao = MagicMock(spec_set=KeyLimitDAO)
        service = KeyService(
            key_dao=key_dao,
            api_key_security=MagicMock(spec_set=ApiKeySecurity),
            group_dao=MagicMock(spec_set=GroupDAO),
            key_limit_dao=key_limit_dao,
            group_limit_dao=MagicMock(spec_set=GroupLimitDAO),
        )
        return service, key_dao, key_limit_dao

    @pytest.mark.asyncio
    async def test_ok(self):
        service, key_dao, key_limit_dao = self._make_service()
        key_uuid = uuid.uuid4()
        group_uuid = uuid.uuid4()
        key = db_mock.get_sample_key(uuid=key_uuid, group_uuid=group_uuid)
        group = db_mock.get_sample_group(uuid=group_uuid)
        key.group = group
        key_dao.get_by_uuid = MagicMock(return_value=key)
        key_dao.remove_group = MagicMock(return_value=1)
        key_limit_dao.delete_group_limits_by_key_uuid = MagicMock(return_value=[])

        await service.remove_group_from_key(key_uuid, group_uuid)

        key_dao.get_by_uuid.assert_called_once_with(key_uuid)
        key_dao.remove_group.assert_called_once_with(key_uuid=key_uuid)
        key_limit_dao.delete_group_limits_by_key_uuid.assert_called_once_with(key_uuid)

    @pytest.mark.asyncio
    async def test_clears_propagated_limit_counters(self):
        service, key_dao, key_limit_dao = self._make_service()
        key_uuid = uuid.uuid4()
        group_uuid = uuid.uuid4()
        key = db_mock.get_sample_key(uuid=key_uuid, group_uuid=group_uuid)
        group = db_mock.get_sample_group(uuid=group_uuid)
        key.group = group
        propagated = db_mock.get_sample_key_limit(
            key_uuid=key_uuid, group_limit_uuid=uuid.uuid4()
        )
        key_dao.get_by_uuid = MagicMock(return_value=key)
        key_dao.remove_group = MagicMock(return_value=1)
        key_limit_dao.delete_group_limits_by_key_uuid = MagicMock(
            return_value=[propagated]
        )
        with patch(
            'radicalbit_ai_gateway.services.key_service.clear_limit_counter',
            new=AsyncMock(),
        ) as mock_clear:
            await service.remove_group_from_key(key_uuid, group_uuid)
        mock_clear.assert_awaited_once_with(
            credential_uuid=str(key_uuid),
            category=propagated.category,
            algorithm=propagated.algorithm,
            window_size=propagated.window_size,
        )

    @pytest.mark.asyncio
    async def test_keycloak_key_raises(self):
        service, key_dao, key_limit_dao = self._make_service()
        key_uuid = uuid.uuid4()
        group_uuid = uuid.uuid4()
        key = db_mock.get_sample_key(uuid=key_uuid, group_uuid=group_uuid)
        key.owner = 'keycloak'
        key_dao.get_by_uuid = MagicMock(return_value=key)
        key_dao.remove_group = MagicMock()
        with pytest.raises(KeyOperationNotAllowedError):
            await service.remove_group_from_key(key_uuid, group_uuid)
        key_dao.remove_group.assert_not_called()
