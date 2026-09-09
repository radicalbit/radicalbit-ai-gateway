from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, select

from radicalbit_ai_gateway.db.database import Database
from radicalbit_ai_gateway.db.tables.project_budget_limit_table import (
    ProjectBudgetLimit,
)


class ProjectBudgetLimitDAO:
    def __init__(self, database: Database):
        self.db = database

    def insert(self, project_budget_limit: ProjectBudgetLimit) -> ProjectBudgetLimit:
        with self.db.begin_session() as session:
            session.add(project_budget_limit)
            session.flush()
            return project_budget_limit

    def insert_many(
        self, project_budget_limits: list[ProjectBudgetLimit]
    ) -> list[ProjectBudgetLimit]:
        """Insert all limits in a single transaction: either all succeed, or
        none do (e.g. if one duplicates an existing or another batch entry).
        """
        with self.db.begin_session() as session:
            session.add_all(project_budget_limits)
            session.flush()
            return project_budget_limits

    def get_by_uuid(self, limit_uuid: UUID) -> ProjectBudgetLimit | None:
        with self.db.begin_session() as session:
            stmt = select(ProjectBudgetLimit).where(
                ProjectBudgetLimit.uuid == limit_uuid
            )
            return session.scalar(stmt)

    def get_by_project_uuid(self, project_uuid: UUID) -> Sequence[ProjectBudgetLimit]:
        with self.db.begin_session() as session:
            stmt = select(ProjectBudgetLimit).where(
                ProjectBudgetLimit.project_uuid == project_uuid
            )
            return session.scalars(stmt).all()

    def delete_by_uuid(self, limit_uuid: UUID) -> int:
        with self.db.begin_session() as session:
            query = delete(ProjectBudgetLimit).where(
                ProjectBudgetLimit.uuid == limit_uuid
            )
            return session.execute(query).rowcount
