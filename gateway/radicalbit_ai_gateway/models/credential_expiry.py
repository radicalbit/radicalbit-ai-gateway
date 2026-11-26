import datetime as dt
from enum import Enum

UTC = getattr(dt, 'UTC', dt.timezone.utc)


class CredentialState(str, Enum):
    ACTIVE = 'active'
    EXPIRING = 'expiring'
    EXPIRED = 'expired'


def utc_today() -> dt.date:
    return dt.datetime.now(tz=UTC).date()


def get_expiry_instant(expires_on: dt.date) -> dt.datetime:
    """Return the last instant a credential expiring on that date still works."""
    return dt.datetime.combine(expires_on, dt.time(23, 59, 59), tzinfo=UTC)


def get_credential_state(
    expires_on: dt.date | None, now: dt.datetime | None = None
) -> CredentialState:
    """State of a credential at an instant, comparing the instant's UTC
    calendar date with the expiry date. A credential expiring on D is valid
    up to 23:59:59 UTC on D, and is shown as expiring from 00:00 UTC on D-1.
    """
    if expires_on is None:
        return CredentialState.ACTIVE
    today = (now or dt.datetime.now(tz=UTC)).astimezone(UTC).date()
    if today > expires_on:
        return CredentialState.EXPIRED
    if today >= expires_on - dt.timedelta(days=1):
        return CredentialState.EXPIRING
    return CredentialState.ACTIVE
