from typing import Annotated, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    SecretStr,
    Tag,
    model_validator,
)
from pydantic.alias_generators import to_camel

from radicalbit_ai_gateway.models.caching import Caching, SemanticCaching
from radicalbit_ai_gateway.models.credentials import CredentialsOut
from radicalbit_ai_gateway.models.fallback import Fallback
from radicalbit_ai_gateway.models.gateway_route_config import (
    RouteBudgetLimiting,
    RouteName,
    RoutePlugins,
    RouteResponses,
)
from radicalbit_ai_gateway.models.guardrails import (
    GUARDRAIL_DISCRIMINATOR,
    CheckGuardrail,
    CheckParameter,
    DecisionJudgeGuardrail,
    DecisionJudgeParameter,
    GuardrailsAIGuardrail,
    GuardrailsAIParameter,
    JudgeGuardrail,
    JudgeParameter,
    PresidioAnalyzerGuardrail,
    PresidioAnonymizerGuardrail,
    RedactParameter,
)
from radicalbit_ai_gateway.models.limiting import (
    AudioDurationLimiting,
    Limiting,
    RateLimiting,
    TokenLimiting,
)
from radicalbit_ai_gateway.models.mcp_server import McpHttpServer, McpStdioServer
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.models.routing import (
    BudgetConditions,
    BudgetRoutingConfig,
    DecisionOutputMappingEntry,
    DecisionRoutingConfig,
    KeywordRoutingConfig,
    LLMRoutingConfig,
    OutputMappingEntry,
    RoutingRuleType,
    SemanticRoutingConfig,
    TextClassificationRoutingConfig,
    TimeRoutingConfig,
    TokenLengthConditions,
    TokenLengthRoutingConfig,
    routing_tag,
)

__all__ = ['CredentialsOut']


class ModelOut(Model[CredentialsOut]):
    credentials: CredentialsOut | None

    # Built from Model.model_dump(), which also holds the computed fields.
    model_config = ConfigDict(
        extra='ignore',
        populate_by_name=True,
        alias_generator=to_camel,
        protected_namespaces=(),
    )

    @model_validator(mode='after')
    def camelize_dict(self):
        params = self.params
        if params:
            self.params = {to_camel(k): v for k, v in params.items()}
        return self


class LimitingOut(Limiting):
    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class RateLimitingOut(RateLimiting):
    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class TokenLimitingOut(TokenLimiting[LimitingOut]):
    input: LimitingOut | None
    output: LimitingOut | None

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class DurationLimitingOut(AudioDurationLimiting):
    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class FallbackOut(Fallback):
    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class JudgeParameterOut(JudgeParameter):
    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class DecisionJudgeParameterOut(DecisionJudgeParameter):
    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
        protected_namespaces=(),
        extra='forbid',
    )


class CheckParameterOut(CheckParameter):
    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class RedactParameterOut(RedactParameter):
    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class GuardrailsAIParameterOut(GuardrailsAIParameter):
    api_key: SecretStr | None = None

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


_GUARDRAIL_OUT_CONFIG = ConfigDict(
    populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
)


class CheckGuardrailOut(CheckGuardrail[CheckParameterOut]):
    model_config = _GUARDRAIL_OUT_CONFIG


class PresidioAnalyzerGuardrailOut(PresidioAnalyzerGuardrail[RedactParameterOut]):
    model_config = _GUARDRAIL_OUT_CONFIG


class PresidioAnonymizerGuardrailOut(PresidioAnonymizerGuardrail[RedactParameterOut]):
    model_config = _GUARDRAIL_OUT_CONFIG


class JudgeGuardrailOut(JudgeGuardrail[JudgeParameterOut]):
    model_config = _GUARDRAIL_OUT_CONFIG


class DecisionJudgeGuardrailOut(DecisionJudgeGuardrail[DecisionJudgeParameterOut]):
    model_config = _GUARDRAIL_OUT_CONFIG


class GuardrailsAIGuardrailOut(GuardrailsAIGuardrail[GuardrailsAIParameterOut]):
    model_config = _GUARDRAIL_OUT_CONFIG


GuardrailOut = Annotated[
    Annotated[CheckGuardrailOut, Tag('CHECK')]
    | Annotated[PresidioAnalyzerGuardrailOut, Tag('PRESIDIO_ANALYZER')]
    | Annotated[PresidioAnonymizerGuardrailOut, Tag('PRESIDIO_ANONYMIZER')]
    | Annotated[JudgeGuardrailOut, Tag('JUDGE')]
    | Annotated[DecisionJudgeGuardrailOut, Tag('DECISION_JUDGE')]
    | Annotated[GuardrailsAIGuardrailOut, Tag('GUARDRAILS_AI')],
    GUARDRAIL_DISCRIMINATOR,
]


# Caching Out classes
class CachingOut(Caching):
    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class SemanticCachingOut(SemanticCaching):
    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


# Routing Out classes
class TokenLengthConditionsOut(TokenLengthConditions):
    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class BudgetConditionsOut(BudgetConditions):
    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


