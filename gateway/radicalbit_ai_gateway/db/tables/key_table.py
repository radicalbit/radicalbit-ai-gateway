from datetime import date, datetime
from typing import TYPE_CHECKING
from uuid import UUID as PyUUID, uuid4

from sqlalchemy import (
    DATE,
    TEXT,
    TIMESTAMP,
    UUID,
    VARCHAR,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from radicalbit_ai_gateway.db.dao.base_dao import BaseDAO
from radicalbit_ai_gateway.db.database import BaseTable, Reflected

if TYPE_CHECKING:
    from radicalbit_ai_gateway.db.tables.group_table import Group
    from radicalbit_ai_gateway.db.tables.key_limit_table import KeyLimit


class Key(Reflected, BaseTable, BaseDAO):
    __tablename__ = 'key'
    __table_args__ = (
        UniqueConstraint('NAME', 'OWNER', name='uq_key_NAME_OWNER'),
        # Authentication looks a credential up by either of its values
        Index('ix_key_PREVIOUS_HASHED_KEY', 'PREVIOUS_HASHED_KEY'),
    )

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
    key_metadata: Mapped[str | None] = mapped_column('METADATA', TEXT(), nullable=True)
    hashed_key: Mapped[str] = mapped_column('HASHED_KEY', VARCHAR(128), nullable=False)
    obscured_key: Mapped[str] = mapped_column(
        'OBSCURED_KEY', VARCHAR(128), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        'CREATED_AT', TIMESTAMP(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        'UPDATED_AT', TIMESTAMP(timezone=True), nullable=False
    )
    # A calendar date, not an instant: valid up to 23:59:59 UTC on that day. None = never.
    expires_on: Mapped[date | None] = mapped_column('EXPIRES_ON', DATE(), nullable=True)
    # Rotation: the previous value's hash and the grace end are kept only
    # for a grace period; the last rotation instant stays until the next rotation.
    previous_hashed_key: Mapped[str | None] = mapped_column(
        'PREVIOUS_HASHED_KEY', VARCHAR(128), nullable=True
    )
    grace_ends_at: Mapped[datetime | None] = mapped_column(
        'GRACE_ENDS_AT', TIMESTAMP(timezone=True), nullable=True
    )
    last_rotated_at: Mapped[datetime | None] = mapped_column(
        'LAST_ROTATED_AT', TIMESTAMP(timezone=True), nullable=True
    )
    group_uuid: Mapped[PyUUID | None] = mapped_column(
        'GROUP_UUID',
        UUID(as_uuid=True),
        ForeignKey('group.UUID', ondelete='SET NULL'),
        nullable=True,
    )
    group: Mapped['Group | None'] = relationship(
        'Group',
        back_populates='keys',
        lazy='selectin',
    )
    limits: Mapped[list['KeyLimit']] = relationship(
        'KeyLimit',
        back_populates='key',
        cascade='all, delete-orphan',
        passive_deletes=True,
        lazy='selectin',
    )
