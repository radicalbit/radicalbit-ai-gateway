import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from tests.common import db_mock
from tests.common.db_integration import DatabaseIntegration

from radicalbit_ai_gateway.db.dao.group_dao import GroupDAO
from radicalbit_ai_gateway.db.dao.key_dao import KeyDAO


class KeyDAOTest(DatabaseIntegration):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.key_dao = KeyDAO(cls.db)
        cls.group_dao = GroupDAO(cls.db)

    def test_insert(self):
        key = db_mock.get_sample_key()
        inserted = self.key_dao.insert(key)
        assert inserted.uuid == key.uuid

    def test_get_all(self):
        api_keys = [
            db_mock.get_sample_key(uuid=uuid.uuid4(), name='one'),
            db_mock.get_sample_key(uuid=uuid.uuid4(), name='two'),
            db_mock.get_sample_key(uuid=uuid.uuid4(), name='three'),
        ]
        _ = [self.key_dao.insert(i) for i in api_keys]
        res = self.key_dao.get_all(only_unassigned=False)
        assert len(res) == 3

    def test_delete_key(self):
        api_keys = [
            db_mock.get_sample_key(uuid=uuid.uuid4(), name='one'),
            db_mock.get_sample_key(uuid=uuid.uuid4(), name='two'),
        ]
        _ = [self.key_dao.insert(i) for i in api_keys]
        res = self.key_dao.get_all(False)
        assert len(res) == 2
        deleted_rows = self.key_dao.delete_by_uuid(api_keys[0].uuid)
        assert deleted_rows == 1
        res = self.key_dao.get_all(False)
        assert len(res) == 1

    def test_get_key_by_uuid(self):
        key = db_mock.get_sample_key()
        inserted = self.key_dao.insert(key)
        assert inserted.uuid == key.uuid
        retrieved_key = self.key_dao.get_by_uuid(key.uuid)
        assert retrieved_key.uuid == key.uuid
        assert retrieved_key.name == key.name

    def test_update_key_name(self):
        key = db_mock.get_sample_key()
        inserted = self.key_dao.insert(key)
        assert inserted.uuid == key.uuid
        new_name = 'new-name'
        updated_rows = self.key_dao.update_key_name(key.uuid, new_name)
        assert updated_rows == 1
        retrieved_key = self.key_dao.get_by_uuid(key.uuid)
        assert retrieved_key.uuid == key.uuid
        assert retrieved_key.name == new_name

    def test_get_key_hashed_key(self):
        key = db_mock.get_sample_key()
        inserted = self.key_dao.insert(key)
        assert inserted.uuid == key.uuid
        retrieved_key = self.key_dao.get_key_by_hashed_key(db_mock.HASHED_KEY)
        assert retrieved_key.uuid == key.uuid

    def test_assign_group(self):
        key = db_mock.get_sample_key()
        inserted = self.key_dao.insert(key)
        group = db_mock.get_sample_group_plain()
        inserted_group = self.group_dao.insert(group)
        assert inserted.uuid == key.uuid
        assigned_key = self.key_dao.assign_group(key.uuid, inserted_group.uuid)
        assert assigned_key is not None
        assert assigned_key.group_uuid == inserted_group.uuid

    def test_assign_group_not_exists_error(self):
        key = db_mock.get_sample_key()
        inserted = self.key_dao.insert(key)
        assert inserted.uuid == key.uuid
        pytest.raises(
            IntegrityError,
            self.key_dao.assign_group,
            key_uuid=key.uuid,
            group_uuid=uuid.uuid4(),
        )

    def test_get_all_keys_ungrouped(self):
        group_one, group_two = uuid.uuid4(), uuid.uuid4()
        self.group_dao.insert(db_mock.get_sample_group(uuid=group_one, name='g1'))
        self.group_dao.insert(db_mock.get_sample_group(uuid=group_two, name='g2'))
        api_keys = [
            db_mock.get_sample_key(uuid=uuid.uuid4(), name='one', group_uuid=group_one),
            db_mock.get_sample_key(uuid=uuid.uuid4(), name='two'),
            db_mock.get_sample_key(
                uuid=uuid.uuid4(), name='three', group_uuid=group_two
            ),
        ]
        _ = [self.key_dao.insert(i) for i in api_keys]
        res = self.key_dao.get_all(only_unassigned=True)
        assert len(res) == 1
