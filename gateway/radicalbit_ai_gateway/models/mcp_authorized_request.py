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

    def event_envelope(self) -> dict[str, str]:
        """Return the fields every event about this request carries.

        Spread into an event payload. Kept here so each MCP emitter does not
        walk its own way into ``key_details``, and so a new envelope field is
        added once.
        """
        return {
            'request_uuid': self.request_uuid,
            'route_name': self.route_name,
            'api_key_uuid': self.key_details.api_key_uuid,
            'api_key_name': self.key_details.api_key_name,
            'group_uuid': self.key_details.group_uuid,
            'group_name': self.key_details.group_name,
            'project_uuid': self.project_uuid,
            'project_name': self.project_name,
        }
