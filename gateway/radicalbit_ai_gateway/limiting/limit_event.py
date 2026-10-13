from typing import Any

from radicalbit_ai_gateway.limiter import ScenarioType, WindowConfig
from radicalbit_ai_gateway.limiter.window_config import WindowStats
from radicalbit_ai_gateway.models.event_payload import LimitScope
from radicalbit_ai_gateway.utils import BUDGET_MULTIPLIER


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
