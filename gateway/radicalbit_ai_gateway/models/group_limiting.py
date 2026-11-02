from __future__ import annotations

from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from radicalbit_ai_gateway.models.credential_limiting import (
    CredentialLimitCategory,
    CredentialLimitsIn,
    RouteLimitConsistencyWarning,
)
from radicalbit_ai_gateway.models.limiting import (
    LimitingAlgorithmType,
    normalize_limit_window,
)


class GroupLimitSkipIn(BaseModel):
    """A conflict to leave as it is: the member already has this limit."""

    key_uuid: UUID
    category: CredentialLimitCategory
    algorithm: LimitingAlgorithmType = LimitingAlgorithmType.FIXED_WINDOW
    window_size: int | str

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    # Canonical, so it matches the saved limit whatever unit it was sent in.
    # Not checked against the allowed list: a skip only ever matches a saved limit
    @field_validator('window_size', mode='before')
    @classmethod
    def normalize_window_size(cls, value: float | str) -> str:
        return normalize_limit_window(value, None)


class GroupLimitsIn(CredentialLimitsIn):
    """Limits to copy onto every credential of a group (bulk assignment).

    A member that already has one of them is a conflict: it is overwritten
    unless listed in `skip`. The group itself keeps nothing.
    """

    skip: list[GroupLimitSkipIn] = Field(default_factory=list)


class GroupLimitOutcome(str, Enum):
    ADDED = 'added'
    OVERWRITTEN = 'overwritten'
    SKIPPED = 'skipped'


class GroupLimitResultOut(BaseModel):
    category: CredentialLimitCategory
    algorithm: LimitingAlgorithmType
    window_size: str
    outcome: GroupLimitOutcome
    # The member's max before the apply: set on conflicts only
    previous_value: float | None = None
    new_value: float

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)


class GroupMemberLimitsOut(BaseModel):
    key_uuid: UUID
    key_name: str
    expired: bool
    limits: list[GroupLimitResultOut]
    # On the limits the member received: skipped ones keep the member's own max
    warnings: list[RouteLimitConsistencyWarning]

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)


class GroupLimitsApplyOut(BaseModel):
    members: list[GroupMemberLimitsOut]

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)
