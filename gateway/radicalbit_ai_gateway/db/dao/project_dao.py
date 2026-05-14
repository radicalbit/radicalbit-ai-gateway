from collections.abc import Sequence
import datetime
from uuid import UUID

from sqlalchemy import func, select, update

from radicalbit_ai_gateway.db.database import Database
from radicalbit_ai_gateway.db.tables.project_table import Project
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
            if project_filter == ProjectFilter.ACTIVE:
                stmt = stmt.where(Project.config_file.is_not(None))
            elif project_filter == ProjectFilter.WITH_USAGE:
                stmt = stmt.where(Project.first_served_at.is_not(None))
            return session.scalars(stmt).all()

    def get_all_with_config(self) -> Sequence[Project]:
        with self.db.begin_session() as session:
            stmt = select(Project).where(
                Project.config_file.is_not(None),
                Project.deleted_at.is_(None),
            )
            return session.scalars(stmt).all()

    def update_draft_config_file(
        self, project_uuid: UUID, draft_config_file: str
    ) -> int:
        now = datetime.datetime.now(tz=_UTC)
        with self.db.begin_session() as session:
            query = (
                update(Project)
                .where(Project.uuid == project_uuid)
                .values(
                    draft_config_file=draft_config_file,
                    config_status=ConfigStatus.DRAFT.value,
                    updated_at=now,
                )
            )
            return session.execute(query).rowcount

    def promote_draft_to_config(self, project_uuid: UUID, config_file: str) -> int:
        now = datetime.datetime.now(tz=_UTC)
        with self.db.begin_session() as session:
            query = (
                update(Project)
                .where(Project.uuid == project_uuid)
                .values(
                    config_file=config_file,
                    draft_config_file=None,
                    config_status=ConfigStatus.SERVED.value,
                    updated_at=now,
                    first_served_at=func.coalesce(Project.first_served_at, now),
                )
            )
            return session.execute(query).rowcount

    def set_config_status(self, project_uuid: UUID, status: ConfigStatus) -> int:
        now = datetime.datetime.now(tz=_UTC)
        with self.db.begin_session() as session:
            query = (
                update(Project)
                .where(Project.uuid == project_uuid)
                .values(config_status=status.value, updated_at=now)
            )
            return session.execute(query).rowcount

    def soft_delete(self, project_uuid: UUID) -> int:
        now = datetime.datetime.now(tz=_UTC)
        with self.db.begin_session() as session:
            query = (
                update(Project)
                .where(Project.uuid == project_uuid)
                .values(deleted_at=now, updated_at=now)
            )
            return session.execute(query).rowcount

    def unserve_config(self, project_uuid: UUID, restore_draft: bool) -> int:
        now = datetime.datetime.now(tz=_UTC)
        with self.db.begin_session() as session:
            project = session.scalar(
                select(Project).where(
                    Project.uuid == project_uuid,
                    Project.deleted_at.is_(None),
                )
            )
            if project is None:
                return 0
            values: dict = {
                'config_status': ConfigStatus.DRAFT.value,
                'config_file': None,
                'updated_at': now,
            }
            if restore_draft:
                values['draft_config_file'] = project.config_file
            query = update(Project).where(Project.uuid == project_uuid).values(**values)
            return session.execute(query).rowcount
