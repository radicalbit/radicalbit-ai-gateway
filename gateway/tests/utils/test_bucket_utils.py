"""Unit tests for bucket_utils module.

Tests the timezone-aware time bucket generation utilities, with special focus on
correct month advancement using relativedelta.
"""

import datetime

import pytest

from radicalbit_ai_gateway.utils.bucket_utils import (
    advance_bucket,
    calculate_start_bucket,
    get_bucket_delta,
    truncate_to_bucket,
)

dt = datetime.datetime
NO_DELTA = datetime.timedelta()


@pytest.mark.parametrize(
    ('value', 'unit', 'expected'),
    [
        pytest.param(
            dt(2026, 1, 15, 14, 30, 45, 123456),
            'hours',
            dt(2026, 1, 15, 14),
            id='hours',
        ),
        pytest.param(
            dt(2026, 1, 15, 14, 30, 45, 123456), 'days', dt(2026, 1, 15), id='days'
        ),
        # Thursday Jan 8 truncates to Monday Jan 5.
        pytest.param(
            dt(2026, 1, 8, 14, 30, 45, 123456),
            'weeks',
            dt(2026, 1, 5),
            id='weeks-monday',
        ),
        pytest.param(
            dt(2026, 1, 15, 14, 30, 45, 123456), 'months', dt(2026, 1, 1), id='months'
        ),
    ],
)
def test_truncate_to_bucket(value, unit, expected):
    assert truncate_to_bucket(value, unit) == expected


@pytest.mark.parametrize(
    ('unit', 'expected'),
    [
        pytest.param('hours', datetime.timedelta(hours=1), id='hours'),
        pytest.param('days', datetime.timedelta(days=1), id='days'),
        pytest.param('weeks', datetime.timedelta(weeks=1), id='weeks'),
        # Months are handled in advance_bucket with relativedelta.
        pytest.param('months', NO_DELTA, id='months-empty'),
    ],
)
def test_get_bucket_delta(unit, expected):
    assert get_bucket_delta(unit) == expected


