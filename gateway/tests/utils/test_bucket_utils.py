"""Unit tests for bucket_utils module.

Tests the timezone-aware time bucket generation utilities, with special focus on
correct month advancement using relativedelta.
"""

import datetime

from radicalbit_ai_gateway.utils.bucket_utils import (
    advance_bucket,
    calculate_start_bucket,
    get_bucket_delta,
    truncate_to_bucket,
)


class TestTruncateToBucket:
    """Tests for truncate_to_bucket function."""

    def test_truncate_hours(self):
        """Test truncating to hour boundary."""
        dt = datetime.datetime(2026, 1, 15, 14, 30, 45, 123456)
        result = truncate_to_bucket(dt, 'hours')
        assert result == datetime.datetime(2026, 1, 15, 14, 0, 0, 0)

    def test_truncate_days(self):
        """Test truncating to day boundary."""
        dt = datetime.datetime(2026, 1, 15, 14, 30, 45, 123456)
        result = truncate_to_bucket(dt, 'days')
        assert result == datetime.datetime(2026, 1, 15, 0, 0, 0, 0)

    def test_truncate_weeks(self):
        """Test truncating to week boundary (Monday)."""
        # Thursday, Jan 8, 2026
        dt = datetime.datetime(2026, 1, 8, 14, 30, 45, 123456)
        result = truncate_to_bucket(dt, 'weeks')
        # Monday, Jan 5, 2026
        assert result == datetime.datetime(2026, 1, 5, 0, 0, 0, 0)

    def test_truncate_months(self):
        """Test truncating to month boundary."""
        dt = datetime.datetime(2026, 1, 15, 14, 30, 45, 123456)
        result = truncate_to_bucket(dt, 'months')
        assert result == datetime.datetime(2026, 1, 1, 0, 0, 0, 0)


class TestGetBucketDelta:
    """Tests for get_bucket_delta function."""

    def test_hours_delta(self):
        """Test delta for hours."""
        delta = get_bucket_delta('hours')
        assert delta == datetime.timedelta(hours=1)

    def test_days_delta(self):
        """Test delta for days."""
        delta = get_bucket_delta('days')
        assert delta == datetime.timedelta(days=1)

    def test_weeks_delta(self):
        """Test delta for weeks."""
        delta = get_bucket_delta('weeks')
        assert delta == datetime.timedelta(weeks=1)

    def test_months_delta(self):
        """Test delta for months returns empty timedelta."""
        delta = get_bucket_delta('months')
        # Months are handled specially in advance_bucket using relativedelta
        assert delta == datetime.timedelta()


