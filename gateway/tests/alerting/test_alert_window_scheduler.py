"""The scheduler ticks the window closing until the gateway shuts down."""

import asyncio

from radicalbit_ai_gateway.alerting.alert_window_scheduler import (
    run_alert_window_scheduler,
)


async def test_the_scheduler_ticks_until_cancelled():
    ticks = []
    task = asyncio.create_task(
        run_alert_window_scheduler(lambda: ticks.append(1), interval_seconds=0.01)
    )

    await asyncio.sleep(0.1)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    count = len(ticks)
    await asyncio.sleep(0.05)

    assert count >= 2
    assert len(ticks) == count


async def test_a_failing_tick_does_not_stop_the_scheduler():
    ticks = []

    def close_windows():
        ticks.append(1)
        raise RuntimeError('redis down')

    task = asyncio.create_task(
        run_alert_window_scheduler(close_windows, interval_seconds=0.01)
    )

    await asyncio.sleep(0.1)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert len(ticks) >= 2
