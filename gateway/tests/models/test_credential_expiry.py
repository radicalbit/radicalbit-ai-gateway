import datetime

from freezegun import freeze_time
import pytest

from radicalbit_ai_gateway.models.credential_expiry import (
    CredentialState,
    get_credential_state,
    utc_today,
)

_UTC = getattr(datetime, 'UTC', datetime.timezone.utc)

EXPIRES_ON = datetime.date(2026, 11, 10)


def _at(*args) -> datetime.datetime:
    return datetime.datetime(*args, tzinfo=_UTC)


@pytest.mark.parametrize(
    ('expires_on', 'now', 'expected'),
    [
        pytest.param(
            None, _at(2026, 11, 10, 12), CredentialState.ACTIVE, id='no expiry date'
        ),
        pytest.param(
            EXPIRES_ON,
            _at(2026, 11, 8, 23, 59, 59, 999999),
            CredentialState.ACTIVE,
            id='just before 00:00 UTC on the day before',
        ),
        pytest.param(
            EXPIRES_ON,
            _at(2026, 11, 9),
            CredentialState.EXPIRING,
            id='00:00 UTC on the day before',
        ),
        pytest.param(
            EXPIRES_ON,
            _at(2026, 11, 10, 23, 59, 59),
            CredentialState.EXPIRING,
            id='23:59:59 UTC on the expiry date',
        ),
        pytest.param(
            EXPIRES_ON,
            _at(2026, 11, 11),
            CredentialState.EXPIRED,
            id='00:00:00 UTC the following day',
        ),
        pytest.param(
            datetime.date(2026, 11, 10),
            _at(2026, 11, 10, 9),
            CredentialState.EXPIRING,
            id='expiry date of today',
        ),
    ],
)
def test_get_credential_state(expires_on, now, expected):
    assert get_credential_state(expires_on, now) == expected


def test_compares_against_the_utc_calendar_date_not_the_local_one():
    # 01:30 on Nov 11 in Rome is still Nov 10 in UTC: the credential has not expired yet
    rome = datetime.timezone(datetime.timedelta(hours=1))
    now = datetime.datetime(2026, 11, 11, 0, 30, tzinfo=rome)
    assert get_credential_state(EXPIRES_ON, now) == CredentialState.EXPIRING


def test_defaults_to_the_current_instant():
    with freeze_time('2026-11-11 00:00:00'):
        assert get_credential_state(EXPIRES_ON) == CredentialState.EXPIRED
    with freeze_time('2026-11-10 23:59:59'):
        assert get_credential_state(EXPIRES_ON) == CredentialState.EXPIRING


def test_utc_today():
    with freeze_time('2026-11-10 23:59:59'):
        assert utc_today() == datetime.date(2026, 11, 10)
