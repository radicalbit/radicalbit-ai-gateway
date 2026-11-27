import uuid

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from typing_extensions import override

from tests.common import db_mock
from tests.common.db_integration import AsyncDatabaseIntegration

from radicalbit_ai_gateway.db.dao.project_budget_limit_dao import ProjectBudgetLimitDAO
from radicalbit_ai_gateway.db.dao.project_dao import ProjectDAO
from radicalbit_ai_gateway.db.tables.project_table import Project


class ProjectBudgetLimitDAOTest(AsyncDatabaseIntegration):
    @override
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project_dao = ProjectDAO(cls.db)
        cls.project_budget_limit_dao = ProjectBudgetLimitDAO(cls.db)

    async def _insert_project(self, name='rb-project'):
        project = db_mock.get_sample_project(uuid=uuid.uuid4(), name=name)
        return await self.insert(project)

    async def test_insert(self):
        project = await self._insert_project()
        limit = db_mock.get_sample_project_budget_limit(project_uuid=project.uuid)
        inserted = await self.project_budget_limit_dao.insert(limit)
        assert inserted.uuid == limit.uuid

    async def test_updating_the_max_keeps_the_same_row_and_window(self):
        project = await self._insert_project()
        limit = db_mock.get_sample_project_budget_limit(
            uuid=uuid.uuid4(),
            project_uuid=project.uuid,
            algorithm='ALIGNED_FIXED_WINDOW',
            window_size='1 day',
            max_value=10.0,
        )
        await self.project_budget_limit_dao.insert(limit)

        await self.project_budget_limit_dao.update_max_value(limit.uuid, 25.0)

        res = await self.project_budget_limit_dao.get_by_uuid(limit.uuid)
        assert res is not None
        assert res.max_value == 25.0
        assert res.algorithm == 'ALIGNED_FIXED_WINDOW'
        assert res.window_size == '1 day'
        assert res.updated_at > limit.updated_at

    async def test_get_by_uuid(self):
        project = await self._insert_project()
        limit = db_mock.get_sample_project_budget_limit(
            uuid=uuid.uuid4(), project_uuid=project.uuid
        )
        await self.project_budget_limit_dao.insert(limit)
        res = await self.project_budget_limit_dao.get_by_uuid(limit.uuid)
        assert res is not None
        assert res.uuid == limit.uuid

    async def test_get_by_project_uuid(self):
        project = await self._insert_project()
        limits = [
            db_mock.get_sample_project_budget_limit(
                uuid=uuid.uuid4(), project_uuid=project.uuid, window_size='1 day'
            ),
            db_mock.get_sample_project_budget_limit(
                uuid=uuid.uuid4(), project_uuid=project.uuid, window_size='1 month'
            ),
        ]
        _ = [await self.project_budget_limit_dao.insert(limit) for limit in limits]
        res = await self.project_budget_limit_dao.get_by_project_uuid(project.uuid)
        assert len(res) == 2

    async def test_get_all_by_project_uuids_returns_only_the_requested_projects(self):
        projects = [await self._insert_project(name=name) for name in ('a', 'b', 'c')]
        limits = [
            await self.project_budget_limit_dao.insert(
                db_mock.get_sample_project_budget_limit(
                    uuid=uuid.uuid4(), project_uuid=project.uuid
                )
            )
            for project in projects
        ]

        res = await self.project_budget_limit_dao.get_all_by_project_uuids(
            [projects[0].uuid, projects[1].uuid]
        )

        assert {(r.uuid, r.project_uuid) for r in res} == {
            (limits[0].uuid, projects[0].uuid),
            (limits[1].uuid, projects[1].uuid),
        }

    async def test_get_all_by_project_uuids_empty_input(self):
        assert await self.project_budget_limit_dao.get_all_by_project_uuids([]) == []

    async def test_duplicate_window_raises_integrity_error(self):
        project = await self._insert_project()
        limit_one = db_mock.get_sample_project_budget_limit(
            uuid=uuid.uuid4(), project_uuid=project.uuid
        )
        limit_two = db_mock.get_sample_project_budget_limit(
            uuid=uuid.uuid4(), project_uuid=project.uuid
        )
        await self.project_budget_limit_dao.insert(limit_one)
        with pytest.raises(IntegrityError):
            await self.project_budget_limit_dao.insert(limit_two)

    async def test_insert_many(self):
        project = await self._insert_project()
        limits = [
            db_mock.get_sample_project_budget_limit(
                uuid=uuid.uuid4(), project_uuid=project.uuid, window_size='1 day'
            ),
            db_mock.get_sample_project_budget_limit(
                uuid=uuid.uuid4(), project_uuid=project.uuid, window_size='1 month'
            ),
        ]
        inserted = await self.project_budget_limit_dao.insert_many(limits)
        assert len(inserted) == 2
        assert (
            len(await self.project_budget_limit_dao.get_by_project_uuid(project.uuid))
            == 2
        )

    async def test_insert_many_is_atomic_on_conflict(self):
        project = await self._insert_project()
        limits = [
            db_mock.get_sample_project_budget_limit(
                uuid=uuid.uuid4(), project_uuid=project.uuid, window_size='1 day'
            ),
            # Duplicates the first one: same window.
            db_mock.get_sample_project_budget_limit(
                uuid=uuid.uuid4(), project_uuid=project.uuid, window_size='1 day'
            ),
        ]
        with pytest.raises(IntegrityError):
            await self.project_budget_limit_dao.insert_many(limits)
        # Neither row should have been committed.
        assert (
            await self.project_budget_limit_dao.get_by_project_uuid(project.uuid) == []
        )

    async def test_delete_by_uuid(self):
        project = await self._insert_project()
        limit = db_mock.get_sample_project_budget_limit(
            uuid=uuid.uuid4(), project_uuid=project.uuid
        )
        await self.project_budget_limit_dao.insert(limit)
        rowcount = await self.project_budget_limit_dao.delete_by_uuid(limit.uuid)
        assert rowcount == 1
        assert await self.project_budget_limit_dao.get_by_uuid(limit.uuid) is None

    async def test_delete_by_uuid_nonexistent_returns_zero(self):
        rowcount = await self.project_budget_limit_dao.delete_by_uuid(uuid.uuid4())
        assert rowcount == 0

    async def test_delete_by_project_uuid(self):
        project = await self._insert_project()
        other_project = await self._insert_project(name='rb-project-other')
        limits = [
            db_mock.get_sample_project_budget_limit(
                uuid=uuid.uuid4(), project_uuid=project.uuid, window_size='1 day'
            ),
            db_mock.get_sample_project_budget_limit(
                uuid=uuid.uuid4(), project_uuid=project.uuid, window_size='1 month'
            ),
        ]
        _ = [await self.project_budget_limit_dao.insert(limit) for limit in limits]
        other_limit = db_mock.get_sample_project_budget_limit(
            uuid=uuid.uuid4(), project_uuid=other_project.uuid
        )
        await self.project_budget_limit_dao.insert(other_limit)

        rowcount = await self.project_budget_limit_dao.delete_by_project_uuid(
            project.uuid
        )

        assert rowcount == 2
        assert (
            await self.project_budget_limit_dao.get_by_project_uuid(project.uuid) == []
        )
        # A different project's limits are untouched.
        assert (
            await self.project_budget_limit_dao.get_by_uuid(other_limit.uuid)
            is not None
        )

    async def test_delete_by_project_uuid_nonexistent_returns_zero(self):
        rowcount = await self.project_budget_limit_dao.delete_by_project_uuid(
            uuid.uuid4()
        )
        assert rowcount == 0

    async def test_cascade_delete_on_project_delete(self):
        project = await self._insert_project()
        await self.project_budget_limit_dao.insert(
            db_mock.get_sample_project_budget_limit(
                uuid=uuid.uuid4(), project_uuid=project.uuid
            )
        )
        # ProjectDAO only exposes a soft delete; exercise the FK's
        # `ondelete='CASCADE'` directly with a hard delete of the row.
        async with self.db.begin_session() as session:
            await session.execute(delete(Project).where(Project.uuid == project.uuid))
        assert (
            await self.project_budget_limit_dao.get_by_project_uuid(project.uuid) == []
        )
