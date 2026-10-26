from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from radicalbit_ai_gateway.limiter.window_config import format_window, parse_window
from radicalbit_ai_gateway.utils import BUDGET_MULTIPLIER

# Valid window sizes for ALIGNED_FIXED_WINDOW (must divide evenly into 86400 seconds)
ALIGNED_FIXED_WINDOW_ALLOWED_SECONDS: frozenset[int] = frozenset(
    {
        60,  # 1 minute
        300,  # 5 minutes
        600,  # 10 minutes
        900,  # 15 minutes
        1800,  # 30 minutes
        3600,  # 1 hour
        7200,  # 2 hours
        10800,  # 3 hours
        14400,  # 4 hours
        21600,  # 6 hours
        28800,  # 8 hours
        43200,  # 12 hours
        86400,  # 1 day
    }
)


class LimitingAlgorithmType(str, Enum):
    FIXED_WINDOW = 'FIXED_WINDOW'
    ALIGNED_FIXED_WINDOW = 'ALIGNED_FIXED_WINDOW'


# Windows a credential or project limit can have. Route limits in a
# configuration are not bound to this list.
LIMIT_WINDOW_ALLOWED_SECONDS: dict[LimitingAlgorithmType, frozenset[int]] = {
    LimitingAlgorithmType.ALIGNED_FIXED_WINDOW: ALIGNED_FIXED_WINDOW_ALLOWED_SECONDS,
    LimitingAlgorithmType.FIXED_WINDOW: ALIGNED_FIXED_WINDOW_ALLOWED_SECONDS
    | {
        604800,  # 1 week
        2592000,  # 1 month
    },
}


def normalize_limit_window(
    value: float | str, algorithm: LimitingAlgorithmType | None
) -> str:
    """Return the window of a credential or project limit in its largest exact unit.

    So '60 seconds', 60 and '1 minute' are stored, and compared, as one window.

    Args:
        value: Window as a string (e.g., '24 hours') or in seconds.
        algorithm: Algorithm of the limit, whose allowed list the window must be
            in. None when the algorithm failed its own validation: then only
            the window itself is checked.

    Returns:
        The window in its largest exact unit, e.g. '1 day'.

    Raises:
        ValueError: If the window is not a positive whole number of seconds, or
            not in the allowed list of the algorithm.

    """
    if isinstance(value, str):
        window_seconds = parse_window(value)
    elif isinstance(value, bool) or not float(value).is_integer():
        raise ValueError(f"Window size '{value}' must be a whole number of seconds.")
    else:
        window_seconds = int(value)
    if window_seconds <= 0:
        raise ValueError(f"Window size '{value}' must be longer than 0.")
    window_size = format_window(window_seconds)
    if algorithm is None:
        return window_size
    allowed_seconds = LIMIT_WINDOW_ALLOWED_SECONDS[algorithm]
    if window_seconds not in allowed_seconds:
        allowed_sizes = ', '.join(format_window(s) for s in sorted(allowed_seconds))
        raise ValueError(
            f"Window size '{value}' is not allowed for {algorithm.value}. "
            f'Allowed sizes: {allowed_sizes}'
        )
    return window_size


