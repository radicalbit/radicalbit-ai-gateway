import logging

from fastapi import APIRouter, Depends, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from radicalbit_ai_gateway.ai_gateway import GatewayRoute
from radicalbit_ai_gateway.endpoints.chat_completions import pipeline as chat_pipeline
from radicalbit_ai_gateway.endpoints.chat_completions.params import (
    CompletionCreateParams,
)
from radicalbit_ai_gateway.endpoints.chat_completions.pipeline import (
    CHAT_FIELDS,
    ChatRequest,
)
from radicalbit_ai_gateway.endpoints.common.admission import Admission
from radicalbit_ai_gateway.endpoints.common.http import endpoint, sse_response
from radicalbit_ai_gateway.routes.dependencies import (
    get_gateway_routes,
    get_request_uuid,
)
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.trace_attributes import (
    OperationCategory,
    set_operation_category,
)

logger = logging.getLogger(get_app_config().log_config.logger_name)


def _log_chat_request(
    request: Request, params: CompletionCreateParams, route_name: str
) -> None:
    logger.debug('Chat completion request: %s', params)
    client_host = request.client.host if request.client else 'unknown'
    logger.debug(
        'Received request: method=%s path=%s client=%s',
        request.method,
        request.url.path,
        client_host,
    )
    logger.debug('Received completion_create_params: %s', params)
    logger.debug('Messages: %s', list(params.get('messages')))
    logger.debug('Tools: %s', list(params.get('tools') or []))
    logger.debug(
        'Received params: %s',
        {k: v for k, v in params.items() if k not in CHAT_FIELDS},
    )
    logger.info('Invoked route name: %s', route_name)


class ChatCompletionsRoute:
    @staticmethod
    def get_chat_completions_router(admission: Admission) -> APIRouter:
        router = APIRouter()

        # This endpoint must follow the openai standard
        # https://platform.openai.com/docs/api-reference/chat/create
        @router.post('/v1/chat/completions')
        @endpoint('chat_completions')
        async def chat_completions(
            request: Request,
            completion_create_params: CompletionCreateParams,
            gateway_routes: dict[str, GatewayRoute] = Depends(get_gateway_routes),
            request_uuid: str = Depends(get_request_uuid),
        ):
            scope = await admission.admit(
                request,
                gateway_routes,
                completion_create_params.get('model', 'unknown'),
                request_uuid,
                streaming=bool(completion_create_params.get('stream')),
                announce=lambda route_name: _log_chat_request(
                    request, completion_create_params, route_name
                ),
            )
            chat = ChatRequest.of(completion_create_params)
            if chat.stream:
                items = await chat_pipeline.stream(scope, chat)
                buffered = scope.route.guardrails.has_output
                return sse_response(
                    items,
                    scope.headers(),
                    done_log='Streaming finished (Buffered): [DONE]'
                    if buffered
                    else 'Streaming finished: [DONE]',
                )

            completion = await chat_pipeline.complete(scope, chat)
            logger.info('Invoke response: %s', completion)
            request.state.otel_model_name = completion.model
            set_operation_category(OperationCategory.ENDPOINT)
            return JSONResponse(
                content=jsonable_encoder(completion), headers=scope.headers()
            )

        return router
