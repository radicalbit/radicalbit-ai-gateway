import datetime
from enum import Enum

from radicalbit_ai_gateway.limiter.window_config import parse_window
from radicalbit_ai_gateway.models.credential_expiry import (
    UTC,
    CredentialState,
    get_credential_state,
    get_expiry_instant,
)

GRACE_ENDING_WINDOW = datetime.timedelta(hours=24)
MIN_GRACE_PERIOD = datetime.timedelta(hours=1)

# Compared in seconds, so an absurd N is refused before any date arithmetic
_MIN_GRACE_PERIOD_SECONDS = int(MIN_GRACE_PERIOD.total_seconds())
_MAX_GRACE_PERIOD_SECONDS = 365 * 24 * 60 * 60


class GracePeriodOutOfBoundsError(ValueError):
    pass


def parse_grace_period(text: str) -> datetime.timedelta:
    """Parse a grace period in the same "N unit" format as limit windows."""
    seconds = parse_window(text)
    if seconds < _MIN_GRACE_PERIOD_SECONDS:
        raise ValueError('The grace period must be at least 1 hour')
    if seconds > _MAX_GRACE_PERIOD_SECONDS:
        raise ValueError('The grace period must be at most 1 year (365 days)')
    return datetime.timedelta(seconds=seconds)


def get_grace_end(
    grace_period: datetime.timedelta | None,
    expires_on: datetime.date | None,
    now: datetime.datetime,
) -> datetime.datetime | None:
    """When a grace period starting now ends, or None for no grace period.
    It must not end after the expiry, and is refused outright within 1 hour of it.
    """
    if grace_period is None:
        return None
    grace_end = now + grace_period
    if expires_on is None:
        return grace_end
    expiry_instant = get_expiry_instant(expires_on)
    if expiry_instant - now < MIN_GRACE_PERIOD:
        raise GracePeriodOutOfBoundsError(
            'The credential expires in less than 1 hour: only no grace period is accepted'
        )
    if grace_end > expiry_instant:
        raise GracePeriodOutOfBoundsError(
            f'The grace period would end after the credential expires ({expiry_instant})'
        )
    return grace_end


class RotationState(str, Enum):
    NONE = 'none'
    IN_GRACE = 'in_grace'
    GRACE_ENDING = 'grace_ending'
    ROTATED = 'rotated'


def previous_value_authenticates(
    expires_on: datetime.date | None,
    grace_ends_at: datetime.datetime | None,
    now: datetime.datetime | None = None,
) -> bool:
    """Tell whether the previous value still authenticates: only before the grace
    end, and only while the credential has not expired.
    """
    now = now or datetime.datetime.now(tz=UTC)
    return (
        grace_ends_at is not None
        and now < grace_ends_at
        and get_credential_state(expires_on, now) != CredentialState.EXPIRED
    )


def get_rotation_state(
    expires_on: datetime.date | None,
    grace_ends_at: datetime.datetime | None,
    last_rotated_at: datetime.datetime | None,
    now: datetime.datetime | None = None,
) -> RotationState:
    if last_rotated_at is None:
        return RotationState.NONE
    now = now or datetime.datetime.now(tz=UTC)
    if not previous_value_authenticates(expires_on, grace_ends_at, now):
        return RotationState.ROTATED
    if grace_ends_at - now <= GRACE_ENDING_WINDOW:
        return RotationState.GRACE_ENDING
    return RotationState.IN_GRACE
