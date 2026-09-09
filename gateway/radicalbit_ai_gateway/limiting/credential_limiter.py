from radicalbit_ai_gateway.events.events_processor import emit_event
from radicalbit_ai_gateway.limiter import (
    AlignedFixedWindowLimiter,
    FixedWindowLimiter,
    InMemoryStorage,
    RedisStorage,
    ScenarioType,
    WindowConfig,
)
from radicalbit_ai_gateway.limiter.window_config import WindowStats
from radicalbit_ai_gateway.metrics.define_metrics import (
    rate_limiting_counter,
    token_input_limiting_counter,
    token_output_limiting_counter,
)
from radicalbit_ai_gateway.models.credential_limiting import (
    CredentialLimitCategory,
    CredentialLimitOut,
)
from radicalbit_ai_gateway.models.event_payload import LimitEventPayload
from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.models.limiting import LimitingAlgorithmType
from radicalbit_ai_gateway.utils import BUDGET_MULTIPLIER
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import (
    BudgetLimitExceededError,
    InputTokenLimitExceeded,
    OutputTokenLimitExceeded,
    RequestRateLimitExceeded,
)
from radicalbit_ai_gateway.utils.token_encoding import count_tokens

app_config = get_app_config()

_CATEGORY_EVENT_TYPE = {
    CredentialLimitCategory.RATE: EventType.CREDENTIAL_RATE_LIMIT,
    CredentialLimitCategory.TOKEN_INPUT: EventType.CREDENTIAL_TOKEN_INPUT_LIMIT,
    CredentialLimitCategory.TOKEN_OUTPUT: EventType.CREDENTIAL_TOKEN_OUTPUT_LIMIT,
}


class _LimitEntry:
    __slots__ = ('limiter', 'window', 'limit_out')

    def __init__(
        self,
        limiter: FixedWindowLimiter | AlignedFixedWindowLimiter,
        window: WindowConfig,
        limit_out: CredentialLimitOut,
    ):
        self.limiter = limiter
        self.window = window
        self.limit_out = limit_out


