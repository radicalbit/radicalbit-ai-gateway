"""The scope of a request in tests that call an endpoint's pipeline directly."""

from tests.common.limits import request_limits
from tests.common.request_identity import with_identity

from radicalbit_ai_gateway.gateway_route.scope import RequestScope


def scope_of(route, limits=None, **caller) -> RequestScope:
    """Return the scope of a request to ``route`` by ``caller`` (loose
    identity fields; the tests' caller for those not given).
    """
    identity = with_identity(
        route_name=route.gateway_route_config.route_name,
        project_uuid=route.project_uuid,
        project_name=route.project_name,
        **caller,
    )['identity']
    return route.for_request(identity, limits or request_limits(route))
