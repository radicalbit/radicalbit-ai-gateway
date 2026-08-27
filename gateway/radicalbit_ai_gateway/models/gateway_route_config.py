from pydantic import BaseModel, ConfigDict, Field

from radicalbit_ai_gateway.limiting.budget_limiting import BudgetLimiter
from radicalbit_ai_gateway.limiting.duration_limiter import DurationLimiter
from radicalbit_ai_gateway.limiting.rate_limiter import RequestRateLimiter
from radicalbit_ai_gateway.limiting.token_limiter import TokenLimiter
from radicalbit_ai_gateway.models.caching import Caching, SemanticCaching
from radicalbit_ai_gateway.models.fallback import Fallback
from radicalbit_ai_gateway.models.limiting import (
    AudioDurationLimiting,
    BudgetLimiting,
    RateLimiting,
    TokenLimiting,
)


class GatewayRouteConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    route_name: str = Field(
        ...,
        description='Unique name for the route configuration.',
        examples=['example_route', 'production_route'],
    )
    chat_models: list[str] | None = Field(
        default=None,
        description='List of chat model IDs for the route.',
    )
    embedding_models: list[str] | None = Field(
        default=None,
        description='List of embedding model IDs for the route.',
    )
    transcription_models: list[str] | None = Field(
        default=None,
        description='List of transcription model IDs for the route.',
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
    duration_limiting: AudioDurationLimiting | None = Field(
        default=None,
        description='Audio duration limiting configuration for transcription routes (WAV only).',
    )
    routing: str | None = Field(
        default=None,
        description='Name of a top-level routing config.',
    )
    plugins: dict | None = Field(
        default=None,
        description=('Plugins configuration for the route.'),
    )
    mcp_servers: list[str] | None = Field(
        default=None,
        description='Aliases of top-level MCP servers exposed on this route.',
    )

    def get_token_limiter(self, project_uuid: str) -> TokenLimiter:
        return TokenLimiter(
            project_uuid=project_uuid,
            route_name=self.route_name,
            input_config=getattr(self.token_limiting, 'input', None),
            output_config=getattr(self.token_limiting, 'output', None),
        )

    def get_budget_limiter(self, project_uuid: str) -> BudgetLimiter:
        return BudgetLimiter(
            project_uuid=project_uuid,
            route_name=self.route_name,
            config=self.budget_limiting,
        )

    def get_rate_limiter(self, project_uuid: str) -> RequestRateLimiter:
        return RequestRateLimiter(
            project_uuid=project_uuid,
            route_name=self.route_name,
            rate_limiting_config=self.rate_limiting,
        )

    def get_duration_limiter(self, project_uuid: str) -> DurationLimiter:
        return DurationLimiter(
            project_uuid=project_uuid,
            route_name=self.route_name,
            config=self.duration_limiting,
        )
