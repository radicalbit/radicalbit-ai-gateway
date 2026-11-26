from enum import Enum
from typing import Annotated, Generic, Literal, Protocol, Union

from cron_converter import Cron
from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    Tag,
    field_validator,
    model_validator,
)

# typing_extensions: a TypeVar default needs Python 3.13.
from typing_extensions import TypeVar

from radicalbit_ai_gateway.models.guardrails import GuardrailMessageRole

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
    model_config = ConfigDict(extra='forbid')

    gte: int | None = Field(None, ge=0)
    lte: int | None = Field(None, ge=0)
    between: list[int] | None = Field(None, min_length=2, max_length=2)


class BudgetConditions(BaseModel):
    model_config = ConfigDict(extra='forbid')

    threshold: float = Field(ge=0.0, le=1.0)


Conditions = list[str] | TokenLengthConditions | BudgetConditions

# The conditions an entry holds: the configuration's, or a response's.
ConditionsT = TypeVar('ConditionsT', bound=Conditions, default=Conditions)


class OutputMappingEntry(BaseModel, Generic[ConditionsT]):
    model_config = ConfigDict(extra='forbid')

    model_id: str
    conditions: ConditionsT


ConditionsT_co = TypeVar(
    'ConditionsT_co', bound=Conditions, default=Conditions, covariant=True
)


class ConditionsEntry(Protocol[ConditionsT_co]):
    """What the routing configs read of an output_mapping entry with conditions."""

    @property
    def model_id(self) -> str: ...

    @property
    def conditions(self) -> ConditionsT_co: ...


# The output_mapping entries of a routing config: the configuration's, or a
# response's.
EntryT = TypeVar('EntryT')
ConditionsEntryT = TypeVar(
    'ConditionsEntryT', bound=ConditionsEntry, default=OutputMappingEntry
)
# Deterministic rules read conditions of one kind each.
StringConditionsEntryT = TypeVar(
    'StringConditionsEntryT',
    bound=ConditionsEntry[list[str]],
    default=OutputMappingEntry[list[str]],
)
TokenLengthConditionsEntryT = TypeVar(
    'TokenLengthConditionsEntryT',
    bound=ConditionsEntry[TokenLengthConditions],
    default=OutputMappingEntry[TokenLengthConditions],
)
BudgetConditionsEntryT = TypeVar(
    'BudgetConditionsEntryT',
    bound=ConditionsEntry[BudgetConditions],
    default=OutputMappingEntry[BudgetConditions],
)


class RoutingConfig(BaseModel, Generic[EntryT]):
    """Base class for all routing configurations."""

    model_config = ConfigDict(extra='forbid')

    name: str
    default_model_id: str
    output_mapping: list[EntryT]

    @field_validator('output_mapping')
    @classmethod
    def validate_output_mapping(cls, v: list[EntryT]) -> list[EntryT]:
        if not v:
            raise ValueError('output_mapping must not be empty')
        return v


class DeterministicRoutingConfigBase(RoutingConfig[EntryT], Generic[EntryT]):
    """A fixed rule picks the model; each rule has its own config class."""

    type: Literal['deterministic'] = 'deterministic'


class KeywordRoutingConfig(
    DeterministicRoutingConfigBase[StringConditionsEntryT],
    Generic[StringConditionsEntryT],
):
    """The first entry with a keyword in the last human message wins."""

    rule: Literal[RoutingRuleType.KEYWORD]


class TimeRoutingConfig(
    DeterministicRoutingConfigBase[StringConditionsEntryT],
    Generic[StringConditionsEntryT],
):
    """The first entry with a cron expression matching the current time wins."""

    rule: Literal[RoutingRuleType.TIME]

    @model_validator(mode='after')
    def validate_cron_expressions(self) -> Self:
        for entry in self.output_mapping:
            for cron_str in entry.conditions:
                try:
                    Cron(cron_str)
                except Exception as e:  # noqa: PERF203
                    raise ValueError(
                        f"invalid cron expression '{cron_str}' for model '{entry.model_id}': {e}"
                    ) from e
        return self


class TokenLengthRoutingConfig(
    DeterministicRoutingConfigBase[TokenLengthConditionsEntryT],
    Generic[TokenLengthConditionsEntryT],
):
    """Routes on the token count: of the last human message (token_length) or
    of the whole conversation (context_length).
    """

    rule: Literal[RoutingRuleType.TOKEN_LENGTH, RoutingRuleType.CONTEXT_LENGTH]

    @model_validator(mode='after')
    def validate_conditions(self) -> Self:
        for entry in self.output_mapping:
            conditions = entry.conditions
            set_fields = sum(
                f is not None
                for f in (conditions.gte, conditions.lte, conditions.between)
            )
            if set_fields != 1:
                raise ValueError(
                    f"Rule '{self.rule.value}': conditions for model '{entry.model_id}' must have exactly one of gte, lte, or between set"
                )
            if (
                conditions.between is not None
                and conditions.between[0] > conditions.between[1]
            ):
                raise ValueError(
                    f"Rule '{self.rule.value}': conditions for model '{entry.model_id}' must have between[0] <= between[1]"
                )
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


class BudgetRoutingConfig(
    DeterministicRoutingConfigBase[BudgetConditionsEntryT],
    Generic[BudgetConditionsEntryT],
):
    """The entry with the highest threshold the route's budget usage reached wins."""

    rule: Literal[RoutingRuleType.BUDGET]


