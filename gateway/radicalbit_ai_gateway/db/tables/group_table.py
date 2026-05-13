import uuid

from sqlalchemy import TEXT, TIMESTAMP, UUID, VARCHAR, Column, UniqueConstraint
from sqlalchemy.orm import relationship

from radicalbit_ai_gateway.db.dao.base_dao import BaseDAO
from radicalbit_ai_gateway.db.database import BaseTable, Reflected


class Group(Reflected, BaseTable, BaseDAO):
    __tablename__ = 'group'
    __table_args__ = (UniqueConstraint('NAME', 'OWNER', name='uq_group_NAME_OWNER'),)
    uuid = Column(
        'UUID',
        UUID(as_uuid=True),
        nullable=False,
        default=uuid.uuid4,
        primary_key=True,
    )
    name = Column('NAME', VARCHAR(), nullable=False)
    owner = Column('OWNER', VARCHAR(), nullable=False, default='gateway')
    group_metadata = Column('METADATA', TEXT(), nullable=True)
    created_at = Column('CREATED_AT', TIMESTAMP(timezone=True), nullable=False)
    updated_at = Column('UPDATED_AT', TIMESTAMP(timezone=True), nullable=False)

    group_routes = relationship(
        'GroupRoute',
        back_populates='group',
        lazy='selectin',
        cascade='all, delete-orphan',
        passive_deletes=True,
    )
    keys = relationship(
        'Key',
        back_populates='group',
        cascade='all, delete-orphan',
        passive_deletes=True,
        lazy='selectin',
    )
