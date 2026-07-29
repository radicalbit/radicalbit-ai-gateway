from collections.abc import Awaitable, Callable
import logging
from uuid import UUID

from fastapi import FastAPI
from langchain.embeddings.base import init_embeddings
from langchain_core.embeddings import Embeddings
import redis

from radicalbit_ai_gateway.ai_gateway import GatewayRoute
from radicalbit_ai_gateway.caching.abstract_cache import AbstractCache
from radicalbit_ai_gateway.caching.gateway_cache import GatewayCache
from radicalbit_ai_gateway.caching.in_memory_cache import CacheToolsInMemory
from radicalbit_ai_gateway.caching.redis_cache import RedisCache
from radicalbit_ai_gateway.caching.semantic_caching import SemanticCache
from radicalbit_ai_gateway.guardrails.guardrail_engine import GuardrailEngine
from radicalbit_ai_gateway.guardrails.judges.judge_engine import JudgeEngine
from radicalbit_ai_gateway.guardrails.presidio import PresidioEngine
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.models.model import MockGatewayEmbeddings, Model
from radicalbit_ai_gateway.models.project_entry import ProjectEntry
from radicalbit_ai_gateway.models.routing import (
    SemanticRoutingConfig,
    TextClassificationRoutingConfig,
)
from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.routing import (
    DeterministicRouter,
    SemanticRouter,
    TextClassificationRouter,
)
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.parse_provider_and_model import (
    parse_provider_and_model,
)
from radicalbit_ai_gateway.utils.secrets import resolve_secrets_from_string

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)


def build_embeddings_model(model: Model, httpx_client=None) -> Embeddings:
    provider, model_name = parse_provider_and_model(model.model)
    params = model.params or {}
    credentials = (
        model.credentials.model_dump(exclude_none=True) if model.credentials else {}
    )
    if provider == 'mock':
        latency_ms = int(params.get('latency_ms', 0))
        vector_size = int(params.get('vector_size', 5))
        return MockGatewayEmbeddings(latency_ms=latency_ms, vector_size=vector_size)
    langchain_provider = provider.replace('-', '_')
    return init_embeddings(
        model=model_name,
        provider=langchain_provider,
        http_async_client=httpx_client,
        **{**params, **credentials},
    )


async def initialize_async_routers(routes: dict[str, GatewayRoute]) -> None:
    for route_name, route in routes.items():
        if isinstance(route.router, SemanticRouter):
            try:
                await route.router.initialize()
            except Exception:
                logger.exception(
                    'Failed to initialize semantic router for route %s — '
                    'will fall back to default model',
                    route_name,
                )


def get_proper_cache(
    route_config: GatewayRouteConfig, redis_client: redis.Redis | None
) -> AbstractCache | None:
    if not route_config.caching:
        return None
    if redis_client is None:
        return CacheToolsInMemory()
    if route_config.caching.type == 'exact':
        return RedisCache(redis_client=redis_client)
    return SemanticCache(
        redis_client=redis_client,
        similarity_threshold=route_config.caching.similarity_threshold,
        dim=route_config.caching.dim,
        distance_metric=route_config.caching.distance_metric,
    )


