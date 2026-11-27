"""The FastAPI dependencies of the proxy endpoints."""

import logging

from fastapi import HTTPException, Request

from radicalbit_ai_gateway.gateway_route.route import GatewayRoute
from radicalbit_ai_gateway.utils.app_config import get_app_config

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)


async def get_gateway_routes(request: Request) -> dict[str, GatewayRoute]:
    """Return the built GatewayRoute registry, keyed ``'{project}/{route}'``."""
    routes = getattr(request.app.state, 'routes', None)
    if not isinstance(routes, dict):
        raise HTTPException(
            status_code=503,
            detail='AI Gateway not initialized. Please check server configuration.',
        )
    # app.state is untyped: keep the entries the route factory stores.
    return {
        key: route
        for key, route in routes.items()
        if isinstance(key, str) and isinstance(route, GatewayRoute)
    }


async def get_request_uuid(request: Request) -> str:
    request_uuid = getattr(request.state, 'request_uuid', None)
    if not isinstance(request_uuid, str):
        logger.warning(
            'No request_uuid stamped for %s %s; RequestEventMiddleware did not '
            'match this path. Serving the request unattributed.',
            request.method,
            request.url.path,
        )
        return ''
    return request_uuid
