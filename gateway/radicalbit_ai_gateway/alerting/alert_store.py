"""The state alert rules share across gateway replicas.

Limit-window rules claim one key per limit window, so only one replica sends.
Tumbling-window rules count events per window and register each open window
until a replica closes it. The state lives in Redis; without Redis an
in-process store with the same interface keeps it, which is correct for a
single replica only, like the limiters' own fallback.

The store is async: alerts are dispatched as tasks on the event loop.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import UTC, datetime

from redis.asyncio import Redis

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


class AlertStore(ABC):
    def __init__(self, clock: Clock = utc_now):
        self._clock = clock

    def now(self) -> datetime:
        return self._clock()

    async def close(self) -> None:
        """Release what the store holds open. Nothing by default."""

    @abstractmethod
    async def claim(self, key: str, ttl_seconds: int) -> bool:
        """Set `key` if absent. Return whether this call set it."""

    @abstractmethod
    async def increment(self, key: str, ttl_seconds: int) -> int:
        """Add one to the counter at `key` and return its new value."""

    @abstractmethod
    async def take(self, key: str) -> int:
        """Remove the counter at `key` and return its value, 0 if absent."""

    @abstractmethod
    async def open_window(self, window: str, closes_at: datetime) -> None:
        """Register `window` as open until `closes_at`."""

    @abstractmethod
    async def windows_due(self, now: datetime) -> list[str]:
        """Return the open windows that close at or before `now`."""

    @abstractmethod
    async def close_window(self, window: str) -> bool:
        """Unregister `window`. Return whether this call removed it."""


class RedisAlertStore(AlertStore):
    _OPEN_WINDOWS = 'alert:windows:open'

    def __init__(self, client: Redis, clock: Clock = utc_now):
        super().__init__(clock)
        self._client = client

    async def claim(self, key: str, ttl_seconds: int) -> bool:
        return bool(await self._client.set(key, 1, nx=True, ex=ttl_seconds))

    async def increment(self, key: str, ttl_seconds: int) -> int:
        async with self._client.pipeline() as pipe:
            pipe.incr(key)
            pipe.expire(key, ttl_seconds)
            count, _ = await pipe.execute()
        return int(count)

    async def take(self, key: str) -> int:
        value = await self._client.getdel(key)
        return int(value) if value is not None else 0

    async def open_window(self, window: str, closes_at: datetime) -> None:
        await self._client.zadd(self._OPEN_WINDOWS, {window: closes_at.timestamp()})

    async def windows_due(self, now: datetime) -> list[str]:
        members = await self._client.zrangebyscore(
            self._OPEN_WINDOWS, '-inf', now.timestamp()
        )
        return [m.decode() if isinstance(m, bytes) else m for m in members]

    async def close_window(self, window: str) -> bool:
        return await self._client.zrem(self._OPEN_WINDOWS, window) == 1

    async def close(self) -> None:
        await self._client.aclose()


class InProcessAlertStore(AlertStore):
    """Every method runs to its end with no await inside, so one event loop
    never sees a half-done update and no lock is needed.
    """

    def __init__(self, clock: Clock = utc_now):
        super().__init__(clock)
        self._values: dict[str, tuple[int, float]] = {}  # key -> (value, expiry)
        self._open_windows: dict[str, datetime] = {}

    def _live(self, key: str) -> int | None:
        entry = self._values.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if self.now().timestamp() >= expires_at:
            del self._values[key]
            return None
        return value

    def _expiry(self, ttl_seconds: int) -> float:
        return self.now().timestamp() + ttl_seconds

    async def claim(self, key: str, ttl_seconds: int) -> bool:
        if self._live(key) is not None:
            return False
        self._values[key] = (1, self._expiry(ttl_seconds))
        return True

    async def increment(self, key: str, ttl_seconds: int) -> int:
        count = (self._live(key) or 0) + 1
        self._values[key] = (count, self._expiry(ttl_seconds))
        return count

    async def take(self, key: str) -> int:
        count = self._live(key) or 0
        self._values.pop(key, None)
        return count

    async def open_window(self, window: str, closes_at: datetime) -> None:
        self._open_windows[window] = closes_at

    async def windows_due(self, now: datetime) -> list[str]:
        return [w for w, closes in self._open_windows.items() if closes <= now]

    async def close_window(self, window: str) -> bool:
        return self._open_windows.pop(window, None) is not None


def build_alert_store(redis_url: str | None, clock: Clock = utc_now) -> AlertStore:
    """Build the store on Redis when it is configured, in process otherwise."""
    if redis_url:
        return RedisAlertStore(Redis.from_url(redis_url), clock=clock)
    return InProcessAlertStore(clock=clock)
