from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, select, update

from radicalbit_ai_gateway.db.database import Database
from radicalbit_ai_gateway.db.tables.key_limit_table import KeyLimit


class KeyLimitDAO:
    def __init__(self, database: Database):
        self.db = database

    async def insert(self, key_limit: KeyLimit) -> KeyLimit:
        async with self.db.begin_session() as session:
            session.add(key_limit)
            await session.flush()
            return key_limit

    async def insert_many(self, key_limits: list[KeyLimit]) -> list[KeyLimit]:
        """Insert all limits in a single transaction: either all succeed, or
        none do (e.g. if one duplicates an existing or another batch entry).
        """
        async with self.db.begin_session() as session:
            session.add_all(key_limits)
            await session.flush()
            return key_limits

    async def save_many(
        self, to_insert: list[KeyLimit], to_update: list[KeyLimit]
    ) -> None:
        """Insert new limits and update the max of existing ones, identified by
        their own uuid, in one transaction: either all succeed or none do.
        """
        async with self.db.begin_session() as session:
            session.add_all(to_insert)
            for limit in to_update:
                await session.execute(
                    update(KeyLimit)
                    .where(KeyLimit.uuid == limit.uuid)
                    .values(max_value=limit.max_value, updated_at=limit.updated_at)
                )
            await session.flush()

    async def get_by_uuid(self, limit_uuid: UUID) -> KeyLimit | None:
        async with self.db.begin_session() as session:
            return await session.scalar(
                select(KeyLimit).where(KeyLimit.uuid == limit_uuid)
            )

    async def get_by_key_uuid(self, key_uuid: UUID) -> Sequence[KeyLimit]:
        async with self.db.begin_session() as session:
            stmt = select(KeyLimit).where(KeyLimit.key_uuid == key_uuid)
            return (await session.scalars(stmt)).all()

    async def get_all_by_key_uuids(self, key_uuids: list[UUID]) -> Sequence[KeyLimit]:
        if not key_uuids:
            return []
        async with self.db.begin_session() as session:
            stmt = select(KeyLimit).where(KeyLimit.key_uuid.in_(key_uuids))
            return (await session.scalars(stmt)).all()

    async def delete_by_uuid(self, limit_uuid: UUID) -> int:
        async with self.db.begin_session() as session:
            query = delete(KeyLimit).where(KeyLimit.uuid == limit_uuid)
            return (await session.execute(query)).rowcount
