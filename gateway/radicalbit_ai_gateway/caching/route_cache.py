"""The response cache a request is answered from: looked up before the model
is called, stored after.

A route's ``RouteCache`` holds its backend (Redis, the semantic index, or
memory) and how long an entry lives; each request gets a ``RequestCache``,
bound to its caller and to the limits the semantic cache's embedding call is
charged to (ADR 0006). ``lookup`` takes an entry adapter, which each endpoint defines in its
``cache`` module: what identifies the request, and how its reply is stored.
It returns a ``Cached``: the reply on a hit, and where to ``store`` the reply
on a miss. The keys, the semantic embedding, the events, the metrics and the
trace spans stay behind it.

Guardrails stay outside: an endpoint screens a hit with the output guardrails
as it screens a model's reply, and stores only screened text.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import logging
from typing import Any, Generic, Protocol, TypeVar

import numpy as np
from openai.types.create_embedding_response import CreateEmbeddingResponse
from traceloop.sdk.decorators import task

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
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.trace_attributes import (
    OperationCategory,
    set_operation_category,
)

logger = logging.getLogger(get_app_config().log_config.logger_name)

CACHE_HIT_HEADER = 'X-RB-AIGATEWAY-CACHE-HIT'

V = TypeVar('V')


# ---------------------------------------------------------------------------
# What a lookup returns
# ---------------------------------------------------------------------------


class Cached(Generic[V]):
    """A lookup's answer: the reply on a hit, and where a reply is stored.

    ``Cached()`` is the answer of a request the cache does not serve: no hit,
    and ``store`` does nothing.
    """

    def __init__(
        self,
        value: V | None = None,
        store: Callable[[V], Awaitable[None]] | None = None,
    ) -> None:
        self.value = value
        self._store = store

    @property
    def hit(self) -> bool:
        return self.value is not None

    def headers(self) -> dict[str, str]:
        """Return the cache header of the response."""
        return {CACHE_HIT_HEADER: 'true'} if self.hit else {}

    async def store(self, value: V) -> None:
        """Store ``value`` as the reply of a miss. Does nothing on a hit, or
        for a request the cache does not serve.
        """
        if self._store is not None and not self.hit:
            await self._store(value)


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


class Entry(Protocol[V]):
    #: The spans the lookup and the backend read run in, outermost first.
    lookup_spans: tuple[str, ...]
    get_spans: tuple[str, ...]
    #: True when only an exact or in-memory cache serves the endpoint.
    exact_only: bool
    #: The debug line of a hit, given the key.
    hit_log: str | None

    def signature(self) -> str | None:
        """Return what identifies the request; None when it is not cached."""

    def text(self) -> str:
        """Return the text the semantic cache embeds."""

    def parse(self, raw: str) -> V | None:
        """Return the stored reply; None when the entry is not one."""

    def dump(self, value: V) -> str: ...

    def hit(self, value: V) -> Hit: ...

    def refresh(self, value: V) -> V:
        """Return a hit's reply as a reply made now."""

    def store_spans(self, value: V) -> tuple[str, ...]: ...


class ExactEntry:
    """An entry only an exact or in-memory cache serves, with no spans of
    its own.
    """

    lookup_spans = ()
    get_spans = ()
    exact_only = True

    def text(self) -> str:
        return ''

    def refresh(self, value):
        return value

    def store_spans(self, value) -> tuple[str, ...]:
        return ()


# ---------------------------------------------------------------------------
# A route's and a request's cache
# ---------------------------------------------------------------------------


def cache_key(project_uuid: str, route_name: str, key_uuid: str, entry: Entry) -> str:
    """Return the storage key of an entry; it must have a signature."""
    return AbstractCache.generate_cache_key(
        project_uuid, route_name, entry.signature(), key_uuid
    )


async def _call(fn, *args):
    return await fn(*args)


SPANS = (
    'lookup_cache',
    'get_cached_response',
    'set_cached_response',
    'set_cached_stream_response',
    'generate_semantic_cache_embedding',
    'lookup_responses_cache',
)
_IN_SPAN = {name: task(name=name)(_call) for name in SPANS}


async def _within(spans: tuple[str, ...], fn, *args):
    """Run ``fn(*args)`` in the trace spans named, outermost first."""
    if not spans:
        return await fn(*args)
    return await _IN_SPAN[spans[0]](_within, spans[1:], fn, *args)


