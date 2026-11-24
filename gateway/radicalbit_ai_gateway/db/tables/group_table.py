from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID as PyUUID, uuid4

from sqlalchemy import TEXT, TIMESTAMP, UUID, VARCHAR, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from radicalbit_ai_gateway.db.dao.base_dao import BaseDAO
from radicalbit_ai_gateway.db.database import BaseTable, Reflected

if TYPE_CHECKING:
    from radicalbit_ai_gateway.db.tables.group_route_table import GroupRoute
    from radicalbit_ai_gateway.db.tables.key_table import Key


class Group(Reflected, BaseTable, BaseDAO):
    __tablename__ = 'group'
    __table_args__ = (UniqueConstraint('NAME', 'OWNER', name='uq_group_NAME_OWNER'),)
    uuid: Mapped[PyUUID] = mapped_column(
        'UUID',
        UUID(as_uuid=True),
        nullable=False,
        default=uuid4,
        primary_key=True,
    )
    name: Mapped[str] = mapped_column('NAME', VARCHAR(), nullable=False)
    owner: Mapped[str] = mapped_column(
        'OWNER', VARCHAR(), nullable=False, default='gateway'
    )
    group_metadata: Mapped[str | None] = mapped_column(
        'METADATA', TEXT(), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        'CREATED_AT', TIMESTAMP(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        'UPDATED_AT', TIMESTAMP(timezone=True), nullable=False
    )

    group_routes: Mapped[list['GroupRoute']] = relationship(
        'GroupRoute',
        back_populates='group',
        lazy='selectin',
        cascade='all, delete-orphan',
        passive_deletes=True,
    )
    keys: Mapped[list['Key']] = relationship(
        'Key',
        back_populates='group',
        passive_deletes=True,
        lazy='selectin',
    )
