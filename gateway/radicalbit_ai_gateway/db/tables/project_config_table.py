import uuid

from sqlalchemy import (
    TEXT,
    TIMESTAMP,
    UUID,
    Column,
    Enum as SAEnum,
    ForeignKey,
    Index,
    UniqueConstraint,
    text,
)

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
    uuid = Column(
        'UUID',
        UUID(as_uuid=True),
        nullable=False,
        default=uuid.uuid4,
        primary_key=True,
    )
    project_uuid = Column(
        'PROJECT_UUID',
        UUID(as_uuid=True),
        ForeignKey('project.UUID', ondelete='CASCADE'),
        nullable=False,
    )
    slot = Column(
        'SLOT',
        SAEnum(Slot, name='project_config_slot', create_type=True),
        nullable=False,
    )
    config_file = Column('CONFIG_FILE', TEXT(), nullable=True)
    config_status = Column(
        'CONFIG_STATUS',
        SAEnum(ConfigStatus, name='project_config_status', create_type=True),
        nullable=False,
        server_default='DRAFT',
    )
    created_at = Column('CREATED_AT', TIMESTAMP(timezone=True), nullable=False)
    updated_at = Column('UPDATED_AT', TIMESTAMP(timezone=True), nullable=True)
    deleted_at = Column('DELETED_AT', TIMESTAMP(timezone=True), nullable=True)
