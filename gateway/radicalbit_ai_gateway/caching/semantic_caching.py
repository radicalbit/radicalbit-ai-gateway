import asyncio
import logging

import numpy as np
from redis.asyncio import Redis
from redis.commands.search.field import TagField, VectorField
from redis.commands.search.index_definition import IndexDefinition, IndexType
from redis.commands.search.query import Query
from traceloop.sdk.decorators import task

from radicalbit_ai_gateway.caching.abstract_cache import AbstractCache
from radicalbit_ai_gateway.metrics.define_metrics import semantic_cache_similarity
from radicalbit_ai_gateway.utils.app_config import get_app_config

app_config = get_app_config()

logger = logging.getLogger(app_config.log_config.logger_name)


class SemanticCache(AbstractCache):
    def __init__(
        self,
        redis_client: Redis,
        similarity_threshold: float,
        dim: int,
        distance_metric: str,
    ):
        self.redis_client = redis_client
        self.similarity_threshold = similarity_threshold
        self.dim = dim
        self.distance_metric = distance_metric
        self.index_name = 'ai_gateway_idx'

        self.schema = [
            TagField('project_uuid'),
            TagField('route_name'),
            TagField('key_uuid'),
            VectorField(
                'embedding',
                'FLAT',
                {
                    'TYPE': 'FLOAT32',
                    'DIM': self.dim,
                    'DISTANCE_METRIC': self.distance_metric,
                },
            ),
        ]

        self._background_tasks: set[asyncio.Task] = set()

        async def create_index() -> None:
            try:
                await self.redis_client.ft(self.index_name).create_index(
                    self.schema,
                    definition=IndexDefinition(index_type=IndexType.HASH),
                )
                logger.info('Created Redis search index: %s', self.index_name)
            except Exception as error:
                # An existing index keeps the schema it was created with, so one
                # created before project scoping has no project_uuid field and
                # every project filter matches nothing. Drop it by hand
                # (FT.DROPINDEX ai_gateway_idx) to have this one take effect.
                logger.warning(
                    'Redis search index %s was not created, it may already exist '
                    'with an older schema: %s',
                    self.index_name,
                    error,
                )

        try:
            index_task = asyncio.create_task(create_index())
        except RuntimeError:
            logger.warning(
                'No running event loop: Redis search index %s was not created',
                self.index_name,
            )
        else:
            # Keep a strong reference until the task completes, otherwise it can
            # be garbage collected mid-flight.
            self._background_tasks.add(index_task)
            index_task.add_done_callback(self._background_tasks.discard)

    def _build_filter_conditions(self, **kwargs) -> str:
        """Build the tag filter that scopes a lookup to one project's route.

        The values come from ``kwargs``, never from parsing ``cache_key``: a
        positional parse silently degrades to a permanent miss as soon as the
        key format changes.
        """
        project_uuid = kwargs.get('project_uuid')
        route_name = kwargs.get('route_name')
        key_uuid = kwargs.get('key_uuid')
        if not project_uuid:
            raise ValueError('project_uuid param must be passed')
        if not route_name:
            raise ValueError('route_name param must be passed')
        if not key_uuid:
            raise ValueError('key_uuid param must be passed')
        # Tag values go in verbatim: valkey-search matches them literally, so
        # escaping the ``-`` in a route name or a UUID makes the backslash part
        # of the value and the filter matches nothing.
        return (
            f'@project_uuid:{{{project_uuid}}} '
            f'@route_name:{{{route_name}}} '
            f'@key_uuid:{{{key_uuid}}}'
        )

    @task(name='get_semantic_cache')
    async def get(self, cache_key: str, **kwargs) -> str | None:
        embeddings = kwargs.get('embeddings')
        if embeddings is None:
            raise ValueError('Embeddings param must be passed')
        route_name = kwargs.get('route_name')
        k = kwargs.get('k', 1)
        query_vector = embeddings.astype(np.float32).tobytes()
        filter_conditions = self._build_filter_conditions(**kwargs)
        vector_query = (
            f'({filter_conditions})=>[KNN {k} @embedding $query_vector AS score]'
        )
        query = (
            Query(vector_query)
            .paging(0, k)
            .return_fields('response', 'score')
            .dialect(2)
        )
        try:
            results = await self.redis_client.ft(self.index_name).search(
                query, query_params={'query_vector': query_vector}
            )
        except Exception:
            logger.error(
                'Something went wrong while executing searching with query:  %s',
                query.__dict__,
            )
            return None
        if results.docs:
            best_match = results.docs[0]
            similarity = 1 - float(best_match.score)
            # Return the cached response if within threshold
            if similarity >= self.similarity_threshold:
                logger.info(
                    'Semantic cache hit with similarity: %s',
                    similarity,
                )
                self._record_metric(
                    route_name=route_name, similarity_score=similarity, cache_hit=True
                )
                return best_match.response
            self._record_metric(
                route_name=route_name, similarity_score=similarity, cache_hit=False
            )
        return None

    @task(name='set_semantic_cache')
    async def set(
        self,
        cache_key: str,
        response: str,
        ttl: int | None,
        **kwargs,
    ):
        embeddings = kwargs.get('embeddings')
        if embeddings is None:
            raise ValueError('Embeddings param must be passed')
        project_uuid = kwargs.get('project_uuid')
        route_name = kwargs.get('route_name')
        if not project_uuid:
            raise ValueError('project_uuid param must be passed')
        if not route_name:
            raise ValueError('route_name param must be passed')
        mapping = {
            'response': response,
            'project_uuid': project_uuid,
            'route_name': route_name,
            'embedding': embeddings.astype(np.float32).tobytes(),
        }
        key_uuid = kwargs.get('key_uuid')
        if key_uuid is not None:
            mapping['key_uuid'] = key_uuid

        await self.redis_client.hset(cache_key, mapping=mapping)
        if ttl:
            await self.redis_client.expire(cache_key, ttl)

    def _record_metric(self, route_name: str, similarity_score: float, cache_hit: bool):
        semantic_cache_similarity.record(
            similarity_score,
            attributes={'route_name': route_name, 'cache_hit': cache_hit},
        )
