from radicalbit_ai_gateway.models.gateway_config_out import GatewayRouteConfigOut
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig


def test_the_out_route_config_starts_with_every_field_of_the_route_config():
    """The dashboard builds the Out model from a dump of the route config, and
    the Out model forbids extra fields: a field added to one only fails there.
    The shared fields also keep the schema's property order.
    """
    route_fields = list(GatewayRouteConfig.model_fields)
    out_fields = list(GatewayRouteConfigOut.model_fields)
    assert out_fields[: len(route_fields)] == route_fields