class TestAdvanceBucket:
    """Tests for advance_bucket function."""

    def test_advance_hours(self):
        """Test advancing hour buckets."""
        bucket = datetime.datetime(2026, 1, 15, 14, 0, 0, 0)
        delta = datetime.timedelta(hours=1)
        result = advance_bucket(bucket, 'hours', delta, 0)
        assert result == datetime.datetime(2026, 1, 15, 15, 0, 0, 0)

    def test_advance_days(self):
        """Test advancing day buckets."""
        bucket = datetime.datetime(2026, 1, 15, 0, 0, 0, 0)
        delta = datetime.timedelta(days=1)
        result = advance_bucket(bucket, 'days', delta, 0)
        assert result == datetime.datetime(2026, 1, 16, 0, 0, 0, 0)

    def test_advance_weeks(self):
        """Test advancing week buckets."""
        bucket = datetime.datetime(2026, 1, 5, 0, 0, 0, 0)  # Monday
        delta = datetime.timedelta(weeks=1)
        result = advance_bucket(bucket, 'weeks', delta, 0)
        assert result == datetime.datetime(2026, 1, 12, 0, 0, 0, 0)

    def test_advance_months_utc_jan_to_feb(self):
        """Test advancing from January to February in UTC."""
        bucket = datetime.datetime(2026, 1, 1, 0, 0, 0, 0)
        delta = datetime.timedelta()
        result = advance_bucket(bucket, 'months', delta, 0)
        assert result == datetime.datetime(2026, 2, 1, 0, 0, 0, 0)

    def test_advance_months_utc_jan31_to_feb(self):
        """Test advancing from Jan 31 to Feb 1 in UTC."""
        # Even if bucket is Jan 31, should advance to Feb 1
        bucket = datetime.datetime(2026, 1, 31, 0, 0, 0, 0)
        delta = datetime.timedelta()
        result = advance_bucket(bucket, 'months', delta, 0)
        assert result == datetime.datetime(2026, 2, 1, 0, 0, 0, 0)

    def test_advance_months_utc_oct_to_nov(self):
        """Test advancing from October to November in UTC."""
        bucket = datetime.datetime(2024, 10, 1, 0, 0, 0, 0)
        delta = datetime.timedelta()
        result = advance_bucket(bucket, 'months', delta, 0)
        assert result == datetime.datetime(2024, 11, 1, 0, 0, 0, 0)

    def test_advance_months_utc_oct31_to_nov(self):
        """Test advancing from Oct 31 to Nov 1 in UTC."""
        # This was the bug: Oct 31 + 32 days = Dec 2, which would skip November
        bucket = datetime.datetime(2024, 10, 31, 0, 0, 0, 0)
        delta = datetime.timedelta()
        result = advance_bucket(bucket, 'months', delta, 0)
        assert result == datetime.datetime(2024, 11, 1, 0, 0, 0, 0)

    def test_advance_months_utc_dec_to_jan_next_year(self):
        """Test advancing from December to January of next year."""
        bucket = datetime.datetime(2024, 12, 1, 0, 0, 0, 0)
        delta = datetime.timedelta()
        result = advance_bucket(bucket, 'months', delta, 0)
        assert result == datetime.datetime(2025, 1, 1, 0, 0, 0, 0)

    def test_advance_months_leap_year_feb_to_mar(self):
        """Test advancing from February to March in leap year."""
        bucket = datetime.datetime(2024, 2, 1, 0, 0, 0, 0)  # 2024 is a leap year
        delta = datetime.timedelta()
        result = advance_bucket(bucket, 'months', delta, 0)
        assert result == datetime.datetime(2024, 3, 1, 0, 0, 0, 0)

    def test_advance_months_leap_year_feb29_to_mar(self):
        """Test advancing from Feb 29 to Mar 1 in leap year."""
        bucket = datetime.datetime(2024, 2, 29, 0, 0, 0, 0)
        delta = datetime.timedelta()
        result = advance_bucket(bucket, 'months', delta, 0)
        assert result == datetime.datetime(2024, 3, 1, 0, 0, 0, 0)

    def test_advance_months_with_gmt_plus_1(self):
        """Test advancing months with GMT+01:00 offset."""
        # User is in GMT+01:00, so UTC timestamps are shifted
        # Oct 1, 2024 00:00 GMT+01:00 = Sep 30, 2024 23:00 UTC
        bucket = datetime.datetime(2024, 9, 30, 23, 0, 0, 0)
        delta = datetime.timedelta()
        offset_seconds = 3600  # GMT+01:00
        result = advance_bucket(bucket, 'months', delta, offset_seconds)
        # Nov 1, 2024 00:00 GMT+01:00 = Oct 31, 2024 23:00 UTC
        assert result == datetime.datetime(2024, 10, 31, 23, 0, 0, 0)

    def test_advance_months_with_gmt_minus_5(self):
        """Test advancing months with GMT-05:00 offset."""
        # User is in GMT-05:00
        # Jan 1, 2026 00:00 GMT-05:00 = Jan 1, 2026 05:00 UTC
        bucket = datetime.datetime(2026, 1, 1, 5, 0, 0, 0)
        delta = datetime.timedelta()
        offset_seconds = -18000  # GMT-05:00
        result = advance_bucket(bucket, 'months', delta, offset_seconds)
        # Feb 1, 2026 00:00 GMT-05:00 = Feb 1, 2026 05:00 UTC
        assert result == datetime.datetime(2026, 2, 1, 5, 0, 0, 0)

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

    def test_advance_months_oct31_with_offset_gmt_plus_2(self):
        """Test the specific bug case: Oct 31 with GMT+02:00 offset.

        This was the case that caused month skipping:
        Oct 31, 2024 22:00 UTC (Nov 1, 00:00 GMT+02:00)
        With old logic: Oct 31 + 32 days = Dec 2, skip November
        With new logic: Oct 31 + 1 month = Nov 30 (which becomes Nov 1 in user's TZ)
        """
        # Oct 31, 2024 00:00 GMT+02:00 = Sep 30, 2024 22:00 UTC
        bucket = datetime.datetime(2024, 9, 30, 22, 0, 0, 0)
        delta = datetime.timedelta()
        offset_seconds = 7200  # GMT+02:00

        result = advance_bucket(bucket, 'months', delta, offset_seconds)

        # Nov 1, 2024 00:00 GMT+02:00 = Oct 31, 2024 22:00 UTC
        assert result == datetime.datetime(2024, 10, 31, 22, 0, 0, 0)

        # Verify it's actually November (not December)
        # In user's timezone: result + offset = Nov 1, 2024 00:00
        user_tz_result = result + datetime.timedelta(seconds=offset_seconds)
        assert user_tz_result.month == 11
        assert user_tz_result.day == 1


class TestCalculateStartBucket:
    """Tests for calculate_start_bucket function."""

    def test_calculate_start_bucket_utc_hours(self):
        """Test calculating start bucket for hours in UTC."""
        dt = datetime.datetime(2026, 1, 15, 14, 30, 0, 0)
        start_bucket, delta = calculate_start_bucket(dt, 'hours', 0)
        assert start_bucket == datetime.datetime(2026, 1, 15, 14, 0, 0, 0)
        assert delta == datetime.timedelta(hours=1)

    def test_calculate_start_bucket_with_offset_days(self):
        """Test calculating start bucket for days with timezone offset."""
        # User in GMT+01:00 queries at 2026-01-15 14:30 their time
        # which is 2026-01-15 13:30 UTC
        dt = datetime.datetime(2026, 1, 15, 13, 30, 0, 0)
        offset_seconds = 3600  # GMT+01:00
        start_bucket, delta = calculate_start_bucket(dt, 'days', offset_seconds)

        # Should be aligned to user's day boundary: 2026-01-15 00:00 GMT+01:00
        # which is 2026-01-14 23:00 UTC
        assert start_bucket == datetime.datetime(2026, 1, 14, 23, 0, 0, 0)
        assert delta == datetime.timedelta(days=1)

    def test_calculate_start_bucket_with_offset_months(self):
        """Test calculating start bucket for months with timezone offset."""
        # User in GMT+01:00 queries at 2026-01-15 14:30 their time
        # which is 2026-01-15 13:30 UTC
        dt = datetime.datetime(2026, 1, 15, 13, 30, 0, 0)
        offset_seconds = 3600  # GMT+01:00
        start_bucket, delta = calculate_start_bucket(dt, 'months', offset_seconds)

        # Should be aligned to user's month boundary: 2026-01-01 00:00 GMT+01:00
        # which is 2025-12-31 23:00 UTC
        assert start_bucket == datetime.datetime(2025, 12, 31, 23, 0, 0, 0)
        assert delta == datetime.timedelta()
