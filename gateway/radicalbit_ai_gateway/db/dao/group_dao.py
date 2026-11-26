from collections.abc import Sequence
import datetime as dt
from uuid import UUID

from sqlalchemy import delete, select, update

from radicalbit_ai_gateway.db.dao.dml import rows_matched
from radicalbit_ai_gateway.db.database import Database
from radicalbit_ai_gateway.db.tables.group_route_table import GroupRoute
from radicalbit_ai_gateway.db.tables.group_table import Group
from radicalbit_ai_gateway.db.tables.key_table import Key
from radicalbit_ai_gateway.db.tables.project_table import Project


class GroupDAO:
    def __init__(self, database: Database):
        self.db = database

    async def insert(self, group: Group) -> Group:
        async with self.db.begin_session() as session:
            session.add(group)
            await session.flush()
            return group

    async def get_by_uuid(self, group_uuid: UUID) -> Group | None:
        async with self.db.begin_session() as session:
            stmt = select(Group).where(Group.uuid == group_uuid)
            return await session.scalar(stmt)

    async def get_all(self) -> Sequence[Group]:
        async with self.db.begin_session() as session:
            stmt = select(Group)
            return (await session.scalars(stmt)).all()

    async def get_all_by_owner(self, owner: str) -> Sequence[Group]:
        async with self.db.begin_session() as session:
            stmt = select(Group).where(Group.owner == owner)
            return (await session.scalars(stmt)).all()

    async def delete_by_uuid(self, group_uuid: UUID) -> Group | None:
        async with self.db.begin_session() as session:
            query = select(Group).where(Group.uuid == group_uuid)
            group_to_delete = (await session.execute(query)).scalar_one_or_none()
            if not group_to_delete:
                return None
            await session.delete(group_to_delete)
            return group_to_delete

    async def update_group_name(self, group_uuid: UUID, name: str) -> int:
        UTC = getattr(dt, 'UTC', dt.timezone.utc)
        now = dt.datetime.now(tz=UTC)
        async with self.db.begin_session() as session:
            query = (
                update(Group)
                .where(Group.uuid == group_uuid)
                .values(name=name, updated_at=now)
            )
            return await rows_matched(session, query)

    async def add_route(self, group_route: GroupRoute) -> GroupRoute:
        async with self.db.begin_session() as session:
            session.add(group_route)
            await session.flush()
            return group_route

    async def remove_project_route(
        self, group_uuid: UUID, project_uuid: UUID, route_name: str
    ) -> int:
        async with self.db.begin_session() as session:
            query = delete(GroupRoute).where(
                GroupRoute.group_uuid == group_uuid,
                GroupRoute.project_uuid == project_uuid,
                GroupRoute.route_name == route_name,
            )
            return await rows_matched(session, query)

    async def get_by_name_and_owner(self, name: str, owner: str) -> Group | None:
        async with self.db.begin_session() as session:
            stmt = select(Group).where(Group.name == name, Group.owner == owner)
            return await session.scalar(stmt)

    async def check_key_uuid_for_route(
        self, project_uuid: UUID, route_name: str, key_uuid: UUID
    ) -> Group | None:
        async with self.db.begin_session() as session:
            query = (
                select(Group)
                .join(GroupRoute, Group.uuid == GroupRoute.group_uuid)
                .join(Key, Group.uuid == Key.group_uuid)
                .where(GroupRoute.project_uuid == project_uuid)
                .where(GroupRoute.route_name == route_name)
                .where(Key.uuid == key_uuid)
            )
            return await session.scalar(query)

    async def get_all_group_by_route_name(
        self, project_uuid: UUID, route_name: str
    ) -> Sequence[Group]:
        async with self.db.begin_session() as session:
            stmt = (
                select(Group)
                .join(GroupRoute)
                .where(GroupRoute.project_uuid == project_uuid)
                .where(GroupRoute.route_name == route_name)
            )
            return (await session.scalars(stmt)).all()

    async def delete_orphaned_associations(
        self, project_uuid: UUID, valid_route_names: list[str]
    ) -> int:
        """Delete the project's group↔route associations whose route_name is not
        in valid_route_names (the routes of the newly served config). Returns the
        number of deleted rows.
        """
        async with self.db.begin_session() as session:
            query = delete(GroupRoute).where(
                GroupRoute.project_uuid == project_uuid,
                GroupRoute.route_name.notin_(valid_route_names),
            )
            return await rows_matched(session, query)

    async def get_route_names_by_group_uuid(self, group_uuid: UUID) -> list[str]:
        """Return fully-qualified route names (project_name/route_name) for a group."""
        async with self.db.begin_session() as session:
            stmt = (
                select(Project.name, GroupRoute.route_name)
                .join(GroupRoute, GroupRoute.project_uuid == Project.uuid)
                .where(
                    GroupRoute.group_uuid == group_uuid,
                    Project.deleted_at.is_(None),
                )
            )
            rows = (await session.execute(stmt)).all()
            return [f'{row[0]}/{row[1]}' for row in rows]

    async def get_names_by_uuids(self, uuids: list[UUID]) -> dict[UUID, str]:
        if not uuids:
            return {}
        async with self.db.begin_session() as session:
            rows = await session.execute(
                select(Group.uuid, Group.name).where(Group.uuid.in_(uuids))
            )
            return {row[0]: row[1] for row in rows}