class CredentialLimiter:
    """Runtime enforcement of the calling credential's own limits.

    Built fresh per request from the credential's configured limits
    (``KeyDetails.limits``) and published on a context var right after
    authentication. Unlike route-level limiters, it can't be stored on the
    ``GatewayRoute`` instance: that's a shared singleton reused by every
    credential that calls the route, while this must vary per credential.

    A credential can have several limits in the same category with
    different windows (e.g. two rate limits, or a daily and a monthly
    budget). Semantics are AND: every configured window for a category is
    checked on every request, and the request is blocked if any one of
    them is exceeded.
    """

    def __init__(
        self,
        credential_uuid: str,
        credential_name: str,
        limits: list[CredentialLimitOut],
    ):
        self.credential_uuid = credential_uuid
        self.credential_name = credential_name
        self._entries: dict[CredentialLimitCategory, list[_LimitEntry]] = {}
        if not limits:
            return

        if app_config.redis_config.redis_url:
            storage = RedisStorage(uri=app_config.redis_config.redis_url)
        else:
            storage = InMemoryStorage()
        for limit in limits:
            self._entries.setdefault(limit.category, []).append(
                self._build_entry(limit, storage)
            )

    def has_category(self, category: CredentialLimitCategory) -> bool:
        return category in self._entries

    def _build_entry(self, limit: CredentialLimitOut, storage) -> _LimitEntry:
        limiter_cls = (
            AlignedFixedWindowLimiter
            if limit.algorithm == LimitingAlgorithmType.ALIGNED_FIXED_WINDOW
            else FixedWindowLimiter
        )
        window_limit = (
            int(limit.value * BUDGET_MULTIPLIER)
            if limit.category == CredentialLimitCategory.BUDGET
            else int(limit.value)
        )
        window = WindowConfig.from_parts(
            limit=window_limit,
            window=limit.window_size,
            # Sentinel: the credential UUID takes the project_uuid slot for
            # key isolation, and '*' the route slot — a credential limit
            # applies across every route the credential calls, not one.
            project_uuid=self.credential_uuid,
            route_name='*',
            scenario_type=ScenarioType(limit.category.value),
        )
        return _LimitEntry(limiter=limiter_cls(storage), window=window, limit_out=limit)

    async def _first_exceeded(
        self, category: CredentialLimitCategory, cost: int
    ) -> tuple[_LimitEntry, WindowStats] | None:
        """Test only, no hit — the first window in *category* that *cost*
        would exceed, or None if all have room.
        """
        for entry in self._entries.get(category, []):
            if not await entry.limiter.test(entry.window, cost=cost):
                stats = await entry.limiter.get_window_stats(entry.window)
                return entry, stats
        return None

    async def _hit(self, category: CredentialLimitCategory, cost: int) -> None:
        for entry in self._entries.get(category, []):
            await entry.limiter.hit(entry.window, cost=cost)

    def _emit_block_event(
        self,
        category: CredentialLimitCategory,
        request_uuid: str,
        group_uuid: str,
        group_name: str,
        route_name: str,
        project_uuid: str,
        project_name: str,
    ) -> None:
        emit_event(
            LimitEventPayload(
                request_uuid=request_uuid,
                api_key_uuid=self.credential_uuid,
                api_key_name=self.credential_name,
                group_uuid=group_uuid,
                group_name=group_name,
                project_uuid=project_uuid,
                project_name=project_name,
                event_type=_CATEGORY_EVENT_TYPE[category],
                route_name=route_name,
                value=1.0,
            )
        )

    async def check_and_count_request(
        self,
        *,
        request_uuid: str,
        group_uuid: str,
        group_name: str,
        route_name: str,
        project_uuid: str = '',
        project_name: str = '',
    ) -> None:
        if not self.has_category(CredentialLimitCategory.RATE):
            return

        exceeded = await self._first_exceeded(CredentialLimitCategory.RATE, cost=1)
        if exceeded is not None:
            entry, stats = exceeded
            self._emit_block_event(
                CredentialLimitCategory.RATE,
                request_uuid,
                group_uuid,
                group_name,
                route_name,
                project_uuid,
                project_name,
            )
            rate_limiting_counter.add(1, {'route_name': route_name})
            raise RequestRateLimitExceeded(
                message=(
                    f'Credential rate limit exceeded: {entry.limit_out.value:g} '
                    f'requests per {entry.limit_out.window_size} on credential '
                    f'"{self.credential_name}". Please retry after '
                    f'{stats.remaining_time} seconds.'
                ),
                log_message=(
                    '[CREDENTIAL RATE LIMIT] '
                    f'[credential={self.credential_name}] '
                    f'[limit={entry.limit_out.value:g}] '
                    f'[window={entry.limit_out.window_size}] '
                    f'[reset_s={stats.remaining_time}] '
                    '[action=BLOCK]'
                ),
                route_name=route_name,
            )
        await self._hit(CredentialLimitCategory.RATE, cost=1)

    async def check_input_tokens(
        self,
        *,
        text: str,
        model_string: str,
        request_uuid: str,
        group_uuid: str,
        group_name: str,
        route_name: str,
        project_uuid: str = '',
        project_name: str = '',
    ) -> None:
        """Mirrors TokenLimiter.check_input's text + model_string signature
        (tokenized here) so callers don't need tokenization knowledge just
        to share a count with the route-level check.
        """
        if not self.has_category(CredentialLimitCategory.TOKEN_INPUT):
            return

        tokens = count_tokens(text, model_string)
        exceeded = await self._first_exceeded(
            CredentialLimitCategory.TOKEN_INPUT, cost=tokens
        )
        if exceeded is not None:
            entry, stats = exceeded
            self._emit_block_event(
                CredentialLimitCategory.TOKEN_INPUT,
                request_uuid,
                group_uuid,
                group_name,
                route_name,
                project_uuid,
                project_name,
            )
            token_input_limiting_counter.add(1, {'route_name': route_name})
            raise InputTokenLimitExceeded(
                message=(
                    f'Credential input token limit exceeded: {entry.limit_out.value:g} '
                    f'tokens per {entry.limit_out.window_size} on credential '
                    f'"{self.credential_name}". Please retry after '
                    f'{stats.remaining_time} seconds.'
                ),
                log_message=(
                    '[CREDENTIAL TOKEN LIMIT] '
                    f'[credential={self.credential_name}] [direction=INPUT] '
                    f'[attempted={tokens}] [limit={entry.limit_out.value:g}] '
                    f'[window={entry.limit_out.window_size}] '
                    f'[reset_s={stats.remaining_time}] [action=BLOCK]'
                ),
            )

    async def count_input_tokens(self, tokens: int) -> None:
        await self._hit(CredentialLimitCategory.TOKEN_INPUT, cost=tokens)

    async def check_output_tokens(
        self,
        *,
        request_uuid: str,
        group_uuid: str,
        group_name: str,
        route_name: str,
        project_uuid: str = '',
        project_name: str = '',
    ) -> None:
        """cost=1: the completion size isn't known yet, so this only tests
        that some room remains — same approximate pre-check as the
        route-level TokenLimiter.check_output.
        """
        if not self.has_category(CredentialLimitCategory.TOKEN_OUTPUT):
            return

        exceeded = await self._first_exceeded(
            CredentialLimitCategory.TOKEN_OUTPUT, cost=1
        )
        if exceeded is not None:
            entry, stats = exceeded
            self._emit_block_event(
                CredentialLimitCategory.TOKEN_OUTPUT,
                request_uuid,
                group_uuid,
                group_name,
                route_name,
                project_uuid,
                project_name,
            )
            token_output_limiting_counter.add(1, {'route_name': route_name})
            raise OutputTokenLimitExceeded(
                message=(
                    f'Credential output token limit exceeded: {entry.limit_out.value:g} '
                    f'tokens per {entry.limit_out.window_size} on credential '
                    f'"{self.credential_name}". Please retry after '
                    f'{stats.remaining_time} seconds.'
                ),
                log_message=(
                    '[CREDENTIAL TOKEN LIMIT] '
                    f'[credential={self.credential_name}] [direction=OUTPUT] '
                    f'[limit={entry.limit_out.value:g}] '
                    f'[window={entry.limit_out.window_size}] '
                    f'[reset_s={stats.remaining_time}] [action=BLOCK]'
                ),
            )

    async def count_output_tokens(self, tokens: int) -> None:
        await self._hit(CredentialLimitCategory.TOKEN_OUTPUT, cost=tokens)

    async def check_budget(self) -> None:
        """No event on block, matching route-level BudgetLimiter.check_budget
        — only rate/token blocks emit events today.
        """
        if not self.has_category(CredentialLimitCategory.BUDGET):
            return

        exceeded = await self._first_exceeded(CredentialLimitCategory.BUDGET, cost=1)
        if exceeded is not None:
            entry, stats = exceeded
            raise BudgetLimitExceededError(
                message=(
                    f'Credential budget limit exceeded: {entry.limit_out.value:g} '
                    f'per {entry.limit_out.window_size} on credential '
                    f'"{self.credential_name}". Please retry after '
                    f'{stats.remaining_time} seconds.'
                ),
                log_message=(
                    '[CREDENTIAL BUDGET LIMIT] '
                    f'[credential={self.credential_name}] '
                    f'[limit={entry.limit_out.value:g}] '
                    f'[window={entry.limit_out.window_size}] '
                    f'[reset_s={stats.remaining_time}] [action=BLOCK]'
                ),
            )

    async def count_budget_input(
        self, token_count: int, input_cost_per_token: float
    ) -> None:
        cost = int(token_count * input_cost_per_token * BUDGET_MULTIPLIER)
        await self._hit(CredentialLimitCategory.BUDGET, cost=cost)

    async def count_budget_output(
        self, token_count: int, output_cost_per_token: float
    ) -> None:
        cost = int(token_count * output_cost_per_token * BUDGET_MULTIPLIER)
        await self._hit(CredentialLimitCategory.BUDGET, cost=cost)

    async def count_budget_duration(
        self, seconds: float, cost_per_second: float
    ) -> None:
        cost = int(seconds * cost_per_second * BUDGET_MULTIPLIER)
        await self._hit(CredentialLimitCategory.BUDGET, cost=cost)
