import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from tests.common import db_mock
from tests.common.db_integration import DatabaseIntegration

from radicalbit_ai_gateway.db.dao.group_dao import GroupDAO
from radicalbit_ai_gateway.db.dao.group_limit_dao import GroupLimitDAO
from radicalbit_ai_gateway.db.dao.key_dao import KeyDAO
from radicalbit_ai_gateway.db.dao.key_limit_dao import KeyLimitDAO


class KeyLimitDAOTest(DatabaseIntegration):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.key_dao = KeyDAO(cls.db)
        cls.key_limit_dao = KeyLimitDAO(cls.db)
        cls.group_dao = GroupDAO(cls.db)
        cls.group_limit_dao = GroupLimitDAO(cls.db)

    def _insert_key(self, name='rb-key'):
        key = db_mock.get_sample_key(uuid=uuid.uuid4(), name=name)
        return self.key_dao.insert(key)

    def _insert_group_limit(self, name='group'):
        group = self.group_dao.insert(
            db_mock.get_sample_group_plain(uuid=uuid.uuid4(), name=name)
        )
        [limit] = self.group_limit_dao.insert_many(
            [db_mock.get_sample_group_limit(uuid=uuid.uuid4(), group_uuid=group.uuid)]
        )
        return limit

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

    def test_insert_many(self):
        key = self._insert_key()
        limits = [
            db_mock.get_sample_key_limit(
                uuid=uuid.uuid4(), key_uuid=key.uuid, category='budget'
            ),
            db_mock.get_sample_key_limit(
                uuid=uuid.uuid4(),
                key_uuid=key.uuid,
                category='request_rate',
                window_size='1 hour',
            ),
        ]
        inserted = self.key_limit_dao.insert_many(limits)
        assert len(inserted) == 2
        assert len(self.key_limit_dao.get_by_key_uuid(key.uuid)) == 2

    def test_update_many(self):
        group_limit = self._insert_group_limit()
        key = self._insert_key()
        limit = self.key_limit_dao.insert(
            db_mock.get_sample_key_limit(uuid=uuid.uuid4(), key_uuid=key.uuid)
        )
        limit.max_value = 99.0
        limit.group_limit_uuid = group_limit.uuid
        self.key_limit_dao.update_many([limit])
        res = self.key_limit_dao.get_by_uuid(limit.uuid)
        assert res.max_value == 99.0
        assert res.group_limit_uuid == group_limit.uuid

    def test_insert_many_is_atomic_on_conflict(self):
        key = self._insert_key()
        limits = [
            db_mock.get_sample_key_limit(
                uuid=uuid.uuid4(), key_uuid=key.uuid, category='request_rate'
            ),
            # Duplicates the first one: same category/algorithm/window.
            db_mock.get_sample_key_limit(
                uuid=uuid.uuid4(), key_uuid=key.uuid, category='request_rate'
            ),
        ]
        pytest.raises(IntegrityError, self.key_limit_dao.insert_many, limits)
        # Neither row should have been committed.
        assert self.key_limit_dao.get_by_key_uuid(key.uuid) == []

    def test_cascade_delete_on_key_delete(self):
        key = self._insert_key()
        self.key_limit_dao.insert(
            db_mock.get_sample_key_limit(uuid=uuid.uuid4(), key_uuid=key.uuid)
        )
        deleted_rows = self.key_dao.delete_by_uuid(key.uuid)
        assert deleted_rows == 1
        assert self.key_limit_dao.get_by_key_uuid(key.uuid) == []

    def test_delete_by_uuid(self):
        key = self._insert_key()
        limit = self.key_limit_dao.insert(
            db_mock.get_sample_key_limit(uuid=uuid.uuid4(), key_uuid=key.uuid)
        )
        deleted_rows = self.key_limit_dao.delete_by_uuid(limit.uuid)
        assert deleted_rows == 1
        assert self.key_limit_dao.get_by_uuid(limit.uuid) is None

    def test_delete_by_uuid_missing_returns_zero(self):
        assert self.key_limit_dao.delete_by_uuid(uuid.uuid4()) == 0

    def test_get_by_group_limit_uuid(self):
        group_limit = self._insert_group_limit()
        key_one = self._insert_key(name='one')
        key_two = self._insert_key(name='two')
        self.key_limit_dao.insert(
            db_mock.get_sample_key_limit(
                uuid=uuid.uuid4(),
                key_uuid=key_one.uuid,
                group_limit_uuid=group_limit.uuid,
            )
        )
        self.key_limit_dao.insert(
            db_mock.get_sample_key_limit(
                uuid=uuid.uuid4(),
                key_uuid=key_two.uuid,
                group_limit_uuid=group_limit.uuid,
            )
        )
        res = self.key_limit_dao.get_by_group_limit_uuid(group_limit.uuid)
        assert len(res) == 2

    def test_cascade_delete_on_group_limit_delete(self):
        group_limit = self._insert_group_limit()
        key = self._insert_key()
        self.key_limit_dao.insert(
            db_mock.get_sample_key_limit(
                uuid=uuid.uuid4(),
                key_uuid=key.uuid,
                group_limit_uuid=group_limit.uuid,
            )
        )
        self.group_limit_dao.delete_by_uuid(group_limit.uuid)
        assert self.key_limit_dao.get_by_key_uuid(key.uuid) == []

    def test_delete_group_limits_by_key_uuid(self):
        group_limit = self._insert_group_limit()
        key = self._insert_key()
        propagated = self.key_limit_dao.insert(
            db_mock.get_sample_key_limit(
                uuid=uuid.uuid4(),
                key_uuid=key.uuid,
                group_limit_uuid=group_limit.uuid,
            )
        )
        individual = self.key_limit_dao.insert(
            db_mock.get_sample_key_limit(
                uuid=uuid.uuid4(),
                key_uuid=key.uuid,
                category='request_rate',
                window_size='1 hour',
            )
        )
        deleted = self.key_limit_dao.delete_group_limits_by_key_uuid(key.uuid)
        assert {limit.uuid for limit in deleted} == {propagated.uuid}
        remaining = self.key_limit_dao.get_by_key_uuid(key.uuid)
        assert {limit.uuid for limit in remaining} == {individual.uuid}

    def test_delete_group_limits_by_key_uuid_none_propagated(self):
        key = self._insert_key()
        self.key_limit_dao.insert(
            db_mock.get_sample_key_limit(uuid=uuid.uuid4(), key_uuid=key.uuid)
        )
        assert self.key_limit_dao.delete_group_limits_by_key_uuid(key.uuid) == []
