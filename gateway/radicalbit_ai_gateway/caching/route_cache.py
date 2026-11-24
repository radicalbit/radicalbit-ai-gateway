"""The response cache a request is answered from: looked up before the model
is called, stored after.

A route's ``RouteCache`` holds its backend (Redis, the semantic index, or
memory) and how long an entry lives; each request gets a ``RequestCache``,
bound to its caller and to the limits the semantic cache's embedding call is
charged to (ADR 0006). ``lookup`` takes an entry adapter, which each endpoint defines in its
``cache`` module: what identifies the request, and how its reply is stored.
It returns a ``Cached``: a ``CacheHit`` with the reply, or a ``CacheMiss``
with where to ``store`` the reply made instead. The keys, the semantic embedding, the events, the metrics and the
trace spans stay behind it.

Guardrails stay outside: an endpoint screens a hit with the output guardrails
as it screens a model's reply, and stores only screened text.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import logging
from typing import (
    TYPE_CHECKING,
    Any,
    Generic,
    Literal,
    ParamSpec,
    Protocol,
    TypeVar,
    TypeVarTuple,
    Union,
)

import numpy as np
from openai.types.create_embedding_response import CreateEmbeddingResponse

from radicalbit_ai_gateway.caching.abstract_cache import AbstractCache
from radicalbit_ai_gateway.caching.gateway_cache import GatewayCache
from radicalbit_ai_gateway.events.events_processor import emit_event
from radicalbit_ai_gateway.limiting.limits import RequestLimits
from radicalbit_ai_gateway.metrics.define_metrics import (
    cache_hit_counter,
    cache_input_tokens,
    cache_output_tokens,
)
from radicalbit_ai_gateway.models.caching import CacheType
from radicalbit_ai_gateway.models.event_payload import CacheEventPayload
from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.models.request_identity import RequestIdentity
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.telemetry.tracing import task
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.trace_attributes import (
    OperationCategory,
    set_operation_category,
)

if TYPE_CHECKING:
    from radicalbit_ai_gateway.invocation.embedding_model_invoker import (
        EmbeddingModelInvoker,
    )

logger = logging.getLogger(get_app_config().log_config.logger_name)

CACHE_HIT_HEADER = 'X-RB-AIGATEWAY-CACHE-HIT'

V = TypeVar('V')
S = TypeVar('S')
S_contra = TypeVar('S_contra', contravariant=True)
T = TypeVar('T')
R = TypeVar('R')
P = ParamSpec('P')
Ts = TypeVarTuple('Ts')


# ---------------------------------------------------------------------------
# What a lookup returns
# ---------------------------------------------------------------------------


class CacheHit(Generic[V]):
    """A lookup that hit: ``value`` is the reply it serves. A hit stores
    nothing.
    """

    def __init__(self, value: V) -> None:
        self._value = value

    @property
    def value(self) -> V:
        return self._value

    @property
    def hit(self) -> Literal[True]:
        return True

    def headers(self) -> dict[str, str]:
        """Return the cache header of the response."""
        return {CACHE_HIT_HEADER: 'true'}

    async def store(self, value: object) -> None:
        """Do nothing: the reply of a hit is the cache's own."""


class CacheMiss(Generic[S]):
    """A lookup that missed: ``store`` stores the reply made instead.

    ``CacheMiss()`` is the answer of a request the cache does not serve:
    ``store`` does nothing.
    """

    def __init__(self, store: Callable[[S], Awaitable[None]] | None = None) -> None:
        self._store = store

    @property
    def value(self) -> None:
        return None

    @property
    def hit(self) -> Literal[False]:
        return False

    def headers(self) -> dict[str, str]:
        """Return the cache header of the response: none on a miss."""
        return {}

    async def store(self, value: S) -> None:
        """Store ``value`` as the reply of the miss."""
        if self._store is not None:
            await self._store(value)


