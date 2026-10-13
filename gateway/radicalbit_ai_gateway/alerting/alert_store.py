"""The state alert rules share across gateway replicas.

Limit-window rules claim one key per limit window, so only one replica sends.
Tumbling-window rules count events per window and register each open window
until a replica closes it. The state lives in Redis; without Redis an
in-process store with the same interface keeps it, which is correct for a
single replica only, like the limiters' own fallback.

The store is synchronous, unlike the limiters' storage: alerts are dispatched on
the alert executor's threads, off the event loop.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import UTC, datetime
import threading

from redis import Redis

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


class AlertStore(ABC):
    def __init__(self, clock: Clock = utc_now):
        self._clock = clock

    def now(self) -> datetime:
        return self._clock()

    @abstractmethod
    def claim(self, key: str, ttl_seconds: int) -> bool:
        """Set `key` if absent. Return whether this call set it."""

    @abstractmethod
    def increment(self, key: str, ttl_seconds: int) -> int:
        """Add one to the counter at `key` and return its new value."""

    @abstractmethod
    def take(self, key: str) -> int:
        """Remove the counter at `key` and return its value, 0 if absent."""

    @abstractmethod
    def open_window(self, window: str, closes_at: datetime) -> None:
        """Register `window` as open until `closes_at`."""

    @abstractmethod
    def windows_due(self, now: datetime) -> list[str]:
        """Return the open windows that close at or before `now`."""

    @abstractmethod
    def close_window(self, window: str) -> bool:
        """Unregister `window`. Return whether this call removed it."""


class RedisAlertStore(AlertStore):
    _OPEN_WINDOWS = 'alert:windows:open'

    def __init__(self, client: Redis, clock: Clock = utc_now):
        super().__init__(clock)
        self._client = client

    def claim(self, key: str, ttl_seconds: int) -> bool:
        return bool(self._client.set(key, 1, nx=True, ex=ttl_seconds))

    def increment(self, key: str, ttl_seconds: int) -> int:
        pipe = self._client.pipeline()
        pipe.incr(key)
        pipe.expire(key, ttl_seconds)
        count, _ = pipe.execute()
        return int(count)

    def take(self, key: str) -> int:
        value = self._client.getdel(key)
        return int(value) if value is not None else 0

    def open_window(self, window: str, closes_at: datetime) -> None:
        self._client.zadd(self._OPEN_WINDOWS, {window: closes_at.timestamp()})

    def windows_due(self, now: datetime) -> list[str]:
        members = self._client.zrangebyscore(
            self._OPEN_WINDOWS, '-inf', now.timestamp()
        )
        return [m.decode() if isinstance(m, bytes) else m for m in members]

    def close_window(self, window: str) -> bool:
        return self._client.zrem(self._OPEN_WINDOWS, window) == 1


class InProcessAlertStore(AlertStore):
    def __init__(self, clock: Clock = utc_now):
        super().__init__(clock)
        self._lock = threading.Lock()
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

    def claim(self, key: str, ttl_seconds: int) -> bool:
        with self._lock:
            if self._live(key) is not None:
                return False
            self._values[key] = (1, self._expiry(ttl_seconds))
            return True

    def increment(self, key: str, ttl_seconds: int) -> int:
        with self._lock:
            count = (self._live(key) or 0) + 1
            self._values[key] = (count, self._expiry(ttl_seconds))
            return count

    def take(self, key: str) -> int:
        with self._lock:
            count = self._live(key) or 0
            self._values.pop(key, None)
            return count

    def open_window(self, window: str, closes_at: datetime) -> None:
        with self._lock:
            self._open_windows[window] = closes_at

    def windows_due(self, now: datetime) -> list[str]:
        with self._lock:
            return [w for w, closes in self._open_windows.items() if closes <= now]

    def close_window(self, window: str) -> bool:
        with self._lock:
            return self._open_windows.pop(window, None) is not None


def build_alert_store(redis_url: str | None, clock: Clock = utc_now) -> AlertStore:
    """Build the store on Redis when it is configured, in process otherwise."""
    if redis_url:
        return RedisAlertStore(Redis.from_url(redis_url), clock=clock)
    return InProcessAlertStore(clock=clock)
