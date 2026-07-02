from collections.abc import Sequence
import datetime
from uuid import UUID

from sqlalchemy import select, update

from radicalbit_ai_gateway.db.database import Database
from radicalbit_ai_gateway.db.tables.project_config_table import ProjectConfig
from radicalbit_ai_gateway.db.tables.project_table import Project
from radicalbit_ai_gateway.models.config_slot import Slot
from radicalbit_ai_gateway.models.config_status import ConfigStatus
from radicalbit_ai_gateway.models.project_dto import ProjectFilter

_UTC = getattr(datetime, 'UTC', datetime.timezone.utc)


class ProjectDAO:
    def __init__(self, database: Database):
        self.db = database

    def insert(self, project: Project) -> Project:
        with self.db.begin_session() as session:
            session.add(project)
            session.flush()
            return project

    def insert_with_configs(
        self,
        project: Project,
        slots: Sequence[tuple[Slot, str | None, ConfigStatus]],
    ) -> Project:
        """Insert a project and its initial config slots in a single
        transaction, so a project is never left with a partial set of slots
        (the "always 2 slots" invariant holds even on a mid-creation crash).
        """
        now = datetime.datetime.now(tz=_UTC)
        with self.db.begin_session() as session:
            session.add(project)
            session.flush()  # assign project.uuid before linking the configs
            for slot, config_file, status in slots:
                session.add(
                    ProjectConfig(
                        project_uuid=project.uuid,
                        slot=slot.value,
                        config_file=config_file,
                        config_status=status.value,
                        created_at=now,
                        updated_at=None,
                    )
                )
            session.flush()
            return project

    def get_by_uuid(self, project_uuid: UUID) -> Project | None:
        with self.db.begin_session() as session:
            stmt = select(Project).where(
                Project.uuid == project_uuid,
                Project.deleted_at.is_(None),
            )
            return session.scalar(stmt)

    def get_all(self) -> Sequence[Project]:
        with self.db.begin_session() as session:
            stmt = select(Project).where(Project.deleted_at.is_(None))
            return session.scalars(stmt).all()

    def get_all_filtered(
        self, project_filter: ProjectFilter | None = None
    ) -> Sequence[Project]:
        with self.db.begin_session() as session:
            stmt = select(Project).where(Project.deleted_at.is_(None))
            if project_filter in (ProjectFilter.ACTIVE, ProjectFilter.PROD):
                stmt = stmt.where(Project.served_config_uuid.is_not(None))
            elif project_filter == ProjectFilter.DEV:
                stmt = stmt.where(Project.served_config_uuid.is_(None))
            elif project_filter == ProjectFilter.WITH_USAGE:
                stmt = stmt.where(Project.first_served_at.is_not(None))
            return session.scalars(stmt).all()

    def get_all_by_config_status(
        self, config_status: ConfigStatus | None = None, *, exclude_empty: bool = False
    ) -> Sequence[Project]:
        """Return non-deleted projects, optionally restricted to those having at
        least one non-deleted config slot in the given status.

        When ``exclude_empty`` is set, the matching slot must also have content
        (``updated_at`` populated): freshly seeded slots start as DRAFT with a
        NULL ``updated_at`` (the EMPTY template state), so this distinguishes a
        genuine DRAFT from an untouched EMPTY slot.
        """
        with self.db.begin_session() as session:
            stmt = select(Project).where(Project.deleted_at.is_(None))
            if config_status is not None:
                conditions = [
                    ProjectConfig.project_uuid == Project.uuid,
                    ProjectConfig.config_status == config_status.value,
                    ProjectConfig.deleted_at.is_(None),
                ]
                if exclude_empty:
                    conditions.append(ProjectConfig.updated_at.is_not(None))
                has_matching_config = (
                    select(ProjectConfig.uuid).where(*conditions).exists()
                )
                stmt = stmt.where(has_matching_config)
            return session.scalars(stmt).all()

    def get_all_with_config(self) -> Sequence[Project]:
        """Projects that currently have a served config (used at startup)."""
        with self.db.begin_session() as session:
            stmt = select(Project).where(
                Project.served_config_uuid.is_not(None),
                Project.deleted_at.is_(None),
            )
            return session.scalars(stmt).all()

    def soft_delete(self, project_uuid: UUID) -> int:
        now = datetime.datetime.now(tz=_UTC)
        with self.db.begin_session() as session:
            query = (
                update(Project)
                .where(Project.uuid == project_uuid)
                .values(deleted_at=now, updated_at=now)
            )
            return session.execute(query).rowcount
