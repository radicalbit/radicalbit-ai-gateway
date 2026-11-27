from sqlalchemy import and_, or_, select

from radicalbit_ai_gateway.db.database import Database
from radicalbit_ai_gateway.db.tables.group_route_table import GroupRoute


class GroupRouteDAO:
    def __init__(self, database: Database):
        self.db = database

    async def add(self, group_route: GroupRoute) -> GroupRoute:
        async with self.db.begin_session() as session:
            session.add(group_route)
            await session.flush()
            return group_route

    async def add_bulk(self, group_route: list[GroupRoute]) -> list[GroupRoute]:
        if not group_route:
            return []
        async with self.db.begin_session() as session:
            session.add_all(group_route)
            await session.flush()
            conditions = [
                and_(
                    GroupRoute.group_uuid == gr.group_uuid,
                    GroupRoute.project_uuid == gr.project_uuid,
                    GroupRoute.route_name == gr.route_name,
                )
                for gr in group_route
            ]
            stmt = select(GroupRoute).where(or_(*conditions))
            return list((await session.scalars(stmt)).all())
