from sqlalchemy import UUID, VARCHAR, Column, ForeignKey
from sqlalchemy.orm import relationship

from radicalbit_ai_gateway.db.dao.base_dao import BaseDAO
from radicalbit_ai_gateway.db.database import BaseTable, Reflected


class GroupRoute(Reflected, BaseTable, BaseDAO):
    __tablename__ = 'group_routes'

    group_uuid = Column(
        'GROUP_UUID',
        UUID(as_uuid=True),
        ForeignKey('group.UUID', ondelete='CASCADE'),
        nullable=False,
        primary_key=True,
    )
    route_name = Column(
        'ROUTE_NAME',
        VARCHAR(),
        nullable=False,
        primary_key=True,
    )
    project_uuid = Column(
        'PROJECT_UUID',
        UUID(as_uuid=True),
        ForeignKey('project.UUID', ondelete='CASCADE'),
        nullable=False,
        primary_key=True,
    )

    group = relationship('Group', back_populates='group_routes', lazy='selectin')
    project = relationship('Project', lazy='selectin', viewonly=True)
