from typing import TYPE_CHECKING
from uuid import UUID as PyUUID

from sqlalchemy import UUID, VARCHAR, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from radicalbit_ai_gateway.db.dao.base_dao import BaseDAO
from radicalbit_ai_gateway.db.database import BaseTable, Reflected

if TYPE_CHECKING:
    from radicalbit_ai_gateway.db.tables.group_table import Group
    from radicalbit_ai_gateway.db.tables.project_table import Project


class GroupRoute(Reflected, BaseTable, BaseDAO):
    __tablename__ = 'group_routes'

    group_uuid: Mapped[PyUUID] = mapped_column(
        'GROUP_UUID',
        UUID(as_uuid=True),
        ForeignKey('group.UUID', ondelete='CASCADE'),
        nullable=False,
        primary_key=True,
    )
    route_name: Mapped[str] = mapped_column(
        'ROUTE_NAME',
        VARCHAR(),
        nullable=False,
        primary_key=True,
    )
    project_uuid: Mapped[PyUUID] = mapped_column(
        'PROJECT_UUID',
        UUID(as_uuid=True),
        ForeignKey('project.UUID', ondelete='CASCADE'),
        nullable=False,
        primary_key=True,
    )

    group: Mapped['Group'] = relationship(
        'Group', back_populates='group_routes', lazy='selectin'
    )
    project: Mapped['Project'] = relationship('Project', lazy='selectin', viewonly=True)
