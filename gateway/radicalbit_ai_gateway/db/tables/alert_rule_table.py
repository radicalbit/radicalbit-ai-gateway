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
    scope = Column('SCOPE', VARCHAR(), nullable=False, default='route')
    # The project uuid. A rule stored before project uuids were used may still
    # hold a project name, which then resolves to nothing and shows as stale.
    project = Column('PROJECT', VARCHAR(), nullable=True)
    route = Column('ROUTE', VARCHAR(), nullable=True)
    credential_uuid = Column('CREDENTIAL_UUID', UUID(as_uuid=True), nullable=True)
    event = Column('EVENT', VARCHAR(), nullable=False)
    time_aggregation = Column(
        'TIME_AGGREGATION', VARCHAR(), nullable=False, default='instant'
    )
    window_size = Column('WINDOW_SIZE', VARCHAR(), nullable=True)
    channel = Column('CHANNEL', VARCHAR(), nullable=False, default='email')
    recipients = Column(
        'RECIPIENTS', TEXT(), nullable=False
    )  # Stored as JSON string list of emails
    enabled = Column('ENABLED', BOOLEAN(), nullable=False, default=False)
    deleted = Column('DELETED', BOOLEAN(), nullable=False, default=False)
    created_at = Column('CREATED_AT', TIMESTAMP(timezone=True), nullable=False)
    updated_at = Column('UPDATED_AT', TIMESTAMP(timezone=True), nullable=False)
