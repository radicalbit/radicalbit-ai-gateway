from collections.abc import Sequence
import datetime
from uuid import UUID

from sqlalchemy import Select, asc, delete, select, update

from radicalbit_ai_gateway.db.database import Database
from radicalbit_ai_gateway.db.tables.key_table import Key


class KeyDAO:
    def __init__(self, database: Database):
        self.db = database

    @staticmethod
    def _get_all_stmt() -> Select:
        return select(Key)

    def insert(self, key: Key) -> Key:
        with self.db.begin_session() as session:
            session.add(key)
            session.flush()
            return key

    def get_all(self, only_unassigned: bool, owner: str | None = None) -> Sequence[Key]:
        with self.db.begin_session() as session:
            stmt = self._get_all_stmt()
            if only_unassigned:
                stmt = stmt.where(Key.group_uuid.is_(None))
            if owner:
                stmt = stmt.where(Key.owner == owner)
            stmt = stmt.order_by(asc(Key.name))
            return session.scalars(stmt).all()

    def get_by_uuid(self, key_uuid: UUID) -> Key:
        with self.db.begin_session() as session:
            return session.scalar(select(Key).where(Key.uuid == key_uuid))

    def update_key_name(self, key_uuid: UUID, name: str) -> int:
        UTC = getattr(datetime, 'UTC', datetime.timezone.utc)
        now = datetime.datetime.now(tz=UTC)
        with self.db.begin_session() as session:
            query = (
                update(Key)
                .where(Key.uuid == key_uuid)
                .values(name=name, updated_at=now)
            )
            return session.execute(query).rowcount

    def delete_by_uuid(self, key_uuid: UUID) -> int:
        with self.db.begin_session() as session:
            query = delete(Key).where(Key.uuid == key_uuid)
            return session.execute(query).rowcount

    def get_key_by_hashed_key(self, hashed_api_key: str) -> Key:
        with self.db.begin_session() as session:
            return session.scalar(select(Key).where(Key.hashed_key == hashed_api_key))

    def assign_group(self, key_uuid: UUID, group_uuid: UUID) -> Key | None:
        UTC = getattr(datetime, 'UTC', datetime.timezone.utc)
        now = datetime.datetime.now(tz=UTC)

        with self.db.begin_session() as session:
            query = (
                update(Key)
                .where(Key.uuid == key_uuid)
                .values(group_uuid=group_uuid, updated_at=now)
                .returning(Key)
            )
            return session.scalars(query).one_or_none()

    def remove_group(self, key_uuid: UUID) -> int:
        UTC = getattr(datetime, 'UTC', datetime.timezone.utc)
        now = datetime.datetime.now(tz=UTC)

        with self.db.begin_session() as session:
            query = (
                update(Key)
                .where(Key.uuid == key_uuid)
                .values(group_uuid=None, updated_at=now)
            )
            return session.execute(query).rowcount

    def get_names_by_uuids(self, uuids: list[UUID]) -> dict[UUID, str]:
        if not uuids:
            return {}
        with self.db.begin_session() as session:
            rows = session.query(Key.uuid, Key.name).filter(Key.uuid.in_(uuids)).all()
            return {row[0]: row[1] for row in rows}
