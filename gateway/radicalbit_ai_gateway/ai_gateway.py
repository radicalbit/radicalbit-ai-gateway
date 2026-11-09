from radicalbit_ai_gateway.caching.gateway_cache import GatewayCache
from radicalbit_ai_gateway.caching.route_cache import RouteCache
from radicalbit_ai_gateway.guardrails.guardrails import RouteGuardrails
from radicalbit_ai_gateway.invocation.chat_model_invoker import ChatModelInvoker
from radicalbit_ai_gateway.invocation.decision_model_invoker import DecisionModelInvoker
from radicalbit_ai_gateway.invocation.embedding_model_invoker import (
    EmbeddingModelInvoker,
)
from radicalbit_ai_gateway.invocation.transcription_model_invoker import (
    TranscriptionModelInvoker,
)
from radicalbit_ai_gateway.limiting.limits import RequestLimits, RouteLimits
from radicalbit_ai_gateway.models.fallback import FallbackModelType
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.models.request_identity import RequestIdentity
from radicalbit_ai_gateway.pipeline.scope import RequestScope
from radicalbit_ai_gateway.routing import (
    DecisionRouter,
    DeterministicRouter,
    LLMRouter,
    SemanticRouter,
    TextClassificationRouter,
)
from radicalbit_ai_gateway.services.cost_service import CostService


class GatewayRoute:
    """A route, built once when its configuration is loaded: its models and
    their invokers, its router, and its limits, guardrails and cache. A
    request to it runs in a ``RequestScope`` (see ``for_request``) through
    the endpoint's pipeline (``radicalbit_ai_gateway.pipeline``).
    """

    def __init__(
        self,
        gateway_route_config: GatewayRouteConfig,
        chat_models: list[Model] | None,
        embedding_models: list[Model] | None,
        cost_service: CostService,
        gateway_cache: GatewayCache | None,
        httpx_client=None,
        router: DeterministicRouter
        | SemanticRouter
        | TextClassificationRouter
        | DecisionRouter
        | LLMRouter
        | None = None,
        route_limits: RouteLimits = RouteLimits(),
        transcription_models: list[Model] | None = None,
        decision_models: list[Model] | None = None,
        guardrails: RouteGuardrails = RouteGuardrails(),
        project_uuid: str = '',
        project_name: str = '',
    ):
        self.gateway_route_config = gateway_route_config
        self.project_uuid = project_uuid
        self.project_name = project_name
        self.chat_models = chat_models or []
        self.embedding_models = embedding_models or []
        self.transcription_models = transcription_models or []
        self.decision_models = decision_models or []
        self.router = router
        self.guardrails = guardrails
        self.gateway_cache = gateway_cache
        self.route_limits = route_limits
        self.cost_service = cost_service

        def invoker(cls, models: list[Model], kind: FallbackModelType):
            """Return the invoker of ``models``, None when there are none."""
            if not models:
                return None
            return cls(
                models=models,
                fallbacks=[
                    fallback
                    for fallback in gateway_route_config.fallback or []
                    if fallback.type == kind
                ],
                cost_service=cost_service,
                httpx_client=httpx_client,
            )

        self.chat_invoker: ChatModelInvoker | None = invoker(
            ChatModelInvoker, self.chat_models, FallbackModelType.CHAT
        )
        self.embedding_invoker: EmbeddingModelInvoker | None = invoker(
            EmbeddingModelInvoker, self.embedding_models, FallbackModelType.EMBEDDING
        )
        self.transcription_invoker: TranscriptionModelInvoker | None = invoker(
            TranscriptionModelInvoker,
            self.transcription_models,
            FallbackModelType.TRANSCRIPTION,
        )
        self.decision_invoker: DecisionModelInvoker | None = invoker(
            DecisionModelInvoker, self.decision_models, FallbackModelType.DECISION
        )
        self.ttl = (
            gateway_route_config.caching.ttl if gateway_route_config.caching else None
        )
        self.cache = RouteCache.from_config(
            gateway_route_config,
            gateway_cache,
            cost_service,
            self.embedding_invoker,
            self.embedding_models,
        )

    def for_request(
        self, identity: RequestIdentity, limits: RequestLimits
    ) -> RequestScope:
        """Return the scope of one request to this route: its limits, and the
        route's guardrails and cache bound to it. Judge and semantic cache
        calls are charged to its limits (ADR 0006).
        """
        return RequestScope(
            route=self,
            identity=identity,
            limits=limits,
            guardrails=self.guardrails.for_request(identity, limits.charge_call),
            cache=self.cache.for_request(identity, limits),
        )
