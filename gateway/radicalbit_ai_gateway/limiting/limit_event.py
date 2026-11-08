from collections.abc import Iterable
from typing import Any

from radicalbit_ai_gateway.events.events_processor import emit_event
from radicalbit_ai_gateway.limiter import (
    BaseFixedWindowLimiter,
    Consumption,
    ScenarioType,
    WindowConfig,
)
from radicalbit_ai_gateway.limiter.window_config import WindowStats
from radicalbit_ai_gateway.models.event_payload import LimitEventPayload, LimitScope
from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.models.request_identity import RequestIdentity
from radicalbit_ai_gateway.utils import BUDGET_MULTIPLIER
from radicalbit_ai_gateway.utils.app_config import get_app_config


def limit_fields(
    scope: LimitScope, window: WindowConfig, stats: WindowStats
) -> dict[str, Any]:
    """Return the ``LimitEventPayload`` fields naming the limit and its window.

    They say which limit this is and how far its window has gone. Budget
    windows count in internal units, so they are reported back in currency.
    """
    divisor = BUDGET_MULTIPLIER if window.scenario_type is ScenarioType.BUDGET else 1
    return {
        'limit_scope': scope,
        'category': window.scenario_type.value,
        'window_seconds': window.window_seconds,
        'maximum': window.limit / divisor,
        'consumption': stats.consumed / divisor,
        'reset_time': stats.reset_time,
        'window_id': stats.window_id,
    }


def crossed_percentages(
    consumed: int, cost: int, maximum: int, percentages: Iterable[int]
) -> list[int]:
    """Return the percentages of `maximum` that the hit of `cost` crossed.

    A percentage is crossed when the counter was below it before the hit and
    is at or above it after: `consumed` is the counter after the hit.
    """
    previous = consumed - cost
    return sorted(
        pct for pct in percentages if previous * 100 < pct * maximum <= consumed * 100
    )


async def emit_thresholds(
    limiter: BaseFixedWindowLimiter,
    window: WindowConfig,
    cost: int,
    consumption: Consumption,
    scope: LimitScope,
    identity: RequestIdentity,
) -> None:
    """Emit an event per threshold the hit of `cost` crossed in `window`.

    `consumption` is the window's counter after the hit. The percentages are
    the global ones from the alert config.
    """
    crossed = crossed_percentages(
        consumption.value,
        cost,
        window.limit,
        get_app_config().alert_config.alert_threshold_percentages,
    )
    if not crossed:
        return
    # Only the store knows when a fixed window, opened by its first hit, resets.
    stats = (await limiter.get_window_stats(window))._replace(
        consumed=consumption.value, window_id=consumption.window_id
    )
    for percentage in crossed:
        emit_event(
            LimitEventPayload(
                **identity.event_fields(),
                event_type=EventType.LIMIT_THRESHOLD,
                value=1.0,
                threshold_percentage=percentage,
                **limit_fields(scope, window, stats),
            )
        )