def build_gateway_routes_from_config(
    gateway_config: GatewayConfig,
    guardrail_engine: GuardrailEngine,
    redis_client: redis.Redis | None,
    cost_service: CostService,
    httpx_client,
) -> dict[str, GatewayRoute]:
    routes: dict[str, GatewayRoute] = {}
    chat_by_id = gateway_config.chat_models_by_id
    emb_by_id = gateway_config.embedding_models_by_id
    transcription_by_id = gateway_config.transcription_models_by_id

    for route_name, route_config in gateway_config.routes.items():
        chat_models = (
            [chat_by_id[mid] for mid in (route_config.chat_models or [])]
            if route_config.chat_models
            else None
        )
        embedding_models = (
            [emb_by_id[mid] for mid in (route_config.embedding_models or [])]
            if route_config.embedding_models
            else None
        )
        transcription_models = (
            [
                transcription_by_id[mid]
                for mid in (route_config.transcription_models or [])
            ]
            if route_config.transcription_models
            else None
        )
        cache_client = get_proper_cache(route_config, redis_client)
        gateway_cache = GatewayCache(cache_client) if cache_client is not None else None
        token_limiter = (
            route_config.get_token_limiter() if route_config.token_limiting else None
        )
        rate_limiter = (
            route_config.get_rate_limiter() if route_config.rate_limiting else None
        )
        budget_limiter = (
            route_config.get_budget_limiter() if route_config.budget_limiting else None
        )
        router = None
        if route_config.routing and gateway_config.routing:
            routing_config = gateway_config.routing_by_name.get(route_config.routing)
            if routing_config:
                route_models_by_id = {m.model_id: m for m in (chat_models or [])}
                if isinstance(routing_config, TextClassificationRoutingConfig):
                    router = TextClassificationRouter(
                        config=routing_config,
                        models_by_id=route_models_by_id,
                    )
                elif isinstance(routing_config, SemanticRoutingConfig):
                    emb_model = gateway_config.embedding_models_by_id[
                        routing_config.embedding_model_id
                    ]
                    embeddings_instance = build_embeddings_model(
                        emb_model, httpx_client
                    )
                    router = SemanticRouter(
                        config=routing_config,
                        models_by_id=route_models_by_id,
                        embeddings_model=embeddings_instance,
                    )
                else:
                    router = DeterministicRouter(
                        config=routing_config,
                        models_by_id=route_models_by_id,
                        budget_limiter=budget_limiter,
                    )
        routes[route_name] = GatewayRoute(
            gateway_route_config=route_config,
            chat_models=chat_models,
            embedding_models=embedding_models,
            transcription_models=transcription_models,
            guardrail_engine=guardrail_engine,
            gateway_cache=gateway_cache,
            cost_service=cost_service,
            httpx_client=httpx_client,
            router=router,
            token_limiter=token_limiter,
            rate_limiter=rate_limiter,
            budget_limiter=budget_limiter,
        )

    return routes


def build_project_route_registrar(
    app: FastAPI,
    httpx_client,
) -> tuple[
    Callable[[UUID, str, str], Awaitable[None]], Callable[[UUID], Awaitable[None]]
]:
    """Return callables to register and deregister project routes.

    The register callable parses a YAML config string and registers the
    declared routes in ``app.state.routes`` under the key
    ``project_name/route_name``.

    The deregister callable removes all routes and the project config
    for a given project UUID.
    """
    presidio_engine = PresidioEngine()
    judge_engine = JudgeEngine(
        prompt_manager=PromptManager.get_global(),
        httpx_client=httpx_client,
    )

    async def register_project_routes(
        project_uuid: UUID,
        project_name: str,
        yaml_content: str,
    ) -> None:
        resolved = resolve_secrets_from_string(yaml_content)
        project_gateway_config = GatewayConfig.model_validate(resolved)
        project_cost_service = CostService(
            chat_models_by_id=project_gateway_config.chat_models_by_id,
            embedding_models_by_id=project_gateway_config.embedding_models_by_id,
            transcription_models_by_id=project_gateway_config.transcription_models_by_id,
        )
        project_guardrail_engine = GuardrailEngine(
            presidio_engine=presidio_engine,
            judge_engine=judge_engine,
            guardrails=project_gateway_config.guardrails,
            chat_models_by_id=project_gateway_config.chat_models_by_id,
            cost_service=project_cost_service,
        )

        project_redis_client = None
        if project_gateway_config.cache:
            project_redis_client = redis.asyncio.Redis(
                host=project_gateway_config.cache.redis_host,
                port=project_gateway_config.cache.redis_port,
                decode_responses=True,
            )
        routes = build_gateway_routes_from_config(
            project_gateway_config,
            project_guardrail_engine,
            project_redis_client,
            project_cost_service,
            httpx_client,
        )
        uuid_str = str(project_uuid)
        await initialize_async_routers(routes)
        for route_name, route in routes.items():
            full_key = f'{project_name}/{route_name}'
            route.project_uuid = uuid_str
            route.project_name = project_name
            app.state.routes[full_key] = route
            logger.info('Registered project route: %s', full_key)

        app.state.project_configs[project_name] = ProjectEntry(
            uuid=project_uuid,
            config=project_gateway_config,
        )
        logger.info('Registered project config: %s', project_name)

    async def deregister_project_routes(project_uuid: UUID) -> None:
        uuid_str = str(project_uuid)
        keys_to_remove = [
            key
            for key, route in app.state.routes.items()
            if getattr(route, 'project_uuid', None) == uuid_str
        ]
        for key in keys_to_remove:
            del app.state.routes[key]
            logger.info('Deregistered project route: %s', key)

        config_key = next(
            (
                name
                for name, entry in app.state.project_configs.items()
                if entry.uuid == project_uuid
            ),
            None,
        )
        if config_key:
            del app.state.project_configs[config_key]
            logger.info('Deregistered project config: %s', config_key)

    return register_project_routes, deregister_project_routes
