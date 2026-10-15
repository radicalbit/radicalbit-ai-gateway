import datetime
from enum import Enum

UTC = getattr(datetime, 'UTC', datetime.timezone.utc)


class CredentialState(str, Enum):
    ACTIVE = 'active'
    EXPIRING = 'expiring'
    EXPIRED = 'expired'


def utc_today() -> datetime.date:
    return datetime.datetime.now(tz=UTC).date()


def get_credential_state(
    expires_on: datetime.date | None, now: datetime.datetime | None = None
) -> CredentialState:
    """State of a credential at an instant, comparing the instant's UTC
    calendar date with the expiry date. A credential expiring on D is valid
    up to 23:59:59 UTC on D, and is shown as expiring from 00:00 UTC on D-1.
    """
    if expires_on is None:
        return CredentialState.ACTIVE
    today = (now or datetime.datetime.now(tz=UTC)).astimezone(UTC).date()
    if today > expires_on:
        return CredentialState.EXPIRED
    if today >= expires_on - datetime.timedelta(days=1):
        return CredentialState.EXPIRING
    return CredentialState.ACTIVE
