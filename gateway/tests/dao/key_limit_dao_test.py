import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from tests.common import db_mock
from tests.common.db_integration import AsyncDatabaseIntegration

from radicalbit_ai_gateway.db.dao.key_dao import KeyDAO
from radicalbit_ai_gateway.db.dao.key_limit_dao import KeyLimitDAO


class KeyLimitDAOTest(AsyncDatabaseIntegration):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.key_dao = KeyDAO(cls.db)
        cls.key_limit_dao = KeyLimitDAO(cls.db)

    async def _insert_key(self, name='rb-key'):
        key = db_mock.get_sample_key(uuid=uuid.uuid4(), name=name)
        return await self.key_dao.insert(key)

    async def test_insert(self):
        key = await self._insert_key()
        limit = db_mock.get_sample_key_limit(key_uuid=key.uuid)
        inserted = await self.key_limit_dao.insert(limit)
        assert inserted.uuid == limit.uuid

    async def test_get_by_uuid(self):
        key = await self._insert_key()
        limit = db_mock.get_sample_key_limit(uuid=uuid.uuid4(), key_uuid=key.uuid)
        await self.key_limit_dao.insert(limit)
        res = await self.key_limit_dao.get_by_uuid(limit.uuid)
        assert res.uuid == limit.uuid

    async def test_get_by_key_uuid(self):
        key = await self._insert_key()
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
        _ = [await self.key_limit_dao.insert(i) for i in limits]
        res = await self.key_limit_dao.get_by_key_uuid(key.uuid)
        assert len(res) == 2

    async def test_get_all_by_key_uuids(self):
        key_one = await self._insert_key(name='one')
        key_two = await self._insert_key(name='two')
        await self.key_limit_dao.insert(
            db_mock.get_sample_key_limit(uuid=uuid.uuid4(), key_uuid=key_one.uuid)
        )
        await self.key_limit_dao.insert(
            db_mock.get_sample_key_limit(uuid=uuid.uuid4(), key_uuid=key_two.uuid)
        )
        res = await self.key_limit_dao.get_all_by_key_uuids(
            [key_one.uuid, key_two.uuid]
        )
        assert len(res) == 2

    async def test_get_all_by_key_uuids_empty_input(self):
        assert await self.key_limit_dao.get_all_by_key_uuids([]) == []

    async def test_duplicate_limit_raises_integrity_error(self):
        key = await self._insert_key()
        limit_one = db_mock.get_sample_key_limit(uuid=uuid.uuid4(), key_uuid=key.uuid)
        limit_two = db_mock.get_sample_key_limit(uuid=uuid.uuid4(), key_uuid=key.uuid)
        await self.key_limit_dao.insert(limit_one)
        with pytest.raises(IntegrityError):
            await self.key_limit_dao.insert(limit_two)

    async def test_insert_many(self):
        key = await self._insert_key()
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
        inserted = await self.key_limit_dao.insert_many(limits)
        assert len(inserted) == 2
        assert len(await self.key_limit_dao.get_by_key_uuid(key.uuid)) == 2

    async def test_save_many_inserts_and_updates_the_max(self):
        key = await self._insert_key()
        existing = await self.key_limit_dao.insert(
            db_mock.get_sample_key_limit(uuid=uuid.uuid4(), key_uuid=key.uuid)
        )
        existing.max_value = 99.0
        new = db_mock.get_sample_key_limit(
            uuid=uuid.uuid4(), key_uuid=key.uuid, category='request_rate'
        )
        await self.key_limit_dao.save_many([new], [existing])
        assert (await self.key_limit_dao.get_by_uuid(existing.uuid)).max_value == 99.0
        assert await self.key_limit_dao.get_by_uuid(new.uuid) is not None

    async def test_save_many_is_atomic_on_conflict(self):
        key = await self._insert_key()
        existing = await self.key_limit_dao.insert(
            db_mock.get_sample_key_limit(uuid=uuid.uuid4(), key_uuid=key.uuid)
        )
        existing.max_value = 99.0
        # Same category/algorithm/window as the existing one
        duplicate = db_mock.get_sample_key_limit(uuid=uuid.uuid4(), key_uuid=key.uuid)
        with pytest.raises(IntegrityError):
            await self.key_limit_dao.save_many([duplicate], [existing])
        assert (await self.key_limit_dao.get_by_uuid(existing.uuid)).max_value == 10.0

    async def test_insert_many_is_atomic_on_conflict(self):
        key = await self._insert_key()
        limits = [
            db_mock.get_sample_key_limit(
                uuid=uuid.uuid4(), key_uuid=key.uuid, category='request_rate'
            ),
            # Duplicates the first one: same category/algorithm/window.
            db_mock.get_sample_key_limit(
                uuid=uuid.uuid4(), key_uuid=key.uuid, category='request_rate'
            ),
        ]
        with pytest.raises(IntegrityError):
            await self.key_limit_dao.insert_many(limits)
        # Neither row should have been committed.
        assert await self.key_limit_dao.get_by_key_uuid(key.uuid) == []

    async def test_cascade_delete_on_key_delete(self):
        key = await self._insert_key()
        await self.key_limit_dao.insert(
            db_mock.get_sample_key_limit(uuid=uuid.uuid4(), key_uuid=key.uuid)
        )
        deleted_rows = await self.key_dao.delete_by_uuid(key.uuid)
        assert deleted_rows == 1
        assert await self.key_limit_dao.get_by_key_uuid(key.uuid) == []

    async def test_delete_by_uuid(self):
        key = await self._insert_key()
        limit = await self.key_limit_dao.insert(
            db_mock.get_sample_key_limit(uuid=uuid.uuid4(), key_uuid=key.uuid)
        )
        deleted_rows = await self.key_limit_dao.delete_by_uuid(limit.uuid)
        assert deleted_rows == 1
        assert await self.key_limit_dao.get_by_uuid(limit.uuid) is None

    async def test_delete_by_uuid_missing_returns_zero(self):
        assert await self.key_limit_dao.delete_by_uuid(uuid.uuid4()) == 0
