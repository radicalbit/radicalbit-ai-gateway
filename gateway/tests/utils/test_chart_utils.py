"""Unit tests for chart_utils module."""

import datetime

from radicalbit_ai_gateway.utils.chart_utils import get_bucket_end_timestamp


class TestGetBucketEndTimestamp:
    """Tests for get_bucket_end_timestamp function."""

    def test_hours(self):
        dt = datetime.datetime(2026, 1, 15, 14, 30, 0)
        assert get_bucket_end_timestamp(dt, 'hours') == datetime.datetime(
            2026, 1, 15, 15, 30, 0
        )

    def test_days(self):
        dt = datetime.datetime(2026, 1, 15, 14, 30, 0)
        assert get_bucket_end_timestamp(dt, 'days') == datetime.datetime(
            2026, 1, 16, 14, 30, 0
        )

    def test_weeks(self):
        dt = datetime.datetime(2026, 1, 15, 14, 30, 0)
        assert get_bucket_end_timestamp(dt, 'weeks') == datetime.datetime(
            2026, 1, 22, 14, 30, 0
        )

    def test_months(self):
        dt = datetime.datetime(2026, 1, 15, 14, 30, 0)
        assert get_bucket_end_timestamp(dt, 'months') == datetime.datetime(
            2026, 2, 15, 14, 30, 0
        )

    def test_months_jan31_clamps_to_feb28(self):
        """Relativedelta clamps Jan 31 + 1 month to Feb 28 on non-leap year."""
        dt = datetime.datetime(2026, 1, 31, 0, 0, 0)
        assert get_bucket_end_timestamp(dt, 'months') == datetime.datetime(
            2026, 2, 28, 0, 0, 0
        )

    def test_months_jan31_clamps_to_feb29_on_leap_year(self):
        """Relativedelta clamps Jan 31 + 1 month to Feb 29 on leap year."""
        dt = datetime.datetime(2024, 1, 31, 0, 0, 0)
        assert get_bucket_end_timestamp(dt, 'months') == datetime.datetime(
            2024, 2, 29, 0, 0, 0
        )

    def test_months_dec_wraps_to_next_year(self):
        dt = datetime.datetime(2026, 12, 1, 0, 0, 0)
        assert get_bucket_end_timestamp(dt, 'months') == datetime.datetime(
            2027, 1, 1, 0, 0, 0
        )

    def test_hours_day_boundary(self):
        """Advancing an hour at 23:30 crosses into the next day."""
        dt = datetime.datetime(2026, 1, 15, 23, 30, 0)
        assert get_bucket_end_timestamp(dt, 'hours') == datetime.datetime(
            2026, 1, 16, 0, 30, 0
        )

    def test_preserves_timezone(self):
        """Timezone info is preserved in the result."""
        dt = datetime.datetime(2026, 1, 15, 12, 0, 0, tzinfo=datetime.timezone.utc)
        result = get_bucket_end_timestamp(dt, 'days')
        assert result.tzinfo == datetime.timezone.utc
        assert result == datetime.datetime(
            2026, 1, 16, 12, 0, 0, tzinfo=datetime.timezone.utc
        )
