"""Storage base class for limiting."""

from __future__ import annotations

from abc import ABC, abstractmethod


class Storage(ABC):
    """Abstract base class for limit storage backends."""

    @abstractmethod
    async def get(self, key: str) -> int | None:
        """Get current counter value.

        Args:
            key: The storage key.

        Returns:
            Current value or None if key doesn't exist or expired.

        """

    @abstractmethod
    async def get_ttl(self, key: str) -> int | None:
        """Get the expiration timestamp for a key.

        Args:
            key: The storage key.

        Returns:
            Unix timestamp (seconds) when key expires, or None if key doesn't exist.

        """

    @abstractmethod
    async def get_window_id(self, key: str) -> str | None:
        """Get the window ID for a key.

        Args:
            key: The storage key.

        Returns:
            UUID if the window exists, None otherwise.

        """

    @abstractmethod
    async def increment(
        self,
        key: str,
        amount: int,
        ttl_seconds: int,
        window_start: int,
    ) -> tuple[int, str]:
        """Increment counter for window, resetting if window changed.

        Args:
            key: The storage key.
            amount: Amount to increment by.
            ttl_seconds: Time-to-live in seconds.
            window_start: Unix timestamp (seconds) of the window start.

        Returns:
            Tuple of (new_count, window_id).

        """

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete a key's counter, if present."""

    async def get_many(self, keys: list[str]) -> list[int | None]:
        """Get several counters, in one round trip where the backend can.

        Args:
            keys: The storage keys.

        Returns:
            Each key's current value, or None if it doesn't exist or expired.

        """
        return [await self.get(key) for key in keys]

    async def increment_many(
        self, increments: list[tuple[str, int, int, int]]
    ) -> list[tuple[int, str]]:
        """Increment several counters, in one round trip where the backend can.

        Args:
            increments: ``increment``'s arguments (key, amount, ttl_seconds,
                window_start), one tuple per counter.

        Returns:
            ``increment``'s result for each, in order.

        """
        return [await self.increment(*increment) for increment in increments]
