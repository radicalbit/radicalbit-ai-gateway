from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, select

from radicalbit_ai_gateway.db.database import Database
from radicalbit_ai_gateway.db.tables.key_limit_table import KeyLimit


class KeyLimitDAO:
    def __init__(self, database: Database):
        self.db = database

    def insert(self, key_limit: KeyLimit) -> KeyLimit:
        with self.db.begin_session() as session:
            session.add(key_limit)
            session.flush()
            return key_limit

    def insert_many(self, key_limits: list[KeyLimit]) -> list[KeyLimit]:
        """Insert all limits in a single transaction: either all succeed, or
        none do (e.g. if one duplicates an existing or another batch entry).
        """
        with self.db.begin_session() as session:
            session.add_all(key_limits)
            session.flush()
            return key_limits

    def get_by_uuid(self, limit_uuid: UUID) -> KeyLimit | None:
        with self.db.begin_session() as session:
            return session.scalar(select(KeyLimit).where(KeyLimit.uuid == limit_uuid))

    def get_by_key_uuid(self, key_uuid: UUID) -> Sequence[KeyLimit]:
        with self.db.begin_session() as session:
            stmt = select(KeyLimit).where(KeyLimit.key_uuid == key_uuid)
            return session.scalars(stmt).all()

    def get_all_by_key_uuids(self, key_uuids: list[UUID]) -> Sequence[KeyLimit]:
        if not key_uuids:
            return []
        with self.db.begin_session() as session:
            stmt = select(KeyLimit).where(KeyLimit.key_uuid.in_(key_uuids))
            return session.scalars(stmt).all()

    def delete_by_uuid(self, limit_uuid: UUID) -> int:
        with self.db.begin_session() as session:
            query = delete(KeyLimit).where(KeyLimit.uuid == limit_uuid)
            return session.execute(query).rowcount
