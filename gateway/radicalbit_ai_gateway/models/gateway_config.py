from collections import Counter
from typing import Any

from radicalbit_ai_gateway.models.model import Model

try:
    from typing import Self
except ImportError:
    from typing_extensions import Self

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from radicalbit_ai_gateway.models.caching import CacheConfig, SemanticCaching
from radicalbit_ai_gateway.models.fallback import FallbackModelType
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.models.guardrails import Guardrail, GuardrailType
from radicalbit_ai_gateway.models.routing import (
    AnyRoutingConfig,
    DeterministicRoutingConfig,
    RoutingRuleType,
    SemanticRoutingConfig,
)
from radicalbit_ai_gateway.utils.config_hooks import (
    build_route_extension_model,
    get_extension_validators,
    get_known_extension_keys,
)


def get_model_from_model_id(
    models_by_id: dict[str, Model],
    route_name: str,
    model_id: str,
) -> Model:
    model = models_by_id.get(model_id)
    if model:
        return model

    raise ValueError(f'Model {model_id} not found for route {route_name}')


class GatewayConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    routes: dict[str, GatewayRouteConfig] = {}
    chat_models: list[Model]
    embedding_models: list[Model] | None = None
    cache: CacheConfig | None = None
    guardrails: list[Guardrail] | None = None
    routing: list[AnyRoutingConfig] | None = None

    @property
    def chat_models_by_id(self) -> dict[str, Model]:
        return {m.model_id: m for m in self.chat_models}

    @property
    def embedding_models_by_id(self) -> dict[str, Model]:
        return {m.model_id: m for m in (self.embedding_models or [])}

    @property
    def routing_by_name(self) -> dict[str, AnyRoutingConfig]:
        return {r.name: r for r in (self.routing or [])}

    @property
    def is_semantic_caching_enable(self) -> bool:
        return any(
            route.caching is not None and route.caching.type == 'semantic'
            for route in self.routes.values()
        )

    def has_judge_guardrail(self, route_config: GatewayRouteConfig) -> bool:
        """Check if the route has any guardrails with type JUDGE."""
        if not self.guardrails or not route_config.guardrails:
            return False
        guardrail_names = set(route_config.guardrails)
        return any(
            g.name in guardrail_names and g.type == GuardrailType.JUDGE
            for g in self.guardrails
        )

    def get_route_feature_flags(
        self, route_config: GatewayRouteConfig
    ) -> tuple[bool, bool, bool, bool]:
        """Detect route feature flags based on configuration.

        Returns:
            Tuple of (has_chat_models, has_judges, has_embedding_models, has_semantic_cache)

        """
        has_chat_models = len(route_config.chat_models) > 0
        has_judges = self.has_judge_guardrail(route_config)
        has_embedding_models = (
            route_config.embedding_models is not None
            and len(route_config.embedding_models) > 0
        )
        has_semantic_cache = isinstance(route_config.caching, SemanticCaching)
        return has_chat_models, has_judges, has_embedding_models, has_semantic_cache

    @model_validator(mode='before')
    @classmethod
    def inject_route_name(cls, data: Any) -> Any:
        """Inject route name in GatewayRouteConfig from dict of gateway config"""
        if isinstance(data, dict):
            for key in data.get('routes', {}):
                if isinstance(data['routes'][key], dict):
                    data['routes'][key]['route_name'] = key
        return data

    @model_validator(mode='after')
    def validate_models_and_routes(self) -> Self:
        chat_ids = [m.model_id for m in self.chat_models]
        emb_ids = [m.model_id for m in (self.embedding_models or [])]

        if len(chat_ids) != len(set(chat_ids)):
            raise ValueError('All chat_models must have unique model_id.')
        if len(emb_ids) != len(set(emb_ids)):
            raise ValueError('All embedding_models must have unique model_id.')
        if set(chat_ids) & set(emb_ids):
            raise ValueError(
                'chat_models and embedding_models must have globally unique model_id.'
            )

        chat_defined = set(self.chat_models_by_id.keys())
        emb_defined = set(self.embedding_models_by_id.keys())

        # Route-level reference validation
        for route_name, route in self.routes.items():
            route_chat_ids = route.chat_models
            route_emb_ids = list(route.embedding_models or [])

            if len(route_chat_ids) != len(set(route_chat_ids)):
                raise ValueError(
                    f'Route {route_name}: chat_models must have unique ids.'
                )
            if len(route_emb_ids) != len(set(route_emb_ids)):
                raise ValueError(
                    f'Route {route_name}: embedding_models must have unique ids.'
                )
            if set(route_chat_ids) & set(route_emb_ids):
                raise ValueError(
                    f'Route {route_name}: chat_models and embedding_models must have globally unique model_id.'
                )

            missing_chat = sorted(
                [mid for mid in route_chat_ids if mid not in chat_defined]
            )
            if missing_chat:
                raise ValueError(
                    f'Route {route_name}: chat_models not declared in top-level chat_models: {", ".join(missing_chat)}'
                )

            missing_emb = sorted(
                [mid for mid in route_emb_ids if mid not in emb_defined]
            )
            if missing_emb:
                raise ValueError(
                    f'Route {route_name}: embedding_models not declared in top-level embedding_models: {", ".join(missing_emb)}'
                )

            # Fallback validation
            if route.fallback:
                for fb in route.fallback:
                    if fb.type == FallbackModelType.CHAT:
                        valid_ids = set(route_chat_ids)
                        label = 'chat'
                    elif fb.type == FallbackModelType.EMBEDDING:
                        valid_ids = set(route_emb_ids)
                        label = 'embedding'
                    else:
                        raise ValueError(
                            f'Route {route_name}: Unknown fallback type {fb.type.value}'
                        )

                    if fb.target not in valid_ids:
                        raise ValueError(
                            f'Route {route_name}: Target model {fb.target} in fallback must be present in the {label} models.'
                        )
                    if not set(fb.fallbacks).issubset(valid_ids):
                        raise ValueError(
                            f'Route {route_name}: All fallback models for target {fb.target} must be present in the {label} models.'
                        )

            # Semantic caching validation
            if isinstance(route.caching, SemanticCaching):
                if not route_emb_ids:
                    raise ValueError(
                        f'Route {route_name}: Semantic caching requires at least one embedding model to be referenced.'
                    )
                if route.caching.embedding_model_id not in set(route_emb_ids):
                    raise ValueError(
                        f'Route {route_name}: Embedding model {route.caching.embedding_model_id} is not referenced in route embedding_models'
                    )
                if route.caching.embedding_model_id not in emb_defined:
                    raise ValueError(
                        f'Route {route_name}: Embedding model {route.caching.embedding_model_id} is not defined in top-level embedding_models.'
                    )

        return self

    @model_validator(mode='after')
    def validate_cache_if_configured(self) -> Self:
        """Validate if cache is configured if enabled in routes"""
        if not self.cache:
            for route in self.routes.values():
                if route.caching and route.caching.enabled:
                    raise ValueError(
                        'Configure cache of the gateway if caching for a route is enabled'
                    )
        return self

    @model_validator(mode='after')
    def validate_guardrail_names_unique(self) -> Self:
        """Ensure global guardrail names are unique (case-insensitive, trimmed)"""
        if not self.guardrails:
            return self

        norm = lambda s: s.strip().casefold()
        normalized = [norm(g.name) for g in self.guardrails]
        counts = Counter(normalized)
        dups_norm = {n for n, c in counts.items() if c > 1}

        if dups_norm:
            # Show original names that collide after normalization
            dup_originals = sorted(
                {g.name.strip() for g in self.guardrails if norm(g.name) in dups_norm}
            )
            raise ValueError(
                f'Guardrail names must be unique. Duplicates found: {", ".join(dup_originals)}'
            )
        return self

    @model_validator(mode='after')
    def validate_route_guardrails(self) -> Self:
        """Post-resolution:
        - no duplicates within a single route (explicit, redundant check)
        - consistency with global guardrails (should be guaranteed by the 'before' validator; here we assert defensively)
        """
        if not self.routes:
            return self

        def norm(s: str) -> str:
            return s.strip().casefold()

        global_names_norm = {norm(g.name) for g in (self.guardrails or [])}

        for r_name, route in self.routes.items():
            names = route.guardrails or []
            counts = Counter(norm(n) for n in names)
            dups = [n for n, c in counts.items() if c > 1]
            if dups:
                dup_originals = sorted({n for n in names if norm(n) in set(dups)})
                raise ValueError(
                    f"Route '{r_name}': duplicate guardrails: {', '.join(dup_originals)}"
                )

            unknown = [n for n in names if norm(n) not in global_names_norm]
            if unknown:
                # This should not happen if the 'before' validator resolved names correctly, but keep a clear message.
                raise ValueError(
                    f"Route '{r_name}': guardrails not declared in top-level config: {', '.join(sorted(unknown))}"
                )

        return self

    @model_validator(mode='after')
    def validate_routing(self) -> Self:
        """Validate routing configurations and their references."""
        if not self.routing:
            return self

        # Routing names must be unique
        names = [r.name for r in self.routing]
        if len(names) != len(set(names)):
            raise ValueError('All routing configs must have unique names.')

        routing_by_name = self.routing_by_name

        for route_name, route in self.routes.items():
            if not route.routing:
                continue

            if route.routing not in routing_by_name:
                raise ValueError(
                    f"Route '{route_name}': routing '{route.routing}' not declared in top-level routing configs."
                )

            routing_config = routing_by_name[route.routing]
            route_model_ids = set(route.chat_models)

            if isinstance(routing_config, SemanticRoutingConfig):
                if routing_config.embedding_model_id not in set(
                    self.embedding_models_by_id
                ):
                    raise ValueError(
                        f"Route '{route_name}': semantic routing embedding_model_id '{routing_config.embedding_model_id}' "
                        f'not found in top-level embedding_models.'
                    )

            # default_model_id must be in route's chat_models
            if routing_config.default_model_id not in route_model_ids:
                raise ValueError(
                    f"Route '{route_name}': routing default_model_id '{routing_config.default_model_id}' "
                    f'not in route chat_models.'
                )

            # output_mapping model_ids must reference route chat_models
            for entry in routing_config.output_mapping:
                if entry.model_id not in route_model_ids:
                    raise ValueError(
                        f"Route '{route_name}': routing, "
                        f"model_id '{entry.model_id}' not in route chat_models."
                    )

            # budget routing requires budget_limiting to be configured on the route
            if (
                isinstance(routing_config, DeterministicRoutingConfig)
                and routing_config.rule == RoutingRuleType.BUDGET
                and route.budget_limiting is None
            ):
                raise ValueError(
                    f"Route '{route_name}': budget routing requires budget_limiting to be configured."
                )

        return self

    @model_validator(mode='after')
    def validate_route_extensions(self) -> Self:
        """Validate each route's ``extension`` against the registered plugins.

        ``extension`` is typed ``dict`` in the route model because its allowed
        keys are only known once plugins register. Here, at config-load time, we
        build a model whose fields are exactly the keys plugins claimed
        (``extra='forbid'``) so an ``extension`` key no plugin claims — a typo'd
        or stale plugin name — is rejected instead of being silently ignored.
        Each plugin's per-slice validator (registered via
        ``register_extension_slice_validator``) then validates its slice's
        contents. Validation runs once here rather than on every
        ``GatewayRouteConfig`` construction.
        """
        validators = get_extension_validators()
        if not validators:
            return self
        known_keys = get_known_extension_keys()
        # Gate unknown keys only when some plugin declared one. With only raw,
        # whole-``extension`` validators (no declared key) there is nothing to
        # gate against, so those keep validating the dict themselves.
        extension_model = (
            build_route_extension_model(known_keys) if known_keys else None
        )
        for route_name, route in self.routes.items():
            if not route.extension:
                continue
            if extension_model is not None:
                try:
                    extension_model.model_validate(route.extension)
                except ValidationError as exc:
                    unknown = sorted(str(e['loc'][0]) for e in exc.errors())
                    raise ValueError(
                        f"Route '{route_name}': unknown 'extension' key(s) "
                        f'{unknown}; valid keys: {sorted(known_keys)}'
                    ) from exc
            for validate in validators:
                validate(route.extension)
        return self
