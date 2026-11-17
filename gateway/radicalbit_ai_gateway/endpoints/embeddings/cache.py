"""How an embeddings request is cached."""

from __future__ import annotations

from dataclasses import dataclass
import json

from openai.types.create_embedding_response import CreateEmbeddingResponse

from radicalbit_ai_gateway.caching.route_cache import ExactEntry, Hit


@dataclass(frozen=True)
class EmbeddingEntry(ExactEntry):
    """An embeddings request, keyed on its (redacted) input texts."""

    texts: list[str]

    hit_log = 'Embedding cache hit. Key: %s'

    def signature(self) -> str:
        return (
            f'inputs:{json.dumps(self.texts, ensure_ascii=False)};'
            f'extra_args:{json.dumps({})}'
        )

    def parse(self, raw: str) -> CreateEmbeddingResponse:
        return CreateEmbeddingResponse.model_validate(json.loads(raw))

    def dump(self, value: CreateEmbeddingResponse) -> str:
        return value.model_dump_json(indent=None)

    def hit(self, value: CreateEmbeddingResponse) -> Hit:
        return Hit(value.model, value.usage)
