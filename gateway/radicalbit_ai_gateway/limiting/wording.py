"""What a limit says when it blocks or lets a request through.

One entry per scope and category: the error the client gets, the line it is
logged with, the event type and the metric. They are read by clients,
operators and alert rules (``alerting/limit_event_names.py``): change none of
them by accident.
"""

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any

from radicalbit_ai_gateway.limiter import WindowStats
from radicalbit_ai_gateway.limiting.windows import Category, Window
from radicalbit_ai_gateway.metrics.define_metrics import (
    audio_duration_limiting_counter,
    rate_limiting_counter,
    token_input_limiting_counter,
    token_output_limiting_counter,
)
from radicalbit_ai_gateway.models.event_payload import LimitScope
from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.models.request_identity import RequestIdentity
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import (
    AppError,
    AudioDurationLimitExceeded,
    BudgetLimitExceededError,
    InputTokenLimitExceeded,
    OutputTokenLimitExceeded,
    RequestRateLimitExceeded,
)
from radicalbit_ai_gateway.utils.money import format_usd

logger = logging.getLogger(get_app_config().log_config.logger_name)

# The error of a block, from the window, the cost attempted, the window's
# state and the request.
ErrorBuilder = Callable[[Window, int, WindowStats, RequestIdentity], AppError]


@dataclass(frozen=True)
class Block:
    event_type: EventType
    metric: Any  # an OpenTelemetry counter, or None
    error: ErrorBuilder


def _retry(stats: WindowStats) -> str:
    return f' Please retry after {stats.remaining_time} seconds.'


def _route_requests(w, attempted, stats, identity) -> AppError:
    route = identity.route_name
    return RequestRateLimitExceeded(
        limit_scope=w.scope,
        message=(
            f'Request rate limit exceeded: {w.shown_value} requests per '
            f'{w.shown_window}.' + _retry(stats)
        ),
        log_message=(
            '[RATE LIMIT] '
            f'[route={route}] '
            '[kind=REQUEST] '
            f'[limit={w.shown_value}] '
            f'[window={w.shown_window}] '
            f'[remaining={stats.remaining}] '
            f'[reset_s={stats.remaining_time}] '
            '[action=BLOCK]'
        ),
        route_name=route,
    )


def _route_input_tokens(w, attempted, stats, identity) -> AppError:
    return InputTokenLimitExceeded(
        limit_scope=w.scope,
        message=(
            f'Input token limit exceeded: {w.shown_value} tokens per '
            f'{w.shown_window}.' + _retry(stats)
        ),
        log_message=(
            '[TOKEN LIMIT] '
            f'[route={identity.route_name}] '
            '[kind=TOKEN] [direction=INPUT] '
            f'[attempted={attempted}] '
            f'[limit={w.shown_value}] '
            f'[window={w.shown_window}] '
            f'[remaining={stats.remaining}] '
            f'[reset_s={stats.remaining_time}] '
            f'[item={w.config}] '
            '[allowed=False] '
            '[action=BLOCK]'
        ),
    )


def _route_output_tokens(w, attempted, stats, identity) -> AppError:
    return OutputTokenLimitExceeded(
        limit_scope=w.scope,
        message=(
            f'Output token limit exceeded: {w.shown_value} tokens per '
            f'{w.shown_window}.' + _retry(stats)
        ),
        log_message=(
            '[TOKEN LIMIT] '
            f'[route={identity.route_name}] '
            '[kind=TOKEN] [direction=OUTPUT] '
            f'[attempted={attempted}] '
            f'[limit={w.shown_value}] '
            f'[window={w.shown_window}] '
            f'[remaining={stats.remaining}] '
            f'[reset_s={stats.remaining_time}] '
            '[action=BLOCK]'
        ),
    )


def _route_cost(w, attempted, stats, identity) -> AppError:
    route = identity.route_name
    return BudgetLimitExceededError(
        f'Budget limit exceeded: {format_usd(w.shown_value)} per '
        f'{w.shown_window} on route "{route}".' + _retry(stats),
        limit_scope=w.scope,
        log_message=(
            '[BUDGET LIMIT] '
            f'[route={route}] '
            '[kind=BUDGET] '
            f'[attempted={attempted}] '
            f'[limit={w.shown_value}] '
            f'[window={w.shown_window}] '
            f'[remaining={stats.remaining}] '
            f'[reset_s={stats.remaining_time}] '
            f'[item={w.config}] '
            '[action=BLOCK]'
        ),
    )


