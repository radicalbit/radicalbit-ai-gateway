"""Aligned fixed window limiter implementation."""

from __future__ import annotations

import time

from radicalbit_ai_gateway.limiter.base import BaseFixedWindowLimiter
from radicalbit_ai_gateway.limiter.window_config import WindowConfig, WindowStats


class AlignedFixedWindowLimiter(BaseFixedWindowLimiter):
    """Fixed window rate limiter with calendar-aligned window boundaries.

    Implements a fixed window limiting algorithm where:
    - Time is divided into fixed windows aligned to calendar time (UTC)
    - 1 day window -> starts at 00:00:00 UTC
    - 1 hour window -> starts at :00 minutes
    - Each window has a maximum capacity
    - Counter resets at window boundaries
    """

    @property
    def _window_type(self) -> str:
        return 'aligned'

    def _calculate_window_boundary(self, window_seconds: int) -> tuple[int, int]:
        """Calculate aligned window start and remaining TTL.

        Window aligned to calendar boundaries.
        """
        now = time.time_ns() // 1_000_000_000
        window_start = (now // window_seconds) * window_seconds
        window_end = window_start + window_seconds
        return window_start, window_end - now

    def _empty_stats(self, item: WindowConfig) -> WindowStats:
        """Create WindowStats for a non-existent or expired window."""
        window_start, _ = self._calculate_window_boundary(item.window_seconds)
        reset_time = window_start + item.window_seconds
        current_time = time.time_ns() // 1_000_000_000
        remaining_time = max(0, reset_time - current_time)
        return WindowStats(
            remaining=item.limit,
            reset_time=reset_time,
            window_id=None,
            remaining_time=remaining_time,
        )
