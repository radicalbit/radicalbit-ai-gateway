import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from tests.common import db_mock
from tests.common.db_integration import DatabaseIntegration

from radicalbit_ai_gateway.db.dao.key_dao import KeyDAO
from radicalbit_ai_gateway.db.dao.key_limit_dao import KeyLimitDAO


class KeyLimitDAOTest(DatabaseIntegration):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.key_dao = KeyDAO(cls.db)
        cls.key_limit_dao = KeyLimitDAO(cls.db)

    def _insert_key(self, name='rb-key'):
        key = db_mock.get_sample_key(uuid=uuid.uuid4(), name=name)
        return self.key_dao.insert(key)

    def test_insert(self):
        key = self._insert_key()
        limit = db_mock.get_sample_key_limit(key_uuid=key.uuid)
        inserted = self.key_limit_dao.insert(limit)
        assert inserted.uuid == limit.uuid

    def test_get_by_uuid(self):
        key = self._insert_key()
        limit = db_mock.get_sample_key_limit(uuid=uuid.uuid4(), key_uuid=key.uuid)
        self.key_limit_dao.insert(limit)
        res = self.key_limit_dao.get_by_uuid(limit.uuid)
        assert res.uuid == limit.uuid

    def test_get_by_key_uuid(self):
        key = self._insert_key()
        limits = [
            db_mock.get_sample_key_limit(
                uuid=uuid.uuid4(),
                key_uuid=key.uuid,
                category='budget',
                window_size='1 day',
            ),
            db_mock.get_sample_key_limit(
                uuid=uuid.uuid4(),
                key_uuid=key.uuid,
                category='budget',
                window_size='1 month',
            ),
        ]
        _ = [self.key_limit_dao.insert(i) for i in limits]
        res = self.key_limit_dao.get_by_key_uuid(key.uuid)
        assert len(res) == 2

    def test_get_all_by_key_uuids(self):
        key_one = self._insert_key(name='one')
        key_two = self._insert_key(name='two')
        self.key_limit_dao.insert(
            db_mock.get_sample_key_limit(uuid=uuid.uuid4(), key_uuid=key_one.uuid)
        )
        self.key_limit_dao.insert(
            db_mock.get_sample_key_limit(uuid=uuid.uuid4(), key_uuid=key_two.uuid)
        )
        res = self.key_limit_dao.get_all_by_key_uuids([key_one.uuid, key_two.uuid])
        assert len(res) == 2

    def test_get_all_by_key_uuids_empty_input(self):
        assert self.key_limit_dao.get_all_by_key_uuids([]) == []

    def test_duplicate_limit_raises_integrity_error(self):
        key = self._insert_key()
        limit_one = db_mock.get_sample_key_limit(uuid=uuid.uuid4(), key_uuid=key.uuid)
        limit_two = db_mock.get_sample_key_limit(uuid=uuid.uuid4(), key_uuid=key.uuid)
        self.key_limit_dao.insert(limit_one)
        pytest.raises(IntegrityError, self.key_limit_dao.insert, limit_two)

    def test_cascade_delete_on_key_delete(self):
        key = self._insert_key()
        self.key_limit_dao.insert(
            db_mock.get_sample_key_limit(uuid=uuid.uuid4(), key_uuid=key.uuid)
        )
        deleted_rows = self.key_dao.delete_by_uuid(key.uuid)
        assert deleted_rows == 1
        assert self.key_limit_dao.get_by_key_uuid(key.uuid) == []
