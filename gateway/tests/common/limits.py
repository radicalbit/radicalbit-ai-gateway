from uuid import uuid4

from tests.common.db_mock import API_KEY_UUID, GROUP_UUID, REQUEST_UUID

from radicalbit_ai_gateway.limiting.limits import RequestLimits, shared_limits
from radicalbit_ai_gateway.limiting.windows import Window
from radicalbit_ai_gateway.models.credential_limiting import CredentialLimitOut
from radicalbit_ai_gateway.models.limiting import LimitingAlgorithmType
from radicalbit_ai_gateway.models.project_budget_limiting import ProjectBudgetLimitOut
from radicalbit_ai_gateway.models.request_identity import RequestIdentity


def request_limits(
    route,
    credential_limits=(),
    project_limits=(),
    *,
    request_uuid: str = str(REQUEST_UUID),
    api_key_uuid: str = str(API_KEY_UUID),
    api_key_name: str = 'rb-key',
    group_uuid: str = str(GROUP_UUID),
    group_name: str = 'test-group',
) -> RequestLimits:
    """Return the limits of a request to ``route``, as an endpoint resolves
    them, for the caller the tests use unless told otherwise.
    """
    return shared_limits.resolve(
        RequestIdentity(
            request_uuid=request_uuid,
            route_name=route.gateway_route_config.route_name,
            api_key_uuid=api_key_uuid,
            api_key_name=api_key_name,
            group_uuid=group_uuid,
            group_name=group_name,
            project_uuid=route.project_uuid,
            project_name=route.project_name,
        ),
        route.route_limits,
        credential_limits,
        project_limits,
    )


def credential_limit(
    category: str, value: float, window_size: str = '1 minute'
) -> CredentialLimitOut:
    return CredentialLimitOut(
        uuid=uuid4(),
        category=category,
        algorithm=LimitingAlgorithmType.FIXED_WINDOW,
        window_size=window_size,
        value=value,
        created_at='2026-01-01 00:00:00',
        updated_at='2026-01-01 00:00:00',
    )


def project_limit(value: float, window_size: str = '1 minute') -> ProjectBudgetLimitOut:
    return ProjectBudgetLimitOut(
        uuid=uuid4(),
        algorithm=LimitingAlgorithmType.FIXED_WINDOW,
        window_size=window_size,
        value=value,
        created_at='2026-01-01 00:00:00',
        updated_at='2026-01-01 00:00:00',
    )


async def consumed(window: Window) -> int:
    """Return what the process's limit storage counts in ``window``."""
    storage = shared_limits.storage
    stats = await window.limiter(storage).get_window_stats(window.config)
    return stats.consumed
