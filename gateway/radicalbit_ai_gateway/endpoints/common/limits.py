"""Checking a request's demand on its limits, as every endpoint does."""

from traceloop.sdk.decorators import task

from radicalbit_ai_gateway.limiting.limits import Demand, RequestLimits


async def _check(limits: RequestLimits, demand: Demand) -> None:
    await limits.check(demand)


def checked_in_span(name: str):
    """Return a limit check that runs in a trace span named ``name``."""
    return task(name=name)(_check)


async def check_limits(limits: RequestLimits, demand: Demand, check=None) -> None:
    """Check ``demand`` on the request's limits, if any applies.

    ``check`` runs the check in a trace span of its own.
    """
    if limits.applies(demand):
        await (check or _check)(limits, demand)