#: A lookup's answer: a hit serving a ``V``, or a miss storing an ``S``.
#: ``if cached.hit:`` narrows it to the hit, whose ``value`` is a ``V``.
Cached = Union[CacheHit[V], CacheMiss[S]]


# ---------------------------------------------------------------------------
# Entries: what identifies a request, and how its reply is stored
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Hit:
    """What a hit served: its model and usage, priced for the hit's events.

    ``free_input_tokens`` are input tokens the hit reports at no cost.
    """

    model_id: str
    usage: Any = None
    free_input_tokens: int = 0


class Entry(Protocol[V, S_contra]):
    """A request as the cache keys it: a hit serves a ``V``, a miss stores
    an ``S``.
    """

    @property
    def lookup_spans(self) -> tuple[str, ...]:
        """The spans the lookup runs in, outermost first."""

    @property
    def get_spans(self) -> tuple[str, ...]:
        """The spans the backend read runs in, outermost first."""

    @property
    def exact_only(self) -> bool:
        """True when only an exact or in-memory cache serves the endpoint."""

    @property
    def hit_log(self) -> str | None:
        """The debug line of a hit, given the key."""

    def signature(self) -> str | None:
        """Return what identifies the request; None when it is not cached."""

    def text(self) -> str:
        """Return the text the semantic cache embeds."""

    def parse(self, raw: str) -> V | None:
        """Return the stored reply; None when the entry is not one."""

    def dump(self, value: S_contra) -> str: ...

    def hit(self, value: V) -> Hit: ...

    def refresh(self, value: V) -> V:
        """Return a hit's reply as a reply made now."""

    def store_spans(self, value: S_contra) -> tuple[str, ...]: ...


class ExactEntry:
    """An entry only an exact or in-memory cache serves, with no spans of
    its own.
    """

    lookup_spans = ()
    get_spans = ()
    exact_only = True

    def text(self) -> str:
        return ''

    def refresh(self, value: T) -> T:
        return value

    def store_spans(self, value: object) -> tuple[str, ...]:
        return ()


# ---------------------------------------------------------------------------
# A route's and a request's cache
# ---------------------------------------------------------------------------


def cache_key(
    project_uuid: str, route_name: str, key_uuid: str, entry: Entry[Any, Any]
) -> str:
    """Return the storage key of an entry; it must have a signature."""
    signature = entry.signature()
    if signature is None:
        raise ValueError('An entry with no signature has no cache key')
    return AbstractCache.generate_cache_key(
        project_uuid, route_name, signature, key_uuid
    )


async def _descend(
    spans: tuple[str, ...], fn: Callable[[*Ts], Awaitable[R]], *args: *Ts
) -> R:
    return await _within(spans, fn, *args)


SPANS = (
    'lookup_cache',
    'get_cached_response',
    'set_cached_response',
    'set_cached_stream_response',
    'generate_semantic_cache_embedding',
    'lookup_responses_cache',
    'lookup_messages_cache',
)
_IN_SPAN = {name: task(name=name)(_descend) for name in SPANS}


async def _within(
    spans: tuple[str, ...], fn: Callable[[*Ts], Awaitable[R]], *args: *Ts
) -> R:
    """Run ``fn(*args)`` in the trace spans named, outermost first."""
    if not spans:
        return await fn(*args)
    return await _IN_SPAN[spans[0]](spans[1:], fn, *args)


@dataclass(frozen=True)
class EnabledCache:
    """The cache of a route that caches: its backend, how long an entry
    lives, and what prices a hit's events.
    """

    backend: GatewayCache
    cost_service: CostService
    ttl: int | None = None
    #: What embeds a request's text for the semantic cache: the route's
    #: embedding invoker and its first embedding model.
    embedder: EmbeddingModelInvoker | None = None
    embedding_model: Model | None = None


