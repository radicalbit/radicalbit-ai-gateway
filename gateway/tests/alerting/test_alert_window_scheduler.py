"""The scheduler ticks the window closing until the gateway shuts down."""

import asyncio
import threading
from unittest.mock import patch

from radicalbit_ai_gateway.alerting import alert_window_scheduler
from radicalbit_ai_gateway.alerting.alert_window_scheduler import (
    run_alert_window_scheduler,
)


class Ticks:
    """An async `close_windows` that counts its calls."""

    def __init__(self):
        self.count = 0

    async def __call__(self) -> None:
        self.count += 1


async def test_the_scheduler_ticks_until_cancelled():
    ticks = Ticks()
    task = asyncio.create_task(run_alert_window_scheduler(ticks, interval_seconds=0.01))

    await asyncio.sleep(0.1)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    count = ticks.count
    await asyncio.sleep(0.05)

    assert count >= 2
    assert ticks.count == count


async def test_a_scheduler_cancelled_while_waiting_never_ticks():
    ticks = Ticks()
    task = asyncio.create_task(run_alert_window_scheduler(ticks, interval_seconds=60))
    await asyncio.sleep(0)

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert task.cancelled()
    assert ticks.count == 0


async def test_a_tick_runs_on_the_event_loop_not_in_a_thread():
    threads = []

    async def close_windows():
        threads.append(threading.get_ident())

    task = asyncio.create_task(
        run_alert_window_scheduler(close_windows, interval_seconds=0.01)
    )
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert threads
    assert set(threads) == {threading.get_ident()}


async def test_a_failing_tick_does_not_stop_the_scheduler():
    ticks = Ticks()

    async def close_windows():
        await ticks()
        raise RuntimeError('redis down')

    # The gateway logger writes to the real stderr, past pytest's capture.
    with patch.object(alert_window_scheduler, 'logger') as logger:
        task = asyncio.create_task(
            run_alert_window_scheduler(close_windows, interval_seconds=0.01)
        )

        await asyncio.sleep(0.1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert ticks.count >= 2
    logger.exception.assert_called_with('Failed to close alert windows')
