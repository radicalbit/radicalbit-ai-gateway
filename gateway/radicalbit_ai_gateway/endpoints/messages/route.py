import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from traceloop.sdk.decorators import task

from radicalbit_ai_gateway.auth.request_auth import authenticate_anthropic_request
from radicalbit_ai_gateway.endpoints.common.admission import Admission
from radicalbit_ai_gateway.endpoints.common.dependencies import (
    get_gateway_routes,
    get_request_uuid,
)
from radicalbit_ai_gateway.endpoints.common.http import endpoint
from radicalbit_ai_gateway.endpoints.common.streaming_response import (
    StreamingResponseWithStatusCode,
)
from radicalbit_ai_gateway.endpoints.messages import pipeline as messages_pipeline
from radicalbit_ai_gateway.endpoints.messages.params import MessageCreateParams
from radicalbit_ai_gateway.endpoints.messages.serving import (
    anthropic_headers,
    serve_stream,
)
from radicalbit_ai_gateway.gateway_route.route import GatewayRoute
from radicalbit_ai_gateway.models.auth_dto import KeyDetails
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import GatewayNotFoundError
from radicalbit_ai_gateway.utils.trace_attributes import (
    OperationCategory,
    in_request_trace,
    set_operation_category,
)

logger = logging.getLogger(get_app_config().log_config.logger_name)


@task(name='auth_api_key')
async def authenticate(
    request: Request, project_uuid: str, project_name: str
) -> KeyDetails:
    """Read the credential as Anthropic clients send it (``x-api-key``), or
    as a bearer token.
    """
    return await authenticate_anthropic_request(request, project_uuid, project_name)


class MessagesRoute:
    @staticmethod
    def get_messages_router(admission: Admission) -> APIRouter:
        router = APIRouter()

        # This endpoint follows the Anthropic Messages API:
        # https://docs.claude.com/en/api/messages
        # A request is served by a model that serves the Messages API, as the
        # client sent it once the route's policies applied, with only `model`
        # swapped. It is never translated.
        @router.post('/v1/messages')
        @endpoint('messages')
        async def messages(
            request: Request,
            message_create_params: MessageCreateParams,
            gateway_routes: dict[str, GatewayRoute] = Depends(get_gateway_routes),
            request_uuid: str = Depends(get_request_uuid),
        ):
            def announce(route_name: str) -> None:
                logger.info('Invoked route name (messages): %s', route_name)

            is_stream = bool(message_create_params.get('stream'))
            scope = await admission.admit(
                request,
                gateway_routes,
                message_create_params['model'],
                request_uuid,
                streaming=is_stream,
                announce=announce,
                authenticate=authenticate,
            )
            # The request as the client sent it, unknown fields included: the
            # gateway's policies apply to it, then it goes upstream.
            body = await request.json()
            headers = anthropic_headers(request.headers)

            if is_stream:
                frames = await messages_pipeline.stream(scope, body, headers)
                set_operation_category(OperationCategory.ENDPOINT)
                return StreamingResponseWithStatusCode(
                    in_request_trace(serve_stream(frames)),
                    media_type='text/event-stream',
                    headers=scope.headers(),
                )

            message = await messages_pipeline.respond(scope, body, headers)
            set_operation_category(OperationCategory.ENDPOINT)
            return JSONResponse(content=message, headers=scope.headers())

        # The Messages API endpoints the gateway does not serve: count_tokens,
        # batches. Out of the OpenAPI schema, as the unsupported Responses
        # paths: it only answers 404, and its operationId would change between
        # processes.
        @router.api_route(
            '/v1/messages/{path:path}',
            methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'],
            include_in_schema=False,
        )
        async def messages_unsupported(request: Request, path: str):
            raise GatewayNotFoundError(
                f'{request.method} /v1/messages/{path} is not supported by the gateway'
            )

        return router
