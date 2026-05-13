"""Fixed window limiter implementation."""

from __future__ import annotations

import time

from radicalbit_ai_gateway.limiter.base import BaseFixedWindowLimiter
from radicalbit_ai_gateway.limiter.window_config import WindowConfig, WindowStats


class FixedWindowLimiter(BaseFixedWindowLimiter):
    """Fixed window limiter with windows starting at first request.

    Implements a fixed window limiting algorithm where:
    - Window starts at first request
    - Each window has a maximum capacity and fixed duration
    - Counter resets when window expires
    - New window starts at next request after expiration
    """

    @property
    def _window_type(self) -> str:
        return 'fixed'

    def _calculate_window_boundary(self, window_seconds: int) -> tuple[int, int]:
        """Calculate fixed window start and TTL.

        Window starts at current timestamp, TTL is full duration.
        """
        now = time.time_ns() // 1_000_000_000
        return now, window_seconds

    def _empty_stats(self, item: WindowConfig) -> WindowStats:
        """Create WindowStats for a non-existent or expired window."""
        return WindowStats(
            remaining=item.limit,
            reset_time=(time.time_ns() // 1_000_000_000) + item.window_seconds,
            window_id=None,
            remaining_time=item.window_seconds,
        )
