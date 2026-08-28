from fastapi import HTTPException, Request


async def get_gateway_routes(request: Request) -> dict:
    """Return the built GatewayRoute registry, keyed ``'{project}/{route}'``."""
    routes = getattr(request.app.state, 'routes', None)
    if routes is None:
        raise HTTPException(
            status_code=503,
            detail='AI Gateway not initialized. Please check server configuration.',
        )
    return routes


async def get_request_uuid(request: Request) -> str:
    return request.state.request_uuid
