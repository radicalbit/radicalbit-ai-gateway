from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from radicalbit_ai_gateway.limiter import (
    AlignedFixedWindowLimiter,
    FixedWindowLimiter,
    InMemoryStorage,
    RedisStorage,
    Storage,
)
from radicalbit_ai_gateway.limiter.window_config import WindowConfig
from radicalbit_ai_gateway.models.event_dto import WindowProgressBarDTO
from radicalbit_ai_gateway.utils import BUDGET_MULTIPLIER
from radicalbit_ai_gateway.utils.app_config import get_app_config

app_config = get_app_config()


def new_limiter_storage() -> Storage:
    """Open the counters' storage: Redis when configured, else this process's memory."""
    if app_config.redis_config.redis_url:
        return RedisStorage(uri=app_config.redis_config.redis_url)
    return InMemoryStorage()


@asynccontextmanager
async def shared_limiter_storage() -> AsyncIterator[Storage]:
    """One storage for every limiter read in the block, closed at its end."""
    storage = new_limiter_storage()
    try:
        yield storage
    finally:
        if isinstance(storage, RedisStorage):
            await storage.close()


async def window_progress_bar(
    limiter: FixedWindowLimiter | AlignedFixedWindowLimiter,
    window: WindowConfig,
    is_budget: bool = False,
) -> WindowProgressBarDTO:
    """How much of *window*'s current window is used, and when it resets.

    Budget windows are stored in micro-units: they are reported in dollars.
    """
    stats = await limiter.get_window_stats(window)
    filled = window.limit - stats.remaining
    if is_budget:
        window_size = window.limit / BUDGET_MULTIPLIER
        window_filled = filled / BUDGET_MULTIPLIER
    else:
        window_size = float(window.limit)
        window_filled = float(max(0, filled))
    pct = (window_filled / window_size * 100) if window_size > 0 else 0.0
    return WindowProgressBarDTO(
        window_length=window.window_seconds,
        window_start_time=stats.reset_time - window.window_seconds,
        window_end_time=stats.reset_time,
        window_size=window_size,
        window_filled_size=window_filled,
        window_filled_percentage=pct,
    )