class Limiting(BaseModel):
    model_config = ConfigDict(extra='forbid', populate_by_name=True)

    algorithm: LimitingAlgorithmType = Field(
        default=LimitingAlgorithmType.FIXED_WINDOW,
        description='Algorithm used for rate limiting.',
        examples=['FIXED_WINDOW', 'ALIGNED_FIXED_WINDOW'],
    )
    window_size: int | str = Field(
        default='1 minute',
        description="Size of the time window for rate limiting. Can be an integer (seconds) or a string (e.g., '1 minute').",
        examples=['10 seconds', '1 minute', '1 hour'],
    )
    max_requests: int | None = Field(
        default=None,
        description='Maximum number of requests allowed in the specified time window.',
        ge=1,
        examples=[10, 50, 100],
    )
    max_tokens: int | None = Field(
        default=None,
        description='Maximum number of tokens allowed in the specified time window.',
        ge=1,
        examples=[1000, 5000, 10000],
        alias='max_token',
        serialization_alias='maxTokens',
    )
    max_budget: float | None = Field(
        default=None,
        description='Maximum budget allowed in the specified time window.',
        ge=0.0,
        examples=[1.5, 5.50, 10.0],
    )
    max_duration_seconds: float | None = Field(
        default=None,
        description='Maximum seconds of audio allowed in the specified time window (WAV only).',
        ge=1,
        examples=[60, 300, 3600],
    )

    @property
    def max_budget_in_units(self) -> int | None:
        """Convert max_budget to micro-units for internal use."""
        if self.max_budget is not None:
            return int(self.max_budget * BUDGET_MULTIPLIER)
        return None

    @field_validator('algorithm', mode='before')
    def validate_lower_case_enum(cls, value: LimitingAlgorithmType) -> str:
        return value.upper()

    @field_validator('window_size', mode='before')
    def is_window_size_parsable(cls, value: int | str) -> int | str:
        if isinstance(value, str):
            try:
                parse_window(value)
            except ValueError as e:
                raise ValueError(
                    f'Invalid window_size format: {value}. {str(e)}'
                ) from e
            else:
                return value
        return value

    @model_validator(mode='after')
    def only_one_max_field(self):
        set_fields_count = sum(
            v is not None
            for v in [
                self.max_requests,
                self.max_tokens,
                self.max_budget,
                self.max_duration_seconds,
            ]
        )
        if set_fields_count > 1:
            raise ValueError(
                'Only one of max_requests, max_tokens, max_budget, or '
                'max_duration_seconds can be set.'
            )
        return self

    @model_validator(mode='after')
    def validate_aligned_fixed_window_size(self):
        if self.algorithm != LimitingAlgorithmType.ALIGNED_FIXED_WINDOW:
            return self

        # Convert window_size to seconds
        if isinstance(self.window_size, str):
            window_seconds = parse_window(self.window_size)
        else:
            window_seconds = self.window_size

        if window_seconds not in ALIGNED_FIXED_WINDOW_ALLOWED_SECONDS:
            allowed_sizes = [
                '1 minute',
                '5 minutes',
                '10 minutes',
                '15 minutes',
                '30 minutes',
                '1 hour',
                '2 hours',
                '3 hours',
                '4 hours',
                '6 hours',
                '8 hours',
                '12 hours',
                '1 day',
            ]
            raise ValueError(
                f"Window size '{self.window_size}' ({window_seconds}s) is not allowed for ALIGNED_FIXED_WINDOW. "
                f'Allowed sizes (must divide evenly into 1 day): {", ".join(allowed_sizes)}'
            )
        return self


class RateLimiting(Limiting):
    @model_validator(mode='after')
    def max_requests_set(self):
        if not self.max_requests:
            raise ValueError('max_requests must be set for rate limiting.')
        return self


class TokenLimiting(BaseModel):
    model_config = ConfigDict(extra='forbid')

    input: Limiting | None = Field(
        default=None, description='Rate limiting for input tokens.'
    )
    output: Limiting | None = Field(
        default=None, description='Rate limiting for output tokens.'
    )

    @model_validator(mode='after')
    def max_tokens_set(self):
        for side, limiting in (('input', self.input), ('output', self.output)):
            if limiting is not None and not limiting.max_tokens:
                raise ValueError(f'{side}.max_tokens must be set for token limiting.')
        return self


class BudgetLimiting(Limiting):
    @model_validator(mode='after')
    def max_budget_set(self):
        # 0 is a valid budget: it blocks every request.
        if self.max_budget is None:
            raise ValueError('max_budget must be set for budget limiting.')
        return self


class AudioDurationLimiting(Limiting):
    @model_validator(mode='after')
    def max_duration_seconds_set(self):
        if not self.max_duration_seconds:
            raise ValueError('max_duration_seconds must be set for duration limiting.')
        return self