class TestAdvanceBucket:
    """Tests for advance_bucket function."""

    @pytest.mark.parametrize(
        ('bucket', 'unit', 'delta', 'offset', 'expected'),
        [
            pytest.param(
                dt(2026, 1, 15, 14),
                'hours',
                datetime.timedelta(hours=1),
                0,
                dt(2026, 1, 15, 15),
                id='hours',
            ),
            pytest.param(
                dt(2026, 1, 15),
                'days',
                datetime.timedelta(days=1),
                0,
                dt(2026, 1, 16),
                id='days',
            ),
            pytest.param(
                dt(2026, 1, 5),
                'weeks',
                datetime.timedelta(weeks=1),
                0,
                dt(2026, 1, 12),
                id='weeks',
            ),
            pytest.param(
                dt(2026, 1, 1),
                'months',
                NO_DELTA,
                0,
                dt(2026, 2, 1),
                id='utc-jan-to-feb',
            ),
            pytest.param(
                dt(2026, 1, 31),
                'months',
                NO_DELTA,
                0,
                dt(2026, 2, 1),
                id='utc-jan31-to-feb',
            ),
            pytest.param(
                dt(2024, 10, 1),
                'months',
                NO_DELTA,
                0,
                dt(2024, 11, 1),
                id='utc-oct-to-nov',
            ),
            # Regression: Oct 31 + 32 days = Dec 2 skipped November.
            pytest.param(
                dt(2024, 10, 31),
                'months',
                NO_DELTA,
                0,
                dt(2024, 11, 1),
                id='utc-oct31-to-nov',
            ),
            pytest.param(
                dt(2024, 12, 1),
                'months',
                NO_DELTA,
                0,
                dt(2025, 1, 1),
                id='utc-dec-to-jan-next-year',
            ),
            pytest.param(
                dt(2024, 2, 1),
                'months',
                NO_DELTA,
                0,
                dt(2024, 3, 1),
                id='leap-year-feb-to-mar',
            ),
            pytest.param(
                dt(2024, 2, 29),
                'months',
                NO_DELTA,
                0,
                dt(2024, 3, 1),
                id='leap-year-feb29-to-mar',
            ),
            # Oct 1 00:00 GMT+1 = Sep 30 23:00 UTC -> Nov 1 00:00 GMT+1 = Oct 31 23:00 UTC
            pytest.param(
                dt(2024, 9, 30, 23),
                'months',
                NO_DELTA,
                3600,
                dt(2024, 10, 31, 23),
                id='gmt-plus-1',
            ),
            # Jan 1 00:00 GMT-5 = Jan 1 05:00 UTC -> Feb 1 05:00 UTC
            pytest.param(
                dt(2026, 1, 1, 5),
                'months',
                NO_DELTA,
                -18000,
                dt(2026, 2, 1, 5),
                id='gmt-minus-5',
            ),
            # Regression: Oct 1 00:00 GMT+2 = Sep 30 22:00 UTC must reach Nov 1 00:00
            # GMT+2 = Oct 31 22:00 UTC, not skip to December.
            pytest.param(
                dt(2024, 9, 30, 22),
                'months',
                NO_DELTA,
                7200,
                dt(2024, 10, 31, 22),
                id='gmt-plus-2-oct31',
            ),
        ],
    )
    def test_advance_bucket(self, bucket, unit, delta, offset, expected):
        assert advance_bucket(bucket, unit, delta, offset) == expected

    def test_advance_months_twelve_month_progression(self):
        """Test advancing through 12 months without skips or duplicates."""
        buckets = []
        bucket = datetime.datetime(2024, 1, 1, 0, 0, 0, 0)
        delta = datetime.timedelta()

        # Start with first bucket, then advance 12 times
        buckets.append(bucket)
        for _ in range(12):
            bucket = advance_bucket(bucket, 'months', delta, 0)
            buckets.append(bucket)

        # Verify we have 13 unique buckets (start + 12 advancements)
        assert len(buckets) == 13

        # Verify no duplicates
        assert len(set(buckets)) == 13

        # Verify correct months
        months = [b.month for b in buckets]
        expected_months = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 1]  # Jan-Dec-Jan
        assert months == expected_months

        # Verify correct years
        years = [b.year for b in buckets]
        expected_years = [2024] * 12 + [2025]
        assert years == expected_years

    def test_advance_months_with_offset_twelve_month_progression(self):
        """Test 12-month progression with timezone offset."""
        buckets = []
        # GMT+01:00: Jan 1, 2024 00:00 GMT+01:00 = Dec 31, 2023 23:00 UTC
        bucket = datetime.datetime(2023, 12, 31, 23, 0, 0, 0)
        delta = datetime.timedelta()
        offset_seconds = 3600  # GMT+01:00

        # Start with first bucket, then advance 12 times
        buckets.append(bucket)
        for _ in range(12):
            bucket = advance_bucket(bucket, 'months', delta, offset_seconds)
            buckets.append(bucket)

        # Verify no duplicates
        assert len(set(buckets)) == 13

        # Verify all buckets are at 23:00 UTC (00:00 GMT+01:00)
        for b in buckets:
            assert b.hour == 23
            assert b.minute == 0
            assert b.second == 0


# A GMT+01:00 user querying at 2026-01-15 14:30 local time is at 13:30 UTC;
# buckets align to the user's boundaries, expressed in UTC.
@pytest.mark.parametrize(
    ('value', 'unit', 'offset', 'expected_bucket', 'expected_delta'),
    [
        pytest.param(
            dt(2026, 1, 15, 14, 30),
            'hours',
            0,
            dt(2026, 1, 15, 14),
            datetime.timedelta(hours=1),
            id='utc-hours',
        ),
        pytest.param(
            dt(2026, 1, 15, 13, 30),
            'days',
            3600,
            dt(2026, 1, 14, 23),
            datetime.timedelta(days=1),
            id='gmt-plus-1-days',
        ),
        pytest.param(
            dt(2026, 1, 15, 13, 30),
            'months',
            3600,
            dt(2025, 12, 31, 23),
            NO_DELTA,
            id='gmt-plus-1-months',
        ),
    ],
)
def test_calculate_start_bucket(value, unit, offset, expected_bucket, expected_delta):
    assert calculate_start_bucket(value, unit, offset) == (
        expected_bucket,
        expected_delta,
    )
