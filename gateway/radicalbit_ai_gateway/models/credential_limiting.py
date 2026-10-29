from __future__ import annotations

import datetime
from enum import Enum
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic.alias_generators import to_camel

from radicalbit_ai_gateway.db.tables.key_limit_table import KeyLimit
from radicalbit_ai_gateway.limiter.window_config import ScenarioType
from radicalbit_ai_gateway.models.limiting import (
    Limiting,
    LimitingAlgorithmType,
    normalize_limit_window,
)


class CredentialLimitCategory(str, Enum):
    RATE = ScenarioType.REQUEST_RATE.value
    TOKEN_INPUT = ScenarioType.TOKEN_INPUT.value
    TOKEN_OUTPUT = ScenarioType.TOKEN_OUTPUT.value
    BUDGET = ScenarioType.BUDGET.value


# Which field of the existing `Limiting` model each category maps to, so we can
# reuse its algorithm/window_size validation instead of duplicating it. Shared
# with group_limiting.py, which validates against the same categories.
CATEGORY_TO_LIMITING_FIELD: dict[CredentialLimitCategory, str] = {
    CredentialLimitCategory.RATE: 'max_requests',
    CredentialLimitCategory.TOKEN_INPUT: 'max_tokens',
    CredentialLimitCategory.TOKEN_OUTPUT: 'max_tokens',
    CredentialLimitCategory.BUDGET: 'max_budget',
}


class CredentialLimitIn(BaseModel):
    category: CredentialLimitCategory
    algorithm: LimitingAlgorithmType = LimitingAlgorithmType.FIXED_WINDOW
    window_size: int | str = '1 minute'
    value: float = Field(
        ...,
        gt=0,
        description='Threshold for this limit: request count, token count, or budget amount depending on category.',
        examples=[10, 1000, 1.5],
    )

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    # A field validator, not a model one, so a 422 points at windowSize
    @field_validator('window_size', mode='before')
    @classmethod
    def normalize_window_size(cls, value: float | str, info: ValidationInfo) -> str:
        return normalize_limit_window(value, info.data.get('algorithm'))

    @model_validator(mode='after')
    def validate_against_limiting_schema(self) -> CredentialLimitIn:
        field_name = CATEGORY_TO_LIMITING_FIELD[self.category]
        # Raises ValueError (-> 422) if algorithm/window_size are inconsistent,
        # reusing the validation already defined on `Limiting`.
        Limiting(
            algorithm=self.algorithm,
            window_size=self.window_size,
            **{field_name: self.value},
        )
        return self

    def to_key_limit(self, key_uuid: UUID) -> KeyLimit:
        UTC = getattr(datetime, 'UTC', datetime.timezone.utc)
        now = datetime.datetime.now(tz=UTC)
        return KeyLimit(
            key_uuid=key_uuid,
            category=self.category.value,
            algorithm=self.algorithm.value,
            window_size=str(self.window_size),
            max_value=self.value,
            created_at=now,
            updated_at=now,
        )


class CredentialLimitsIn(BaseModel):
    """A batch of limits to create on a credential in a single call — e.g. a rate,
    a token and a budget limit configured together from one UI form submission.
    """

    limits: list[CredentialLimitIn] = Field(..., min_length=1)

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    @model_validator(mode='after')
    def no_duplicates_within_batch(self) -> CredentialLimitsIn:
        seen = set()
        for limit in self.limits:
            key = (limit.category, limit.algorithm, str(limit.window_size))
            if key in seen:
                raise ValueError(
                    f'Duplicate limit in request: {limit.category.value} with '
                    f'algorithm {limit.algorithm.value} and window '
                    f'{limit.window_size} was submitted more than once.'
                )
            seen.add(key)
        return self

    def to_key_limits(self, key_uuid: UUID) -> list[KeyLimit]:
        return [limit.to_key_limit(key_uuid) for limit in self.limits]


class CredentialLimitValueIn(BaseModel):
    value: float = Field(
        ...,
        gt=0,
        description='New threshold for the limit; its category, window type and window stay as they are.',
        examples=[10, 1000, 1.5],
    )

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, extra='forbid'
    )


def validate_limit_value(
    category: CredentialLimitCategory,
    algorithm: LimitingAlgorithmType,
    window_size: str,
    value: float,
) -> None:
    Limiting(
        algorithm=algorithm,
        window_size=window_size,
        **{CATEGORY_TO_LIMITING_FIELD[category]: value},
    )


class CredentialLimitOut(BaseModel):
    uuid: UUID
    category: CredentialLimitCategory
    algorithm: LimitingAlgorithmType
    window_size: str
    value: float
    created_at: str
    updated_at: str

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    @staticmethod
    def from_key_limit(key_limit: KeyLimit) -> CredentialLimitOut:
        return CredentialLimitOut(
            uuid=key_limit.uuid,
            category=CredentialLimitCategory(key_limit.category),
            algorithm=LimitingAlgorithmType(key_limit.algorithm),
            window_size=key_limit.window_size,
            value=float(key_limit.max_value),
            created_at=str(key_limit.created_at),
            updated_at=str(key_limit.updated_at),
        )


class CredentialLimitUpdatedOut(CredentialLimitOut):
    previous_value: float
