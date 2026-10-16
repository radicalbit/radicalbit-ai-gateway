import datetime

import pytest

from radicalbit_ai_gateway.models.credential_rotation import (
    GracePeriodOutOfBoundsError,
    RotationState,
    get_grace_end,
    get_rotation_state,
    parse_grace_period,
    previous_value_authenticates,
)

_UTC = getattr(datetime, 'UTC', datetime.timezone.utc)

ROTATED_AT = datetime.datetime(2026, 11, 1, 12, tzinfo=_UTC)
GRACE_ENDS_AT = datetime.datetime(2026, 11, 4, 12, tzinfo=_UTC)
EXPIRES_ON = datetime.date(2026, 11, 3)


def _at(*args) -> datetime.datetime:
    return datetime.datetime(*args, tzinfo=_UTC)


@pytest.mark.parametrize(
    ('expires_on', 'grace_ends_at', 'last_rotated_at', 'now', 'state', 'previous'),
    [
        pytest.param(
            None, None, None, _at(2026, 11, 2), RotationState.NONE, False,
            id='never rotated',
        ),
        pytest.param(
            None, GRACE_ENDS_AT, ROTATED_AT, _at(2026, 11, 2),
            RotationState.IN_GRACE, True,
            id='inside the grace period',
        ),
        pytest.param(
            None, GRACE_ENDS_AT, ROTATED_AT, _at(2026, 11, 3, 11, 59, 59),
            RotationState.IN_GRACE, True,
            id='just over 24 hours before the grace end',
        ),
        pytest.param(
            None, GRACE_ENDS_AT, ROTATED_AT, _at(2026, 11, 3, 12),
            RotationState.GRACE_ENDING, True,
            id='exactly 24 hours before the grace end',
        ),
        pytest.param(
            None, GRACE_ENDS_AT, ROTATED_AT, _at(2026, 11, 4, 11, 59, 59),
            RotationState.GRACE_ENDING, True,
            id='just before the grace end',
        ),
        pytest.param(
            None, GRACE_ENDS_AT, ROTATED_AT, GRACE_ENDS_AT,
            RotationState.ROTATED, False,
            id='the grace end instant',
        ),
        pytest.param(
            None, GRACE_ENDS_AT, ROTATED_AT, _at(2026, 11, 10),
            RotationState.ROTATED, False,
            id='after the grace end',
        ),
        pytest.param(
            None, None, ROTATED_AT, _at(2026, 11, 1, 12),
            RotationState.ROTATED, False,
            id='no grace period, or ended early',
        ),
        pytest.param(
            EXPIRES_ON, GRACE_ENDS_AT, ROTATED_AT, _at(2026, 11, 3, 23, 59, 59),
            RotationState.GRACE_ENDING, True,
            id='last second before the expiry, mid-grace',
        ),
        pytest.param(
            EXPIRES_ON, GRACE_ENDS_AT, ROTATED_AT, _at(2026, 11, 4),
            RotationState.ROTATED, False,
            id='an expiry during the grace period',
        ),
    ],
)  # fmt: skip
def test_rotation_state(
    expires_on, grace_ends_at, last_rotated_at, now, state, previous
):
    assert get_rotation_state(expires_on, grace_ends_at, last_rotated_at, now) == state
    assert previous_value_authenticates(expires_on, grace_ends_at, now) is previous


@pytest.mark.parametrize(
    ('text', 'expected'),
    [
        ('1 hour', datetime.timedelta(hours=1)),
        ('24 hours', datetime.timedelta(hours=24)),
        ('1 day', datetime.timedelta(days=1)),
        ('3 days', datetime.timedelta(days=3)),
        ('2 weeks', datetime.timedelta(weeks=2)),
        (' 1 week ', datetime.timedelta(weeks=1)),
        ('365 days', datetime.timedelta(days=365)),
        ('8760 hours', datetime.timedelta(days=365)),
        ('52 weeks', datetime.timedelta(weeks=52)),
        ('1 month', datetime.timedelta(days=30)),
        ('90 minutes', datetime.timedelta(minutes=90)),
        ('3600 seconds', datetime.timedelta(hours=1)),
        ('2 Days', datetime.timedelta(days=2)),
    ],
)
def test_parse_grace_period(text, expected):
    assert parse_grace_period(text) == expected


@pytest.mark.parametrize(
    'text',
    ['0 hours', '30 minutes', '1 fortnight', 'hours', '-1 hour', '1.5 hours', ''],
)
def test_parse_grace_period_rejects_other_shapes_and_units(text):
    with pytest.raises(ValueError):
        parse_grace_period(text)


@pytest.mark.parametrize(
    'text',
    ['366 days', '8761 hours', '53 weeks', '13 months', '99999999999999999999 weeks'],
)
def test_parse_grace_period_rejects_more_than_one_year(text):
    with pytest.raises(ValueError, match='at most 1 year'):
        parse_grace_period(text)


NOW = _at(2026, 11, 3, 12)


def test_grace_end_is_now_plus_the_duration():
    assert get_grace_end(datetime.timedelta(hours=24), None, NOW) == _at(
        2026, 11, 4, 12
    )


def test_no_grace_period_has_no_grace_end():
    assert get_grace_end(None, EXPIRES_ON, NOW) is None


def test_grace_end_may_reach_the_last_second_of_the_expiry_date():
    to_last_second = datetime.timedelta(hours=11, minutes=59, seconds=59)
    end = get_grace_end(to_last_second, EXPIRES_ON, NOW)
    assert end == _at(2026, 11, 3, 23, 59, 59)


def test_grace_end_after_the_expiry_is_refused():
    with pytest.raises(
        GracePeriodOutOfBoundsError, match='after the credential expires'
    ):
        get_grace_end(datetime.timedelta(hours=12), EXPIRES_ON, NOW)


def test_within_one_hour_of_the_expiry_only_no_grace_period_is_accepted():
    now = _at(2026, 11, 3, 23, 0, 0)  # 59:59 left before 23:59:59 UTC
    assert get_grace_end(None, EXPIRES_ON, now) is None
    with pytest.raises(GracePeriodOutOfBoundsError, match='less than 1 hour'):
        get_grace_end(datetime.timedelta(hours=1), EXPIRES_ON, now)
