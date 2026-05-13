from enum import Enum
from typing import Annotated, Literal, Union

from cron_converter import Cron
from pydantic import BaseModel, Field, field_validator, model_validator

try:
    from typing import Self
except ImportError:
    from typing_extensions import Self


class RoutingRuleType(str, Enum):
    KEYWORD = 'keyword'
    TOKEN_LENGTH = 'token_length'
    CONTEXT_LENGTH = 'context_length'
    TIME = 'time'
    BUDGET = 'budget'


class TokenLengthConditions(BaseModel):
    gte: int | None = Field(None, ge=0)
    lte: int | None = Field(None, ge=0)
    between: list[int] | None = Field(None, min_length=2, max_length=2)


class BudgetConditions(BaseModel):
    threshold: float = Field(ge=0.0, le=1.0)


class OutputMappingEntry(BaseModel):
    model_id: str
    conditions: list[str] | TokenLengthConditions | BudgetConditions


class RoutingConfig(BaseModel):
    """Base class for all routing configurations."""

    name: str
    default_model_id: str
    output_mapping: list[OutputMappingEntry]

    @field_validator('output_mapping')
    @classmethod
    def validate_output_mapping(
        cls, v: list[OutputMappingEntry]
    ) -> list[OutputMappingEntry]:
        if not v:
            raise ValueError('output_mapping must not be empty')
        return v


class DeterministicRoutingConfig(RoutingConfig):
    type: Literal['deterministic'] = 'deterministic'
    rule: RoutingRuleType

    @model_validator(mode='after')
    def validate_conditions_match_rule(self) -> Self:
        for entry in self.output_mapping:
            if self.rule in (RoutingRuleType.KEYWORD, RoutingRuleType.TIME):
                if not isinstance(entry.conditions, list):
                    raise ValueError(
                        f"Rule '{self.rule.value}': conditions for model '{entry.model_id}' must be a list of strings"
                    )
                if self.rule == RoutingRuleType.TIME:
                    for cron_str in entry.conditions:
                        try:
                            Cron(cron_str)
                        except Exception as e:  # noqa: PERF203
                            raise ValueError(
                                f"invalid cron expression '{cron_str}' for model '{entry.model_id}': {e}"
                            ) from e
            elif self.rule in (
                RoutingRuleType.TOKEN_LENGTH,
                RoutingRuleType.CONTEXT_LENGTH,
            ):
                if not isinstance(entry.conditions, TokenLengthConditions):
                    raise ValueError(
                        f"Rule '{self.rule.value}': conditions for model '{entry.model_id}' must be a TokenLengthConditions object"
                    )
                set_fields = sum(
                    f is not None
                    for f in (
                        entry.conditions.gte,
                        entry.conditions.lte,
                        entry.conditions.between,
                    )
                )
                if set_fields != 1:
                    raise ValueError(
                        f"Rule '{self.rule.value}': conditions for model '{entry.model_id}' must have exactly one of gte, lte, or between set"
                    )
                if (
                    entry.conditions.between is not None
                    and entry.conditions.between[0] > entry.conditions.between[1]
                ):
                    raise ValueError(
                        f"Rule '{self.rule.value}': conditions for model '{entry.model_id}' must have between[0] <= between[1]"
                    )

            elif self.rule == RoutingRuleType.BUDGET:
                if not isinstance(entry.conditions, BudgetConditions):
                    raise ValueError(
                        f"Rule 'budget': conditions for model '{entry.model_id}' must be a BudgetConditions object"
                    )

        if self.rule in (RoutingRuleType.TOKEN_LENGTH, RoutingRuleType.CONTEXT_LENGTH):
            self._validate_no_overlapping_ranges()

        return self

    def _validate_no_overlapping_ranges(self) -> None:
        """Check that no between range overlaps with another condition.

        gte/gte and lte/lte overlaps are fine — the router sorts them
        deterministically. Only between ranges create ambiguity.
        """
        INF = float('inf')
        between_ranges: list[tuple[str, float, float]] = []
        other_ranges: list[tuple[str, float, float]] = []
        for entry in self.output_mapping:
            cond = entry.conditions
            if not isinstance(cond, TokenLengthConditions):
                continue
            if cond.between is not None:
                between_ranges.append(
                    (entry.model_id, cond.between[0], cond.between[1])
                )
            elif cond.gte is not None:
                other_ranges.append((entry.model_id, cond.gte, INF))
            elif cond.lte is not None:
                other_ranges.append((entry.model_id, 0, cond.lte))

        # Check between vs between
        for i in range(len(between_ranges)):
            for j in range(i + 1, len(between_ranges)):
                id_a, lo_a, hi_a = between_ranges[i]
                id_b, lo_b, hi_b = between_ranges[j]
                if lo_a <= hi_b and lo_b <= hi_a:
                    raise ValueError(
                        f"Rule '{self.rule.value}': overlapping conditions between model '{id_a}' and model '{id_b}'"
                    )
        # Check between vs gte/lte
        for id_a, lo_a, hi_a in between_ranges:
            for id_b, lo_b, hi_b in other_ranges:
                if lo_a <= hi_b and lo_b <= hi_a:
                    raise ValueError(
                        f"Rule '{self.rule.value}': overlapping conditions between model '{id_a}' and model '{id_b}'"
                    )


class TextClassificationRoutingConfig(RoutingConfig):
    type: Literal['text_classification'] = 'text_classification'
    url: str
    timeout: float = Field(
        default=5.0, gt=0, description='HTTP timeout in seconds for classifier calls'
    )

    @field_validator('url')
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v.startswith(('http://', 'https://')):
            raise ValueError("url must start with 'http://' or 'https://'")
        return v


class SemanticRoutingConfig(RoutingConfig):
    type: Literal['semantic'] = 'semantic'
    embedding_model_id: str
    similarity_threshold: float = Field(default=0.35, ge=0.0, le=1.0)

    @model_validator(mode='after')
    def validate_conditions_are_string_lists(self) -> Self:
        for entry in self.output_mapping:
            if not isinstance(entry.conditions, list):
                raise TypeError(
                    f"Semantic routing: conditions for model '{entry.model_id}' must be a list of strings"
                )
        return self


AnyRoutingConfig = Annotated[
    Union[
        DeterministicRoutingConfig,
        TextClassificationRoutingConfig,
        SemanticRoutingConfig,
    ],
    Field(discriminator='type'),
]
