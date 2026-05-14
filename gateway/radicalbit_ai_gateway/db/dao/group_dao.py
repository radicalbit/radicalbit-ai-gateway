from collections.abc import Sequence
import datetime
from uuid import UUID

from sqlalchemy import delete, select, update

from radicalbit_ai_gateway.db.database import Database
from radicalbit_ai_gateway.db.tables.group_route_table import GroupRoute
from radicalbit_ai_gateway.db.tables.group_table import Group
from radicalbit_ai_gateway.db.tables.key_table import Key
from radicalbit_ai_gateway.db.tables.project_table import Project


class GroupDAO:
    def __init__(self, database: Database):
        self.db = database

    def insert(self, group: Group) -> Group:
        with self.db.begin_session() as session:
            session.add(group)
            session.flush()
            return group

    def get_by_uuid(self, group_uuid: UUID) -> Group:
        with self.db.begin_session() as session:
            stmt = select(Group).where(Group.uuid == group_uuid)
            return session.scalar(stmt)

    def get_all(self) -> Sequence[Group]:
        with self.db.begin_session() as session:
            stmt = select(Group)
            return session.scalars(stmt).all()

    def get_all_by_owner(self, owner: str) -> Sequence[Group]:
        with self.db.begin_session() as session:
            stmt = select(Group).where(Group.owner == owner)
            return session.scalars(stmt).all()

    def delete_by_uuid(self, group_uuid: UUID) -> Group | None:
        with self.db.begin_session() as session:
            query = select(Group).where(Group.uuid == group_uuid)
            group_to_delete = session.execute(query).scalar_one_or_none()
            if not group_to_delete:
                return None
            session.delete(group_to_delete)
            return group_to_delete

    def update_group_name(self, group_uuid: UUID, name: str) -> int:
        UTC = getattr(datetime, 'UTC', datetime.timezone.utc)
        now = datetime.datetime.now(tz=UTC)
        with self.db.begin_session() as session:
            query = (
                update(Group)
                .where(Group.uuid == group_uuid)
                .values(name=name, updated_at=now)
            )
            return session.execute(query).rowcount

    def add_route(self, group_route: GroupRoute) -> GroupRoute:
        with self.db.begin_session() as session:
            session.add(group_route)
            session.flush()
            return group_route

    def remove_project_route(
        self, group_uuid: UUID, project_uuid: UUID, route_name: str
    ) -> int:
        with self.db.begin_session() as session:
            query = delete(GroupRoute).where(
                GroupRoute.group_uuid == group_uuid,
                GroupRoute.project_uuid == project_uuid,
                GroupRoute.route_name == route_name,
            )
            return session.execute(query).rowcount

    def get_by_name_and_owner(self, name: str, owner: str) -> Group | None:
        with self.db.begin_session() as session:
            stmt = select(Group).where(Group.name == name, Group.owner == owner)
            return session.scalar(stmt)

    def check_key_uuid_for_route(
        self, project_uuid: UUID, route_name: str, key_uuid: UUID
    ) -> Group | None:
        with self.db.begin_session() as session:
            query = (
                select(Group)
                .join(GroupRoute, Group.uuid == GroupRoute.group_uuid)
                .join(Key, Group.uuid == Key.group_uuid)
                .where(GroupRoute.project_uuid == project_uuid)
                .where(GroupRoute.route_name == route_name)
                .where(Key.uuid == key_uuid)
            )
            return session.scalar(query)

    def get_all_group_by_route_name(
        self, project_uuid: UUID, route_name: str
    ) -> Sequence[Group]:
        with self.db.begin_session() as session:
            stmt = (
                select(Group)
                .join(GroupRoute)
                .where(GroupRoute.project_uuid == project_uuid)
                .where(GroupRoute.route_name == route_name)
            )
            return session.scalars(stmt).all()

    def get_route_names_by_group_uuid(self, group_uuid: UUID) -> list[str]:
        """Return fully-qualified route names (project_name/route_name) for a group."""
        with self.db.begin_session() as session:
            stmt = (
                select(Project.name, GroupRoute.route_name)
                .join(GroupRoute, GroupRoute.project_uuid == Project.uuid)
                .where(
                    GroupRoute.group_uuid == group_uuid,
                    Project.deleted_at.is_(None),
                )
            )
            rows = session.execute(stmt).all()
            return [f'{row[0]}/{row[1]}' for row in rows]

    def get_names_by_uuids(self, uuids: list[UUID]) -> dict[UUID, str]:
        if not uuids:
            return {}
        with self.db.begin_session() as session:
            rows = (
                session.query(Group.uuid, Group.name)
                .filter(Group.uuid.in_(uuids))
                .all()
            )
            return {row[0]: row[1] for row in rows}
