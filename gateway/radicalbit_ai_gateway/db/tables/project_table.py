import uuid

from sqlalchemy import (
    TEXT,
    TIMESTAMP,
    UUID,
    VARCHAR,
    Column,
    Enum as SAEnum,
    UniqueConstraint,
)

from radicalbit_ai_gateway.db.dao.base_dao import BaseDAO
from radicalbit_ai_gateway.db.database import BaseTable, Reflected
from radicalbit_ai_gateway.models.config_status import ConfigStatus


class Project(Reflected, BaseTable, BaseDAO):
    __tablename__ = 'project'
    __table_args__ = (UniqueConstraint('NAME', name='uq_project_NAME'),)
    uuid = Column(
        'UUID',
        UUID(as_uuid=True),
        nullable=False,
        default=uuid.uuid4,
        primary_key=True,
    )
    name = Column('NAME', VARCHAR(), nullable=False)
    description = Column('DESCRIPTION', TEXT(), nullable=True)
    config_file = Column('CONFIG_FILE', TEXT(), nullable=True)
    draft_config_file = Column('DRAFT_CONFIG_FILE', TEXT(), nullable=True)
    config_status = Column(
        'CONFIG_STATUS',
        SAEnum(ConfigStatus, name='project_config_status', create_type=True),
        nullable=False,
        server_default='DRAFT',
    )
    created_at = Column('CREATED_AT', TIMESTAMP(timezone=True), nullable=False)
    updated_at = Column('UPDATED_AT', TIMESTAMP(timezone=True), nullable=False)
    first_served_at = Column('FIRST_SERVED_AT', TIMESTAMP(timezone=True), nullable=True)
