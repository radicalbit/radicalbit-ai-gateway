from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from radicalbit_ai_gateway.endpoints.common.admission import Admission
from radicalbit_ai_gateway.endpoints.common.dependencies import (
    get_gateway_routes,
    get_request_uuid,
)
from radicalbit_ai_gateway.endpoints.common.http import endpoint
from radicalbit_ai_gateway.endpoints.mcp.admission import McpAdmissionRules
from radicalbit_ai_gateway.gateway_route.route import GatewayRoute
from radicalbit_ai_gateway.mcp_proxy.list_cache import McpListCache
from radicalbit_ai_gateway.services.mcp_service import McpService


class McpRoute:
    @staticmethod
    def get_mcp_router(mcp_service: McpService, admission: Admission) -> APIRouter:
        router = APIRouter(tags=['mcp'])

        # The root span covers the whole request: admission, with its limit
        # check, as well as the dispatch.
        @router.post('/{project_name}/{route_name}/mcp')
        @endpoint('mcp_request')
        async def mcp_post(
            request: Request,
            project_name: str,
            route_name: str,
            gateway_routes: dict[str, GatewayRoute] = Depends(get_gateway_routes),
            request_uuid: str = Depends(get_request_uuid),
        ) -> Response:
            # Admitted as on /v1, with MCP's own rules. The admission check
            # counts one inbound JSON-RPC message as 1, before the body parse:
            # notifications count too, one HTTP POST is one request. Fan-out is
            # not counted: a tools/list opening five upstream sessions is still
            # a single call against the gateway's contract with its client.
            rules = McpAdmissionRules(mcp_service, project_name, route_name)
            scope = await admission.admit(
                request,
                gateway_routes,
                f'{project_name}/{route_name}',
                request_uuid,
                authenticate=rules.authenticate,
                rules=rules,
            )
            route = scope.route
            authorized = mcp_service.authorized(
                request,
                request_uuid=request_uuid,
                project_name=project_name,
                project_uuid=rules.project_uuid or route.project_uuid,
                route_name=route_name,
                key_details=rules.key_details,
            )
            list_cache = McpListCache.for_route(
                gateway_cache=route.gateway_cache,
                ttl=route.cache.ttl,
                authorized=authorized,
            )

            result = await mcp_service.dispatch(request, authorized, list_cache)
            if result.payload is None:
                return Response(status_code=result.status_code)
            return JSONResponse(result.payload, status_code=result.status_code)

        return router
