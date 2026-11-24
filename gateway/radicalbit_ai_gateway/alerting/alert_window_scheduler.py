"""Close the tumbling alert windows on a fixed tick, for the gateway's lifetime.

Every replica runs the scheduler; the alert store lets exactly one of them
claim each closed window.
"""

import asyncio
from collections.abc import Awaitable, Callable
import logging

from radicalbit_ai_gateway.utils.app_config import get_app_config

logger = logging.getLogger(get_app_config().log_config.logger_name)


async def run_alert_window_scheduler(
    close_windows: Callable[[], Awaitable[None]], interval_seconds: float
) -> None:
    """Await `close_windows` every `interval_seconds` until cancelled."""
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await close_windows()
        except Exception:
            logger.exception('Failed to close alert windows')
