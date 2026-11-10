"""Admission: what every proxy endpoint does before it serves a request."""

from collections.abc import Callable
import logging
from uuid import UUID

from fastapi import Request
from traceloop.sdk.decorators import task

from radicalbit_ai_gateway.ai_gateway import GatewayRoute
from radicalbit_ai_gateway.auth.request_auth import authenticate_bearer_request
from radicalbit_ai_gateway.db.dao.project_budget_limit_dao import ProjectBudgetLimitDAO
from radicalbit_ai_gateway.endpoints.common.scope import RequestScope
from radicalbit_ai_gateway.limiting.limits import (
    ADMISSION,
    RequestLimits,
    load_project_limits,
    shared_limits,
)
from radicalbit_ai_gateway.middleware.request_event_context import RequestEventContext
from radicalbit_ai_gateway.models.auth_dto import KeyDetails
from radicalbit_ai_gateway.models.request_identity import RequestIdentity
from radicalbit_ai_gateway.services.group_service import GroupService
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import GatewayBadRequest, InvalidApiKey
from radicalbit_ai_gateway.utils.request_context import (
    get_current_request_tags,
    set_current_route_config,
)
from radicalbit_ai_gateway.utils.trace_attributes import (
    OperationCategory,
    set_operation_category,
    set_trace_attributes,
)

logger = logging.getLogger(get_app_config().log_config.logger_name)


@task(name='auth_api_key')
async def set_api_key_uuid(
    request: Request, project_uuid: str, project_name: str
) -> KeyDetails:
    return await authenticate_bearer_request(request, project_uuid, project_name)


def set_early_project_trace_attributes(
    request: Request,
    route_key: str | None,
    route: GatewayRoute | None,
) -> None:
    """Set project identity on the span before route validation and auth.

    Ensures traces from failed requests (unknown route, bad API key) remain
    visible in project-scoped queries.
    """
    if route is not None:
        set_trace_attributes(
            project_uuid=route.project_uuid,
            project_name=route.project_name,
            tags=list(get_current_request_tags()),
        )
        return
    project_name, _, route_name_part = (route_key or '').partition('/')
    entry = getattr(request.app.state, 'project_configs', {}).get(project_name)
    if entry:
        set_trace_attributes(
            project_uuid=str(entry.uuid),
            project_name=project_name,
            route_name=route_name_part or route_key,
            tags=list(get_current_request_tags()),
        )
    else:
        set_trace_attributes(
            route_name=route_name_part or route_key,
            tags=list(get_current_request_tags()),
        )


class Admission:
    """Admits a request to a route: finds the route, authenticates the
    caller, checks the caller may use the route, and resolves and checks the
    request's limits.
    """

    def __init__(
        self,
        group_service: GroupService,
        project_budget_limit_dao: ProjectBudgetLimitDAO,
    ) -> None:
        self._group_service = group_service
        self._project_budget_limit_dao = project_budget_limit_dao

    async def admit(
        self,
        request: Request,
        routes: dict[str, GatewayRoute],
        route_key: str | None,
        request_uuid: str,
        *,
        streaming: bool = False,
        announce: Callable[[str], None] | None = None,
    ) -> RequestScope:
        """Return the scope of a request the gateway serves, or raise the
        error that refuses it. ``announce`` logs the request once its caller
        is known.
        """
        route = routes.get(route_key)
        set_early_project_trace_attributes(request, route_key, route)
        if route is None:
            raise GatewayBadRequest(
                f'The route name [{route_key}] was not found in the config'
            )
        route_name = route.gateway_route_config.route_name
        # The route labels the request's metrics and, for per-route log
        # filtering, its log lines (cleared by @endpoint).
        request.state.otel_route_name = route_name
        set_current_route_config(route.gateway_route_config)

        set_operation_category(OperationCategory.ENDPOINT)
        set_trace_attributes(
            request_uuid=request_uuid,
            route_name=route_name,
            tags=list(get_current_request_tags()),
        )
        # The request event knows the route even when auth fails.
        ctx = RequestEventContext.get_or_create(request)
        ctx.route_name = route_name
        ctx.is_streaming = streaming

        set_operation_category(OperationCategory.AUTH)
        key_details = await set_api_key_uuid(
            request, route.project_uuid, route.project_name
        )
        set_trace_attributes(
            api_key_uuid=key_details.api_key_uuid,
            api_key_name=key_details.api_key_name,
            group_uuid=key_details.group_uuid,
            group_name=key_details.group_name,
            project_uuid=route.project_uuid,
            project_name=route.project_name,
            tags=list(get_current_request_tags()),
        )
        if announce:
            announce(route_name)

        # Not a member: the same answer as a wrong key, so a caller cannot
        # tell the route exists.
        if not self._group_service.check_key_uuid_for_route(
            route_key, UUID(key_details.api_key_uuid)
        ):
            raise InvalidApiKey('Incorrect API key provided.')

        ctx.project_uuid = route.project_uuid
        ctx.project_name = route.project_name
        limits = await self._resolve_limits(route, key_details, request_uuid)
        # Request limits first, before anything is processed or spent.
        await limits.check(ADMISSION)
        return route.for_request(limits.identity, limits)

    async def _resolve_limits(
        self, route: GatewayRoute, key_details: KeyDetails, request_uuid: str
    ) -> RequestLimits:
        """Return the limits of a request: its route's, its credential's and
        its project's, read as they are now.
        """
        project_limits = await load_project_limits(
            route.project_uuid, self._project_budget_limit_dao
        )
        return shared_limits.resolve(
            RequestIdentity(
                request_uuid=request_uuid,
                route_name=route.gateway_route_config.route_name,
                api_key_uuid=key_details.api_key_uuid,
                api_key_name=key_details.api_key_name,
                group_uuid=key_details.group_uuid,
                group_name=key_details.group_name,
                project_uuid=route.project_uuid,
                project_name=route.project_name,
            ),
            route.route_limits,
            key_details.limits,
            project_limits,
        )
