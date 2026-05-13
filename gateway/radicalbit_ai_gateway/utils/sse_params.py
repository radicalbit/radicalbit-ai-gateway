from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Query

from radicalbit_ai_gateway.utils.exceptions import GatewayBadRequest


def validate_sse_params(
    _gte: Annotated[
        int | None,
        Query(
            description='Seconds to look back from now (mutually exclusive with _from/_to)'
        ),
    ] = None,
    _from: Annotated[
        int | None, Query(description='Unix timestamp for start of range')
    ] = None,
    _to: Annotated[
        int | None, Query(description='Unix timestamp for end of range')
    ] = None,
) -> tuple[int | None, int | None, int | None]:
    """Validate SSE time parameters. Raises GatewayBadRequest if invalid."""
    if _gte is not None and (_from is not None or _to is not None):
        raise GatewayBadRequest(
            'Cannot use _gte parameter together with _from or _to parameters'
        )
    if _gte is not None and _gte <= 0:
        raise GatewayBadRequest('Parameter _gte must be a positive integer')
    return _gte, _from, _to


def compute_sse_time_range(
    _gte: int | None, _from: int | None, _to: int | None
) -> tuple[datetime | None, datetime | None]:
    """Compute from/to datetime for SSE endpoints.

    When _gte is provided, returns a rolling window (now - _gte, None).
    Otherwise returns fixed timestamps from _from/_to.
    """
    if _gte is not None:
        return datetime.now(timezone.utc) - timedelta(seconds=_gte), None
    from_datetime = datetime.fromtimestamp(_from, timezone.utc) if _from else None
    to_datetime = datetime.fromtimestamp(_to, timezone.utc) if _to else None
    return from_datetime, to_datetime
