from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from radicalbit_ai_gateway.endpoints.common.admission import caller_identity
from radicalbit_ai_gateway.endpoints.common.http import traced_endpoint
from radicalbit_ai_gateway.gateway_route.route import GatewayRoute
from radicalbit_ai_gateway.limiting.limits import ADMISSION, shared_limits
from radicalbit_ai_gateway.mcp_proxy.list_cache import McpListCache
from radicalbit_ai_gateway.routes.dependencies import (
    get_gateway_routes,
    get_request_uuid,
)
from radicalbit_ai_gateway.services.mcp_service import McpService


class McpRoute:
    @staticmethod
    def get_mcp_router(mcp_service: McpService) -> APIRouter:
        router = APIRouter(tags=['mcp'])

        # The root span for the whole request, so it covers the rate-limit
        # check as well as the dispatch. Not @endpoint: MCP records no HTTP
        # request metrics.
        @router.post('/{project_name}/{route_name}/mcp')
        @traced_endpoint('mcp_request')
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

            # Request limits first: the credential's before the route's,
            # which decides the error reported when both would block.
            #
            # One inbound JSON-RPC message counts as 1. The check precedes
            # the body parse, so notifications count too — one HTTP POST is
            # one request, as on /v1/*. Fan-out is deliberately not counted:
            # a tools/list opening five upstream sessions is still a single
            # call against the gateway's contract with its client. Raises
            # RequestRateLimitExceeded (HTTP 429) past the threshold.
            if route is not None:
                key_details = authorized.key_details
                request_limits = shared_limits.resolve(
                    caller_identity(
                        request_uuid,
                        authorized.route_name,
                        authorized.project_uuid,
                        authorized.project_name,
                        key_details,
                    ),
                    route.route_limits,
                    key_details.limits,
                )
                await request_limits.check(ADMISSION)

            list_cache = McpListCache.for_route(
                gateway_cache=route.gateway_cache if route else None,
                ttl=route.cache.ttl if route else None,
                authorized=authorized,
            )

            result = await mcp_service.dispatch(request, authorized, list_cache)
            if result.payload is None:
                return Response(status_code=result.status_code)
            return JSONResponse(result.payload, status_code=result.status_code)

        return router
