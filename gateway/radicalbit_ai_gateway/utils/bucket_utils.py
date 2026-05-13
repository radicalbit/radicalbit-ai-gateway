"""Utility functions for timezone-aware time bucket generation.

This module provides helper functions for creating time-based buckets that respect
user timezone offsets, used primarily for chart data aggregation.

The key insight is that ClickHouse bucket functions (toStartOfDay, toStartOfWeek,
toStartOfMonth) work in UTC. To create buckets aligned to a user's timezone, we use
a shift-truncate-shift pattern:
1. Shift the timestamp by the timezone offset
2. Truncate to the bucket boundary
3. Shift back by the timezone offset
"""

from datetime import datetime, timedelta
from typing import Literal

from dateutil.relativedelta import relativedelta


def truncate_to_bucket(
    dt: datetime,
    granularity: Literal['hours', 'days', 'weeks', 'months'],
) -> datetime:
    """Truncate a datetime to the start of its bucket.

    Args:
        dt: The datetime to truncate (may be timezone-shifted)
        granularity: The bucket granularity

    Returns:
        The datetime truncated to the bucket boundary

    """
    if granularity == 'hours':
        return dt.replace(minute=0, second=0, microsecond=0)
    if granularity == 'days':
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)
    if granularity == 'weeks':
        # ClickHouse toStartOfWeek with mode=1 starts weeks on Monday
        days_since_monday = dt.weekday()
        return (dt - timedelta(days=days_since_monday)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    # granularity == 'months'
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def get_bucket_delta(
    granularity: Literal['hours', 'days', 'weeks', 'months'],
) -> timedelta:
    """Get the timedelta for advancing to the next bucket.

    Args:
        granularity: The time granularity

    Returns:
        Timedelta representing one bucket increment

    """
    if granularity == 'hours':
        return timedelta(hours=1)
    if granularity == 'days':
        return timedelta(days=1)
    if granularity == 'weeks':
        return timedelta(weeks=1)
    # months: handled specially in advance_bucket using relativedelta
    return timedelta()


def advance_bucket(
    bucket: datetime,
    granularity: Literal['hours', 'days', 'weeks', 'months'],
    delta: timedelta,
    offset_seconds: int,
) -> datetime:
    """Advance a bucket to the next bucket boundary.

    For months, special handling is needed because month lengths vary.
    We use dateutil.relativedelta for proper month arithmetic instead of
    a fixed timedelta, which prevents month skipping (e.g., Jan 31 + 32 days
    would skip to March).

    When there's a timezone offset, we must shift, advance, then shift back.

    Args:
        bucket: The current bucket datetime in UTC
        granularity: The time granularity
        delta: The base delta from get_bucket_delta
        offset_seconds: Timezone offset in seconds (0 for UTC)

    Returns:
        The next bucket datetime in UTC

    """
    if granularity == 'months':
        if offset_seconds != 0:
            # Shift to user timezone, add one month, normalize, shift back
            offset_delta = timedelta(seconds=offset_seconds)
            shifted = bucket + offset_delta
            # Add exactly one month first, then normalize to day 1
            next_shifted = shifted + relativedelta(months=1)
            next_shifted = next_shifted.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            return next_shifted - offset_delta
        # UTC case: add one month, then normalize to day 1
        next_bucket = bucket + relativedelta(months=1)
        return next_bucket.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # For hours, days, weeks - simple addition
    return bucket + delta


def calculate_start_bucket(
    dt: datetime,
    granularity: Literal['hours', 'days', 'weeks', 'months'],
    offset_seconds: int,
) -> tuple[datetime, timedelta]:
    """Calculate the first bucket boundary and bucket size for chart data.

    Matches ClickHouse's timezone-aware bucketing: the timestamp is shifted by the
    offset, truncated to the bucket boundary, then shifted back.

    Args:
        dt: The starting datetime in UTC
        granularity: The time granularity for bucketing
        offset_seconds: Timezone offset in seconds (0 for UTC)

    Returns:
        A tuple of (start_bucket_utc, bucket_delta)

    """
    if offset_seconds == 0:
        return truncate_to_bucket(dt, granularity), get_bucket_delta(granularity)

    # Apply the same shift-truncate-shift pattern used in the DAO
    offset_delta = timedelta(seconds=offset_seconds)
    shifted = dt + offset_delta
    shifted_truncated = truncate_to_bucket(shifted, granularity)
    start_bucket = shifted_truncated - offset_delta
    return start_bucket, get_bucket_delta(granularity)
