"""Window configuration and stats for limiter."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import NamedTuple


class ScenarioType(Enum):
    """Type of limiter scenario."""

    REQUEST_RATE = 'request_rate'
    TOKEN_INPUT = 'token_input'
    TOKEN_OUTPUT = 'token_output'
    BUDGET = 'budget'


# Time unit constants
_SECOND = 1
_MINUTE = 60 * _SECOND
_HOUR = 60 * _MINUTE
_DAY = 24 * _HOUR
_WEEK = 7 * _DAY
_MONTH = 30 * _DAY  # standard approximation

# Time unit to seconds mapping (singular and plural)
_TIME_UNITS: dict[str, int] = {
    'second': _SECOND,
    'seconds': _SECOND,
    'minute': _MINUTE,
    'minutes': _MINUTE,
    'hour': _HOUR,
    'hours': _HOUR,
    'day': _DAY,
    'days': _DAY,
    'week': _WEEK,
    'weeks': _WEEK,
    'month': _MONTH,
    'months': _MONTH,
}

# Pattern to parse window strings like "1 minute" or "10 seconds"
_WINDOW_PATTERN = re.compile(r'^(\d+)\s*(\w+)$')


class WindowStats(NamedTuple):
    """Statistics for a limit window."""

    remaining: int
    reset_time: int  # Unix timestamp (seconds) when window resets
    window_id: str | None  # UUID of the current window, None if no window exists
    remaining_time: int  # Seconds until window expires


def parse_window(window_string: str) -> int:
    """Parse a window duration string to seconds.

    Args:
        window_string: String like '1 minute', '30 seconds', '2 weeks'.

    Returns:
        Duration in seconds.

    Raises:
        ValueError: If the string format is invalid or unit is unknown.

    """
    match = _WINDOW_PATTERN.match(window_string.strip())
    if not match:
        raise ValueError(
            f"Invalid window format: '{window_string}'. "
            "Expected format: 'count unit' (e.g., '1 minute', '30 seconds')"
        )

    period = int(match.group(1))
    unit = match.group(2).lower()

    if unit not in _TIME_UNITS:
        valid_units = sorted(set(_TIME_UNITS.keys()))
        raise ValueError(f"Unknown time unit: '{unit}'. Supported units: {valid_units}")

    return period * _TIME_UNITS[unit]


@dataclass
class WindowConfig:
    """Configuration for a fixed window limit.

    Attributes:
        limit: Maximum allowed in the window.
        window_seconds: Window duration in seconds.
        route_name: Name of the route for key isolation.
        scenario_type: Type of rate limiting scenario (request_rate, token_input, token_output).
        project_uuid: UUID of the owning project, for key isolation only. Route
            names are unique only within a project, so without this two projects
            declaring the same route name share one window. Empty string keeps
            the unscoped key format, for call sites with no project context.

    """

    limit: int
    window_seconds: int
    route_name: str
    scenario_type: ScenarioType
    project_uuid: str = ''

    @classmethod
    def from_parts(
        cls,
        limit: int,
        window: str | int,
        route_name: str,
        scenario_type: ScenarioType,
        project_uuid: str = '',
    ) -> WindowConfig:
        """Create WindowConfig from limit and window size.

        Args:
            limit: Maximum allowed in the window.
            window: Window size as string (e.g., '1 minute') or seconds (int).
            route_name: Name of the route for key isolation.
            scenario_type: Type of rate limiting scenario.
            project_uuid: UUID of the owning project, for key isolation only.

        Returns:
            WindowConfig instance.

        """
        window_seconds = parse_window(window) if isinstance(window, str) else window
        return cls(
            limit=limit,
            window_seconds=window_seconds,
            route_name=route_name,
            scenario_type=scenario_type,
            project_uuid=project_uuid,
        )
