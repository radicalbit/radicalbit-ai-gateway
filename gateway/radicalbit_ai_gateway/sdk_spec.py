"""The OpenAPI spec the Management SDK is generated from.

Only the operations in ``SDK_OPERATION_IDS``, and the schemas they reach: the
rest of the app (the inference endpoints above all) stays out of the SDK.
"""

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts

SDK_OPERATION_IDS = (
    'projects_create',
    'projects_list',
    'projects_get',
    'credentials_create',
    'credentials_list',
    'credentials_get',
    'credentials_delete',
    'credentials_rotate',
    'credentials_end_grace_period',
    'groups_create',
    'groups_list',
    'groups_get',
    'groups_add_credentials',
    'groups_remove_credential',
    'groups_add_routes',
    'groups_remove_route',
    'configs_validate',
    'configs_save',
    'configs_upload',
    'configs_approve',
    'configs_cancel_approval',
    'configs_serve',
    'configs_unserve',
)


def sdk_routes(app: FastAPI) -> list[RouteContext]:
    # Routes of included routers are only reachable through their contexts
    return [
        context
        for context in iter_route_contexts(app.routes)
        if isinstance(context.original_route, APIRoute)
        and context.operation_id in SDK_OPERATION_IDS
    ]


# The SDK spec carries the API version, not the build version: the build version
# changes on every commit and would make the committed spec always look stale.
# The SDK package version follows the gateway release instead.
SDK_SPEC_VERSION = 'v1'


def build_sdk_spec(app: FastAPI) -> dict[str, Any]:
    routes = sdk_routes(app)
    missing = set(SDK_OPERATION_IDS) - {route.operation_id for route in routes}
    if missing:
        raise ValueError(f'SDK operations not found in the app: {sorted(missing)}')
    return get_openapi(
        title='Radicalbit AI Gateway Management API',
        version=SDK_SPEC_VERSION,
        openapi_version=app.openapi_version,
        description='The management API of the Radicalbit AI Gateway.',
        routes=routes,
    )
