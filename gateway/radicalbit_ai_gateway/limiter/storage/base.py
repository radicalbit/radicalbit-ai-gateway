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
