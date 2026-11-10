"""What MCP's admission keeps of its own on the shared path (see
``AdmissionRules``): the request is attributed before any check, the Origin
is checked before the credential, an unknown route answers 404 after auth,
and a key not bound to the route answers 403.
"""

from fastapi import Request

from radicalbit_ai_gateway.endpoints.common.admission import (
    AdmissionRules,
    Authenticate,
    set_api_key_uuid,
)
from radicalbit_ai_gateway.gateway_route.route import GatewayRoute
from radicalbit_ai_gateway.models.auth_dto import KeyDetails
from radicalbit_ai_gateway.services.mcp_service import McpService
from radicalbit_ai_gateway.utils.exceptions import McpTransportError
from radicalbit_ai_gateway.utils.trace_attributes import (
    OperationCategory,
    set_operation_category,
)


class McpAdmissionRules(AdmissionRules):
    """The admission rules of one MCP request to ``project_name/route_name``.

    ``authenticate`` is the request's credential check: the Origin first,
    then the bearer token. It keeps the caller's key, for the dispatch.
    """

    def __init__(self, service: McpService, project_name: str, route_name: str):
        self._service = service
        self.project_name = project_name
        self.route_name = route_name
        self.project_uuid = ''
        self.key_details: KeyDetails | None = None

    def opened(
        self,
        request: Request,
        route_key: str | None,
        route: GatewayRoute | None,
        request_uuid: str,
    ) -> None:
        self.project_uuid = self._service.open(
            request, self.project_name, self.route_name, request_uuid
        )

    async def authenticate(
        self, request: Request, project_uuid: str, project_name: str
    ) -> KeyDetails:
        self._service.validate_origin(request)
        set_operation_category(OperationCategory.AUTH)
        self.key_details = await set_api_key_uuid(request, project_uuid, project_name)
        return self.key_details

    async def unknown_route(
        self, request: Request, route_key: str | None, authenticate: Authenticate
    ) -> Exception:
        # Authenticated first: an unknown route is told only to a caller
        # with a valid key.
        await authenticate(request, self.project_uuid, self.project_name)
        return McpTransportError(
            f"Unknown project or route: '{self.project_name}/{self.route_name}'",
            404,
            code='mcp_route_not_found',
        )

    def not_member(self, route: GatewayRoute) -> Exception:
        return McpTransportError(
            f'API Key not associated with route {self.route_name}',
            403,
            code='mcp_key_not_bound',
        )
