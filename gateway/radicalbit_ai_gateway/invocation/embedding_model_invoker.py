import logging
import time

from langchain.embeddings.base import init_embeddings
from langchain_core.embeddings import Embeddings
from openai.types.create_embedding_response import CreateEmbeddingResponse, Usage
from openai.types.embedding import Embedding
from traceloop.sdk.decorators import task

from radicalbit_ai_gateway.invocation.model_invoker import ModelInvoker
from radicalbit_ai_gateway.models.fallback import Fallback
from radicalbit_ai_gateway.models.model import MockGatewayEmbeddings, Model
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.build_user_content import build_user_content_from_texts
from radicalbit_ai_gateway.utils.exceptions import (
    ModelInvokerBadRequest,
    ModelInvokerInternalError,
)
from radicalbit_ai_gateway.utils.parse_provider_and_model import (
    parse_provider_and_model,
)
from radicalbit_ai_gateway.utils.token_encoding import count_tokens

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)


class EmbeddingModelInvoker(ModelInvoker):
    def __init__(
        self,
        models: list[Model],
        cost_service: CostService,
        fallbacks: list[Fallback] | None,
        httpx_client=None,
    ):
        super().__init__(
            models=models,
            cost_service=cost_service,
            fallbacks=fallbacks,
            httpx_client=httpx_client,
        )
        self._initialize_models(self._build_model)

    def _build_model(self, model: Model) -> Embeddings:
        """Build an embedding model from configuration.

        Returns:
            Embeddings: An embedding model instance.

        """
        provider, model_name = parse_provider_and_model(model.model)
        params = model.params or {}
        credentials = (
            model.credentials.model_dump(exclude_none=True) if model.credentials else {}
        )

        # Handle mock provider (gateway-specific)
        if provider == 'mock':
            latency_ms: int = int(params.get('latency_ms', 0))
            vector_size: int = int(params.get('vector_size', 5))
            return MockGatewayEmbeddings(latency_ms=latency_ms, vector_size=vector_size)

        # Map gateway provider names to LangChain provider names
        # LangChain uses underscore (google_genai) while gateway uses hyphen (google-genai)
        langchain_provider = provider.replace('-', '_')

        # init_embeddings handles provider recognition and model initialization
        # LangChain accepts api_key directly as an alias for provider-specific keys
        return init_embeddings(
            model=model_name,
            provider=langchain_provider,
            http_async_client=self.httpx_client,
            **{**params, **credentials},
        )

    @task(name='llm_embed')
    async def embed(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        route_name: str,
        input_texts: list[str],
        model_id: str,
        is_semantic_search: bool = False,
        project_uuid: str = '',
        project_name: str = '',
        **kwargs,
    ) -> CreateEmbeddingResponse:
        if model_id not in self.model_map:
            raise ModelInvokerBadRequest(f'Embed model {model_id} not defined')

        model, embedding_model, fallbacks = self.model_map[model_id]

        logger.debug(
            'Invoking embedding model %s with input texts: %s',
            model_id,
            input_texts,
        )

        _, result_model_name = parse_provider_and_model(model.model)

        start_time = time.monotonic()
        vectors = None
        model_invoked: Model = Model(model_id='unknown', model='unknown')
        fallback_triggered = False
        try:
            vectors = await embedding_model.aembed_documents(input_texts)
            model_invoked = model
        except Exception as primary_embedding_model_exception:
            logger.warning(
                'Primary embedding model %s failed: %s. Trying fallbacks...',
                model_id,
                str(primary_embedding_model_exception),
            )

            for fallback_model, fallback_embeddings in fallbacks or []:
                _, result_model_name = parse_provider_and_model(fallback_model.model)
                try:
                    vectors = await fallback_embeddings.aembed_documents(input_texts)
                    fallback_triggered = True
                    model_invoked = fallback_model
                    break
                except Exception as fallback_embedding_model_exception:
                    logger.warning(
                        'Fallback embedding model %s failed: %s',
                        result_model_name,
                        str(fallback_embedding_model_exception),
                    )
            if vectors is None:
                logger.error(
                    'All embedding models failed for route %s, model %s',
                    route_name,
                    model_id,
                    exc_info=primary_embedding_model_exception,
                )
                raise ModelInvokerInternalError(
                    f'All embedding models failed for model {route_name}: {str(primary_embedding_model_exception)}'
                ) from primary_embedding_model_exception

        latency_ms = (time.monotonic() - start_time) * 1000
        token_input_count = count_tokens(
            build_user_content_from_texts(input_texts), model_invoked.model
        )

        self._record_metrics(
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            group_uuid=group_uuid,
            api_key_name=api_key_name,
            group_name=group_name,
            route_name=route_name,
            target_model_id=model.model_id,
            model=model_invoked,
            latency_ms=latency_ms,
            model_type='embeddings',
            token_input_count=token_input_count,
            fallback_triggered=fallback_triggered,
            is_semantic_search=is_semantic_search,
            project_uuid=project_uuid,
            project_name=project_name,
        )

        usage = Usage(prompt_tokens=token_input_count, total_tokens=token_input_count)
        data = [
            Embedding(index=i, embedding=vec, object='embedding')
            for i, vec in enumerate(vectors)
        ]

        return CreateEmbeddingResponse(
            object='list', data=data, model=result_model_name, usage=usage
        )
