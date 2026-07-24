from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from radicalbit_ai_gateway.services.mcp_service import McpService


class McpRoute:
    @staticmethod
    def get_mcp_router(mcp_service: McpService) -> APIRouter:
        router = APIRouter(tags=['mcp'])

        @router.post('/{project_name}/{route_name}/mcp')
        async def mcp_post(
            request: Request, project_name: str, route_name: str
        ) -> Response:
            result = await mcp_service.handle_post(request, project_name, route_name)
            if result.payload is None:
                return Response(status_code=result.status_code)
            return JSONResponse(result.payload, status_code=result.status_code)

        return router
