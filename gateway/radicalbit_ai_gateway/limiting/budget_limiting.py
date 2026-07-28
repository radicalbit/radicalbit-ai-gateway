import logging

from traceloop.sdk.decorators import task

from radicalbit_ai_gateway.limiter import (
    AlignedFixedWindowLimiter,
    FixedWindowLimiter,
    InMemoryStorage,
    RedisStorage,
    ScenarioType,
    WindowConfig,
)
from radicalbit_ai_gateway.models.limiting import Limiting, LimitingAlgorithmType
from radicalbit_ai_gateway.utils import BUDGET_MULTIPLIER
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import BudgetLimitExceededError

app_config = get_app_config()
logging_config_dict = app_config.log_config.model_dump()
logger = logging.getLogger(app_config.log_config.logger_name)


class BudgetLimiter:
    def __init__(
        self,
        route_name: str,
        config: Limiting | None = None,
    ):
        self.route_name = route_name
        self.config = config

        # Use Redis storage if Redis config are provided, otherwise fall back to MemoryStorage
        if app_config.redis_config.redis_url:
            self.storage = RedisStorage(uri=app_config.redis_config.redis_url)
        else:
            self.storage = InMemoryStorage()

        self.limiter = self._create_limiter(config) if config else None
        self.item = (
            self._create_item(config, route_name, ScenarioType.BUDGET)
            if config
            else None
        )

    def _create_limiter(
        self, config: Limiting
    ) -> FixedWindowLimiter | AlignedFixedWindowLimiter:
        """Create a limiter from a Limiting configuration."""
        if config.algorithm == LimitingAlgorithmType.ALIGNED_FIXED_WINDOW:
            return AlignedFixedWindowLimiter(self.storage)
        return FixedWindowLimiter(self.storage)

    @staticmethod
    def _create_item(
        config: Limiting, route_name: str, scenario_type: ScenarioType
    ) -> WindowConfig:
        """Create the item for the window to store max_budget inside the window_size"""
        if config.max_budget_in_units is None:
            raise ValueError('max_budget must be set for budget limiting')
        return WindowConfig.from_parts(
            limit=config.max_budget_in_units,
            window=config.window_size,
            route_name=route_name,
            scenario_type=scenario_type,
        )

    async def count_input(self, token_count: int, input_cost_per_token: float) -> None:
        cost = int(token_count * input_cost_per_token * BUDGET_MULTIPLIER)
        if not self.limiter or not self.item:
            return
        await self.limiter.hit(self.item, cost=cost)

    async def count_output(
        self, token_count: int, output_cost_per_token: float
    ) -> None:
        cost = int(token_count * output_cost_per_token * BUDGET_MULTIPLIER)
        if not self.limiter or not self.item:
            return
        await self.limiter.hit(self.item, cost=cost)

    @task(name='check_budget_limit')
    async def check_budget(self) -> None:
        """Check if budget counter is exceeded. Raise BudgetLimitExceededError if limit is exceeded."""
        if not self.limiter or not self.item or not self.config:
            logger.debug(
                '[BUDGET LIMIT] [route=%s] [kind=BUDGET] [configured=false] [action=SKIP]',
                self.route_name,
            )
            return

        attempted = 1
        allowed = await self.limiter.test(self.item, cost=attempted)
        if not allowed:
            state = await self.limiter.get_window_stats(self.item)

            log_message = (
                '[BUDGET LIMIT] '
                f'[route={self.route_name}] '
                '[kind=BUDGET] '
                f'[attempted={attempted}] '
                f'[limit={self.config.max_budget}] '
                f'[window={self.config.window_size}] '
                f'[remaining={state.remaining}] '
                f'[reset_s={state.remaining_time}] '
                f'[item={self.item}] '
                '[action=BLOCK]'
            )

            user_message = (
                f'Budget limit exceeded: {self.config.max_budget} per {self.config.window_size}.'
                f' Please retry after {state.remaining_time} seconds.'
            )

            raise BudgetLimitExceededError(
                user_message,
                log_message=log_message,
            )

        logger.debug(
            '[BUDGET LIMIT] [route=%s] [kind=BUDGET] '
            '[attempted=%s] [limit=%s] [window=%s] [action=ALLOW]',
            self.route_name,
            attempted,
            self.config.max_budget,
            self.config.window_size,
        )

    async def get_total_current_usage(self) -> float:
        if self.limiter is not None and self.item is not None:
            stats = await self.limiter.get_window_stats(self.item)
            return stats.remaining
        return 0
