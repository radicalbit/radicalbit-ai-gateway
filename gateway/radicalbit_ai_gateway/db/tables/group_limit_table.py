import uuid

from sqlalchemy import (
    NUMERIC,
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


class GroupLimit(Reflected, BaseTable, BaseDAO):
    __tablename__ = 'group_limit'
    __table_args__ = (
        UniqueConstraint(
            'GROUP_UUID',
            'CATEGORY',
            'ALGORITHM',
            'WINDOW_SIZE',
            name='uq_group_limit_GROUP_UUID_CATEGORY_ALGORITHM_WINDOW_SIZE',
        ),
    )

    uuid = Column(
        'UUID',
        UUID(as_uuid=True),
        nullable=False,
        default=uuid.uuid4,
        primary_key=True,
    )
    group_uuid = Column(
        'GROUP_UUID',
        UUID(as_uuid=True),
        ForeignKey('group.UUID', ondelete='CASCADE'),
        nullable=False,
    )
    category = Column('CATEGORY', VARCHAR(), nullable=False)
    algorithm = Column('ALGORITHM', VARCHAR(), nullable=False)
    window_size = Column('WINDOW_SIZE', VARCHAR(), nullable=False)
    max_value = Column('MAX_VALUE', NUMERIC(), nullable=False)
    created_at = Column('CREATED_AT', TIMESTAMP(timezone=True), nullable=False)
    updated_at = Column('UPDATED_AT', TIMESTAMP(timezone=True), nullable=False)

    group = relationship(
        'Group',
        back_populates='limits',
        lazy='selectin',
    )
    propagated_key_limits = relationship(
        'KeyLimit',
        back_populates='group_limit',
        lazy='selectin',
    )
