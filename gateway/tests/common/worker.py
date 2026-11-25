import functools

import anyio


def in_worker(fn):
    """Call sync ``fn`` the way a sync route calls it: in a worker thread of a
    running event loop, so it can run async DB calls with ``run_from_worker``.
    """

    def call(*args, **kwargs):
        async def main():
            return await anyio.to_thread.run_sync(
                functools.partial(fn, *args, **kwargs)
            )

        return anyio.run(main)

    return call
