import logging

from fastapi import HTTPException, Request

from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.utils.app_config import get_app_config

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)


async def get_gateway_routes(request: Request) -> dict:
    """Return the built GatewayRoute registry, keyed ``'{project}/{route}'``."""
    routes = getattr(request.app.state, 'routes', None)
    if routes is None:
        raise HTTPException(
            status_code=503,
            detail='AI Gateway not initialized. Please check server configuration.',
        )
    return routes


async def get_route_configs(request: Request) -> dict[str, GatewayRouteConfig]:
    """Return the served routes' configurations, keyed ``'{project}/{route}'``.

    Empty before the gateway has built its routes: a management write must not
    fail because of that.
    """
    routes = getattr(request.app.state, 'routes', None) or {}
    return {name: route.gateway_route_config for name, route in routes.items()}


async def get_request_uuid(request: Request) -> str:
    request_uuid = getattr(request.state, 'request_uuid', None)
    if request_uuid is None:
        logger.warning(
            'No request_uuid stamped for %s %s; RequestEventMiddleware did not '
            'match this path. Serving the request unattributed.',
            request.method,
            request.url.path,
        )
        return ''
    return request_uuid
