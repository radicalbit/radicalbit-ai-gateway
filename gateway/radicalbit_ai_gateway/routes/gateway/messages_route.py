import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from radicalbit_ai_gateway.ai_gateway import GatewayRoute
from radicalbit_ai_gateway.db.dao.project_budget_limit_dao import ProjectBudgetLimitDAO
from radicalbit_ai_gateway.messages.request import MessageCreateParams
from radicalbit_ai_gateway.messages.serving import (
    anthropic_headers,
    serve_messages_stream,
)
from radicalbit_ai_gateway.middleware.request_event_context import RequestEventContext
from radicalbit_ai_gateway.pipeline import messages as messages_pipeline
from radicalbit_ai_gateway.pipeline.http import endpoint
from radicalbit_ai_gateway.services.group_service import GroupService
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.dependencies import (
    get_gateway_routes,
    get_request_uuid,
)
from radicalbit_ai_gateway.utils.endpoint_helpers import (
    resolve_request_limits,
    set_anthropic_api_key_uuid,
    set_early_project_trace_attributes,
)
from radicalbit_ai_gateway.utils.exceptions import (
    GatewayBadRequest,
    GatewayNotFoundError,
    InvalidApiKey,
)
from radicalbit_ai_gateway.utils.request_context import (
    get_current_request_tags,
    set_current_route_config,
)
from radicalbit_ai_gateway.utils.streaming_response import (
    StreamingResponseWithStatusCode,
)
from radicalbit_ai_gateway.utils.trace_attributes import (
    OperationCategory,
    in_request_trace,
    set_operation_category,
    set_trace_attributes,
)

logger = logging.getLogger(get_app_config().log_config.logger_name)


class MessagesRoute:
    @staticmethod
    def get_messages_router(
        group_service: GroupService,
        project_budget_limit_dao: ProjectBudgetLimitDAO,
    ) -> APIRouter:
        router = APIRouter()

        # This endpoint follows the Anthropic Messages API:
        # https://docs.claude.com/en/api/messages
        # A request is served by a model that serves the Messages API, as the client
        # sent it with only `model` swapped. It is never translated.
        @router.post('/v1/messages')
        @endpoint('messages')
        async def messages(
            request: Request,
            message_create_params: MessageCreateParams,
            gateway_routes: dict[str, GatewayRoute] = Depends(get_gateway_routes),
            request_uuid: str = Depends(get_request_uuid),
        ):
            # Mark the root workflow span with ENDPOINT category
            set_operation_category(OperationCategory.ENDPOINT)

            route_key = message_create_params['model']
            route = gateway_routes.get(route_key)

            set_early_project_trace_attributes(request, route_key, route)

            if route is None:
                raise GatewayBadRequest(
                    f'The route name [{route_key}] was not found in the config'
                )
            route_name = route.gateway_route_config.route_name
            # Publish the route config for per-route log filtering (cleared by the decorator).
            set_current_route_config(route.gateway_route_config)
            request.state.otel_route_name = route_name

            set_trace_attributes(
                request_uuid=request_uuid,
                route_name=route_name,
                tags=list(get_current_request_tags()),
            )

            is_stream = bool(message_create_params.get('stream'))
            ctx = RequestEventContext.get_or_create(request)
            ctx.route_name = route_name
            ctx.is_streaming = is_stream

            set_operation_category(OperationCategory.AUTH)
            key_details = await set_anthropic_api_key_uuid(
                request, route.project_uuid, route.project_name
            )

            set_trace_attributes(
                api_key_uuid=key_details.api_key_uuid,
                api_key_name=key_details.api_key_name,
                group_uuid=key_details.group_uuid,
                group_name=key_details.group_name,
                project_uuid=route.project_uuid,
                project_name=route.project_name,
                tags=list(get_current_request_tags()),
            )

            # The request as the client sent it, unknown fields included.
            body = await request.json()

            logger.info('Invoked route name (messages): %s', route_name)

            if not group_service.check_key_uuid_for_route(
                route_key, UUID(key_details.api_key_uuid)
            ):
                raise InvalidApiKey(f'API Key not associated with route {route_name}')

            ctx.project_uuid = route.project_uuid
            ctx.project_name = route.project_name
            # Routing charges its calls to the request's limits. Checking them goes
            # here, as on the Responses API: AG-1132.
            request_limits = await resolve_request_limits(
                route, key_details, request_uuid, project_budget_limit_dao
            )

            scope = route.for_request(request_limits.identity, request_limits)
            prepared = await messages_pipeline.prepare(
                scope, body, anthropic_headers(request.headers)
            )

            if is_stream:
                set_operation_category(OperationCategory.ENDPOINT)
                return StreamingResponseWithStatusCode(
                    in_request_trace(
                        serve_messages_stream(messages_pipeline.stream(scope, prepared))
                    ),
                    media_type='text/event-stream',
                )

            message = await messages_pipeline.respond(scope, prepared)
            set_operation_category(OperationCategory.ENDPOINT)
            return JSONResponse(content=message)


        # The Messages API endpoints the gateway does not serve: count_tokens, batches.
        @router.api_route(
            '/v1/messages/{path:path}',
            methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'],
        )
        async def messages_unsupported(request: Request, path: str):
            raise GatewayNotFoundError(
                f'{request.method} /v1/messages/{path} is not supported by the gateway'
            )

        return router
