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

        async def create_index():
            await self.redis_client.ft(self.index_name).create_index(
                self.schema,
                definition=IndexDefinition(index_type=IndexType.HASH),
            )

        try:
            background_tasks = set()
            index_task = asyncio.create_task(create_index())
            background_tasks.add(task)
            index_task.add_done_callback(background_tasks.discard)
            logger.info('Created new Redis search index: ai_gateway_idx')
        except Exception:
            logger.info("Redis index 'ai_gateway_idx' already exists or error occurred")

    @task(name='get_semantic_cache')
    async def get(self, cache_key: str, **kwargs) -> str | None:
        route_name = cache_key.split(':')[3]
        embeddings = kwargs.get('embeddings')
        if embeddings is None:
            raise ValueError('Embeddings param must be passed')
        key_uuid = kwargs.get('key_uuid')
        k = kwargs.get('k', 1)
        query_vector = embeddings.astype(np.float32).tobytes()
        filter_conditions = f'@route_name:{{{route_name}}} @key_uuid:{{{key_uuid}}}'
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
        route_name = cache_key.split(':')[3]
        embeddings = kwargs.get('embeddings')
        if embeddings is None:
            raise ValueError('Embeddings param must be passed')
        mapping = {
            'response': response,
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
