from typing import Annotated, Union

from pydantic import ConfigDict, Field, SecretStr, model_validator
from pydantic.alias_generators import to_camel

from radicalbit_ai_gateway.models.caching import Caching, SemanticCaching
from radicalbit_ai_gateway.models.credentials import Credentials
from radicalbit_ai_gateway.models.fallback import Fallback
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.models.guardrails import (
    CheckParameter,
    Guardrail,
    GuardrailsAIParameter,
    JudgeParameter,
    RedactParameter,
)
from radicalbit_ai_gateway.models.limiting import Limiting, RateLimiting, TokenLimiting
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.models.routing import (
    BudgetConditions,
    DeterministicRoutingConfig,
    OutputMappingEntry,
    SemanticRoutingConfig,
    TextClassificationRoutingConfig,
    TokenLengthConditions,
)


class CredentialsOut(Credentials):
    api_key: SecretStr | None

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class ModelOut(Model):
    credentials: CredentialsOut | None

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
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


class TokenLimitingOut(TokenLimiting):
    input: LimitingOut | None
    output: LimitingOut | None

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


GuardrailParameterOut = Annotated[
    Union[
        CheckParameterOut,
        RedactParameterOut,
        JudgeParameterOut,
        GuardrailsAIParameterOut,
    ],
    Field(discriminator='type'),
]


class GuardrailOut(Guardrail):
    parameters: GuardrailParameterOut

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


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


class OutputMappingEntryOut(OutputMappingEntry):
    conditions: list[str] | TokenLengthConditionsOut | BudgetConditionsOut

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class DeterministicRoutingConfigOut(DeterministicRoutingConfig):
    output_mapping: list[OutputMappingEntryOut]

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class TextClassificationRoutingConfigOut(TextClassificationRoutingConfig):
    output_mapping: list[OutputMappingEntryOut]

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class SemanticRoutingConfigOut(SemanticRoutingConfig):
    output_mapping: list[OutputMappingEntryOut]

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


AnyCachingOut = Annotated[
    Union[CachingOut, SemanticCachingOut],
    Field(discriminator='type'),
]

AnyRoutingConfigOut = Annotated[
    Union[
        DeterministicRoutingConfigOut,
        TextClassificationRoutingConfigOut,
        SemanticRoutingConfigOut,
    ],
    Field(discriminator='type'),
]


class GatewayRouteConfigOut(GatewayRouteConfig):
    chat_models: list[ModelOut]
    embedding_models: list[ModelOut] | None
    rate_limiting: RateLimitingOut | None
    token_limiting: TokenLimitingOut | None
    fallback: list[FallbackOut] | None
    guardrails: list[GuardrailOut] | None
    caching: AnyCachingOut | None
    routing: AnyRoutingConfigOut | None

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )
