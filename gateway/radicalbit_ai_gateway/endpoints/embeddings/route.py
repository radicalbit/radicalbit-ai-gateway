from fastapi import APIRouter, Depends, Request
from openai.types import CreateEmbeddingResponse
from openai.types.embedding_create_params import EmbeddingCreateParams

from radicalbit_ai_gateway.endpoints.common.admission import Admission
from radicalbit_ai_gateway.endpoints.common.http import endpoint
from radicalbit_ai_gateway.endpoints.embeddings import pipeline as embeddings_pipeline
from radicalbit_ai_gateway.gateway_route.route import GatewayRoute
from radicalbit_ai_gateway.routes.dependencies import (
    get_gateway_routes,
    get_request_uuid,
)
from radicalbit_ai_gateway.utils.trace_attributes import (
    OperationCategory,
    set_operation_category,
)


class EmbeddingsRoute:
    @staticmethod
    def get_embeddings_router(admission: Admission) -> APIRouter:
        router = APIRouter()

        # This endpoint must follow the openai standard
        @router.post(
            '/v1/embeddings',
            response_model=CreateEmbeddingResponse,
            response_model_exclude_none=True,
        )
        @endpoint('embeddings')
        async def embeddings(
            request: Request,
            embedding_create_params: EmbeddingCreateParams,
            gateway_routes: dict[str, GatewayRoute] = Depends(get_gateway_routes),
            request_uuid: str = Depends(get_request_uuid),
        ):
            scope = await admission.admit(
                request,
                gateway_routes,
                embedding_create_params.get('model'),
                request_uuid,
            )
            input_texts = embedding_create_params.get('input')
            if isinstance(input_texts, str):
                input_texts = [input_texts]

            set_operation_category(OperationCategory.ENDPOINT)
            return await embeddings_pipeline.embed(scope, input_texts)

        return router
