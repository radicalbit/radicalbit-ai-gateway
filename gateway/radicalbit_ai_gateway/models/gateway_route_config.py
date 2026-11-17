from pydantic import BaseModel, ConfigDict, Field

from radicalbit_ai_gateway.models.caching import Caching, SemanticCaching
from radicalbit_ai_gateway.models.fallback import Fallback
from radicalbit_ai_gateway.models.limiting import (
    AudioDurationLimiting,
    BudgetLimiting,
    RateLimiting,
    TokenLimiting,
)
from radicalbit_ai_gateway.models.responses import ResponsesSettings


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
    decision_models: list[str] | None = Field(
        default=None,
        description='List of decision model IDs for the route. The first one serves its traffic.',
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
        description='Shared budget limiting configuration for the route, covering input and output costs.',
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
    responses: ResponsesSettings | None = Field(
        default=None,
        description='Governance of the OpenAI Responses API on this route.',
    )
