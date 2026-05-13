"""In-memory storage backend for limiting."""

from __future__ import annotations

import asyncio
import time
from typing import NamedTuple
import uuid

from radicalbit_ai_gateway.limiter.storage.base import Storage


class _Entry(NamedTuple):
    """Internal storage entry."""

    value: int
    expires_at: int
    window_id: str
    window_start: int


class InMemoryStorage(Storage):
    """Thread-safe in-memory storage for limiting.

    Uses a dictionary to store counter values with expiration timestamps.
    Lazy expiration: expired entries are cleaned up on access.
    """

    def __init__(self) -> None:
        self._data: dict[str, _Entry] = {}
        self._lock = asyncio.Lock()

    def _get_valid_entry(self, key: str) -> _Entry | None:
        """Get entry if it exists and hasn't expired, cleaning up if expired."""
        entry = self._data.get(key)
        if entry is None:
            return None

        if entry.expires_at <= time.time_ns() // 1_000_000_000:
            del self._data[key]
            return None

        return entry

    async def get(self, key: str) -> int | None:
        """Get current counter value or None if expired/missing."""
        async with self._lock:
            entry = self._get_valid_entry(key)
            return entry.value if entry else None

    async def get_ttl(self, key: str) -> int | None:
        """Get expiration timestamp or None if key doesn't exist."""
        async with self._lock:
            entry = self._get_valid_entry(key)
            return entry.expires_at if entry else None

    async def get_window_id(self, key: str) -> str | None:
        """Get the window ID for a key."""
        async with self._lock:
            entry = self._get_valid_entry(key)
            return entry.window_id if entry else None

    async def increment(
        self,
        key: str,
        amount: int,
        ttl_seconds: int,
        window_start: int,
    ) -> tuple[int, str]:
        """Increment counter for window, resetting if window changed."""
        async with self._lock:
            now = time.time_ns() // 1_000_000_000
            expires_at = now + ttl_seconds

            # Check if entry exists and is not expired
            # For fixed windows: if entry exists and not expired, it's the same window
            entry = self._data.get(key)
            if entry is not None and entry.expires_at > now:
                # Same window - increment count, preserve original expires_at and window_id
                new_value = entry.value + amount
                self._data[key] = _Entry(
                    value=new_value,
                    expires_at=entry.expires_at,
                    window_id=entry.window_id,
                    window_start=entry.window_start,
                )
                return new_value, entry.window_id

            # Different window, expired, or no entry - reset with new UUID
            new_value = amount
            window_id = str(uuid.uuid4())
            self._data[key] = _Entry(
                value=new_value,
                expires_at=expires_at,
                window_id=window_id,
                window_start=window_start,
            )
            return new_value, window_id
