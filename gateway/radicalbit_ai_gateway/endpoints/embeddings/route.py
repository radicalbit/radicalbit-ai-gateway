from collections.abc import Iterable

from fastapi import APIRouter, Depends, Request
from openai.types import CreateEmbeddingResponse
from openai.types.embedding_create_params import EmbeddingCreateParams
from pydantic import ValidationError

from radicalbit_ai_gateway.endpoints.common.admission import Admission
from radicalbit_ai_gateway.endpoints.common.dependencies import (
    get_gateway_routes,
    get_request_uuid,
)
from radicalbit_ai_gateway.endpoints.common.http import endpoint
from radicalbit_ai_gateway.endpoints.embeddings import pipeline as embeddings_pipeline
from radicalbit_ai_gateway.gateway_route.route import GatewayRoute
from radicalbit_ai_gateway.utils.exceptions import GatewayBadRequest
from radicalbit_ai_gateway.utils.trace_attributes import (
    OperationCategory,
    set_operation_category,
)


def _input_texts(
    value: str | Iterable[str] | Iterable[int] | Iterable[Iterable[int]],
) -> list[str]:
    """Return the texts of an embeddings request.

    The gateway embeds text: its limits, guardrails and cache read the
    texts, and its providers take texts. Token arrays are refused.
    """
    refusal = GatewayBadRequest(
        'The gateway embeds text input only: token arrays are not supported'
    )
    if isinstance(value, str):
        return [value]
    try:
        # An array that is not a list of strings is validated as it is read:
        # a list of token lists fails as a list of tokens.
        items = list(value)
    except ValidationError as e:
        raise refusal from e
    texts = [item for item in items if isinstance(item, str)]
    if len(texts) != len(items):
        raise refusal
    return texts


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
            input_texts = _input_texts(embedding_create_params['input'])

            set_operation_category(OperationCategory.ENDPOINT)
            return await embeddings_pipeline.embed(scope, input_texts)

        return router
