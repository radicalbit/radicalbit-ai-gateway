from fastapi import Request

from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig


async def get_route_configs(request: Request) -> dict[str, GatewayRouteConfig]:
    """Return the served routes' configurations, keyed ``'{project}/{route}'``.

    Empty before the gateway has built its routes: a management write must not
    fail because of that.
    """
    routes = getattr(request.app.state, 'routes', None) or {}
    return {name: route.gateway_route_config for name, route in routes.items()}
