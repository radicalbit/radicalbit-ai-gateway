"""Unit tests for chart_utils module."""

import datetime

import pytest

from radicalbit_ai_gateway.utils.chart_utils import get_bucket_end_timestamp

dt = datetime.datetime
UTC = datetime.timezone.utc


@pytest.mark.parametrize(
    ('start', 'unit', 'expected'),
    [
        pytest.param(dt(2026, 1, 15, 14, 30), 'hours', dt(2026, 1, 15, 15, 30), id='hours'),
        pytest.param(dt(2026, 1, 15, 14, 30), 'days', dt(2026, 1, 16, 14, 30), id='days'),
        pytest.param(dt(2026, 1, 15, 14, 30), 'weeks', dt(2026, 1, 22, 14, 30), id='weeks'),
        pytest.param(dt(2026, 1, 15, 14, 30), 'months', dt(2026, 2, 15, 14, 30), id='months'),
        # relativedelta clamps Jan 31 + 1 month to the end of February.
        pytest.param(dt(2026, 1, 31), 'months', dt(2026, 2, 28), id='jan31-clamps-to-feb28'),
        pytest.param(dt(2024, 1, 31), 'months', dt(2024, 2, 29), id='jan31-clamps-to-feb29-leap-year'),
        pytest.param(dt(2026, 12, 1), 'months', dt(2027, 1, 1), id='dec-wraps-to-next-year'),
        pytest.param(dt(2026, 1, 15, 23, 30), 'hours', dt(2026, 1, 16, 0, 30), id='hours-day-boundary'),
        pytest.param(
            dt(2026, 1, 15, 12, tzinfo=UTC), 'days', dt(2026, 1, 16, 12, tzinfo=UTC),
            id='preserves-timezone',
        ),
    ],
)  # fmt: skip
def test_get_bucket_end_timestamp(start, unit, expected):
    result = get_bucket_end_timestamp(start, unit)
    assert result == expected
    assert result.tzinfo == expected.tzinfo
