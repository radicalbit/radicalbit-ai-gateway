from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AlertHistoryBucket(BaseModel):
    """Alerts of one rule in one hour, split by send outcome."""

    model_config = ConfigDict(from_attributes=True)

    rule_uuid: UUID
    rule_name: str
    bucket_start: datetime
    sent: int
    failed: int
