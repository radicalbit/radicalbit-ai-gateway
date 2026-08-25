import logging

from traceloop.sdk.decorators import task

from radicalbit_ai_gateway.events.events_processor import emit_event
from radicalbit_ai_gateway.events.notifications_processor import emit_notification
from radicalbit_ai_gateway.limiter import (
    AlignedFixedWindowLimiter,
    FixedWindowLimiter,
    InMemoryStorage,
    RedisStorage,
    ScenarioType,
    WindowConfig,
)
from radicalbit_ai_gateway.metrics.define_metrics import (
    token_input_limiting_counter,
    token_output_limiting_counter,
)
from radicalbit_ai_gateway.models.event_payload import LimitEventPayload
from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.models.limiting import Limiting, LimitingAlgorithmType
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import (
    InputTokenLimitExceeded,
    OutputTokenLimitExceeded,
)
from radicalbit_ai_gateway.utils.token_encoding import count_tokens

app_config = get_app_config()
logging_config_dict = app_config.log_config.model_dump()
logger = logging.getLogger(app_config.log_config.logger_name)


class TokenLimiter:
    def __init__(
        self,
        route_name: str,
        input_config: Limiting | None = None,
        output_config: Limiting | None = None,
        project_uuid: str = '',
    ):
        self.route_name = route_name
        self.input_config = input_config
        self.output_config = output_config
        # Key isolation only: route_name stays the bare route everywhere it is
        # reported (metrics, limit events, logs).
        self.project_uuid = project_uuid

        # Use Redis storage if Redis config are provided, otherwise fall back to MemoryStorage
        if app_config.redis_config.redis_url:
            self.storage = RedisStorage(uri=app_config.redis_config.redis_url)
        else:
            self.storage = InMemoryStorage()

        # Create limiters and items if configs are provided
        self.input_limiter = (
            self._create_limiter(input_config) if input_config else None
        )
        self.output_limiter = (
            self._create_limiter(output_config) if output_config else None
        )
        self.input_item = (
            self._create_item(
                input_config, route_name, ScenarioType.TOKEN_INPUT, project_uuid
            )
            if input_config
            else None
        )
        self.output_item = (
            self._create_item(
                output_config, route_name, ScenarioType.TOKEN_OUTPUT, project_uuid
            )
            if output_config
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
        config: Limiting,
        route_name: str,
        scenario_type: ScenarioType,
        project_uuid: str = '',
    ) -> WindowConfig:
        """Create the item for the window to store max_tokens inside the window_size"""
        if not config.max_tokens:
            raise ValueError('max_tokens must be set for token limiting')
        return WindowConfig.from_parts(
            limit=config.max_tokens,
            window=config.window_size,
            route_name=route_name,
            scenario_type=scenario_type,
            project_uuid=project_uuid,
        )

    @task(name='check_token_input_limit')
    async def check_input(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        text: str,
        model_string: str,
        project_uuid: str = '',
        project_name: str = '',
    ) -> None:
        """Check if input token counter is exceeded.
        Raise InputTokenLimitExceeded if limit is exceeded.
        """
        tokens = count_tokens(text, model_string)

        if not self.input_limiter or not self.input_item or not self.input_config:
            logger.debug(
                '[TOKEN LIMIT] [route=%s] [kind=TOKEN] [direction=INPUT] '
                '[configured=false] [action=SKIP]',
                self.route_name,
                extra={
                    'route': self.route_name,
                    'rate_kind': 'token',
                    'direction': 'input',
                    'configured': False,
                    'action': 'SKIP',
                },
            )
            return

        allowed = await self.input_limiter.test(self.input_item, cost=tokens)

        if not allowed:
            input_state = await self.input_limiter.get_window_stats(self.input_item)

            log_message = (
                '[TOKEN LIMIT] '
                f'[route={self.route_name}] '
                '[kind=TOKEN] [direction=INPUT] '
                f'[attempted={tokens}] '
                f'[limit={self.input_config.max_tokens}] '
                f'[window={self.input_config.window_size}] '
                f'[remaining={input_state.remaining}] '
                f'[reset_s={input_state.remaining_time}] '
                f'[item={self.input_item}] '
                '[allowed=False] '
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
                    event_type=EventType.TOKEN_INPUT_LIMIT,
                    route_name=self.route_name,
                    value=1.0,
                )
            )
            token_input_limiting_counter.add(1, {'route_name': self.route_name})

            user_message = (
                f'Input token limit exceeded: {self.input_config.max_tokens} tokens per {self.input_config.window_size}.'
                f' Please retry after {input_state.remaining_time} seconds.'
            )

            raise InputTokenLimitExceeded(
                message=user_message,
                log_message=log_message,
            )

        logger.debug(
            '[TOKEN LIMIT] [route=%s] [kind=TOKEN] [direction=INPUT] '
            '[attempted=%s] [limit=%s] [window=%s] [action=ALLOW]',
            self.route_name,
            tokens,
            getattr(self.input_config, 'max_tokens', None),
            getattr(self.input_config, 'window_size', ''),
            extra={
                'route': self.route_name,
                'rate_kind': 'token',
                'direction': 'input',
                'attempted': tokens,
                'limit': getattr(self.input_config, 'max_tokens', None),
                'window': str(getattr(self.input_config, 'window_size', '')),
                'action': 'ALLOW',
                'allowed': True,
                'item': str(self.input_item),
            },
        )

    async def count_input(self, prompt_tokens: int) -> None:
        """Consume token in input window"""
        if not self.input_limiter or not self.input_item or not self.input_config:
            return  # No input limiting configured

        await self.input_limiter.hit(self.input_item, cost=prompt_tokens)

        # Emit notification with current window state after deduction
        input_state = await self.input_limiter.get_window_stats(self.input_item)
        current_usage = self.input_config.max_tokens - input_state.remaining

        emit_notification(
            route_name=self.route_name,
            direction='input',
            window_size=self.input_item.window_seconds,
            max_tokens=self.input_config.max_tokens,
            current_usage=current_usage,
            reset_time=input_state.reset_time,
            window_id=input_state.window_id,
        )

    async def count_output(
        self,
        token_count: int,
    ) -> None:
        """Consume token in output window"""
        if not self.output_limiter or not self.output_item:
            return  # No output limiting configured
        await self.output_limiter.hit(self.output_item, cost=token_count)

        # Emit notification with current window state after deduction
        if self.output_config:
            output_state = await self.output_limiter.get_window_stats(self.output_item)
            current_usage = self.output_config.max_tokens - output_state.remaining
            emit_notification(
                route_name=self.route_name,
                direction='output',
                window_size=self.output_item.window_seconds,
                max_tokens=self.output_config.max_tokens,
                current_usage=current_usage,
                reset_time=output_state.reset_time,
                window_id=output_state.window_id,
            )

    @task(name='check_token_output_limit')
    async def check_output(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        project_uuid: str = '',
        project_name: str = '',
    ) -> None:
        """Check if output token counter is exceeded.
        Raise OutputTokenLimitExceeded if limit is exceeded.
        """

        if not self.output_limiter or not self.output_item or not self.output_config:
            logger.debug(
                '[TOKEN LIMIT] [route=%s] [kind=TOKEN] [direction=OUTPUT] '
                '[configured=false] [action=SKIP]',
                self.route_name,
                extra={
                    'route': self.route_name,
                    'rate_kind': 'token',
                    'direction': 'output',
                    'configured': False,
                    'action': 'SKIP',
                },
            )
            return

        attempted = 1
        allowed = await self.output_limiter.test(self.output_item, cost=attempted)

        if not allowed:
            output_state = await self.output_limiter.get_window_stats(self.output_item)

            log_message = (
                '[TOKEN LIMIT] '
                f'[route={self.route_name}] '
                '[kind=TOKEN] [direction=OUTPUT] '
                f'[attempted={attempted}] '
                f'[limit={self.output_config.max_tokens}] '
                f'[window={self.output_config.window_size}] '
                f'[remaining={output_state.remaining}] '
                f'[reset_s={output_state.remaining_time}] '
                '[action=BLOCK]'
            )
            emit_event(
                LimitEventPayload(
                    request_uuid=request_uuid,
                    event_type=EventType.TOKEN_OUTPUT_LIMIT,
                    value=1.0,
                    route_name=self.route_name,
                    api_key_uuid=api_key_uuid,
                    group_uuid=group_uuid,
                    api_key_name=api_key_name,
                    group_name=group_name,
                    project_uuid=project_uuid,
                    project_name=project_name,
                )
            )
            token_output_limiting_counter.add(1, {'route_name': self.route_name})

            user_message = (
                f'Output token limit exceeded: {self.output_config.max_tokens} tokens per {self.output_config.window_size}.'
                f' Please retry after {output_state.remaining_time} seconds.'
            )

            raise OutputTokenLimitExceeded(
                message=user_message,
                log_message=log_message,
            )

        logger.debug(
            '[TOKEN LIMIT] [route=%s] [kind=TOKEN] [direction=OUTPUT] '
            '[attempted=%s] [limit=%s] [window=%s] [action=ALLOW]',
            self.route_name,
            attempted,
            getattr(self.output_config, 'max_tokens', None),
            getattr(self.output_config, 'window_size', ''),
            extra={
                'route': self.route_name,
                'rate_kind': 'token',
                'direction': 'output',
                'attempted': attempted,
                'limit': getattr(self.output_config, 'max_tokens', None),
                'window': str(getattr(self.output_config, 'window_size', '')),
                'action': 'ALLOW',
                'allowed': True,
                'item': str(self.output_item),
            },
        )
