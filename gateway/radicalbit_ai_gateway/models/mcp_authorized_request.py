from pydantic import BaseModel, ConfigDict

from radicalbit_ai_gateway.models.auth_dto import KeyDetails
from radicalbit_ai_gateway.models.mcp_server import AnyMcpServer


class McpAuthorizedRequest(BaseModel):
    """What ``McpService.authorize`` established, for its caller to act on.

    Frozen: authorization is settled by the time this exists, so the endpoint
    applying route-level features to it cannot rewrite what was authorized.

    ``route_key`` is carried so the caller looks the route up under the key the
    binding check already used, rather than rebuilding that format itself.
    """

    model_config = ConfigDict(frozen=True)

    request_uuid: str
    project_name: str
    project_uuid: str
    route_name: str
    route_key: str
    key_details: KeyDetails
    servers: list[AnyMcpServer]
