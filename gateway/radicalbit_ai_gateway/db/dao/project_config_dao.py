from collections.abc import Sequence
import datetime
from typing import NamedTuple
from uuid import UUID

from sqlalchemy import func, select, update

from radicalbit_ai_gateway.db.database import Database
from radicalbit_ai_gateway.db.tables.project_config_table import ProjectConfig
from radicalbit_ai_gateway.db.tables.project_table import Project
from radicalbit_ai_gateway.models.config_status import ConfigStatus

_UTC = getattr(datetime, 'UTC', datetime.timezone.utc)


class ServedConfigWithProject(NamedTuple):
    """A currently-served configuration paired with its project's identity."""

    config_file: str | None
    project_uuid: UUID
    project_name: str


class ProjectConfigDAO:
    def __init__(self, database: Database):
        self.db = database

    async def get_by_uuid(self, config_uuid: UUID) -> ProjectConfig | None:
        async with self.db.begin_session() as session:
            stmt = select(ProjectConfig).where(
                ProjectConfig.uuid == config_uuid,
                ProjectConfig.deleted_at.is_(None),
            )
            return await session.scalar(stmt)

    async def list_by_project(self, project_uuid: UUID) -> Sequence[ProjectConfig]:
        async with self.db.begin_session() as session:
            stmt = (
                select(ProjectConfig)
                .where(
                    ProjectConfig.project_uuid == project_uuid,
                    ProjectConfig.deleted_at.is_(None),
                )
                .order_by(ProjectConfig.slot)
            )
            return (await session.scalars(stmt)).all()

    async def get_served_by_project(self, project_uuid: UUID) -> ProjectConfig | None:
        async with self.db.begin_session() as session:
            stmt = select(ProjectConfig).where(
                ProjectConfig.project_uuid == project_uuid,
                ProjectConfig.config_status == ConfigStatus.SERVED.value,
                ProjectConfig.deleted_at.is_(None),
            )
            return await session.scalar(stmt)

    async def update_config_file(self, config_uuid: UUID, config_file: str) -> int:
        """Update the YAML content of a config and reset it to DRAFT."""
        now = datetime.datetime.now(tz=_UTC)
        async with self.db.begin_session() as session:
            query = (
                update(ProjectConfig)
                .where(
                    ProjectConfig.uuid == config_uuid,
                    ProjectConfig.deleted_at.is_(None),
                )
                .values(
                    config_file=config_file,
                    config_status=ConfigStatus.DRAFT.value,
                    updated_at=now,
                )
            )
            return (await session.execute(query)).rowcount

    async def set_status(self, config_uuid: UUID, status: ConfigStatus) -> int:
        async with self.db.begin_session() as session:
            query = (
                update(ProjectConfig)
                .where(
                    ProjectConfig.uuid == config_uuid,
                    ProjectConfig.deleted_at.is_(None),
                )
                .values(config_status=status.value)
            )
            return (await session.execute(query)).rowcount

    async def serve(self, config_uuid: UUID) -> ProjectConfig | None:
        """Atomically serve a config: demote any currently SERVED config of the
        same project back to DRAFT, promote this one to SERVED, and update the
        project's served reference and first_served_at.
        """
        now = datetime.datetime.now(tz=_UTC)
        async with self.db.begin_session() as session:
            config = await session.scalar(
                select(ProjectConfig).where(
                    ProjectConfig.uuid == config_uuid,
                    ProjectConfig.deleted_at.is_(None),
                )
            )
            if config is None:
                return None

            # Demote the sibling first so the single-SERVED index is never
            # violated mid-transaction.
            await session.execute(
                update(ProjectConfig)
                .where(
                    ProjectConfig.project_uuid == config.project_uuid,
                    ProjectConfig.uuid != config_uuid,
                    ProjectConfig.config_status == ConfigStatus.SERVED.value,
                    ProjectConfig.deleted_at.is_(None),
                )
                .values(config_status=ConfigStatus.DRAFT.value)
            )
            await session.execute(
                update(ProjectConfig)
                .where(ProjectConfig.uuid == config_uuid)
                .values(config_status=ConfigStatus.SERVED.value)
            )
            await session.execute(
                update(Project)
                .where(Project.uuid == config.project_uuid)
                .values(
                    served_config_uuid=config_uuid,
                    first_served_at=func.coalesce(Project.first_served_at, now),
                    updated_at=now,
                )
            )
            return await session.scalar(
                select(ProjectConfig).where(ProjectConfig.uuid == config_uuid)
            )

    async def unserve(self, config_uuid: UUID) -> int:
        """Unserve a config (back to DRAFT) and clear the project's served
        reference when it points to this config.
        """
        now = datetime.datetime.now(tz=_UTC)
        async with self.db.begin_session() as session:
            config = await session.scalar(
                select(ProjectConfig).where(
                    ProjectConfig.uuid == config_uuid,
                    ProjectConfig.deleted_at.is_(None),
                )
            )
            if config is None:
                return 0
            await session.execute(
                update(ProjectConfig)
                .where(ProjectConfig.uuid == config_uuid)
                .values(config_status=ConfigStatus.DRAFT.value)
            )
            await session.execute(
                update(Project)
                .where(
                    Project.uuid == config.project_uuid,
                    Project.served_config_uuid == config_uuid,
                )
                .values(served_config_uuid=None, updated_at=now)
            )
            return 1

    async def list_served_with_project_name(self) -> Sequence[ServedConfigWithProject]:
        """Every served configuration paired with its project's identity.

        Skips soft-deleted configs and soft-deleted projects. Deletes here are
        soft, so a foreign-key cascade never removes the row on its own.
        """
        async with self.db.begin_session() as session:
            stmt = (
                select(ProjectConfig.config_file, Project.uuid, Project.name)
                .join(Project, Project.uuid == ProjectConfig.project_uuid)
                .where(
                    ProjectConfig.config_status == ConfigStatus.SERVED.value,
                    ProjectConfig.deleted_at.is_(None),
                    Project.deleted_at.is_(None),
                )
            )
            return [
                ServedConfigWithProject(*row)
                for row in (await session.execute(stmt)).all()
            ]

    async def soft_delete_by_project(self, project_uuid: UUID) -> int:
        now = datetime.datetime.now(tz=_UTC)
        async with self.db.begin_session() as session:
            query = (
                update(ProjectConfig)
                .where(
                    ProjectConfig.project_uuid == project_uuid,
                    ProjectConfig.deleted_at.is_(None),
                )
                .values(deleted_at=now)
            )
            return (await session.execute(query)).rowcount
