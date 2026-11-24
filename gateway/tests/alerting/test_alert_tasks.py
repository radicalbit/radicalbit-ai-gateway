"""Alert dispatches run as tasks on the event loop, a few at a time."""

import asyncio
import gc
import threading
from unittest.mock import patch

from radicalbit_ai_gateway.alerting import alert_tasks
from radicalbit_ai_gateway.alerting.alert_tasks import AlertTasks


class Dispatch:
    """An alert dispatch that waits until the test lets it finish."""

    running = 0
    peak = 0

    def __init__(self):
        self.release = asyncio.Event()
        self.started = False
        self.done = False
        self.thread: int | None = None

    async def __call__(self) -> None:
        self.started = True
        self.thread = threading.get_ident()
        Dispatch.running += 1
        Dispatch.peak = max(Dispatch.peak, Dispatch.running)
        try:
            await self.release.wait()
            self.done = True
        finally:
            Dispatch.running -= 1


def dispatches(count: int) -> list[Dispatch]:
    Dispatch.running = Dispatch.peak = 0
    return [Dispatch() for _ in range(count)]


async def settle() -> None:
    for _ in range(10):
        await asyncio.sleep(0)


async def test_a_dispatch_runs_on_the_event_loop_not_in_a_thread():
    tasks = AlertTasks(max_concurrency=2)
    [dispatch] = dispatches(1)
    dispatch.release.set()

    assert tasks.schedule(dispatch) is True
    await tasks.join()

    assert dispatch.done
    assert dispatch.thread == threading.get_ident()


async def test_scheduling_returns_before_the_dispatch_runs():
    tasks = AlertTasks(max_concurrency=2)
    [dispatch] = dispatches(1)

    tasks.schedule(dispatch)

    assert not dispatch.started
    dispatch.release.set()
    await tasks.join()


async def test_no_more_than_max_concurrency_dispatches_run_at_once():
    tasks = AlertTasks(max_concurrency=2)
    pending = dispatches(5)

    for dispatch in pending:
        tasks.schedule(dispatch)
    await settle()

    assert [d.started for d in pending] == [True, True, False, False, False]
    for dispatch in pending:
        dispatch.release.set()
    await tasks.join()
    assert all(d.done for d in pending)
    assert Dispatch.peak == 2


async def test_a_scheduled_dispatch_is_kept_alive_until_done():
    tasks = AlertTasks(max_concurrency=1)
    [dispatch] = dispatches(1)

    tasks.schedule(dispatch)
    await settle()
    gc.collect()
    dispatch.release.set()
    await tasks.join()

    assert dispatch.done


async def test_a_failing_dispatch_is_logged_and_the_next_one_still_runs():
    tasks = AlertTasks(max_concurrency=1)
    [after] = dispatches(1)
    after.release.set()

    async def failing() -> None:
        raise RuntimeError('smtp down')

    with patch.object(alert_tasks, 'logger') as logger:
        tasks.schedule(failing)
        tasks.schedule(after)
        await tasks.join()

    assert after.done
    logger.exception.assert_called_once_with(
        'Error dispatching alert rule notification'
    )


async def test_cancel_stops_running_and_waiting_dispatches():
    tasks = AlertTasks(max_concurrency=1)
    running, waiting = dispatches(2)
    tasks.schedule(running)
    tasks.schedule(waiting)
    await settle()

    await tasks.cancel()

    assert running.started and not running.done
    assert not waiting.started
    await tasks.join()  # nothing is left to wait for


def test_without_a_running_event_loop_the_dispatch_is_dropped():
    tasks = AlertTasks(max_concurrency=1)
    [dispatch] = dispatches(1)

    with patch.object(alert_tasks, 'logger') as logger:
        scheduled = tasks.schedule(dispatch)

    assert scheduled is False
    assert not dispatch.started
    logger.warning.assert_called_once()


def test_a_new_event_loop_gets_its_own_limit():
    tasks = AlertTasks(max_concurrency=1)

    async def run_two() -> list[bool]:
        pending = dispatches(2)
        for dispatch in pending:
            tasks.schedule(dispatch)
        await settle()
        for dispatch in pending:
            dispatch.release.set()
        await tasks.join()
        return [d.done for d in pending]

    assert asyncio.run(run_two()) == [True, True]
    assert asyncio.run(run_two()) == [True, True]
