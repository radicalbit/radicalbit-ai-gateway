from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from radicalbit_ai_gateway.models.auth_dto import GroupFullOut
from radicalbit_ai_gateway.models.event_dto import EventsDTO
from radicalbit_ai_gateway.models.gateway_config_out import GatewayRouteConfigOut


class GatewayRouteOut(BaseModel):
    route_name: str
    configuration: GatewayRouteConfigOut
    metrics: EventsDTO
    groups: list[GroupFullOut] | None

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )
