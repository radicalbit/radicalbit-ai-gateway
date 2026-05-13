import unittest
from unittest.mock import MagicMock
import uuid

import pytest

from tests.common import db_mock

from radicalbit_ai_gateway.db.dao.group_dao import GroupDAO
from radicalbit_ai_gateway.db.dao.key_dao import KeyDAO
from radicalbit_ai_gateway.models.auth_dto import (
    GroupFullOut,
    GroupOut,
    KeyFullOut,
    KeyGroupIn,
)
from radicalbit_ai_gateway.services.api_key_security import ApiKeySecurity
from radicalbit_ai_gateway.services.key_service import KeyService
from radicalbit_ai_gateway.utils.exceptions import (
    KeyGroupAlreadyExistsError,
    KeyInternalError,
    KeyNotFoundError,
    KeyOperationNotAllowedError,
)


class KeyServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key_dao: KeyDAO = MagicMock(spec_set=KeyDAO)
        cls.group_dao: GroupDAO = MagicMock(spec_set=GroupDAO)
        cls.api_key_security: ApiKeySecurity = MagicMock(spec_set=ApiKeySecurity)
        cls.key_service = KeyService(
            key_dao=cls.key_dao,
            api_key_security=cls.api_key_security,
            group_dao=cls.group_dao,
        )
        cls.mocks = [cls.key_dao, cls.group_dao]

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
        assert res == KeyFullOut.from_key_obscured(key, include_groups=True)

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

    def test_remove_group_from_key_ok(self):
        key_uuid = uuid.uuid4()
        group_uuid = uuid.uuid4()
        key = db_mock.get_sample_key(uuid=key_uuid, group_uuid=group_uuid)
        group = db_mock.get_sample_group(uuid=group_uuid)
        key.group = group
        self.key_dao.get_by_uuid = MagicMock(return_value=key)
        self.key_dao.remove_group = MagicMock(return_value=1)
        self.key_service.remove_group_from_key(key_uuid, group_uuid)
        self.key_dao.get_by_uuid.assert_called_once_with(key_uuid)
        self.key_dao.remove_group.assert_called_once_with(key_uuid=key_uuid)

    def test_remove_group_from_keycloak_key_raises(self):
        key_uuid = uuid.uuid4()
        group_uuid = uuid.uuid4()
        key = db_mock.get_sample_key(uuid=key_uuid, group_uuid=group_uuid)
        key.owner = 'keycloak'
        self.key_dao.get_by_uuid = MagicMock(return_value=key)
        self.key_dao.remove_group = MagicMock()
        pytest.raises(
            KeyOperationNotAllowedError,
            self.key_service.remove_group_from_key,
            key_uuid,
            group_uuid,
        )
        self.key_dao.remove_group.assert_not_called()
