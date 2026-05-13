import logging

from traceloop.sdk.decorators import task

from radicalbit_ai_gateway.events.events_processor import emit_event
from radicalbit_ai_gateway.limiter import (
    AlignedFixedWindowLimiter,
    FixedWindowLimiter,
    InMemoryStorage,
    RedisStorage,
    ScenarioType,
    WindowConfig,
)
from radicalbit_ai_gateway.metrics.define_metrics import rate_limiting_counter
from radicalbit_ai_gateway.models.event_payload import LimitEventPayload
from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.models.limiting import LimitingAlgorithmType, RateLimiting
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import RequestRateLimitExceeded

app_config = get_app_config()
logging_config_dict = app_config.log_config.model_dump()
logger = logging.getLogger(app_config.log_config.logger_name)


class RequestRateLimiter:
    """Rate limiter for request counting using limits library."""

    def __init__(
        self, route_name: str, rate_limiting_config: RateLimiting | None = None
    ):
        self.route_name = route_name
        self.rate_limiting_config = rate_limiting_config

        # Use Redis storage if available, else MemoryStorage
        if app_config.redis_config.redis_url:
            self.storage = RedisStorage(uri=app_config.redis_config.redis_url)
        else:
            self.storage = InMemoryStorage()

        # Create rate limiter and item if config provided
        self.limiter = self._create_limiter() if rate_limiting_config else None
        self.item = (
            self._create_item(rate_limiting_config, route_name)
            if rate_limiting_config
            else None
        )

    def _create_limiter(self) -> FixedWindowLimiter | AlignedFixedWindowLimiter:
        if (
            self.rate_limiting_config.algorithm
            == LimitingAlgorithmType.ALIGNED_FIXED_WINDOW
        ):
            return AlignedFixedWindowLimiter(self.storage)
        return FixedWindowLimiter(self.storage)

    @staticmethod
    def _create_item(config: RateLimiting, route_name: str) -> WindowConfig:
        if not config.max_requests:
            raise ValueError('max_requests must be set for rate limiting')
        return WindowConfig.from_parts(
            limit=config.max_requests,
            window=config.window_size,
            route_name=route_name,
            scenario_type=ScenarioType.REQUEST_RATE,
        )

    async def _check_request(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        project_uuid: str = '',
        project_name: str = '',
    ) -> None:
        """Check if request limit is exceeded. Raises RequestRateLimitExceeded if limit exceeded."""
        if not self.limiter or not self.item or not self.rate_limiting_config:
            logger.debug(
                '[RATE LIMIT] [route=%s] [kind=REQUEST] '
                '[configured=false] [action=SKIP]',
                self.route_name,
                extra={
                    'route': self.route_name,
                    'rate_kind': 'request',
                    'configured': False,
                    'action': 'SKIP',
                },
            )
            return

        allowed = await self.limiter.test(self.item, cost=1)

        if not allowed:
            state = await self.limiter.get_window_stats(self.item)

            log_message = (
                '[RATE LIMIT] '
                f'[route={self.route_name}] '
                '[kind=REQUEST] '
                f'[limit={self.rate_limiting_config.max_requests}] '
                f'[window={self.rate_limiting_config.window_size}] '
                f'[remaining={state.remaining}] '
                f'[reset_s={state.remaining_time}] '
                '[action=BLOCK]'
            )
            emit_event(
                LimitEventPayload(
                    request_uuid=request_uuid,
                    api_key_uuid=api_key_uuid,
                    group_uuid=group_uuid,
                    api_key_name=api_key_name,
                    group_name=group_name,
                    project_uuid=project_uuid,
                    project_name=project_name,
                    event_type=EventType.RATE_LIMIT,
                    route_name=self.route_name,
                    value=1.0,
                )
            )
            rate_limiting_counter.add(1, {'route_name': self.route_name})

            user_message = (
                f'Request rate limit exceeded: {self.rate_limiting_config.max_requests} requests per {self.rate_limiting_config.window_size}.'
                f' Please retry after {state.remaining_time} seconds.'
            )

            raise RequestRateLimitExceeded(
                message=user_message,
                log_message=log_message,
                route_name=self.route_name,
            )

        logger.debug(
            '[RATE LIMIT] [route=%s] [kind=REQUEST] [action=ALLOW]',
            self.route_name,
            extra={
                'route': self.route_name,
                'rate_kind': 'request',
                'action': 'ALLOW',
            },
        )

    @task(name='check_request_rate')
    async def check_and_count_request(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        project_uuid: str = '',
        project_name: str = '',
    ) -> None:
        """Check if request limit is exceeded and count it if allowed.

        Raises RequestRateLimitExceeded if limit exceeded.
        If limit is not exceeded, consumes one request from the rate limit window.
        """

        # First check if we're allowed
        await self._check_request(
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            group_uuid=group_uuid,
            api_key_name=api_key_name,
            group_name=group_name,
            project_uuid=project_uuid,
            project_name=project_name,
        )

        # If check passed (no exception), count the request
        await self._count_request()

    async def _count_request(self) -> None:
        """Consume a request in the rate limit window."""
        if not self.limiter or not self.item:
            return
        await self.limiter.hit(self.item, cost=1)
