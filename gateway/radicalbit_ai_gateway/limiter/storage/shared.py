"""The limit storage shared by the whole process."""

from radicalbit_ai_gateway.limiter.storage.base import Storage
from radicalbit_ai_gateway.limiter.storage.memory import InMemoryStorage
from radicalbit_ai_gateway.limiter.storage.redis import RedisStorage
from radicalbit_ai_gateway.utils.app_config import get_app_config

_storage: Storage | None = None


def get_limit_storage() -> Storage:
    """Return the process's limit storage, created on first use.

    Redis when a Redis URL is configured, so every replica shares the
    counters; in memory otherwise. One instance, so one Redis connection pool
    and, without Redis, counters that outlive the request that set them.
    """
    global _storage  # noqa: PLW0603
    if _storage is None:
        redis_url = get_app_config().redis_config.redis_url
        _storage = RedisStorage(uri=redis_url) if redis_url else InMemoryStorage()
    return _storage


async def close_limit_storage() -> None:
    """Close the process's limit storage; the next use creates a new one."""
    global _storage  # noqa: PLW0603
    storage, _storage = _storage, None
    if isinstance(storage, RedisStorage):
        await storage.close()
