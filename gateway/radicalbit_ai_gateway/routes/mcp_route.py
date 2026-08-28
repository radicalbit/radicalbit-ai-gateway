from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from traceloop.sdk.decorators import workflow

from radicalbit_ai_gateway.ai_gateway import GatewayRoute
from radicalbit_ai_gateway.services.mcp_service import McpService
from radicalbit_ai_gateway.utils.dependencies import (
    get_gateway_routes,
    get_request_uuid,
)
from radicalbit_ai_gateway.utils.trace_attributes import (
    OperationCategory,
    ensure_endpoint_category,
    set_operation_category,
)


class McpRoute:
    @staticmethod
    def get_mcp_router(mcp_service: McpService) -> APIRouter:
        router = APIRouter(tags=['mcp'])

        # The root span for the whole request, so it covers the rate-limit
        # check as well as the dispatch; ensure_endpoint_category sits inside
        # it to reset the category a rejection leaves behind.
        @router.post('/{project_name}/{route_name}/mcp')
        @workflow(name='mcp_request')
        @ensure_endpoint_category
        async def mcp_post(
            request: Request,
            project_name: str,
            route_name: str,
            gateway_routes: dict[str, GatewayRoute] = Depends(get_gateway_routes),
            request_uuid: str = Depends(get_request_uuid),
        ) -> Response:
            authorized = await mcp_service.authorize(
                request, project_name, route_name, request_uuid
            )

            # Route-level features are applied here rather than inside the
            # service, so this path orchestrates them the way the /v1 endpoints
            # do: the GatewayRoute carries the live instances, the endpoint
            # decides when they run. After authorization, so an unknown route
            # or an unbound key never consumes budget.
            route = gateway_routes.get(authorized.route_key)
            if route is not None and route.request_rate_limiter:
                set_operation_category(OperationCategory.LIMITING)
                # One inbound JSON-RPC message counts as 1. The check precedes
                # the body parse, so notifications count too — one HTTP POST is
                # one request, as on /v1/*. Fan-out is deliberately not
                # counted: a tools/list opening five upstream sessions is still
                # a single call against the gateway's contract with its client.
                # Raises RequestRateLimitExceeded (HTTP 429) past the
                # threshold.
                await route.request_rate_limiter.check_and_count_request(
                    request_uuid=request_uuid,
                    api_key_uuid=authorized.key_details.api_key_uuid,
                    group_uuid=authorized.key_details.group_uuid,
                    api_key_name=authorized.key_details.api_key_name,
                    group_name=authorized.key_details.group_name,
                    project_uuid=authorized.project_uuid,
                    project_name=authorized.project_name,
                )

            result = await mcp_service.dispatch(request, authorized)
            if result.payload is None:
                return Response(status_code=result.status_code)
            return JSONResponse(result.payload, status_code=result.status_code)

        return router
