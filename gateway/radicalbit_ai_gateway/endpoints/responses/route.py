import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from radicalbit_ai_gateway.endpoints.common.admission import Admission
from radicalbit_ai_gateway.endpoints.common.dependencies import (
    get_gateway_routes,
    get_request_uuid,
)
from radicalbit_ai_gateway.endpoints.common.http import endpoint
from radicalbit_ai_gateway.endpoints.common.streaming_response import (
    StreamingResponseWithStatusCode,
)
from radicalbit_ai_gateway.endpoints.responses import pipeline as responses_pipeline
from radicalbit_ai_gateway.endpoints.responses.params import ResponseCreateParamsCustom
from radicalbit_ai_gateway.endpoints.responses.serving import serve_stream
from radicalbit_ai_gateway.gateway_route.route import GatewayRoute
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import GatewayNotFoundError
from radicalbit_ai_gateway.utils.trace_attributes import (
    OperationCategory,
    in_request_trace,
    set_operation_category,
)

logger = logging.getLogger(get_app_config().log_config.logger_name)


class ResponsesRoute:
    @staticmethod
    def get_responses_router(admission: Admission) -> APIRouter:
        router = APIRouter()

        # This endpoint follows the OpenAI Responses API standard:
        # https://platform.openai.com/docs/api-reference/responses
        # A request is served by a model that serves the Responses API, as the
        # client sent it once the route's policies applied.
        @router.post('/v1/responses')
        @endpoint('responses')
        async def responses(
            request: Request,
            response_create_params: ResponseCreateParamsCustom,
            gateway_routes: dict[str, GatewayRoute] = Depends(get_gateway_routes),
            request_uuid: str = Depends(get_request_uuid),
        ):
            def announce(route_name: str) -> None:
                logger.debug('Responses API request: %s', response_create_params)
                logger.info('Invoked route name (responses): %s', route_name)

            is_stream = bool(response_create_params.get('stream'))
            scope = await admission.admit(
                request,
                gateway_routes,
                response_create_params.get('model', 'unknown'),
                request_uuid,
                streaming=is_stream,
                announce=announce,
            )
            # The request as the client sent it: the gateway's policies apply
            # to it, then it goes upstream.
            body = await request.json()

            if is_stream:
                frames = await responses_pipeline.stream(scope, body)
                set_operation_category(OperationCategory.ENDPOINT)
                return StreamingResponseWithStatusCode(
                    in_request_trace(serve_stream(frames)),
                    media_type='text/event-stream',
                    headers=scope.headers(),
                )

            response = await responses_pipeline.respond(scope, body)
            set_operation_category(OperationCategory.ENDPOINT)
            return JSONResponse(content=response, headers=scope.headers())

        # The Responses API endpoints the gateway does not serve yet: those on
        # stored responses (retrieve, delete, cancel, input_items), compact and
        # input_tokens.
        # Out of the OpenAPI schema: it only answers 404, and FastAPI would
        # give it an operationId that changes between processes (the first
        # of its methods in a set), unfit for generated clients.
        @router.api_route(
            '/v1/responses/{path:path}',
            methods=['GET', 'POST', 'DELETE'],
            include_in_schema=False,
        )
        async def responses_unsupported(request: Request, path: str):
            raise GatewayNotFoundError(
                f'{request.method} /v1/responses/{path} is not supported by the gateway yet'
            )

        return router
