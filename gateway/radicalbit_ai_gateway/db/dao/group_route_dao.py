from sqlalchemy import and_, or_

from radicalbit_ai_gateway.db.database import Database
from radicalbit_ai_gateway.db.tables.group_route_table import GroupRoute


class GroupRouteDAO:
    def __init__(self, database: Database):
        self.db = database

    def add(self, group_route: GroupRoute) -> GroupRoute:
        with self.db.begin_session() as session:
            session.add(group_route)
            session.flush()
            return group_route

    def add_bulk(self, group_route: list[GroupRoute]) -> list[GroupRoute]:
        if not group_route:
            return []
        with self.db.begin_session() as session:
            session.add_all(group_route)
            session.flush()
            conditions = [
                and_(
                    GroupRoute.group_uuid == gr.group_uuid,
                    GroupRoute.project_uuid == gr.project_uuid,
                    GroupRoute.route_name == gr.route_name,
                )
                for gr in group_route
            ]
            return session.query(GroupRoute).filter(or_(*conditions)).all()
