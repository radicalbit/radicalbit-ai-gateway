import datetime
import uuid

from sqlalchemy import update

from tests.common import db_mock
from tests.common.db_integration import AsyncDatabaseIntegration

from radicalbit_ai_gateway.db.dao.project_dao import ProjectDAO
from radicalbit_ai_gateway.db.tables.project_table import Project
from radicalbit_ai_gateway.models.config_slot import Slot
from radicalbit_ai_gateway.models.config_status import ConfigStatus
from radicalbit_ai_gateway.models.project_dto import ProjectFilter

UTC = getattr(datetime, 'UTC', datetime.timezone.utc)


def _names(projects) -> list[str]:
    return sorted(p.name for p in projects)


class ProjectDAOTest(AsyncDatabaseIntegration):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project_dao = ProjectDAO(cls.db)

    async def _insert_project(self, name: str, **kwargs) -> Project:
        project = db_mock.get_sample_project(uuid=uuid.uuid4(), name=name, **kwargs)
        inserted = await self.project_dao.insert(project)
        assert (inserted.uuid, inserted.name) == (project.uuid, name)
        return project

    async def _insert_served_project(self, name: str) -> Project:
        """Insert a project plus a SERVED config and wire served_config_uuid."""
        project = await self._insert_project(name)
        config = db_mock.get_sample_project_config(
            project_uuid=project.uuid,
            config_file='served-yaml',
            config_status=ConfigStatus.SERVED,
        )
        await self.insert(config)
        async with self.db.begin_session() as session:
            await session.execute(
                update(Project)
                .where(Project.uuid == project.uuid)
                .values(served_config_uuid=config.uuid)
            )
        return project

    async def _insert_project_with_config(
        self, name: str, *configs: tuple[Slot, ConfigStatus, dict]
    ) -> Project:
        """Insert a project plus one config per (slot, status, overrides)."""
        project = await self._insert_project(name)
        for slot, status, overrides in configs:
            await self.insert(
                db_mock.get_sample_project_config(
                    project_uuid=project.uuid,
                    slot=slot,
                    config_file='some-yaml',
                    config_status=status,
                    **overrides,
                )
            )
        return project

    async def test_lookups_and_filters_exclude_deleted(self):
        # Empty database.
        assert list(await self.project_dao.get_all()) == []
        assert list(await self.project_dao.get_all_filtered(None)) == []
        assert list(await self.project_dao.get_all_with_config()) == []
        assert await self.project_dao.get_by_uuid(uuid.uuid4()) is None
        assert await self.project_dao.soft_delete(uuid.uuid4()) == 0

        await self._insert_served_project('served')
        dev = await self._insert_project('dev')
        await self._insert_project(
            'was-served', first_served_at=datetime.datetime.now(UTC)
        )
        deleted_served = await self._insert_served_project('deleted-served')
        deleted = await self._insert_project('deleted')
        assert await self.project_dao.soft_delete(deleted_served.uuid) == 1
        assert await self.project_dao.soft_delete(deleted.uuid) == 1

        assert (await self.project_dao.get_by_uuid(dev.uuid)).uuid == dev.uuid
        assert await self.project_dao.get_by_uuid(deleted.uuid) is None
        assert await self.project_dao.get_by_uuid(deleted_served.uuid) is None
        live = ['dev', 'served', 'was-served']
        assert _names(await self.project_dao.get_all()) == live
        assert _names(await self.project_dao.get_all_with_config()) == ['served']
        assert {
            f: _names(await self.project_dao.get_all_filtered(f))
            for f in (None, *ProjectFilter)
        } == {
            None: live,
            ProjectFilter.ACTIVE: ['served'],
            ProjectFilter.PROD: ['served'],
            ProjectFilter.DEV: ['dev', 'was-served'],
            ProjectFilter.WITH_USAGE: ['was-served'],
        }

    async def test_get_all_by_config_status(self):
        await self._insert_project('bare')
        await self._insert_project_with_config(
            'draft', (Slot.A, ConfigStatus.DRAFT, {})
        )
        # EMPTY slot: DRAFT with a NULL updated_at (freshly seeded template).
        await self._insert_project_with_config(
            'seeded', (Slot.A, ConfigStatus.DRAFT, {'updated_at': None})
        )
        await self._insert_project_with_config(
            'ready', (Slot.A, ConfigStatus.READY_TO_SERVE, {})
        )
        await self._insert_project_with_config(
            'served', (Slot.A, ConfigStatus.SERVED, {})
        )
        # A project matches on any of its slots.
        await self._insert_project_with_config(
            'two-slots',
            (Slot.A, ConfigStatus.SERVED, {}),
            (Slot.B, ConfigStatus.DRAFT, {}),
        )
        # A soft-deleted slot never matches.
        await self._insert_project_with_config(
            'deleted-slot',
            (Slot.A, ConfigStatus.SERVED, {'deleted_at': datetime.datetime.now(UTC)}),
        )
        deleted = await self._insert_project_with_config(
            'deleted', (Slot.A, ConfigStatus.SERVED, {})
        )
        await self.project_dao.soft_delete(deleted.uuid)

        get = self.project_dao.get_all_by_config_status
        assert {
            'all': _names(await get(None)),
            'draft': _names(await get(ConfigStatus.DRAFT)),
            'draft_non_empty': _names(
                await get(ConfigStatus.DRAFT, exclude_empty=True)
            ),
            'ready': _names(await get(ConfigStatus.READY_TO_SERVE)),
            'served': _names(await get(ConfigStatus.SERVED)),
        } == {
            'all': [
                'bare',
                'deleted-slot',
                'draft',
                'ready',
                'seeded',
                'served',
                'two-slots',
            ],
            'draft': ['draft', 'seeded', 'two-slots'],
            'draft_non_empty': ['draft', 'two-slots'],
            'ready': ['ready'],
            'served': ['served', 'two-slots'],
        }
