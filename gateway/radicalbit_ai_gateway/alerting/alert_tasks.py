"""Run alert dispatches as tasks on the event loop, off the request path.

`emit_event` is sync and has many callers, so it cannot await. It schedules
each dispatch here instead. A semaphore caps how many dispatches run at once.
Each task is held until it is done, so it is never garbage collected half way.
Shutdown cancels the tasks still pending.
"""

import asyncio
from collections.abc import Awaitable, Callable
import logging

from radicalbit_ai_gateway.utils.app_config import get_app_config

logger = logging.getLogger(get_app_config().log_config.logger_name)

Dispatch = Callable[[], Awaitable[None]]


class AlertTasks:
    def __init__(self, max_concurrency: int):
        self._max_concurrency = max_concurrency
        self._tasks: set[asyncio.Task] = set()
        # A semaphore belongs to one event loop: keep the loop it was made on.
        self._loop: asyncio.AbstractEventLoop | None = None
        self._semaphore: asyncio.Semaphore | None = None

    def schedule(self, dispatch: Dispatch) -> bool:
        """Run `dispatch` in a task on the running loop. Return whether it was
        scheduled: with no running loop, it is dropped.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning('No running event loop: alert dispatch dropped')
            return False
        task = loop.create_task(self._run(self._semaphore_for(loop), dispatch))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return True

    async def join(self) -> None:
        """Wait until every dispatch scheduled on this loop is done."""
        while pending := self._on_this_loop():
            await asyncio.gather(*pending, return_exceptions=True)

    async def cancel(self) -> None:
        """Cancel every dispatch scheduled on this loop, and wait for them."""
        pending = self._on_this_loop()
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    def _on_this_loop(self) -> list[asyncio.Task]:
        loop = asyncio.get_running_loop()
        return [t for t in self._tasks if t.get_loop() is loop]

    def _semaphore_for(self, loop: asyncio.AbstractEventLoop) -> asyncio.Semaphore:
        if self._semaphore is None or self._loop is not loop:
            self._loop = loop
            self._semaphore = asyncio.Semaphore(self._max_concurrency)
        return self._semaphore

    @staticmethod
    async def _run(semaphore: asyncio.Semaphore, dispatch: Dispatch) -> None:
        async with semaphore:
            try:
                await dispatch()
            except Exception:
                logger.exception('Error dispatching alert rule notification')
