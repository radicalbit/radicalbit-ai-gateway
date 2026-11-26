from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID as PyUUID, uuid4

from sqlalchemy import NUMERIC, TIMESTAMP, UUID, VARCHAR, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from radicalbit_ai_gateway.db.dao.base_dao import BaseDAO
from radicalbit_ai_gateway.db.database import BaseTable, Reflected

if TYPE_CHECKING:
    from radicalbit_ai_gateway.db.tables.key_table import Key


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

    uuid: Mapped[PyUUID] = mapped_column(
        'UUID',
        UUID(as_uuid=True),
        nullable=False,
        default=uuid4,
        primary_key=True,
    )
    key_uuid: Mapped[PyUUID] = mapped_column(
        'KEY_UUID',
        UUID(as_uuid=True),
        ForeignKey('key.UUID', ondelete='CASCADE'),
        nullable=False,
    )
    category: Mapped[str] = mapped_column('CATEGORY', VARCHAR(), nullable=False)
    algorithm: Mapped[str] = mapped_column('ALGORITHM', VARCHAR(), nullable=False)
    window_size: Mapped[str] = mapped_column('WINDOW_SIZE', VARCHAR(), nullable=False)
    max_value: Mapped[Decimal] = mapped_column('MAX_VALUE', NUMERIC(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        'CREATED_AT', TIMESTAMP(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        'UPDATED_AT', TIMESTAMP(timezone=True), nullable=False
    )

    key: Mapped['Key'] = relationship(
        'Key',
        back_populates='limits',
        lazy='selectin',
    )
