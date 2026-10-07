from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from traceloop.sdk.decorators import workflow

from radicalbit_ai_gateway.ai_gateway import GatewayRoute
from radicalbit_ai_gateway.middleware.request_event_context import RequestEventContext
from radicalbit_ai_gateway.models.decision_request import DecisionRequest
from radicalbit_ai_gateway.services.group_service import GroupService
from radicalbit_ai_gateway.utils.dependencies import (
    get_gateway_routes,
    get_request_uuid,
)
from radicalbit_ai_gateway.utils.endpoint_helpers import (
    otel_metrics_decorator,
    set_api_key_uuid,
    set_early_project_trace_attributes,
)
from radicalbit_ai_gateway.utils.exceptions import GatewayBadRequest, InvalidApiKey
from radicalbit_ai_gateway.utils.request_context import (
    get_current_request_tags,
    reset_route_context,
)
from radicalbit_ai_gateway.utils.trace_attributes import (
    OperationCategory,
    ensure_endpoint_category,
    set_operation_category,
    set_trace_attributes,
)


class DecisionRoute:
    @staticmethod
    def get_decision_router(group_service: GroupService) -> APIRouter:
        router = APIRouter(tags=['decision'])

        # This endpoint follows Typesafe's own contract, passed through
        # unchanged (ADR 0004): https://docs.typesafe.ai
        @router.post('/v1/systemone')
        @otel_metrics_decorator
        @workflow(name='decision_model')
        @ensure_endpoint_category
        @reset_route_context
        async def systemone(
            request: Request,
            decision_request: DecisionRequest,
            gateway_routes: dict[str, GatewayRoute] = Depends(get_gateway_routes),
            request_uuid: str = Depends(get_request_uuid),
        ) -> Response:
            route_key = decision_request.model
            route = gateway_routes.get(route_key)

            set_early_project_trace_attributes(request, route_key, route)

            if route is None:
                raise GatewayBadRequest(
                    f'The route name [{route_key}] was not found in the config'
                )
            route_name = route.gateway_route_config.route_name
            request.state.otel_route_name = route_name

            # Mark the root workflow span with ENDPOINT category
            set_operation_category(OperationCategory.ENDPOINT)

            # Set early trace attributes
            set_trace_attributes(
                request_uuid=request_uuid,
                route_name=route_name,
                tags=list(get_current_request_tags()),
            )

            # Populate request event context first (before auth, so route_name
            # is always captured)
            ctx = RequestEventContext.get_or_create(request)
            ctx.route_name = route_name
            ctx.is_streaming = False

            # Validate API key after context is populated
            set_operation_category(OperationCategory.AUTH)
            key_details = await set_api_key_uuid(
                request, route.project_uuid, route.project_name
            )

            # Set auth-related trace attributes
            set_trace_attributes(
                api_key_uuid=key_details.api_key_uuid,
                api_key_name=key_details.api_key_name,
                group_uuid=key_details.group_uuid,
                group_name=key_details.group_name,
                project_uuid=route.project_uuid,
                project_name=route.project_name,
                tags=list(get_current_request_tags()),
            )

            if not group_service.check_key_uuid_for_route(
                route_key, UUID(key_details.api_key_uuid)
            ):
                raise InvalidApiKey('Incorrect API key provided.')

            ctx.project_uuid = route.project_uuid
            ctx.project_name = route.project_name

            set_operation_category(OperationCategory.ENDPOINT)
            result = await route.invoke_decision(
                request_uuid=request_uuid,
                api_key_uuid=key_details.api_key_uuid,
                api_key_name=key_details.api_key_name,
                group_uuid=key_details.group_uuid,
                group_name=key_details.group_name,
                route_name=route_name,
                body=decision_request.model_dump(),
            )

            return Response(
                content=result.content,
                status_code=result.status_code,
                media_type=result.media_type,
            )

        return router
