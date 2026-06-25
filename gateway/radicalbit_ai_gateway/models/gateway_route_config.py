try:
    from typing import Self
except ImportError:
    from typing_extensions import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from radicalbit_ai_gateway.limiting.budget_limiting import BudgetLimiter
from radicalbit_ai_gateway.limiting.rate_limiter import RequestRateLimiter
from radicalbit_ai_gateway.limiting.token_limiter import TokenLimiter
from radicalbit_ai_gateway.models.caching import Caching, SemanticCaching
from radicalbit_ai_gateway.models.fallback import Fallback
from radicalbit_ai_gateway.models.limiting import (
    BudgetLimiting,
    RateLimiting,
    TokenLimiting,
)
from radicalbit_ai_gateway.utils.config_hooks import get_extension_validators


class GatewayRouteConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    route_name: str = Field(
        ...,
        description='Unique name for the route configuration.',
        examples=['example_route', 'production_route'],
    )
    chat_models: list[str] = Field(
        ...,
        description='List of chat model IDs for the route.',
    )
    embedding_models: list[str] | None = Field(
        default=None,
        description='List of embedding model IDs for the route.',
    )
    rate_limiting: RateLimiting | None = Field(
        default=None,
        description='Rate limiting configuration for the route.',
    )
    token_limiting: TokenLimiting | None = Field(
        default=None,
        description='Token limiting configuration for the route.',
    )
    fallback: list[Fallback] | None = Field(
        default=None,
        description='Fallback configuration for the route, specifying primary and fallback models.',
    )
    guardrails: list[str] | None = Field(
        default=None,
        description='List of guardrail IDs to apply to the route.',
    )
    caching: Caching | SemanticCaching | None = Field(
        default=None,
        description='Caching configuration to apply to the route.',
        discriminator='type',
    )
    budget_limiting: BudgetLimiting | None = Field(
        default=None,
        description='Budget limiting configuration for the route, specifying input and output token limits.',
    )
    routing: str | None = Field(
        default=None,
        description='Name of a top-level routing config.',
    )
    extension: dict | None = Field(
        default=None,
        description=(
            'Free-form configuration consumed by enterprise plugins/extensions. '
            'Opaque to the core gateway, which never reads or interprets it; '
            'enabled plugins validate their own keys.'
        ),
    )

    @model_validator(mode='after')
    def run_extension_validators(self) -> Self:
        """Run registered plugin validators against ``extension``.

        Plugins register validators via
        ``radicalbit_ai_gateway.utils.config_hooks.register_extension_validator``.
        A validator raises ValueError on invalid config, which surfaces as a
        normal config validation error.
        """
        if not self.extension:
            return self
        for validate in get_extension_validators():
            validate(self.extension)
        return self

    def get_token_limiter(self) -> TokenLimiter:
        return TokenLimiter(
            route_name=self.route_name,
            input_config=getattr(self.token_limiting, 'input', None),
            output_config=getattr(self.token_limiting, 'output', None),
        )

    def get_budget_limiter(self) -> BudgetLimiter:
        return BudgetLimiter(
            route_name=self.route_name,
            config=self.budget_limiting,
        )

    def get_rate_limiter(self) -> RequestRateLimiter:
        return RequestRateLimiter(
            route_name=self.route_name,
            rate_limiting_config=self.rate_limiting,
        )
