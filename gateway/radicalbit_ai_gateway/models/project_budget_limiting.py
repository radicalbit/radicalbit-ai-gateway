from __future__ import annotations

import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from radicalbit_ai_gateway.db.tables.project_budget_limit_table import (
    ProjectBudgetLimit,
)
from radicalbit_ai_gateway.models.limiting import Limiting, LimitingAlgorithmType


class ProjectBudgetLimitIn(BaseModel):
    algorithm: LimitingAlgorithmType = LimitingAlgorithmType.FIXED_WINDOW
    window_size: int | str = '1 minute'
    value: float = Field(
        ...,
        gt=0,
        description='Budget threshold for this time window.',
        examples=[1.0, 15.0],
    )

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    @model_validator(mode='after')
    def validate_against_limiting_schema(self) -> ProjectBudgetLimitIn:
        # Raises ValueError (-> 422) if algorithm/window_size are inconsistent,
        # reusing the validation already defined on `Limiting`.
        Limiting(
            algorithm=self.algorithm,
            window_size=self.window_size,
            max_budget=self.value,
        )
        return self

    def to_project_budget_limit(self, project_uuid: UUID) -> ProjectBudgetLimit:
        UTC = getattr(datetime, 'UTC', datetime.timezone.utc)
        now = datetime.datetime.now(tz=UTC)
        return ProjectBudgetLimit(
            project_uuid=project_uuid,
            algorithm=self.algorithm.value,
            window_size=str(self.window_size),
            max_value=self.value,
            created_at=now,
            updated_at=now,
        )


class ProjectBudgetLimitsIn(BaseModel):
    """A batch of budget limits to create on a project in a single call — e.g.
    a daily and a monthly budget configured together from one UI form submission.
    """

    limits: list[ProjectBudgetLimitIn] = Field(..., min_length=1)

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    @model_validator(mode='after')
    def no_duplicates_within_batch(self) -> ProjectBudgetLimitsIn:
        seen = set()
        for limit in self.limits:
            key = (limit.algorithm, str(limit.window_size))
            if key in seen:
                raise ValueError(
                    f'Duplicate limit in request: a budget limit with algorithm '
                    f'{limit.algorithm.value} and window {limit.window_size} was '
                    'submitted more than once.'
                )
            seen.add(key)
        return self

    def to_project_budget_limits(self, project_uuid: UUID) -> list[ProjectBudgetLimit]:
        return [limit.to_project_budget_limit(project_uuid) for limit in self.limits]


class ProjectBudgetLimitOut(BaseModel):
    uuid: UUID
    algorithm: LimitingAlgorithmType
    window_size: str
    value: float
    created_at: str
    updated_at: str

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    @staticmethod
    def from_project_budget_limit(
        project_budget_limit: ProjectBudgetLimit,
    ) -> ProjectBudgetLimitOut:
        return ProjectBudgetLimitOut(
            uuid=project_budget_limit.uuid,
            algorithm=LimitingAlgorithmType(project_budget_limit.algorithm),
            window_size=project_budget_limit.window_size,
            value=float(project_budget_limit.max_value),
            created_at=str(project_budget_limit.created_at),
            updated_at=str(project_budget_limit.updated_at),
        )
