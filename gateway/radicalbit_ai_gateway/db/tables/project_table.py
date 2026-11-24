from datetime import datetime
from uuid import UUID as PyUUID, uuid4

from sqlalchemy import TEXT, TIMESTAMP, UUID, VARCHAR, ForeignKey, Index, text
from sqlalchemy.orm import Mapped, mapped_column

from radicalbit_ai_gateway.db.dao.base_dao import BaseDAO
from radicalbit_ai_gateway.db.database import BaseTable, Reflected


class Project(Reflected, BaseTable, BaseDAO):
    __tablename__ = 'project'
    __table_args__ = (
        Index(
            'uq_project_NAME',
            'NAME',
            unique=True,
            postgresql_where=text('"DELETED_AT" IS NULL'),
        ),
    )
    uuid: Mapped[PyUUID] = mapped_column(
        'UUID',
        UUID(as_uuid=True),
        nullable=False,
        default=uuid4,
        primary_key=True,
    )
    name: Mapped[str] = mapped_column('NAME', VARCHAR(), nullable=False)
    description: Mapped[str | None] = mapped_column(
        'DESCRIPTION', TEXT(), nullable=True
    )
    served_config_uuid: Mapped[PyUUID | None] = mapped_column(
        'SERVED_CONFIG_UUID',
        UUID(as_uuid=True),
        ForeignKey(
            'project_config.UUID',
            ondelete='SET NULL',
            use_alter=True,
            name='fk_project_SERVED_CONFIG_UUID_project_config',
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        'CREATED_AT', TIMESTAMP(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        'UPDATED_AT', TIMESTAMP(timezone=True), nullable=False
    )
    first_served_at: Mapped[datetime | None] = mapped_column(
        'FIRST_SERVED_AT', TIMESTAMP(timezone=True), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        'DELETED_AT', TIMESTAMP(timezone=True), nullable=True
    )


# Register the referenced table in the shared metadata so the
# SERVED_CONFIG_UUID foreign key can always be resolved (e.g. on create_all).
from radicalbit_ai_gateway.db.tables import project_config_table  # noqa: E402, F401
