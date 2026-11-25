import datetime
import uuid

from sqlalchemy import update

from tests.common import db_mock
from tests.common.db_integration import AsyncDatabaseIntegration

from radicalbit_ai_gateway.db.dao.project_config_dao import ProjectConfigDAO
from radicalbit_ai_gateway.db.tables.project_config_table import ProjectConfig
from radicalbit_ai_gateway.db.tables.project_table import Project
from radicalbit_ai_gateway.models.config_slot import Slot
from radicalbit_ai_gateway.models.config_status import ConfigStatus

_UTC = getattr(datetime, 'UTC', datetime.timezone.utc)


class ProjectConfigDAOTest(AsyncDatabaseIntegration):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dao = ProjectConfigDAO(cls.db)

    async def _project(self) -> Project:
        project = db_mock.get_sample_project(
            uuid=uuid.uuid4(), name=f'p-{uuid.uuid4()}'
        )
        return await self.insert(project)

    async def _seed_two(self, project_uuid):
        now = datetime.datetime.now(tz=_UTC)
        a = await self.insert(
            ProjectConfig(
                project_uuid=project_uuid,
                slot=Slot.A.value,
                config_file='# a',
                config_status=ConfigStatus.DRAFT.value,
                created_at=now,
                updated_at=None,
            )
        )
        b = await self.insert(
            ProjectConfig(
                project_uuid=project_uuid,
                slot=Slot.B.value,
                config_file='# b',
                config_status=ConfigStatus.DRAFT.value,
                created_at=now,
                updated_at=None,
            )
        )
        return a.uuid, b.uuid

    async def test_seed_and_list_ordered(self):
        p = await self._project()
        await self._seed_two(p.uuid)
        configs = await self.dao.list_by_project(p.uuid)
        assert [c.slot for c in configs] == ['A', 'B']
        assert await self.dao.get_served_by_project(p.uuid) is None

    async def test_get_by_uuid(self):
        p = await self._project()
        a_id, _ = await self._seed_two(p.uuid)
        assert (await self.dao.get_by_uuid(a_id)).uuid == a_id
        assert await self.dao.get_by_uuid(uuid.uuid4()) is None

    async def test_update_config_file_resets_to_draft(self):
        p = await self._project()
        a_id, _ = await self._seed_two(p.uuid)
        await self.dao.set_status(a_id, ConfigStatus.READY_TO_SERVE)
        assert await self.dao.update_config_file(a_id, 'new') == 1
        updated = await self.dao.get_by_uuid(a_id)
        assert updated.config_file == 'new'
        assert updated.config_status == ConfigStatus.DRAFT.value

    async def test_seeded_configs_have_null_updated_at(self):
        p = await self._project()
        a_id, b_id = await self._seed_two(p.uuid)
        assert (await self.dao.get_by_uuid(a_id)).updated_at is None
        assert (await self.dao.get_by_uuid(b_id)).updated_at is None

    async def test_update_config_file_sets_updated_at(self):
        p = await self._project()
        a_id, _ = await self._seed_two(p.uuid)
        await self.dao.update_config_file(a_id, 'saved')
        assert (await self.dao.get_by_uuid(a_id)).updated_at is not None

    async def test_set_status_keeps_updated_at_null(self):
        p = await self._project()
        a_id, _ = await self._seed_two(p.uuid)
        await self.dao.set_status(a_id, ConfigStatus.READY_TO_SERVE)
        assert (await self.dao.get_by_uuid(a_id)).updated_at is None

    async def test_serve_keeps_config_updated_at_null(self):
        p = await self._project()
        a_id, _ = await self._seed_two(p.uuid)
        await self.dao.serve(a_id)
        assert (await self.dao.get_by_uuid(a_id)).updated_at is None

    async def test_serve_sets_served_ref_and_first_served_at(self):
        p = await self._project()
        a_id, _ = await self._seed_two(p.uuid)
        served = await self.dao.serve(a_id)
        assert served.config_status == ConfigStatus.SERVED.value
        async with self.db.begin_session() as s:
            proj = await s.get(Project, p.uuid)
            assert str(proj.served_config_uuid) == str(a_id)
            assert proj.first_served_at is not None

    async def test_serve_swaps_and_keeps_single_served(self):
        p = await self._project()
        a_id, b_id = await self._seed_two(p.uuid)
        await self.dao.serve(a_id)
        async with self.db.begin_session() as s:
            first_served = (await s.get(Project, p.uuid)).first_served_at
        await self.dao.serve(b_id)
        by = {c.uuid: c.config_status for c in await self.dao.list_by_project(p.uuid)}
        assert by[b_id] == ConfigStatus.SERVED.value
        assert by[a_id] == ConfigStatus.DRAFT.value
        served_rows = [
            c
            for c in await self.dao.list_by_project(p.uuid)
            if c.config_status == ConfigStatus.SERVED.value
        ]
        assert len(served_rows) == 1
        async with self.db.begin_session() as s:
            proj = await s.get(Project, p.uuid)
            assert str(proj.served_config_uuid) == str(b_id)
            assert proj.first_served_at == first_served

    async def test_serve_not_found(self):
        assert await self.dao.serve(uuid.uuid4()) is None

    async def test_unserve_clears_ref(self):
        p = await self._project()
        a_id, _ = await self._seed_two(p.uuid)
        await self.dao.serve(a_id)
        assert await self.dao.unserve(a_id) == 1
        assert await self.dao.get_served_by_project(p.uuid) is None
        async with self.db.begin_session() as s:
            assert (await s.get(Project, p.uuid)).served_config_uuid is None

    async def test_unserve_not_found(self):
        assert await self.dao.unserve(uuid.uuid4()) == 0

    async def test_soft_delete_by_project(self):
        p = await self._project()
        await self._seed_two(p.uuid)
        assert await self.dao.soft_delete_by_project(p.uuid) == 2
        assert list(await self.dao.list_by_project(p.uuid)) == []

    async def _rows_for(self, project_uuid):
        return [
            r
            for r in await self.dao.list_served_with_project_name()
            if r.project_uuid == project_uuid
        ]

    async def test_list_served_with_project_name_returns_the_served_config(self):
        p = await self._project()
        a_id, _ = await self._seed_two(p.uuid)
        await self.dao.serve(a_id)
        rows = await self._rows_for(p.uuid)
        assert [(r.project_uuid, r.project_name, r.config_file) for r in rows] == [
            (p.uuid, p.name, '# a')
        ]

    async def test_list_served_with_project_name_excludes_drafts(self):
        p = await self._project()
        await self._seed_two(p.uuid)
        assert await self._rows_for(p.uuid) == []

    async def test_list_served_with_project_name_excludes_soft_deleted_project(self):
        p = await self._project()
        a_id, _ = await self._seed_two(p.uuid)
        await self.dao.serve(a_id)
        now = datetime.datetime.now(tz=_UTC)
        async with self.db.begin_session() as session:
            await session.execute(
                update(Project).where(Project.uuid == p.uuid).values(deleted_at=now)
            )
        assert await self._rows_for(p.uuid) == []

    async def test_list_served_with_project_name_excludes_soft_deleted_config(self):
        p = await self._project()
        a_id, _ = await self._seed_two(p.uuid)
        await self.dao.serve(a_id)
        await self.dao.soft_delete_by_project(p.uuid)
        assert await self._rows_for(p.uuid) == []