ConditionsOut = list[str] | TokenLengthConditionsOut | BudgetConditionsOut


class OutputMappingEntryOut(OutputMappingEntry[ConditionsOut]):
    conditions: ConditionsOut

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class StringConditionsEntryOut(OutputMappingEntry[list[str]]):
    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class TokenLengthConditionsEntryOut(OutputMappingEntry[TokenLengthConditionsOut]):
    conditions: TokenLengthConditionsOut

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class BudgetConditionsEntryOut(OutputMappingEntry[BudgetConditionsOut]):
    conditions: BudgetConditionsOut

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class KeywordRoutingConfigOut(KeywordRoutingConfig[StringConditionsEntryOut]):
    output_mapping: list[StringConditionsEntryOut]

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class TimeRoutingConfigOut(TimeRoutingConfig[StringConditionsEntryOut]):
    output_mapping: list[StringConditionsEntryOut]

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class TokenLengthRoutingConfigOut(
    TokenLengthRoutingConfig[TokenLengthConditionsEntryOut]
):
    output_mapping: list[TokenLengthConditionsEntryOut]

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class BudgetRoutingConfigOut(BudgetRoutingConfig[BudgetConditionsEntryOut]):
    output_mapping: list[BudgetConditionsEntryOut]

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class TextClassificationRoutingConfigOut(
    TextClassificationRoutingConfig[OutputMappingEntryOut]
):
    output_mapping: list[OutputMappingEntryOut]

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class SemanticRoutingConfigOut(SemanticRoutingConfig[OutputMappingEntryOut]):
    output_mapping: list[OutputMappingEntryOut]

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class DecisionOutputMappingEntryOut(DecisionOutputMappingEntry):
    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class DecisionRoutingConfigOut(DecisionRoutingConfig[DecisionOutputMappingEntryOut]):
    output_mapping: list[DecisionOutputMappingEntryOut]

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class LLMRoutingConfigOut(LLMRoutingConfig[DecisionOutputMappingEntryOut]):
    output_mapping: list[DecisionOutputMappingEntryOut]

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


AnyCachingOut = Annotated[
    Union[CachingOut, SemanticCachingOut],
    Field(discriminator='type'),
]

# Flat, not deterministic configs nested by rule within a union by type: the
# OpenAPI discriminator mapping of a nested union is not a schema reference.
AnyRoutingConfigOut = Annotated[
    Union[
        Annotated[KeywordRoutingConfigOut, Tag(RoutingRuleType.KEYWORD.value)],
        Annotated[TokenLengthRoutingConfigOut, Tag(RoutingRuleType.TOKEN_LENGTH.value)],
        Annotated[
            TokenLengthRoutingConfigOut, Tag(RoutingRuleType.CONTEXT_LENGTH.value)
        ],
        Annotated[TimeRoutingConfigOut, Tag(RoutingRuleType.TIME.value)],
        Annotated[BudgetRoutingConfigOut, Tag(RoutingRuleType.BUDGET.value)],
        Annotated[TextClassificationRoutingConfigOut, Tag('text_classification')],
        Annotated[SemanticRoutingConfigOut, Tag('semantic')],
        Annotated[DecisionRoutingConfigOut, Tag('decision')],
        Annotated[LLMRoutingConfigOut, Tag('llm')],
    ],
    Discriminator(routing_tag),
]


class McpHttpServerOut(McpHttpServer[SecretStr]):
    headers: dict[str, SecretStr] | None = None

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class McpStdioServerOut(McpStdioServer[SecretStr]):
    env: dict[str, SecretStr] | None = None

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


AnyMcpServerOut = Annotated[
    Union[McpHttpServerOut, McpStdioServerOut],
    Field(discriminator='transport'),
]


class UsedModelsOut(BaseModel):
    """Every model a route uses, per category: its own lists plus the models
    its guardrails and routing call.
    """

    chat: list[ModelOut] = []
    embedding: list[ModelOut] = []
    transcription: list[ModelOut] = []
    decision: list[ModelOut] = []

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


# A route's configuration with what it references resolved: models,
# guardrails, routing and MCP servers in full, secrets masked. Not a
# GatewayRouteConfig, where these fields hold names. No docstring: it would
# become the schema's description.
class GatewayRouteConfigOut(BaseModel):
    route_name: RouteName
    chat_models: list[ModelOut] | None
    embedding_models: list[ModelOut] | None
    transcription_models: list[ModelOut] | None
    decision_models: list[ModelOut] | None
    rate_limiting: RateLimitingOut | None
    token_limiting: TokenLimitingOut | None
    fallback: list[FallbackOut] | None
    guardrails: list[GuardrailOut] | None
    caching: AnyCachingOut | None
    budget_limiting: RouteBudgetLimiting = None
    duration_limiting: DurationLimitingOut | None
    routing: AnyRoutingConfigOut | None
    plugins: RoutePlugins = None
    mcp_servers: list[AnyMcpServerOut] | None
    responses: RouteResponses = None
    used_models: UsedModelsOut | None = None

    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
        alias_generator=to_camel,
        protected_namespaces=(),
    )
