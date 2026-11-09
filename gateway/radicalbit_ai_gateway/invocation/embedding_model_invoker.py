import logging

from openai.types.create_embedding_response import CreateEmbeddingResponse, Usage
from openai.types.embedding import Embedding
from traceloop.sdk.decorators import task

from radicalbit_ai_gateway.invocation.errors import Surface, raising
from radicalbit_ai_gateway.invocation.fallback_chain import (
    CallContext,
    Candidate,
    Failure,
    FallbackChain,
    Reply,
    candidates,
)
from radicalbit_ai_gateway.invocation.model_invoker import ModelInvoker
from radicalbit_ai_gateway.invocation.recorder import Call, Tokens
from radicalbit_ai_gateway.llm.embeddings import Embeddings
from radicalbit_ai_gateway.llm.factory import init_embeddings
from radicalbit_ai_gateway.models.fallback import Fallback
from radicalbit_ai_gateway.models.model import MockGatewayEmbeddings, Model
from radicalbit_ai_gateway.models.request_identity import RequestIdentity
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.build_user_content import build_user_content_from_texts
from radicalbit_ai_gateway.utils.exceptions import ModelInvokerBadRequest
from radicalbit_ai_gateway.utils.parse_provider_and_model import (
    parse_provider_and_model,
)
from radicalbit_ai_gateway.utils.token_encoding import count_tokens

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)

EMBEDDINGS_MODEL_TYPE = 'embeddings'


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

        # Factory provider keys use underscores (google_genai) where the gateway
        # config uses hyphens (google-genai)
        factory_provider = provider.replace('-', '_')

        # Every provider accepts api_key directly as an alias for its own key
        return init_embeddings(
            model=model_name,
            provider=factory_provider,
            http_async_client=self.httpx_client,
            **{**params, **credentials},
        )

    async def embed(self, *args, **kwargs) -> CreateEmbeddingResponse:
        response, _ = await self.embed_answered(*args, **kwargs)
        return response

    @task(name='llm_embed')
    async def embed_answered(
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
    ) -> tuple[CreateEmbeddingResponse, Model]:
        """Embed ``input_texts``; return the response and the model that
        answered it, the target or a fallback.
        """
        if model_id not in self.model_map:
            raise ModelInvokerBadRequest(f'Embed model {model_id} not defined')

        model, embedding_model, fallbacks = self.model_map[model_id]

        logger.debug(
            'Invoking embedding model %s with input texts: %s',
            model_id,
            input_texts,
        )

        call = Call(
            identity=RequestIdentity(
                request_uuid=request_uuid,
                route_name=route_name,
                api_key_uuid=api_key_uuid,
                api_key_name=api_key_name,
                group_uuid=group_uuid,
                group_name=group_name,
                project_uuid=project_uuid,
                project_name=project_name,
            ),
            model_type=EMBEDDINGS_MODEL_TYPE,
            target_model_id=model_id,
            is_semantic_search=is_semantic_search,
        )

        def log_failure(candidate: Candidate, error: BaseException) -> None:
            if candidate.is_fallback:
                _, name = parse_provider_and_model(candidate.model.model)
                logger.warning(
                    'Fallback embedding model %s failed: %s', name, str(error)
                )
            else:
                logger.warning(
                    'Primary embedding model %s failed: %s. Trying fallbacks...',
                    model_id,
                    str(error),
                )

        def on_exhausted(failures: list[Failure]):
            logger.error(
                'All embedding models failed for route %s, model %s',
                route_name,
                model_id,
                exc_info=failures[0].error,
            )
            raising(Surface.EMBEDDINGS, route_name)(failures)

        async def embed(candidate: Candidate) -> Reply:
            vectors = await candidate.client.aembed_documents(input_texts)
            tokens = count_tokens(
                build_user_content_from_texts(input_texts), candidate.model.model
            )
            return Reply((vectors, candidate.model, tokens), usage=Tokens(input=tokens))

        chain = FallbackChain(
            candidates((model, embedding_model), fallbacks),
            CallContext(
                call=call,
                recorder=self.recorder,
                on_failure=log_failure,
                on_exhausted=on_exhausted,
            ),
        )
        vectors, model_invoked, token_input_count = await chain.call(embed)
        _, result_model_name = parse_provider_and_model(model_invoked.model)

        usage = Usage(prompt_tokens=token_input_count, total_tokens=token_input_count)
        data = [
            Embedding(index=i, embedding=vec, object='embedding')
            for i, vec in enumerate(vectors)
        ]

        return (
            CreateEmbeddingResponse(
                object='list', data=data, model=result_model_name, usage=usage
            ),
            model_invoked,
        )
