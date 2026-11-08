from radicalbit_ai_gateway.limiter import AlignedFixedWindowLimiter, FixedWindowLimiter
from radicalbit_ai_gateway.limiter.window_config import WindowConfig
from radicalbit_ai_gateway.models.event_dto import WindowProgressBarDTO
from radicalbit_ai_gateway.utils import BUDGET_MULTIPLIER


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
