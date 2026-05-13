import uuid

from sqlalchemy import (
    TEXT,
    TIMESTAMP,
    UUID,
    VARCHAR,
    Column,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from radicalbit_ai_gateway.db.dao.base_dao import BaseDAO
from radicalbit_ai_gateway.db.database import BaseTable, Reflected


class Key(Reflected, BaseTable, BaseDAO):
    __tablename__ = 'key'
    __table_args__ = (UniqueConstraint('NAME', 'OWNER', name='uq_key_NAME_OWNER'),)

    uuid = Column(
        'UUID',
        UUID(as_uuid=True),
        nullable=False,
        default=uuid.uuid4,
        primary_key=True,
    )
    name = Column('NAME', VARCHAR(), nullable=False)
    owner = Column('OWNER', VARCHAR(), nullable=False, default='gateway')
    key_metadata = Column('METADATA', TEXT(), nullable=True)
    hashed_key = Column('HASHED_KEY', VARCHAR(128), nullable=False)
    obscured_key = Column('OBSCURED_KEY', VARCHAR(128), nullable=False)
    created_at = Column('CREATED_AT', TIMESTAMP(timezone=True), nullable=False)
    updated_at = Column('UPDATED_AT', TIMESTAMP(timezone=True), nullable=False)
    group_uuid = Column(
        'GROUP_UUID',
        UUID(as_uuid=True),
        ForeignKey('group.UUID', ondelete='CASCADE'),
        nullable=True,
    )
    group = relationship(
        'Group',
        back_populates='keys',
        lazy='selectin',
    )
