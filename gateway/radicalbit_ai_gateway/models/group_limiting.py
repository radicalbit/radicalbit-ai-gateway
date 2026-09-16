from __future__ import annotations

import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from radicalbit_ai_gateway.db.tables.group_limit_table import GroupLimit
from radicalbit_ai_gateway.models.credential_limiting import (
    CATEGORY_TO_LIMITING_FIELD,
    CredentialLimitCategory,
)
from radicalbit_ai_gateway.models.limiting import Limiting, LimitingAlgorithmType


class GroupLimitIn(BaseModel):
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

    @model_validator(mode='after')
    def validate_against_limiting_schema(self) -> GroupLimitIn:
        field_name = CATEGORY_TO_LIMITING_FIELD[self.category]
        # Raises ValueError (-> 422) if algorithm/window_size are inconsistent,
        # reusing the validation already defined on `Limiting`.
        Limiting(
            algorithm=self.algorithm,
            window_size=self.window_size,
            **{field_name: self.value},
        )
        return self

    def to_group_limit(self, group_uuid: UUID) -> GroupLimit:
        UTC = getattr(datetime, 'UTC', datetime.timezone.utc)
        now = datetime.datetime.now(tz=UTC)
        return GroupLimit(
            group_uuid=group_uuid,
            category=self.category.value,
            algorithm=self.algorithm.value,
            window_size=str(self.window_size),
            max_value=self.value,
            created_at=now,
            updated_at=now,
        )


class GroupLimitsIn(BaseModel):
    """A batch of limits to create on a group in a single call."""

    limits: list[GroupLimitIn] = Field(..., min_length=1)

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    @model_validator(mode='after')
    def no_duplicates_within_batch(self) -> GroupLimitsIn:
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

    def to_group_limits(self, group_uuid: UUID) -> list[GroupLimit]:
        return [limit.to_group_limit(group_uuid) for limit in self.limits]


class GroupLimitOut(BaseModel):
    uuid: UUID
    category: CredentialLimitCategory
    algorithm: LimitingAlgorithmType
    window_size: str
    value: float
    created_at: str
    updated_at: str

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    @staticmethod
    def from_group_limit(group_limit: GroupLimit) -> GroupLimitOut:
        return GroupLimitOut(
            uuid=group_limit.uuid,
            category=CredentialLimitCategory(group_limit.category),
            algorithm=LimitingAlgorithmType(group_limit.algorithm),
            window_size=group_limit.window_size,
            value=float(group_limit.max_value),
            created_at=str(group_limit.created_at),
            updated_at=str(group_limit.updated_at),
        )


class GroupLimitOverwriteWarning(BaseModel):
    """A member credential whose own limit of this type (individually-set or
    from a different/same group) was overwritten by this group limit. The
    last limit applied to a credential always wins.
    """

    key_uuid: UUID
    key_name: str
    category: CredentialLimitCategory
    algorithm: LimitingAlgorithmType
    window_size: str

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)


class GroupLimitsApplyOut(BaseModel):
    limits: list[GroupLimitOut]
    overwritten: list[GroupLimitOverwriteWarning]

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)
