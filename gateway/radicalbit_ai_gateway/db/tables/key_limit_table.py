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


class KeyLimit(Reflected, BaseTable, BaseDAO):
    __tablename__ = 'key_limit'
    __table_args__ = (
        UniqueConstraint(
            'KEY_UUID',
            'CATEGORY',
            'ALGORITHM',
            'WINDOW_SIZE',
            name='uq_key_limit_KEY_UUID_CATEGORY_ALGORITHM_WINDOW_SIZE',
        ),
    )

    uuid = Column(
        'UUID',
        UUID(as_uuid=True),
        nullable=False,
        default=uuid.uuid4,
        primary_key=True,
    )
    key_uuid = Column(
        'KEY_UUID',
        UUID(as_uuid=True),
        ForeignKey('key.UUID', ondelete='CASCADE'),
        nullable=False,
    )
    category = Column('CATEGORY', VARCHAR(), nullable=False)
    algorithm = Column('ALGORITHM', VARCHAR(), nullable=False)
    window_size = Column('WINDOW_SIZE', VARCHAR(), nullable=False)
    max_value = Column('MAX_VALUE', NUMERIC(), nullable=False)
    created_at = Column('CREATED_AT', TIMESTAMP(timezone=True), nullable=False)
    updated_at = Column('UPDATED_AT', TIMESTAMP(timezone=True), nullable=False)

    key = relationship(
        'Key',
        back_populates='limits',
        lazy='selectin',
    )
