from datetime import datetime
from uuid import UUID as PyUUID, uuid4

from sqlalchemy import (
    TEXT,
    TIMESTAMP,
    UUID,
    Enum as SAEnum,
    ForeignKey,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from radicalbit_ai_gateway.db.dao.base_dao import BaseDAO
from radicalbit_ai_gateway.db.database import BaseTable, Reflected
from radicalbit_ai_gateway.models.config_slot import Slot
from radicalbit_ai_gateway.models.config_status import ConfigStatus


class ProjectConfig(Reflected, BaseTable, BaseDAO):
    __tablename__ = 'project_config'
    __table_args__ = (
        # A project has at most two slots (A/B).
        UniqueConstraint(
            'PROJECT_UUID', 'SLOT', name='uq_project_config_PROJECT_UUID_SLOT'
        ),
        # At most one SERVED config per project (partial unique index).
        Index(
            'uq_project_config_served',
            'PROJECT_UUID',
            unique=True,
            postgresql_where=text('"CONFIG_STATUS" = \'SERVED\''),
        ),
    )
    uuid: Mapped[PyUUID] = mapped_column(
        'UUID',
        UUID(as_uuid=True),
        nullable=False,
        default=uuid4,
        primary_key=True,
    )
    project_uuid: Mapped[PyUUID] = mapped_column(
        'PROJECT_UUID',
        UUID(as_uuid=True),
        ForeignKey('project.UUID', ondelete='CASCADE'),
        nullable=False,
    )
    slot: Mapped[Slot] = mapped_column(
        'SLOT',
        SAEnum(Slot, name='project_config_slot', create_type=True),
        nullable=False,
    )
    config_file: Mapped[str | None] = mapped_column(
        'CONFIG_FILE', TEXT(), nullable=True
    )
    config_status: Mapped[ConfigStatus] = mapped_column(
        'CONFIG_STATUS',
        SAEnum(ConfigStatus, name='project_config_status', create_type=True),
        nullable=False,
        server_default='DRAFT',
    )
    created_at: Mapped[datetime] = mapped_column(
        'CREATED_AT', TIMESTAMP(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        'UPDATED_AT', TIMESTAMP(timezone=True), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        'DELETED_AT', TIMESTAMP(timezone=True), nullable=True
    )
