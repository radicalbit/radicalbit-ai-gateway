"""How alert rules name the events of a limit.

A limit blocks a request with `{category}-exceeded-{window}` and crosses a
global threshold with `{category}-{pct}pct-{window}`. The window is written in
the largest unit that divides it exactly, so "30 days" and "1 month" are both
`1mo`. The limiting algorithm is not part of the name.
"""

from dataclasses import dataclass
import re

from radicalbit_ai_gateway.limiter import ScenarioType

RATE_LIMIT = 'rate_limit'
TOKEN_INPUT_LIMIT = 'token_input_limit'
TOKEN_OUTPUT_LIMIT = 'token_output_limit'
BUDGET_LIMIT = 'budget_limit'
AUDIO_DURATION_LIMIT = 'audio_duration_limit'

CATEGORY_BY_SCENARIO = {
    ScenarioType.REQUEST_RATE.value: RATE_LIMIT,
    ScenarioType.TOKEN_INPUT.value: TOKEN_INPUT_LIMIT,
    ScenarioType.TOKEN_OUTPUT.value: TOKEN_OUTPUT_LIMIT,
    ScenarioType.BUDGET.value: BUDGET_LIMIT,
    ScenarioType.AUDIO_DURATION.value: AUDIO_DURATION_LIMIT,
}

CATEGORY_LABELS = {
    RATE_LIMIT: 'Rate limit',
    TOKEN_INPUT_LIMIT: 'Token input limit',
    TOKEN_OUTPUT_LIMIT: 'Token output limit',
    BUDGET_LIMIT: 'Budget limit',
    AUDIO_DURATION_LIMIT: 'Audio duration limit',
}

_DAY = 24 * 60 * 60
_UNITS = (
    ('mo', 30 * _DAY),
    ('w', 7 * _DAY),
    ('d', _DAY),
    ('h', 60 * 60),
    ('m', 60),
    ('s', 1),
)

_EVENT = re.compile(
    rf'^(?P<category>{"|".join(CATEGORY_LABELS)})'
    r'-(?:exceeded|(?P<percentage>\d+)pct)'
    r'-(?P<window>\d+(?:mo|w|d|h|m|s))$'
)


@dataclass(frozen=True)
class LimitEventName:
    """A limit or threshold event, read back from its name."""

    category: str
    window: str
    percentage: int | None = None  # None for the exceeded event

    @property
    def label(self) -> str:
        return CATEGORY_LABELS[self.category]


def window_name(seconds: int) -> str:
    """Write `seconds` in the largest unit that divides it exactly."""
    for unit, size in _UNITS:
        if seconds % size == 0:
            return f'{seconds // size}{unit}'
    raise ValueError(f'A window of {seconds} seconds has no name')


def exceeded_event(category: str, window_seconds: int) -> str:
    return f'{category}-exceeded-{window_name(window_seconds)}'


def threshold_event(category: str, percentage: int, window_seconds: int) -> str:
    return f'{category}-{percentage}pct-{window_name(window_seconds)}'


def parse_limit_event(event: str) -> LimitEventName | None:
    """Read a limit or threshold event name, or None if `event` is neither."""
    match = _EVENT.match(event)
    if match is None:
        return None
    percentage = match['percentage']
    return LimitEventName(
        category=match['category'],
        window=match['window'],
        percentage=int(percentage) if percentage is not None else None,
    )