@dataclass(frozen=True)
class RouteCache:
    """A route's cache, built once when its configuration is loaded.

    ``RouteCache()`` is the cache of a route that caches nothing.
    """

    enabled: EnabledCache | None = None

    @property
    def ttl(self) -> int | None:
        return self.enabled.ttl if self.enabled else None

    @classmethod
    def from_config(
        cls,
        config: GatewayRouteConfig,
        backend: GatewayCache | None,
        cost_service: CostService,
        embedder: EmbeddingModelInvoker | None = None,
        embedding_models: list[Model] | None = None,
    ) -> RouteCache:
        if backend is None:
            return cls()
        return cls(
            EnabledCache(
                backend=backend,
                cost_service=cost_service,
                ttl=config.caching.ttl if config.caching else None,
                embedder=embedder,
                embedding_model=embedding_models[0] if embedding_models else None,
            )
        )

    def for_request(
        self, identity: RequestIdentity, limits: RequestLimits
    ) -> RequestCache:
        return RequestCache(self, identity, limits)


class RequestCache:
    """The cache one request is looked up in and stored to."""

    def __init__(
        self, route: RouteCache, identity: RequestIdentity, limits: RequestLimits
    ) -> None:
        self._route = route
        self._identity = identity
        self._limits = limits

    async def lookup(self, entry: Entry[V, S]) -> Cached[V, S]:
        """Look the request up. A hit records its events and metrics."""
        cache = self._route.enabled
        if cache is None:
            return CacheMiss()
        if entry.exact_only and cache.backend.cache_type not in (
            CacheType.EXACT,
            CacheType.IN_MEMORY,
        ):
            return CacheMiss()
        set_operation_category(OperationCategory.CACHE)

        # A closure, not the generic method: its reply type is the entry's.
        async def lookup(cache: EnabledCache, entry: Entry[V, S]) -> Cached[V, S]:
            return await self._lookup(cache, entry)

        return await _within(entry.lookup_spans, lookup, cache, entry)

    async def _lookup(self, cache: EnabledCache, entry: Entry[V, S]) -> Cached[V, S]:
        signature = entry.signature()
        if signature is None:
            return CacheMiss()
        identity = self._identity
        key = AbstractCache.generate_cache_key(
            identity.project_uuid, identity.route_name, signature, identity.api_key_uuid
        )
        tags: dict[str, Any] = {}
        if cache.backend.cache_type == CacheType.SEMANTIC:
            text = entry.text()
            embeddings = await self._embed(cache, text) if text else None
            if embeddings is None:
                # Without embeddings the semantic cache can neither read nor
                # write.
                return CacheMiss()
            tags = {
                'embeddings': embeddings,
                'project_uuid': identity.project_uuid,
                'route_name': identity.route_name,
                'key_uuid': identity.api_key_uuid,
            }
            value = await _within(
                entry.get_spans,
                self._get,
                cache,
                entry,
                key,
                {**tags, 'user_content': text, 'k': 1},
            )
        else:
            value = await _within(entry.get_spans, self._get, cache, entry, key, {})
        if value is not None:
            return CacheHit(value)

        async def store(reply: S) -> None:
            set_operation_category(OperationCategory.CACHE)
            await _within(
                entry.store_spans(reply), self._set, cache, entry, key, tags, reply
            )

        return CacheMiss(store)

    async def _get(
        self, cache: EnabledCache, entry: Entry[V, S], key: str, kwargs: dict[str, Any]
    ) -> V | None:
        try:
            raw = await cache.backend.get(key, **kwargs)
        except Exception as e:
            # A cache that is down costs the request its cache, not its reply.
            logger.error('Cache lookup failed: %s, continuing without cache', e)
            return None
        if not raw:
            return None
        if entry.hit_log:
            logger.debug(entry.hit_log, key)
        value = entry.parse(raw)
        if value is None:
            return None
        self._record_hit(cache, entry.hit(value))
        return entry.refresh(value)

    async def _set(
        self,
        cache: EnabledCache,
        entry: Entry[V, S],
        key: str,
        tags: dict[str, Any],
        reply: S,
    ) -> None:
        try:
            await cache.backend.set(key, entry.dump(reply), cache.ttl, **tags)
        except Exception as e:
            logger.error('Cache store failed: %s, reply not cached', e)

    async def _embed(self, cache: EnabledCache, text: str) -> np.ndarray | None:
        if cache.embedder is None or cache.embedding_model is None:
            return None
        return await _within(
            ('generate_semantic_cache_embedding',),
            self._call_embedder,
            cache.embedder,
            text,
            cache.embedding_model,
        )

    async def _call_embedder(
        self, embedder: EmbeddingModelInvoker, text: str, model: Model
    ) -> np.ndarray | None:
        try:
            response, answered = await embedder.embed_answered(
                identity=self._identity,
                input_texts=[text],
                model_id=model.model_id,
                is_semantic_search=True,
            )
        except Exception as e:
            logger.error(
                'Error generating embedding for cache: %s, continuing without cache', e
            )
            return None
        await self._charge(answered, response)
        if not response.data or not response.data[0].embedding:
            logger.warning(
                'Failed to generate embedding for semantic caching, '
                'continuing without cache'
            )
            return None
        return np.array(response.data[0].embedding, dtype=np.float32)

    async def _charge(self, model: Model, response: CreateEmbeddingResponse) -> None:
        """Charge the embedding call to the request, as semantic routing's is
        (ADR 0006): its input tokens at the price of ``model``, the model that
        answered (a fallback, when the first failed), as its events price
        them. Its events are the invoker's, flagged semantic.

        The cache never fails a request: a failure here is logged, not raised.
        """
        tokens = response.usage.prompt_tokens if response.usage else 0
        if tokens <= 0:
            return
        try:
            await self._limits.charge_call(model, tokens)
        except Exception:
            logger.exception(
                'Semantic cache embedding on model %s was not charged', model.model_id
            )

    def _record_hit(self, cache: EnabledCache, hit: Hit) -> None:
        identity = self._identity
        cache_type = str(cache.backend.cache_type.value)
        attributes = {'route_name': identity.route_name, 'model_name': hit.model_id}

        def emit(
            event_type: Literal[
                EventType.CACHE_HIT,
                EventType.CACHE_INPUT_TOKENS,
                EventType.CACHE_OUTPUT_TOKENS,
            ],
            value: float,
            cost,
        ) -> None:
            emit_event(
                CacheEventPayload(
                    **identity.event_fields(),
                    value=value,
                    event_type=event_type,
                    cost=cost,
                    cache_type=cache_type,
                    model_id=hit.model_id,
                )
            )

        emit(EventType.CACHE_HIT, 1.0, 0.0)
        cache_hit_counter.add(1, {'route_name': identity.route_name})
        prompt_tokens = getattr(hit.usage, 'prompt_tokens', None)
        if prompt_tokens:
            emit(
                EventType.CACHE_INPUT_TOKENS,
                prompt_tokens,
                self._price(cache, prompt_tokens, 'input', hit.model_id),
            )
            cache_input_tokens.add(prompt_tokens, attributes)
        completion_tokens = getattr(hit.usage, 'completion_tokens', None)
        if completion_tokens:
            emit(
                EventType.CACHE_OUTPUT_TOKENS,
                completion_tokens,
                self._price(cache, completion_tokens, 'output', hit.model_id),
            )
            cache_output_tokens.add(completion_tokens, attributes)
        if hit.free_input_tokens > 0:
            emit(EventType.CACHE_INPUT_TOKENS, hit.free_input_tokens, 0.0)
            cache_input_tokens.add(hit.free_input_tokens, attributes)

    def _price(self, cache: EnabledCache, tokens: int, where: str, model_id: str):
        return cache.cost_service.compute_cost(
            token_processed=tokens, where=where, model_id=model_id
        )
