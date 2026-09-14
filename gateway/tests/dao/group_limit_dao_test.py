import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from tests.common import db_mock
from tests.common.db_integration import DatabaseIntegration

from radicalbit_ai_gateway.db.dao.group_dao import GroupDAO
from radicalbit_ai_gateway.db.dao.group_limit_dao import GroupLimitDAO


class GroupLimitDAOTest(DatabaseIntegration):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.group_dao = GroupDAO(cls.db)
        cls.group_limit_dao = GroupLimitDAO(cls.db)

    def _insert_group(self, name='group'):
        group = db_mock.get_sample_group_plain(uuid=uuid.uuid4(), name=name)
        return self.group_dao.insert(group)

    def test_get_by_uuid(self):
        group = self._insert_group()
        limit = db_mock.get_sample_group_limit(uuid=uuid.uuid4(), group_uuid=group.uuid)
        self.group_limit_dao.insert_many([limit])
        res = self.group_limit_dao.get_by_uuid(limit.uuid)
        assert res.uuid == limit.uuid

    def test_get_by_uuid_missing_returns_none(self):
        assert self.group_limit_dao.get_by_uuid(uuid.uuid4()) is None

    def test_get_by_group_uuid(self):
        group = self._insert_group()
        limits = [
            db_mock.get_sample_group_limit(
                uuid=uuid.uuid4(),
                group_uuid=group.uuid,
                category='budget',
                window_size='1 day',
            ),
            db_mock.get_sample_group_limit(
                uuid=uuid.uuid4(),
                group_uuid=group.uuid,
                category='budget',
                window_size='1 month',
            ),
        ]
        self.group_limit_dao.insert_many(limits)
        res = self.group_limit_dao.get_by_group_uuid(group.uuid)
        assert len(res) == 2

    def test_insert_many(self):
        group = self._insert_group()
        limits = [
            db_mock.get_sample_group_limit(
                uuid=uuid.uuid4(), group_uuid=group.uuid, category='budget'
            ),
            db_mock.get_sample_group_limit(
                uuid=uuid.uuid4(),
                group_uuid=group.uuid,
                category='request_rate',
                window_size='1 hour',
            ),
        ]
        inserted = self.group_limit_dao.insert_many(limits)
        assert len(inserted) == 2
        assert len(self.group_limit_dao.get_by_group_uuid(group.uuid)) == 2

    def test_update_many(self):
        group = self._insert_group()
        [limit] = self.group_limit_dao.insert_many(
            [db_mock.get_sample_group_limit(uuid=uuid.uuid4(), group_uuid=group.uuid)]
        )
        limit.max_value = 42.0
        self.group_limit_dao.update_many([limit])
        res = self.group_limit_dao.get_by_uuid(limit.uuid)
        assert res.max_value == 42.0

    def test_insert_many_is_atomic_on_conflict(self):
        group = self._insert_group()
        limits = [
            db_mock.get_sample_group_limit(
                uuid=uuid.uuid4(), group_uuid=group.uuid, category='request_rate'
            ),
            # Duplicates the first one: same category/algorithm/window.
            db_mock.get_sample_group_limit(
                uuid=uuid.uuid4(), group_uuid=group.uuid, category='request_rate'
            ),
        ]
        pytest.raises(IntegrityError, self.group_limit_dao.insert_many, limits)
        assert self.group_limit_dao.get_by_group_uuid(group.uuid) == []

    def test_cascade_delete_on_group_delete(self):
        group = self._insert_group()
        self.group_limit_dao.insert_many(
            [db_mock.get_sample_group_limit(uuid=uuid.uuid4(), group_uuid=group.uuid)]
        )
        deleted = self.group_dao.delete_by_uuid(group.uuid)
        assert deleted is not None
        assert self.group_limit_dao.get_by_group_uuid(group.uuid) == []

    def test_delete_by_uuid(self):
        group = self._insert_group()
        [limit] = self.group_limit_dao.insert_many(
            [db_mock.get_sample_group_limit(uuid=uuid.uuid4(), group_uuid=group.uuid)]
        )
        deleted_rows = self.group_limit_dao.delete_by_uuid(limit.uuid)
        assert deleted_rows == 1
        assert self.group_limit_dao.get_by_uuid(limit.uuid) is None

    def test_delete_by_uuid_missing_returns_zero(self):
        assert self.group_limit_dao.delete_by_uuid(uuid.uuid4()) == 0
