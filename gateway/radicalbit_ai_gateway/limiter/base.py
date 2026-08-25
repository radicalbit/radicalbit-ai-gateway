"""Base class for fixed window limiters."""

from __future__ import annotations

from abc import ABC, abstractmethod
import time

from radicalbit_ai_gateway.limiter.storage.base import Storage
from radicalbit_ai_gateway.limiter.window_config import WindowConfig, WindowStats


class BaseFixedWindowLimiter(ABC):
    """Abstract base for fixed window limiters."""

    def __init__(self, storage: Storage) -> None:
        """Initialize the limiter.

        Args:
            storage: The storage backend to use for persisting counters.

        """
        self._storage = storage

    @property
    @abstractmethod
    def _window_type(self) -> str:
        """Return the window type identifier (e.g., 'fixed', 'aligned')."""

    def _build_key(self, config: WindowConfig) -> str:
        """Build the storage key from config.

        Key format: limiter:{project_uuid}:{route_name}:{scenario_type}:{window_type}:{window_seconds}
        Example: limiter:0e6f...:my-route:token_input:fixed:60

        Route names are unique only within a project, so the project segment
        is what stops two projects sharing one window. It is always present:
        ``project_uuid`` is a required field. Passing an empty string yields a
        third, malformed keyspace (``limiter::route:...``) that matches neither
        the scoped nor the pre-fix format — callers must supply a real uuid.
        """
        return f'limiter:{config.project_uuid}:{config.route_name}:{config.scenario_type.value}:{self._window_type}:{config.window_seconds}'

    async def test(self, item: WindowConfig, cost: int = 1) -> bool:
        """Test if operation is allowed WITHOUT consuming capacity.

        Args:
            item: Limit configuration.
            cost: Cost of the operation (default 1).

        Returns:
            True if operation is allowed, False otherwise.

        """
        key = self._build_key(item)
        current = await self._storage.get(key)
        if current is None:
            return cost <= item.limit
        return current + cost <= item.limit

    async def hit(self, item: WindowConfig, cost: int = 1) -> bool:
        """Consume capacity and return True if within limit.

        Args:
            item: Limit configuration.
            cost: Cost of the operation (default 1).

        Returns:
            True if operation was allowed and consumed, False if limit exceeded.

        """
        key = self._build_key(item)
        window_start, ttl_remaining = self._calculate_window_boundary(
            item.window_seconds
        )
        new_value, _ = await self._storage.increment(
            key, cost, ttl_remaining, window_start
        )
        return new_value <= item.limit

    async def get_window_stats(self, item: WindowConfig) -> WindowStats:
        """Get remaining capacity and reset time for a window.

        Args:
            item: Limit configuration.

        Returns:
            WindowStats with remaining capacity, reset timestamp, and window ID.

        """
        key = self._build_key(item)
        current = await self._storage.get(key)
        if current is None:
            return self._empty_stats(item)

        ttl = await self._storage.get_ttl(key)
        if ttl is None:
            # Window expired between get and get_ttl - recalculate
            return self._empty_stats(item)

        window_id = await self._storage.get_window_id(key)
        remaining = max(0, item.limit - current)
        current_time = int(time.time())
        remaining_time = max(0, ttl - current_time)
        return WindowStats(
            remaining=remaining,
            reset_time=ttl,
            window_id=window_id,
            remaining_time=remaining_time,
        )

    @abstractmethod
    def _calculate_window_boundary(self, window_seconds: int) -> tuple[int, int]:
        """Calculate window start and TTL.

        Args:
            window_seconds: Window duration in seconds.

        Returns:
            Tuple of (window_start, ttl_remaining).

        """

    @abstractmethod
    def _empty_stats(self, item: WindowConfig) -> WindowStats:
        """Create stats for non-existent window.

        Args:
            item: Limit configuration.

        Returns:
            WindowStats with full remaining capacity and appropriate reset time.

        """
