from collections.abc import Sequence
import datetime as dt
from uuid import UUID

from sqlalchemy import delete, select, update

from radicalbit_ai_gateway.db.dao.dml import rows_matched
from radicalbit_ai_gateway.db.database import Database
from radicalbit_ai_gateway.db.tables.project_budget_limit_table import (
    ProjectBudgetLimit,
)


class ProjectBudgetLimitDAO:
    def __init__(self, database: Database):
        self.db = database

    async def insert(
        self, project_budget_limit: ProjectBudgetLimit
    ) -> ProjectBudgetLimit:
        async with self.db.begin_session() as session:
            session.add(project_budget_limit)
            await session.flush()
            return project_budget_limit

    async def insert_many(
        self, project_budget_limits: list[ProjectBudgetLimit]
    ) -> list[ProjectBudgetLimit]:
        """Insert all limits in a single transaction: either all succeed, or
        none do (e.g. if one duplicates an existing or another batch entry).
        """
        async with self.db.begin_session() as session:
            session.add_all(project_budget_limits)
            await session.flush()
            return project_budget_limits

    async def get_by_uuid(self, limit_uuid: UUID) -> ProjectBudgetLimit | None:
        async with self.db.begin_session() as session:
            stmt = select(ProjectBudgetLimit).where(
                ProjectBudgetLimit.uuid == limit_uuid
            )
            return await session.scalar(stmt)

    async def get_by_project_uuid(
        self, project_uuid: UUID
    ) -> Sequence[ProjectBudgetLimit]:
        async with self.db.begin_session() as session:
            stmt = select(ProjectBudgetLimit).where(
                ProjectBudgetLimit.project_uuid == project_uuid
            )
            return (await session.scalars(stmt)).all()

    async def get_all_by_project_uuids(
        self, project_uuids: list[UUID]
    ) -> Sequence[ProjectBudgetLimit]:
        if not project_uuids:
            return list[ProjectBudgetLimit]()
        async with self.db.begin_session() as session:
            stmt = select(ProjectBudgetLimit).where(
                ProjectBudgetLimit.project_uuid.in_(project_uuids)
            )
            return (await session.scalars(stmt)).all()

    async def update_max_value(self, limit_uuid: UUID, max_value: float) -> None:
        async with self.db.begin_session() as session:
            await session.execute(
                update(ProjectBudgetLimit)
                .where(ProjectBudgetLimit.uuid == limit_uuid)
                .values(
                    max_value=max_value,
                    updated_at=dt.datetime.now(tz=dt.timezone.utc),
                )
            )

    async def delete_by_uuid(self, limit_uuid: UUID) -> int:
        async with self.db.begin_session() as session:
            query = delete(ProjectBudgetLimit).where(
                ProjectBudgetLimit.uuid == limit_uuid
            )
            return await rows_matched(session, query)

    async def delete_by_project_uuid(self, project_uuid: UUID) -> int:
        async with self.db.begin_session() as session:
            query = delete(ProjectBudgetLimit).where(
                ProjectBudgetLimit.project_uuid == project_uuid
            )
            return await rows_matched(session, query)
