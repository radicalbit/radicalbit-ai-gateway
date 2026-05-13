from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CacheType(Enum):
    SEMANTIC = 'semantic'
    EXACT = 'exact'
    IN_MEMORY = 'in-memory'
    UNKNOWN = 'unknown'


class CacheConfig(BaseModel):
    redis_host: str = Field(
        ...,
        description='Redis (or compatible) host',
        examples=['localhost'],
    )
    redis_port: int = Field(
        ...,
        description='Redis (or compatible) port',
        examples=['6379'],
    )


class Caching(BaseModel):
    enabled: bool = Field(
        default=True,
        description='Enable cache for route',
    )
    type: Literal['exact'] = Field(
        ...,
        description='Cache type',
        examples=['exact', 'semantic'],
    )
    ttl: int | None = Field(
        None,
        description='Cache expiration time in seconds (None for infinite)',
        examples=['30', '3600'],
    )

    model_config = ConfigDict(extra='forbid')


class SemanticCaching(BaseModel):
    enabled: bool = Field(
        default=True,
        description='Enable cache for route',
    )
    type: Literal['semantic'] = Field(
        ...,
        description='Cache type',
        examples=['exact', 'semantic'],
    )
    ttl: int | None = Field(
        None,
        description='Cache expiration time in seconds (None for infinite)',
        examples=['30', '3600'],
    )
    embedding_model_id: str = Field(
        ...,
        description='Model ID of the embedding model to use for semantic cache',
        examples=['text-embedding-3-small'],
    )
    similarity_threshold: float = Field(
        0.8,
        description='Similarity threshold for semantic cache (between 0 and 1)',
        examples=['0.8'],
    )
    distance_metric: Literal['cosine', 'euclidean', 'inner_product'] = Field(
        'cosine',
        description='Distance metric for semantic cache',
        examples=['cosine', 'euclidean', 'inner_product'],
    )
    dim: int = Field(
        1536,
        description='Dimensionality of the embeddings produced by the embedding model',
        examples=['1536'],
    )
