from datetime import datetime
from uuid import UUID as PyUUID, uuid4

from sqlalchemy import BOOLEAN, TEXT, TIMESTAMP, UUID, VARCHAR
from sqlalchemy.orm import Mapped, mapped_column

from radicalbit_ai_gateway.db.dao.base_dao import BaseDAO
from radicalbit_ai_gateway.db.database import BaseTable, Reflected


class AlertRule(Reflected, BaseTable, BaseDAO):
    __tablename__ = 'alert_rule'

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
    scope: Mapped[str] = mapped_column(
        'SCOPE', VARCHAR(), nullable=False, default='route'
    )
    # The project uuid. A rule stored before project uuids were used may still
    # hold a project name, which then resolves to nothing and shows as stale.
    project: Mapped[str | None] = mapped_column('PROJECT', VARCHAR(), nullable=True)
    route: Mapped[str | None] = mapped_column('ROUTE', VARCHAR(), nullable=True)
    credential_uuid: Mapped[PyUUID | None] = mapped_column(
        'CREDENTIAL_UUID', UUID(as_uuid=True), nullable=True
    )
    event: Mapped[str] = mapped_column('EVENT', VARCHAR(), nullable=False)
    time_aggregation: Mapped[str] = mapped_column(
        'TIME_AGGREGATION', VARCHAR(), nullable=False, default='instant'
    )
    window_size: Mapped[str | None] = mapped_column(
        'WINDOW_SIZE', VARCHAR(), nullable=True
    )
    channel: Mapped[str] = mapped_column(
        'CHANNEL', VARCHAR(), nullable=False, default='email'
    )
    # Stored as JSON string list of emails
    recipients: Mapped[str] = mapped_column('RECIPIENTS', TEXT(), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        'ENABLED', BOOLEAN(), nullable=False, default=False
    )
    deleted: Mapped[bool] = mapped_column(
        'DELETED', BOOLEAN(), nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        'CREATED_AT', TIMESTAMP(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        'UPDATED_AT', TIMESTAMP(timezone=True), nullable=False
    )
