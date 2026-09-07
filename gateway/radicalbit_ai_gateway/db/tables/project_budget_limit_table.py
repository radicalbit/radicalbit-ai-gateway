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

from radicalbit_ai_gateway.db.dao.base_dao import BaseDAO
from radicalbit_ai_gateway.db.database import BaseTable, Reflected


class ProjectBudgetLimit(Reflected, BaseTable, BaseDAO):
    __tablename__ = 'project_budget_limit'
    __table_args__ = (
        UniqueConstraint(
            'PROJECT_UUID',
            'WINDOW_SIZE',
            name='uq_project_budget_limit_PROJECT_UUID_WINDOW_SIZE',
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
    algorithm = Column('ALGORITHM', VARCHAR(), nullable=False)
    window_size = Column('WINDOW_SIZE', VARCHAR(), nullable=False)
    max_value = Column('MAX_VALUE', NUMERIC(), nullable=False)
    created_at = Column('CREATED_AT', TIMESTAMP(timezone=True), nullable=False)
    updated_at = Column('UPDATED_AT', TIMESTAMP(timezone=True), nullable=False)
