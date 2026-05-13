"""Utility functions for chart data generation and aggregation.

This module provides helper functions for chart-related operations including:
- Granularity determination based on time ranges
- Timezone-aware datetime preparation
- Bucket timestamp generation
- ClickHouse timezone offset helpers
"""

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from dateutil.relativedelta import relativedelta
from sqlalchemy import func as F

from radicalbit_ai_gateway.utils.bucket_utils import (
    advance_bucket,
    calculate_start_bucket,
)

# Thresholds for granularity selection (in hours/days)
# Note: _WEEKS_THRESHOLD is in DAYS, not hours
_HOURS_THRESHOLD = 48  # Use hours for ranges up to 48 hours
_DAYS_THRESHOLD = 48  # Use days for ranges up to 48 days
_WEEKS_THRESHOLD = 336  # Use weeks for ranges up to 336 days (48 weeks)


def determine_granularity(
    _from: datetime | None, _to: datetime | None
) -> Literal['hours', 'days', 'weeks', 'months']:
    """Determine appropriate granularity based on time range.

    Args:
        _from: Start datetime (optional)
        _to: End datetime (optional)

    Returns:
        Granularity string: 'hours', 'days', 'weeks', or 'months'

    """
    if _from is None:
        return 'weeks'

    to_dt = _to if _to else datetime.now(timezone.utc)
    delta = to_dt - _from
    delta_seconds = delta.total_seconds()
    delta_hours = delta_seconds / 3600
    delta_days = delta_seconds / 86400

    # Add one minute buffer
    one_minute_in_hours = 1 / 60
    one_minute_in_days = 1 / 60 / 24

    if delta_hours <= _HOURS_THRESHOLD + one_minute_in_hours:
        return 'hours'
    if delta_days <= _DAYS_THRESHOLD + one_minute_in_days:
        return 'days'
    if delta_days <= _WEEKS_THRESHOLD:
        return 'weeks'
    return 'months'


def prepare_chart_time_range(
    _from: datetime | None,
    _to: datetime | None,
) -> tuple[datetime | None, datetime | None, int]:
    """Prepare datetime range for chart queries.

    Converts to UTC and calculates timezone offset for bucket alignment.

    Args:
        _from: Start datetime in any timezone
        _to: End datetime in any timezone

    Returns:
        Tuple of (from_utc, to_utc, timezone_offset_seconds)

    """
    _from_utc = _from.astimezone(timezone.utc) if _from else None
    _to_utc = _to.astimezone(timezone.utc) if _to else None

    timezone_offset_seconds = (
        int(_from.utcoffset().total_seconds()) if _from and _from.utcoffset() else 0
    )

    return _from_utc, _to_utc, timezone_offset_seconds


def generate_chart_timestamps(
    _from_utc: datetime,
    _to_utc: datetime,
    granularity: Literal['hours', 'days', 'weeks', 'months'],
    timezone_offset_seconds: int,
) -> list[int]:
    """Generate all bucket timestamps for a chart time range.

    Args:
        _from_utc: Start datetime in UTC
        _to_utc: End datetime in UTC
        granularity: Time bucket granularity
        timezone_offset_seconds: Timezone offset for bucket alignment

    Returns:
        List of Unix timestamps for each bucket

    """
    start_bucket, delta = calculate_start_bucket(
        _from_utc, granularity, timezone_offset_seconds
    )

    all_timestamps = []
    current_bucket = start_bucket

    while current_bucket <= _to_utc:
        all_timestamps.append(int(current_bucket.timestamp()))
        current_bucket = advance_bucket(
            current_bucket, granularity, delta, timezone_offset_seconds
        )

    return all_timestamps


def with_timezone_offset(
    bucket_func: Callable,
    offset_seconds: int,
    timestamp_column: Any,
) -> Any:
    """Wrap a ClickHouse bucket function to work with timezone offset.

    ClickHouse bucket functions (toStartOfDay, toStartOfWeek, etc.) work in UTC.
    To get buckets aligned to a user's timezone, we shift the timestamp by the offset,
    apply the bucket function, then shift back.

    Args:
        bucket_func: A ClickHouse bucket function like F.toStartOfDay
        offset_seconds: Timezone offset in seconds (positive for GMT+X, negative for GMT-X)
        timestamp_column: The timestamp column to apply the bucket function to

    Returns:
        A SQL expression that produces timezone-aligned buckets

    """
    if offset_seconds == 0:
        return bucket_func(timestamp_column)
    return F.addSeconds(
        bucket_func(F.addSeconds(timestamp_column, offset_seconds)),
        -offset_seconds,
    )


def get_bucket_function(
    granularity: Literal['hours', 'days', 'weeks', 'months'],
) -> Callable:
    """Get the ClickHouse bucket function for a given granularity.

    Args:
        granularity: Time bucket granularity

    Returns:
        The corresponding ClickHouse bucket function.
        For weeks, mode=1 is used to start weeks on Monday.

    Raises:
        ValueError: If granularity is not supported

    """
    match granularity:
        case 'hours':
            return F.toStartOfHour
        case 'days':
            return F.toStartOfDay
        case 'weeks':
            return lambda ts: F.toStartOfWeek(ts, 1)
        case 'months':
            return F.toStartOfMonth
        case _:
            raise ValueError(f'Unsupported granularity: {granularity}')


def calculate_increment_percentage(data: list[int | float]) -> float:
    """Calculate percentage change between last two data points.

    Formula: ((last_bucket - prev_bucket) / prev_bucket) * 100

    Returns 0.0 if insufficient data
    Returns 0.0 if the last two data points are 0 (no increment)
    Returns 100.0 if previous bucket is 0 (division by 0) and last bucket is not 0, which means a full increment
    """
    if len(data) < 2:
        return 0.0

    last_bucket = data[-1]
    prev_bucket = data[-2]

    if prev_bucket == 0 and last_bucket == 0:
        return 0.0

    if prev_bucket == 0 and last_bucket != 0:
        return 100.0

    return ((last_bucket - prev_bucket) / prev_bucket) * 100


def get_bucket_end_timestamp(
    _from: datetime,
    granularity: Literal['hours', 'days', 'weeks', 'months'],
) -> datetime:
    """Return the datetime that is exactly one granularity unit after _from.

    Args:
        _from: The starting datetime
        granularity: The time unit to advance by

    Returns:
        _from + 1 unit of granularity

    """
    match granularity:
        case 'hours':
            return _from + timedelta(hours=1)
        case 'days':
            return _from + timedelta(days=1)
        case 'weeks':
            return _from + timedelta(weeks=1)
        case 'months':
            return _from + relativedelta(months=1)
