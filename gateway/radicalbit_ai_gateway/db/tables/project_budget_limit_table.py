from datetime import datetime
from decimal import Decimal
from uuid import UUID as PyUUID, uuid4

from sqlalchemy import NUMERIC, TIMESTAMP, UUID, VARCHAR, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from radicalbit_ai_gateway.db.dao.base_dao import BaseDAO
from radicalbit_ai_gateway.db.database import BaseTable, Reflected


class ProjectBudgetLimit(Reflected, BaseTable, BaseDAO):
    __tablename__ = 'project_budget_limit'
    __table_args__ = (
        UniqueConstraint(
            'PROJECT_UUID',
            'ALGORITHM',
            'WINDOW_SIZE',
            name='uq_project_budget_limit_PROJECT_UUID_ALGORITHM_WINDOW_SIZE',
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
    algorithm: Mapped[str] = mapped_column('ALGORITHM', VARCHAR(), nullable=False)
    window_size: Mapped[str] = mapped_column('WINDOW_SIZE', VARCHAR(), nullable=False)
    max_value: Mapped[Decimal] = mapped_column('MAX_VALUE', NUMERIC(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        'CREATED_AT', TIMESTAMP(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        'UPDATED_AT', TIMESTAMP(timezone=True), nullable=False
    )