@dataclass(frozen=True)
class RouteCache:
    """A route's cache, built once when its configuration is loaded.

    ``RouteCache()`` is the cache of a route that caches nothing.
    """

    backend: GatewayCache | None = None
    ttl: int | None = None
    cost_service: CostService | None = None
    #: What embeds a request's text for the semantic cache: the route's
    #: embedding invoker and its first embedding model.
    embedder: Any = None
    embedding_model: Model | None = None

    @classmethod
    def from_config(
        cls,
        config: GatewayRouteConfig,
        backend: GatewayCache | None,
        cost_service: CostService,
        embedder: Any = None,
        embedding_models: list[Model] | None = None,
    ) -> RouteCache:
        if backend is None:
            return cls()
        return cls(
            backend=backend,
            ttl=config.caching.ttl if config.caching else None,
            cost_service=cost_service,
            embedder=embedder,
            embedding_model=(embedding_models or [None])[0],
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

    @property
    def _cache_type(self) -> CacheType:
        return self._route.backend.cache_type

    async def lookup(self, entry: Entry[V]) -> Cached[V]:
        """Look the request up. A hit records its events and metrics."""
        if self._route.backend is None:
            return Cached()
        if entry.exact_only and self._cache_type not in (
            CacheType.EXACT,
            CacheType.IN_MEMORY,
        ):
            return Cached()
        set_operation_category(OperationCategory.CACHE)
        return await _within(entry.lookup_spans, self._lookup, entry)

    async def _lookup(self, entry: Entry[V]) -> Cached[V]:
        signature = entry.signature()
        if signature is None:
            return Cached()
        identity = self._identity
        key = AbstractCache.generate_cache_key(
            identity.project_uuid, identity.route_name, signature, identity.api_key_uuid
        )
        tags: dict[str, Any] = {}
        if self._cache_type == CacheType.SEMANTIC:
            text = entry.text()
            embeddings = await self._embed(text) if text else None
            if embeddings is None:
                # Without embeddings the semantic cache can neither read nor
                # write.
                return Cached()
            tags = {
                'embeddings': embeddings,
                'project_uuid': identity.project_uuid,
                'route_name': identity.route_name,
                'key_uuid': identity.api_key_uuid,
            }
            value = await _within(
                entry.get_spans,
                self._get,
                entry,
                key,
                {**tags, 'user_content': text, 'k': 1},
            )
        else:
            value = await _within(entry.get_spans, self._get, entry, key, {})

        async def store(reply: V) -> None:
            set_operation_category(OperationCategory.CACHE)
            await _within(entry.store_spans(reply), self._set, entry, key, tags, reply)

        return Cached(value, store)

    async def _get(self, entry: Entry[V], key: str, kwargs: dict) -> V | None:
        try:
            raw = await self._route.backend.get(key, **kwargs)
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
        self._record_hit(entry.hit(value))
        return entry.refresh(value)

    async def _set(self, entry: Entry[V], key: str, tags: dict, reply: V) -> None:
        try:
            await self._route.backend.set(
                key, entry.dump(reply), self._route.ttl, **tags
            )
        except Exception as e:
            logger.error('Cache store failed: %s, reply not cached', e)

    async def _embed(self, text: str) -> np.ndarray | None:
        route = self._route
        if route.embedder is None or route.embedding_model is None:
            return None
        return await _within(
            ('generate_semantic_cache_embedding',), self._call_embedder, text
        )

    async def _call_embedder(self, text: str) -> np.ndarray | None:
        model = self._route.embedding_model
        try:
            response, answered = await self._route.embedder.embed_answered(
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

    def _record_hit(self, hit: Hit) -> None:
        identity = self._identity
        cache_type = str(self._cache_type.value)
        attributes = {'route_name': identity.route_name, 'model_name': hit.model_id}

        def emit(event_type: EventType, value: float, cost) -> None:
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
                self._price(prompt_tokens, 'input', hit.model_id),
            )
            cache_input_tokens.add(prompt_tokens, attributes)
        completion_tokens = getattr(hit.usage, 'completion_tokens', None)
        if completion_tokens:
            emit(
                EventType.CACHE_OUTPUT_TOKENS,
                completion_tokens,
                self._price(completion_tokens, 'output', hit.model_id),
            )
            cache_output_tokens.add(completion_tokens, attributes)
        if hit.free_input_tokens > 0:
            emit(EventType.CACHE_INPUT_TOKENS, hit.free_input_tokens, 0.0)
            cache_input_tokens.add(hit.free_input_tokens, attributes)

    def _price(self, tokens: int, where: str, model_id: str):
        return self._route.cost_service.compute_cost(
            token_processed=tokens, where=where, model_id=model_id
        )