def _route_audio_seconds(w, attempted, stats, identity) -> AppError:
    route = identity.route_name
    return AudioDurationLimitExceeded(
        limit_scope=w.scope,
        message=(
            f'Audio duration limit exceeded: {w.shown_value} '
            f'seconds per {w.shown_window}.' + _retry(stats)
        ),
        log_message=(
            '[DURATION LIMIT] '
            f'[route={route}] '
            '[kind=AUDIO_DURATION] '
            f'[attempted={attempted}] '
            f'[limit={w.shown_value}] '
            f'[window={w.shown_window}] '
            f'[remaining={stats.remaining}] '
            f'[reset_s={stats.remaining_time}] '
            '[action=BLOCK]'
        ),
        route_name=route,
    )


def _credential_requests(w, attempted, stats, identity) -> AppError:
    return RequestRateLimitExceeded(
        limit_scope=w.scope,
        message=(
            f'Credential rate limit exceeded: {w.shown_value:g} '
            f'requests per {w.shown_window} on credential '
            f'"{identity.api_key_name}". Please retry after '
            f'{stats.remaining_time} seconds.'
        ),
        log_message=(
            '[CREDENTIAL RATE LIMIT] '
            f'[credential={identity.api_key_name}] '
            f'[limit={w.shown_value:g}] '
            f'[window={w.shown_window}] '
            f'[reset_s={stats.remaining_time}] '
            '[action=BLOCK]'
        ),
        route_name=identity.route_name,
    )


def _credential_input_tokens(w, attempted, stats, identity) -> AppError:
    return InputTokenLimitExceeded(
        limit_scope=w.scope,
        message=(
            f'Credential input token limit exceeded: {w.shown_value:g} '
            f'tokens per {w.shown_window} on credential '
            f'"{identity.api_key_name}". Please retry after '
            f'{stats.remaining_time} seconds.'
        ),
        log_message=(
            '[CREDENTIAL TOKEN LIMIT] '
            f'[credential={identity.api_key_name}] [direction=INPUT] '
            f'[attempted={attempted}] [limit={w.shown_value:g}] '
            f'[window={w.shown_window}] '
            f'[reset_s={stats.remaining_time}] [action=BLOCK]'
        ),
    )


def _credential_output_tokens(w, attempted, stats, identity) -> AppError:
    return OutputTokenLimitExceeded(
        limit_scope=w.scope,
        message=(
            f'Credential output token limit exceeded: {w.shown_value:g} '
            f'tokens per {w.shown_window} on credential '
            f'"{identity.api_key_name}". Please retry after '
            f'{stats.remaining_time} seconds.'
        ),
        log_message=(
            '[CREDENTIAL TOKEN LIMIT] '
            f'[credential={identity.api_key_name}] [direction=OUTPUT] '
            f'[limit={w.shown_value:g}] '
            f'[window={w.shown_window}] '
            f'[reset_s={stats.remaining_time}] [action=BLOCK]'
        ),
    )


def _credential_cost(w, attempted, stats, identity) -> AppError:
    return BudgetLimitExceededError(
        limit_scope=w.scope,
        message=(
            f'Credential budget limit exceeded: {format_usd(w.shown_value)} '
            f'per {w.shown_window} on credential '
            f'"{identity.api_key_name}". Please retry after '
            f'{stats.remaining_time} seconds.'
        ),
        log_message=(
            '[CREDENTIAL BUDGET LIMIT] '
            f'[credential={identity.api_key_name}] '
            f'[limit={w.shown_value:g}] '
            f'[window={w.shown_window}] '
            f'[reset_s={stats.remaining_time}] [action=BLOCK]'
        ),
    )


def _project_cost(w, attempted, stats, identity) -> AppError:
    return BudgetLimitExceededError(
        limit_scope=w.scope,
        message=(
            f'Project budget limit exceeded: {format_usd(w.shown_value)} '
            f'per {w.shown_window} on project '
            f'"{identity.project_name}". Please retry after '
            f'{stats.remaining_time} seconds.'
        ),
        log_message=(
            '[PROJECT BUDGET LIMIT] '
            f'[project={identity.project_name}] '
            f'[limit={w.shown_value:g}] '
            f'[window={w.shown_window}] '
            f'[reset_s={stats.remaining_time}] [action=BLOCK]'
        ),
    )


