import uuid

from sqlalchemy import BOOLEAN, TEXT, TIMESTAMP, UUID, VARCHAR, Column

from radicalbit_ai_gateway.db.dao.base_dao import BaseDAO
from radicalbit_ai_gateway.db.database import BaseTable, Reflected


class AlertRule(Reflected, BaseTable, BaseDAO):
    __tablename__ = 'alert_rule'

    uuid = Column(
        'UUID',
        UUID(as_uuid=True),
        nullable=False,
        default=uuid.uuid4,
        primary_key=True,
    )
    name = Column('NAME', VARCHAR(), nullable=False)
    description = Column('DESCRIPTION', TEXT(), nullable=True)
    project = Column('PROJECT', VARCHAR(), nullable=False)
    route = Column('ROUTE', VARCHAR(), nullable=False)
    scope = Column('SCOPE', VARCHAR(), nullable=False, default='route')
    event = Column('EVENT', VARCHAR(), nullable=False)
    time_aggregation = Column(
        'TIME_AGGREGATION', VARCHAR(), nullable=False, default='instant'
    )
    channel = Column('CHANNEL', VARCHAR(), nullable=False, default='email')
    recipients = Column(
        'RECIPIENTS', TEXT(), nullable=False
    )  # Stored as JSON string list of emails
    enabled = Column('ENABLED', BOOLEAN(), nullable=False, default=False)
    disabled_reason = Column('DISABLED_REASON', TEXT(), nullable=True)
    deleted = Column('DELETED', BOOLEAN(), nullable=False, default=False)
    created_at = Column('CREATED_AT', TIMESTAMP(timezone=True), nullable=False)
    updated_at = Column('UPDATED_AT', TIMESTAMP(timezone=True), nullable=False)
