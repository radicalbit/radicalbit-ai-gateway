"""The 429 of a limit names the scope that blocked it (AG-1063)."""

import json
from unittest.mock import MagicMock

import pytest

from radicalbit_ai_gateway.models.event_payload import LimitScope
from radicalbit_ai_gateway.utils.exceptions import (
    LIMIT_SCOPE_HEADER,
    AudioDurationLimitExceeded,
    BudgetLimitExceededError,
    InputTokenLimitExceeded,
    OutputTokenLimitExceeded,
    RequestRateLimitExceeded,
    audio_duration_limit_exceeded_handler,
    budget_limiter_exception_handler,
    rate_limit_exceeded_handler,
    token_limiter_exception_handler,
)


def _request():
    request = MagicMock()
    request.state = MagicMock()
    return request


async def _answer(error):
    if isinstance(error, BudgetLimitExceededError):
        return budget_limiter_exception_handler(_request(), error)
    if isinstance(error, (InputTokenLimitExceeded, OutputTokenLimitExceeded)):
        return token_limiter_exception_handler(_request(), error)
    if isinstance(error, AudioDurationLimitExceeded):
        return await audio_duration_limit_exceeded_handler(_request(), error)
    return await rate_limit_exceeded_handler(_request(), error)


@pytest.mark.parametrize(
    ('error', 'scope', 'code'),
    [
        (
            InputTokenLimitExceeded('blocked', limit_scope=LimitScope.ROUTE),
            'route',
            'token_limit_rate_limited',
        ),
        (
            RequestRateLimitExceeded('blocked', limit_scope=LimitScope.CREDENTIAL),
            'credential',
            'request_rate_limited',
        ),
        (
            BudgetLimitExceededError('blocked', limit_scope=LimitScope.PROJECT),
            'project',
            'budget_limit_rate_limited',
        ),
        (
            AudioDurationLimitExceeded('blocked', limit_scope=LimitScope.ROUTE),
            'route',
            'audio_duration_rate_limited',
        ),
    ],
)
async def test_a_429_names_the_scope_that_blocked(error, scope, code):
    response = await _answer(error)

    assert response.status_code == 429
    assert response.headers[LIMIT_SCOPE_HEADER] == scope
    assert json.loads(response.body)['error']['code'] == code


async def test_a_429_without_a_scope_has_no_scope_header():
    response = await _answer(OutputTokenLimitExceeded('blocked'))

    assert response.status_code == 429
    assert LIMIT_SCOPE_HEADER not in response.headers
