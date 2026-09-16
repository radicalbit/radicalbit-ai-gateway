from uuid import UUID

from radicalbit_ai_gateway.db.dao.project_budget_limit_dao import ProjectBudgetLimitDAO
from radicalbit_ai_gateway.limiter import (
    AlignedFixedWindowLimiter,
    FixedWindowLimiter,
    InMemoryStorage,
    RedisStorage,
    ScenarioType,
    WindowConfig,
)
from radicalbit_ai_gateway.limiter.window_config import WindowStats
from radicalbit_ai_gateway.models.limiting import LimitingAlgorithmType
from radicalbit_ai_gateway.models.project_budget_limiting import ProjectBudgetLimitOut
from radicalbit_ai_gateway.utils import BUDGET_MULTIPLIER
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import BudgetLimitExceededError

app_config = get_app_config()


class _LimitEntry:
    __slots__ = ('limiter', 'window', 'limit_out')

    def __init__(
        self,
        limiter: FixedWindowLimiter | AlignedFixedWindowLimiter,
        window: WindowConfig,
        limit_out: ProjectBudgetLimitOut,
    ):
        self.limiter = limiter
        self.window = window
        self.limit_out = limit_out


class ProjectBudgetLimiter:
    """Runtime enforcement of a project's own budget limits.

    Built fresh per request from the project's configured budget limits
    (``ProjectBudgetLimit`` rows) and published on a context var right
    after authentication — like ``CredentialLimiter``, it can't live on
    the ``GatewayRoute`` singleton: project budget limits can be added or
    removed via the API at any time, independent of the route config, and
    the route singleton is only rebuilt when a project's config is
    (re-)served.

    ``ProjectBudgetLimit`` has no category column — a project can only
    carry budget limits — so this only covers the budget subset of what
    ``CredentialLimiter`` does.

    A project can have several budget limits with different windows.
    Semantics are AND: every configured window is checked on every
    request, and the request is blocked if any one of them is exceeded.
    """

    def __init__(
        self,
        project_uuid: str,
        project_name: str,
        limits: list[ProjectBudgetLimitOut],
    ):
        self.project_uuid = project_uuid
        self.project_name = project_name
        self._entries: list[_LimitEntry] = []

        if not limits:
            return

        if app_config.redis_config.redis_url:
            storage = RedisStorage(uri=app_config.redis_config.redis_url)
        else:
            storage = InMemoryStorage()
        for limit in limits:
            self._entries.append(self._build_entry(limit, storage))

    def _build_entry(self, limit: ProjectBudgetLimitOut, storage) -> _LimitEntry:
        limiter_cls = (
            AlignedFixedWindowLimiter
            if limit.algorithm == LimitingAlgorithmType.ALIGNED_FIXED_WINDOW
            else FixedWindowLimiter
        )
        window = WindowConfig.from_parts(
            limit=int(limit.value * BUDGET_MULTIPLIER),
            window=limit.window_size,
            # Sentinel: '*' takes the route slot — a project limit applies
            # across every route in the project, not one.
            project_uuid=self.project_uuid,
            route_name='*',
            scenario_type=ScenarioType.BUDGET,
        )
        return _LimitEntry(limiter=limiter_cls(storage), window=window, limit_out=limit)

    async def _first_exceeded(
        self, cost: int
    ) -> tuple[_LimitEntry, WindowStats] | None:
        """Test only, no hit — the first window that *cost* would exceed,
        or None if all have room.
        """
        for entry in self._entries:
            if not await entry.limiter.test(entry.window, cost=cost):
                stats = await entry.limiter.get_window_stats(entry.window)
                return entry, stats
        return None

    async def _hit(self, cost: int) -> None:
        for entry in self._entries:
            await entry.limiter.hit(entry.window, cost=cost)

    async def check_budget(self) -> None:
        if not self._entries:
            return

        exceeded = await self._first_exceeded(cost=1)
        if exceeded is not None:
            entry, stats = exceeded
            raise BudgetLimitExceededError(
                message=(
                    f'Project budget limit exceeded: {entry.limit_out.value:g} '
                    f'per {entry.limit_out.window_size} on project '
                    f'"{self.project_name}". Please retry after '
                    f'{stats.remaining_time} seconds.'
                ),
                log_message=(
                    '[PROJECT BUDGET LIMIT] '
                    f'[project={self.project_name}] '
                    f'[limit={entry.limit_out.value:g}] '
                    f'[window={entry.limit_out.window_size}] '
                    f'[reset_s={stats.remaining_time}] [action=BLOCK]'
                ),
            )

    async def count_input(self, token_count: int, input_cost_per_token: float) -> None:
        cost = int(token_count * input_cost_per_token * BUDGET_MULTIPLIER)
        await self._hit(cost)

    async def count_output(
        self, token_count: int, output_cost_per_token: float
    ) -> None:
        cost = int(token_count * output_cost_per_token * BUDGET_MULTIPLIER)
        await self._hit(cost)

    async def count_duration(self, seconds: float, cost_per_second: float) -> None:
        cost = int(seconds * cost_per_second * BUDGET_MULTIPLIER)
        await self._hit(cost)


def load_project_budget_limiter(
    project_uuid: str, project_name: str, dao: ProjectBudgetLimitDAO
) -> ProjectBudgetLimiter | None:
    """Build a ``ProjectBudgetLimiter`` from the project's current budget
    limits, or None if it has none configured (mirrors how a
    ``CredentialLimiter`` is only published when the credential has
    limits).
    """
    if not project_uuid:
        return None
    limits = dao.get_by_project_uuid(UUID(project_uuid))
    if not limits:
        return None
    return ProjectBudgetLimiter(
        project_uuid=project_uuid,
        project_name=project_name,
        limits=[ProjectBudgetLimitOut.from_project_budget_limit(row) for row in limits],
    )


async def clear_project_budget_limit_counter(
    *, project_uuid: str, algorithm: str, window_size: str
) -> None:
    """Key is derived from algorithm/window_size, not the limit's uuid."""
    if app_config.redis_config.redis_url:
        storage = RedisStorage(uri=app_config.redis_config.redis_url)
    else:
        storage = InMemoryStorage()
    limiter_cls = (
        AlignedFixedWindowLimiter
        if algorithm == LimitingAlgorithmType.ALIGNED_FIXED_WINDOW.value
        else FixedWindowLimiter
    )
    limiter = limiter_cls(storage)
    window = WindowConfig.from_parts(
        limit=0,
        window=window_size,
        project_uuid=project_uuid,
        route_name='*',
        scenario_type=ScenarioType.BUDGET,
    )
    await storage.delete(limiter._build_key(window))