def deterministic_rule(value: object) -> object:
    """Return the rule of a deterministic routing config: its input's or a model's."""
    rule = (
        value.get('rule') if isinstance(value, dict) else getattr(value, 'rule', None)
    )
    return rule.value if isinstance(rule, RoutingRuleType) else rule


def routing_tag(value: object) -> object:
    """Return the tag of a routing config in one flat union: its rule for
    deterministic routing, its type otherwise.
    """
    routing_type = (
        value.get('type') if isinstance(value, dict) else getattr(value, 'type', None)
    )
    if routing_type == 'deterministic':
        return deterministic_rule(value)
    return routing_type


# Picks the config class by rule. A callable, not 'rule', for an error that
# lists the rules' values: the default lists the enum members' reprs.
RULE_DISCRIMINATOR = Discriminator(
    deterministic_rule,
    custom_error_type='invalid_routing_rule',
    custom_error_message=(
        'rule must be one of: '
        + ', '.join(repr(rule.value) for rule in RoutingRuleType)
    ),
)

DeterministicRoutingConfig = Annotated[
    Union[
        Annotated[KeywordRoutingConfig, Tag(RoutingRuleType.KEYWORD.value)],
        Annotated[TokenLengthRoutingConfig, Tag(RoutingRuleType.TOKEN_LENGTH.value)],
        Annotated[TokenLengthRoutingConfig, Tag(RoutingRuleType.CONTEXT_LENGTH.value)],
        Annotated[TimeRoutingConfig, Tag(RoutingRuleType.TIME.value)],
        Annotated[BudgetRoutingConfig, Tag(RoutingRuleType.BUDGET.value)],
    ],
    RULE_DISCRIMINATOR,
]


class TextClassificationRoutingConfig(
    RoutingConfig[ConditionsEntryT], Generic[ConditionsEntryT]
):
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


class SemanticRoutingConfig(RoutingConfig[ConditionsEntryT], Generic[ConditionsEntryT]):
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


class DecisionOutputMappingEntry(BaseModel):
    """One option offered to a routing model: decision or LLM routing."""

    model_config = ConfigDict(extra='forbid')

    model_id: str
    description: str

    @field_validator('description')
    @classmethod
    def validate_description(cls, v: str) -> str:
        if not v.strip():
            raise ValueError('description must not be empty')
        return v


# The options of a routing model: the configuration's, or a response's.
ChoiceEntryT = TypeVar(
    'ChoiceEntryT', bound=DecisionOutputMappingEntry, default=DecisionOutputMappingEntry
)


class ModelChoiceRoutingConfig(RoutingConfig[ChoiceEntryT], Generic[ChoiceEntryT]):
    """A routing model reads the request and picks among described options."""

    history: Literal['last', 'all'] = 'last'
    message_roles: list[GuardrailMessageRole] | None = None

    @field_validator('message_roles', mode='before')
    @classmethod
    def validate_message_roles(cls, value):
        """Accept roles in any case, as guardrails do."""
        if isinstance(value, list):
            return [v.upper() if isinstance(v, str) else v for v in value]
        return value

    @model_validator(mode='after')
    def validate_message_roles_need_history_all(self) -> Self:
        if self.message_roles is not None and self.history == 'last':
            raise ValueError(
                'message_roles needs history: all. With history: last only the '
                'last human message is sent.'
            )
        return self


class DecisionRoutingConfig(
    ModelChoiceRoutingConfig[ChoiceEntryT], Generic[ChoiceEntryT]
):
    """A decision model chooses the chat model among the output_mapping options."""

    type: Literal['decision'] = 'decision'
    decision_model_id: str
    fallback_model_id: str | None = None
    instructions: str
    min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator('instructions')
    @classmethod
    def validate_instructions(cls, v: str) -> str:
        if not v.strip():
            raise ValueError('instructions must not be empty')
        return v

    @field_validator('output_mapping')
    @classmethod
    def validate_at_least_two_options(cls, v: list[ChoiceEntryT]) -> list[ChoiceEntryT]:
        # The base validator only rejects an empty list.
        if len(v) < 2:
            raise ValueError('decision routing needs at least 2 output_mapping entries')
        return v


class LLMRoutingConfig(ModelChoiceRoutingConfig[ChoiceEntryT], Generic[ChoiceEntryT]):
    """A chat model scores the request against every output_mapping option."""

    type: Literal['llm'] = 'llm'
    router_model_id: str
    fallback_model_id: str | None = None
    threshold: float = Field(default=0.375, ge=0.0, le=1.0)
    timeout: float = Field(
        default=10.0,
        gt=0,
        description='Timeout in seconds for each router model call',
    )

    @model_validator(mode='after')
    def validate_unique_model_ids(self) -> Self:
        model_ids = [entry.model_id for entry in self.output_mapping]
        if len(model_ids) != len(set(model_ids)):
            raise ValueError('LLM routing: output_mapping model_ids must be unique')
        return self


AnyRoutingConfig = Annotated[
    Union[
        DeterministicRoutingConfig,
        TextClassificationRoutingConfig,
        SemanticRoutingConfig,
        DecisionRoutingConfig,
        LLMRoutingConfig,
    ],
    Field(discriminator='type'),
]
