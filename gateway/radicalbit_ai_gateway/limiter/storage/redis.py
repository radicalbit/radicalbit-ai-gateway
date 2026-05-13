"""Redis storage backend for limiting."""

from __future__ import annotations

import time
import uuid

from redis.asyncio import Redis

from radicalbit_ai_gateway.limiter.storage.base import Storage

# Lua script for atomic increment with TTL and window ID
# Uses a hash to store count, window_id, and window_start in a single key
# Returns: new_value, window_id
# For existing keys: increments without resetting (TTL controls window lifetime)
# For new keys: initializes with passed values
_INCREMENT_SCRIPT = """
local key = KEYS[1]
local amount = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local window_id = ARGV[3]
local window_start = ARGV[4]

local stored_window_start = redis.call('HGET', key, 'window_start')

if stored_window_start then
    -- Key exists - increment count only, DO NOT reset TTL (fixed window)
    local new_value = redis.call('HINCRBY', key, 'count', amount)
    local existing_window_id = redis.call('HGET', key, 'window_id')
    return {new_value, existing_window_id}
else
    -- New key - initialize with passed values
    redis.call('HSET', key, 'count', amount)
    redis.call('HSET', key, 'window_id', window_id)
    redis.call('HSET', key, 'window_start', window_start)
    redis.call('EXPIRE', key, ttl)
    return {amount, window_id}
end
"""


class RedisStorage(Storage):
    """Redis-based distributed storage for limiting.

    Uses atomic operations with Lua scripts for consistency.
    Key format: limiter:{route_name}:{scenario_type}:{window_type}:{window_seconds}
    Stores count and window_id in a hash for single-key efficiency.
    """

    def __init__(self, uri: str) -> None:
        """Initialize Redis storage.

        Args:
            uri: Redis connection URI (e.g., 'redis://localhost:6379').

        """
        self._client = Redis.from_url(uri)
        self._script = self._client.register_script(_INCREMENT_SCRIPT)

    async def get(self, key: str) -> int | None:
        """Get current counter value or None if expired/missing."""
        value = await self._client.hget(key, 'count')
        if value is None:
            return None
        return int(value)

    async def get_ttl(self, key: str) -> int | None:
        """Get expiration timestamp or None if key doesn't exist."""
        ttl = await self._client.ttl(key)
        if ttl < 0:  # Key doesn't exist (-2) or has no expiry (-1)
            return None
        return (time.time_ns() // 1_000_000_000) + ttl

    async def get_window_id(self, key: str) -> str | None:
        """Get the window ID for a key."""
        window_id = await self._client.hget(key, 'window_id')
        if window_id is None:
            return None
        return window_id.decode('utf-8')

    async def increment(
        self,
        key: str,
        amount: int,
        ttl_seconds: int,
        window_start: int,
    ) -> tuple[int, str]:
        """Increment counter for window, resetting if window changed."""
        window_id = str(uuid.uuid4())
        result = await self._script(
            keys=[key],
            args=[amount, ttl_seconds, window_id, window_start],
        )
        new_value = int(result[0])
        returned_window_id = result[1].decode('utf-8')
        return new_value, returned_window_id

    async def close(self) -> None:
        """Close the Redis connection."""
        await self._client.aclose()