BLOCKS: dict[tuple[LimitScope, Category], Block] = {
    (LimitScope.ROUTE, Category.REQUESTS): Block(
        EventType.RATE_LIMIT, rate_limiting_counter, _route_requests
    ),
    (LimitScope.ROUTE, Category.INPUT_TOKENS): Block(
        EventType.TOKEN_INPUT_LIMIT, token_input_limiting_counter, _route_input_tokens
    ),
    (LimitScope.ROUTE, Category.OUTPUT_TOKENS): Block(
        EventType.TOKEN_OUTPUT_LIMIT,
        token_output_limiting_counter,
        _route_output_tokens,
    ),
    (LimitScope.ROUTE, Category.COST): Block(EventType.BUDGET_LIMIT, None, _route_cost),
    (LimitScope.ROUTE, Category.AUDIO_SECONDS): Block(
        EventType.AUDIO_DURATION_LIMIT,
        audio_duration_limiting_counter,
        _route_audio_seconds,
    ),
    (LimitScope.CREDENTIAL, Category.REQUESTS): Block(
        EventType.CREDENTIAL_RATE_LIMIT, rate_limiting_counter, _credential_requests
    ),
    (LimitScope.CREDENTIAL, Category.INPUT_TOKENS): Block(
        EventType.CREDENTIAL_TOKEN_INPUT_LIMIT,
        token_input_limiting_counter,
        _credential_input_tokens,
    ),
    (LimitScope.CREDENTIAL, Category.OUTPUT_TOKENS): Block(
        EventType.CREDENTIAL_TOKEN_OUTPUT_LIMIT,
        token_output_limiting_counter,
        _credential_output_tokens,
    ),
    (LimitScope.CREDENTIAL, Category.COST): Block(
        EventType.CREDENTIAL_BUDGET_LIMIT, None, _credential_cost
    ),
    (LimitScope.PROJECT, Category.COST): Block(
        EventType.PROJECT_BUDGET_LIMIT, None, _project_cost
    ),
}


def log_allowed(window: Window, attempted: int, identity: RequestIdentity) -> None:
    """Log at debug level that a route limit let the request through.

    Credential and project limits log nothing when they allow.
    """
    if window.scope is not LimitScope.ROUTE:
        return
    route = identity.route_name
    category = window.category
    if category is Category.REQUESTS:
        logger.debug(
            '[RATE LIMIT] [route=%s] [kind=REQUEST] [action=ALLOW]',
            route,
            extra={'route': route, 'rate_kind': 'request', 'action': 'ALLOW'},
        )
    elif category in (Category.INPUT_TOKENS, Category.OUTPUT_TOKENS):
        direction = 'INPUT' if category is Category.INPUT_TOKENS else 'OUTPUT'
        logger.debug(
            '[TOKEN LIMIT] [route=%s] [kind=TOKEN] [direction=%s] '
            '[attempted=%s] [limit=%s] [window=%s] [action=ALLOW]',
            route,
            direction,
            attempted,
            window.shown_value,
            window.shown_window,
            extra={
                'route': route,
                'rate_kind': 'token',
                'direction': direction.lower(),
                'attempted': attempted,
                'limit': window.shown_value,
                'window': str(window.shown_window),
                'action': 'ALLOW',
                'allowed': True,
                'item': str(window.config),
            },
        )
    elif category is Category.COST:
        logger.debug(
            '[BUDGET LIMIT] [route=%s] [kind=BUDGET] '
            '[attempted=%s] [limit=%s] [window=%s] [action=ALLOW]',
            route,
            attempted,
            window.shown_value,
            window.shown_window,
        )
    else:
        logger.debug(
            '[DURATION LIMIT] [route=%s] [kind=AUDIO_DURATION] '
            '[attempted=%s] [limit=%s] [window=%s] [action=ALLOW]',
            route,
            attempted,
            window.shown_value,
            window.shown_window,
        )


def log_unknown_audio_duration(identity: RequestIdentity) -> None:
    logger.warning(
        '[DURATION LIMIT] [route=%s] [kind=AUDIO_DURATION] '
        '[action=SKIP] [reason=duration_not_determinable]',
        identity.route_name,
    )
