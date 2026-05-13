import logging

from langchain_core.embeddings import Embeddings
from langchain_core.messages import BaseMessage, HumanMessage
import numpy as np

from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.models.routing import SemanticRoutingConfig
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.build_user_content import stringify_message_content

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)


def _last_human_text(messages: list[BaseMessage]) -> str | None:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            text = stringify_message_content(msg.content)
            if text:
                return text
    return None


def _normalize(v: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(v)
    if norm == 0:
        return v
    return v / norm


class SemanticRouter:
    def __init__(
        self,
        config: SemanticRoutingConfig,
        models_by_id: dict[str, Model],
        embeddings_model: Embeddings,
    ):
        self._config = config
        self._models_by_id = models_by_id
        self._embeddings_model = embeddings_model
        self._centroids: list[tuple[str, np.ndarray]] = []
        self._initialized = False

    async def initialize(self) -> None:
        for entry in self._config.output_mapping:
            utterances = entry.conditions
            if not isinstance(utterances, list) or not utterances:
                logger.warning(
                    'Semantic routing: skipping model %s — no utterances',
                    entry.model_id,
                )
                continue
            vectors = await self._embeddings_model.aembed_documents(utterances)
            centroid = _normalize(np.mean(vectors, axis=0))
            self._centroids.append((entry.model_id, centroid))
            logger.info(
                'Semantic routing: computed centroid for model %s from %d utterances',
                entry.model_id,
                len(utterances),
            )
        self._initialized = True

    async def select_model(self, messages: list[BaseMessage]) -> Model:
        if not self._initialized:
            logger.warning('SemanticRouter not initialized, using default model')
            return self._models_by_id[self._config.default_model_id]

        last_text = _last_human_text(messages)
        if not last_text:
            return self._models_by_id[self._config.default_model_id]

        query_vector = await self._embeddings_model.aembed_query(last_text)
        query = _normalize(np.array(query_vector))

        best_model_id = self._config.default_model_id
        best_similarity = -1.0

        for model_id, centroid in self._centroids:
            similarity = float(np.dot(query, centroid))
            if similarity > best_similarity:
                best_similarity = similarity
                best_model_id = model_id

        logger.debug(
            'Semantic routing: best match model=%s similarity=%.4f threshold=%.4f',
            best_model_id,
            best_similarity,
            self._config.similarity_threshold,
        )
        if best_similarity < self._config.similarity_threshold:
            return self._models_by_id[self._config.default_model_id]

        return self._models_by_id[best_model_id]
