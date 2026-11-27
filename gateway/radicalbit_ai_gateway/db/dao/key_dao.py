from collections.abc import Sequence
import datetime as dt
from uuid import UUID

from sqlalchemy import Select, asc, delete, or_, select, update

from radicalbit_ai_gateway.db.dao.dml import rows_matched
from radicalbit_ai_gateway.db.database import Database, filter_if
from radicalbit_ai_gateway.db.tables.key_table import Key


class KeyDAO:
    def __init__(self, database: Database):
        self.db = database

    @staticmethod
    def _get_all_stmt() -> Select[Key]:
        return select(Key)

    async def insert(self, key: Key) -> Key:
        async with self.db.begin_session() as session:
            session.add(key)
            await session.flush()
            return key

    async def get_all(
        self, only_unassigned: bool, owner: str | None = None
    ) -> Sequence[Key]:
        async with self.db.begin_session() as session:
            stmt = filter_if(
                self._get_all_stmt(), only_unassigned, Key.group_uuid.is_(None)
            )
            stmt = filter_if(stmt, bool(owner), Key.owner == owner)
            stmt = stmt.order_by(asc(Key.name))
            return (await session.scalars(stmt)).all()

    async def get_by_uuid(self, key_uuid: UUID) -> Key | None:
        async with self.db.begin_session() as session:
            return await session.scalar(select(Key).where(Key.uuid == key_uuid))

    async def update_key_name(self, key_uuid: UUID, name: str) -> int:
        UTC = getattr(dt, 'UTC', dt.timezone.utc)
        now = dt.datetime.now(tz=UTC)
        async with self.db.begin_session() as session:
            query = (
                update(Key)
                .where(Key.uuid == key_uuid)
                .values(name=name, updated_at=now)
            )
            return await rows_matched(session, query)

    async def delete_by_uuid(self, key_uuid: UUID) -> int:
        async with self.db.begin_session() as session:
            query = delete(Key).where(Key.uuid == key_uuid)
            return await rows_matched(session, query)

    async def get_key_by_hashed_key(self, hashed_api_key: str) -> Key | None:
        """Find a credential by its current value or its previous one. Whether the
        previous value still authenticates is the caller's decision.
        """
        async with self.db.begin_session() as session:
            return await session.scalar(
                select(Key).where(
                    or_(
                        Key.hashed_key == hashed_api_key,
                        Key.previous_hashed_key == hashed_api_key,
                    )
                )
            )

    async def rotate(
        self,
        key_uuid: UUID,
        expected_hashed_key: str,
        hashed_key: str,
        obscured_key: str,
        grace_ends_at: dt.datetime | None,
        now: dt.datetime,
    ) -> Key | None:
        """Replace the value in a single conditional update, so it applies only if
        the value is still the one the caller read and no grace period is running.
        Returns None when another rotation got there first.
        """
        async with self.db.begin_session() as session:
            query = (
                update(Key)
                .where(
                    Key.uuid == key_uuid,
                    Key.hashed_key == expected_hashed_key,
                    or_(Key.grace_ends_at.is_(None), Key.grace_ends_at <= now),
                )
                .values(
                    hashed_key=hashed_key,
                    obscured_key=obscured_key,
                    previous_hashed_key=expected_hashed_key if grace_ends_at else None,
                    grace_ends_at=grace_ends_at,
                    last_rotated_at=now,
                    updated_at=now,
                )
                .returning(Key)
            )
            return (await session.scalars(query)).one_or_none()

    async def end_grace_period(self, key_uuid: UUID, now: dt.datetime) -> Key | None:
        """Forget the previous value now. Returns None when no grace period is running."""
        async with self.db.begin_session() as session:
            query = (
                update(Key)
                .where(Key.uuid == key_uuid, Key.grace_ends_at > now)
                .values(previous_hashed_key=None, grace_ends_at=None, updated_at=now)
                .returning(Key)
            )
            return (await session.scalars(query)).one_or_none()

    async def assign_group(self, key_uuid: UUID, group_uuid: UUID) -> Key | None:
        UTC = getattr(dt, 'UTC', dt.timezone.utc)
        now = dt.datetime.now(tz=UTC)

        async with self.db.begin_session() as session:
            query = (
                update(Key)
                .where(Key.uuid == key_uuid)
                .values(group_uuid=group_uuid, updated_at=now)
                .returning(Key)
            )
            return (await session.scalars(query)).one_or_none()

    async def remove_group(self, key_uuid: UUID, group_uuid: UUID) -> int:
        """Take the key out of ``group_uuid``; nothing changes if it is not in it."""
        UTC = getattr(dt, 'UTC', dt.timezone.utc)
        now = dt.datetime.now(tz=UTC)

        async with self.db.begin_session() as session:
            query = (
                update(Key)
                .where(Key.uuid == key_uuid, Key.group_uuid == group_uuid)
                .values(group_uuid=None, updated_at=now)
            )
            return await rows_matched(session, query)

    async def get_names_by_uuids(self, uuids: list[UUID]) -> dict[UUID, str]:
        if not uuids:
            return {}
        async with self.db.begin_session() as session:
            rows = await session.execute(
                select(Key.uuid, Key.name).where(Key.uuid.in_(uuids))
            )
            return {row[0]: row[1] for row in rows}
