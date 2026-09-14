from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, select, update

from radicalbit_ai_gateway.db.database import Database
from radicalbit_ai_gateway.db.tables.group_limit_table import GroupLimit


class GroupLimitDAO:
    def __init__(self, database: Database):
        self.db = database

    def insert_many(self, group_limits: list[GroupLimit]) -> list[GroupLimit]:
        """Insert all limits in a single transaction: either all succeed, or
        none do (e.g. if one duplicates an existing or another batch entry).
        """
        with self.db.begin_session() as session:
            session.add_all(group_limits)
            session.flush()
            return group_limits

    def update_many(self, group_limits: list[GroupLimit]) -> list[GroupLimit]:
        """Update max_value/updated_at for existing rows, identified by their
        own uuid. One transaction: either all succeed or none do.
        """
        with self.db.begin_session() as session:
            for limit in group_limits:
                session.execute(
                    update(GroupLimit)
                    .where(GroupLimit.uuid == limit.uuid)
                    .values(max_value=limit.max_value, updated_at=limit.updated_at)
                )
            session.flush()
            return group_limits

    def get_by_uuid(self, limit_uuid: UUID) -> GroupLimit | None:
        with self.db.begin_session() as session:
            return session.scalar(
                select(GroupLimit).where(GroupLimit.uuid == limit_uuid)
            )

    def get_by_group_uuid(self, group_uuid: UUID) -> Sequence[GroupLimit]:
        with self.db.begin_session() as session:
            stmt = select(GroupLimit).where(GroupLimit.group_uuid == group_uuid)
            return session.scalars(stmt).all()

    def delete_by_uuid(self, limit_uuid: UUID) -> int:
        with self.db.begin_session() as session:
            query = delete(GroupLimit).where(GroupLimit.uuid == limit_uuid)
            return session.execute(query).rowcount
