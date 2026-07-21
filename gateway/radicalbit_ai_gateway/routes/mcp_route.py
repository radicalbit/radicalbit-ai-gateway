from fastapi import APIRouter, Request, Response

from radicalbit_ai_gateway.services.mcp_service import McpService


class McpRoute:
    @staticmethod
    def get_mcp_router(mcp_service: McpService) -> APIRouter:
        router = APIRouter(tags=['mcp'])

        @router.post('/{project_name}/{route_name}/mcp')
        async def mcp_post(
            request: Request, project_name: str, route_name: str
        ) -> Response:
            return await mcp_service.handle_post(request, project_name, route_name)

        return router
