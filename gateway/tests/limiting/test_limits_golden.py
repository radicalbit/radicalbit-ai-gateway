"""Golden values of the limits: what must not change when the code does.

Redis keys hold live counters, so a changed key silently resets every limit on
deploy. Errors, log lines and events are read by clients, operators and alert
rules. The expected values below are literals; only the drivers (the
functions that make the code under test produce them) may change.
"""

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from radicalbit_ai_gateway.limiter import InMemoryStorage
from radicalbit_ai_gateway.limiting.limits import (
    Demand,
    Limits,
    RouteLimits,
    Usage,
    shared_limits,
)
from radicalbit_ai_gateway.limiting.windows import credential_window, project_window
from radicalbit_ai_gateway.metrics import define_metrics
from radicalbit_ai_gateway.models.credential_limiting import CredentialLimitOut
from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.models.project_budget_limiting import ProjectBudgetLimitOut
from radicalbit_ai_gateway.models.request_identity import RequestIdentity
from radicalbit_ai_gateway.utils.exceptions import (
    AudioDurationLimitExceeded,
    BudgetLimitExceededError,
    InputTokenLimitExceeded,
    OutputTokenLimitExceeded,
    RequestRateLimitExceeded,
)

P = '2f1c6d4e-0000-4000-8000-0000000000aa'  # project
C = '7a3b9e10-0000-4000-8000-0000000000bb'  # credential
ROUTE = 'my-route'
NOW = 1767225630  # 2026-01-01 00:00:30 UTC: 30s into the aligned hour, 3570s left

IDENTITY = RequestIdentity(
    request_uuid='req-1',
    route_name=ROUTE,
    api_key_uuid=C,
    api_key_name='my-cred',
    group_uuid='grp-1',
    group_name='my-group',
    project_uuid=P,
    project_name='my-project',
)

FIXED = ('FIXED_WINDOW', '1 minute')
ALIGNED = ('ALIGNED_FIXED_WINDOW', '1 hour')

_EMIT_SITES = (
    'radicalbit_ai_gateway.limiting.limits.emit_event',
    'radicalbit_ai_gateway.limiting.limit_event.emit_event',
)

_METRICS = (
    'rate_limiting_counter',
    'token_input_limiting_counter',
    'token_output_limiting_counter',
    'audio_duration_limiting_counter',
)


@pytest.fixture
def events():
    emitted = []
    patches = [patch(site, side_effect=emitted.append) for site in _EMIT_SITES]
    for p in patches:
        p.start()
    yield emitted
    for p in patches:
        p.stop()


@pytest.fixture
def metrics():
    """Yield the limit metrics by name, each recording its calls."""
    mocks = {}
    patches = [patch.object(getattr(define_metrics, name), 'add') for name in _METRICS]
    for name, p in zip(_METRICS, patches, strict=True):
        mocks[name] = p.start()
    yield mocks
    for p in patches:
        p.stop()


def _credential_limit(category: str, value: float, window) -> CredentialLimitOut:
    algorithm, window_size = window
    return CredentialLimitOut(
        uuid='00000000-0000-4000-8000-000000000001',
        category=category,
        algorithm=algorithm,
        window_size=window_size,
        value=value,
        created_at='2026-01-01 00:00:00',
        updated_at='2026-01-01 00:00:00',
    )


def _project_limit(value: float, window) -> ProjectBudgetLimitOut:
    algorithm, window_size = window
    return ProjectBudgetLimitOut(
        uuid='00000000-0000-4000-8000-000000000002',
        algorithm=algorithm,
        window_size=window_size,
        value=value,
        created_at='2026-01-01 00:00:00',
        updated_at='2026-01-01 00:00:00',
    )


# ---------------------------------------------------------------------------
# Drivers: the only part of this file that follows the code's interface
# ---------------------------------------------------------------------------


_ROUTE_LIMIT = {
    'request_rate': ('rate_limiting', 'max_requests'),
    'token_input': ('token_limiting', 'input'),
    'token_output': ('token_limiting', 'output'),
    'budget': ('budget_limiting', 'max_budget'),
    'audio_duration': ('duration_limiting', 'max_duration_seconds'),
}


def _route_limits(category: str, window, maximum) -> RouteLimits:
    algorithm, window_size = window
    field, maximum_field = _ROUTE_LIMIT[category]
    limiting = {'algorithm': algorithm, 'window_size': window_size}
    if field == 'token_limiting':
        limiting = {maximum_field: {**limiting, 'max_token': maximum}}
    else:
        limiting[maximum_field] = maximum
    config = GatewayRouteConfig.model_validate(
        {'route_name': ROUTE, 'chat_models': ['m'], field: limiting}
    )
    return RouteLimits.from_config(config, P)


_ROUTE_MAXIMA = {
    'request_rate': 5,
    'token_input': 5,
    'token_output': 5,
    'budget': 1.5,
    'audio_duration': 90.6,
}


def route_key_and_maximum(category: str, window) -> tuple[str, int]:
    [w] = _route_limits(category, window, _ROUTE_MAXIMA[category]).windows
    return w.key, w.config.limit


def credential_key_and_maximum(category: str, value, window) -> tuple[str, int]:
    w = credential_window(C, category, *window, value)
    return w.key, w.config.limit


def project_key_and_maximum(value: float, window) -> tuple[str, int]:
    w = project_window(P, *window, value)
    return w.key, w.config.limit


async def cleared_credential_key(category: str, window) -> str:
    with patch.object(InMemoryStorage, 'delete', autospec=True) as delete:
        await shared_limits.clear(credential_window(C, category, *window))
    return delete.call_args.args[1]


async def cleared_project_key(window) -> str:
    with patch.object(InMemoryStorage, 'delete', autospec=True) as delete:
        await shared_limits.clear(project_window(P, *window))
    return delete.call_args.args[1]


_FILL_AND_DEMAND = {
    'request_rate': (None, Demand(request=True)),
    'token_input': (Usage(input_tokens=1), Demand(input='room')),
    'token_output': (Usage(output_tokens=1), Demand(output_room=True)),
    'budget': (Usage(costs=(500_000_000,)), Demand(cost_room=True)),
    'audio_duration': (None, Demand(audio_seconds=1.0)),
}


@contextmanager
def frozen_clock(now: int):
    """Stop the clock the limiter reads at ``now``, in epoch seconds.

    The limiter reads ``time.time`` and ``time.time_ns`` only. (freezegun
    would scan every loaded module on each start: a quarter of a second.)
    """
    with (
        patch('time.time', return_value=float(now)),
        patch('time.time_ns', return_value=now * 1_000_000_000),
    ):
        yield


async def block(scope: str, category: str) -> Exception:
    maximum = 0.5 if category == 'budget' else 1
    route, credential, project = RouteLimits(), [], []
    if scope == 'route':
        route = _route_limits(category, FIXED, maximum)
    elif scope == 'credential':
        credential = [_credential_limit(category, maximum, FIXED)]
    else:
        project = [_project_limit(maximum, FIXED)]
    request_limits = Limits(InMemoryStorage()).resolve(
        IDENTITY, route, credential, project
    )
    fill, demand = _FILL_AND_DEMAND[category]
    if fill is None:
        await request_limits.check(demand)
    else:
        await request_limits.count(fill)
    with pytest.raises(Exception) as error:
        await request_limits.check(demand)
    return error.value


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------

ROUTE_KEYS = {
    ('request_rate', FIXED): (f'limiter:{P}:my-route:request_rate:fixed:60', 5),
    ('request_rate', ALIGNED): (f'limiter:{P}:my-route:request_rate:aligned:3600', 5),
    ('token_input', FIXED): (f'limiter:{P}:my-route:token_input:fixed:60', 5),
    ('token_input', ALIGNED): (f'limiter:{P}:my-route:token_input:aligned:3600', 5),
    ('token_output', FIXED): (f'limiter:{P}:my-route:token_output:fixed:60', 5),
    ('token_output', ALIGNED): (
        f'limiter:{P}:my-route:token_output:aligned:3600',
        5,
    ),
    ('budget', FIXED): (f'limiter:{P}:my-route:budget:fixed:60', 1_500_000_000),
    ('budget', ALIGNED): (f'limiter:{P}:my-route:budget:aligned:3600', 1_500_000_000),
    ('audio_duration', FIXED): (f'limiter:{P}:my-route:audio_duration:fixed:60', 91),
    ('audio_duration', ALIGNED): (
        f'limiter:{P}:my-route:audio_duration:aligned:3600',
        91,
    ),
}

CREDENTIAL_KEYS = {
    ('request_rate', 7, FIXED): (f'limiter:{C}:*:request_rate:fixed:60', 7),
    ('request_rate', 7, ALIGNED): (f'limiter:{C}:*:request_rate:aligned:3600', 7),
    ('token_input', 70, FIXED): (f'limiter:{C}:*:token_input:fixed:60', 70),
    ('token_input', 70, ALIGNED): (f'limiter:{C}:*:token_input:aligned:3600', 70),
    ('token_output', 70, FIXED): (f'limiter:{C}:*:token_output:fixed:60', 70),
    ('token_output', 70, ALIGNED): (f'limiter:{C}:*:token_output:aligned:3600', 70),
    ('budget', 2.5, FIXED): (f'limiter:{C}:*:budget:fixed:60', 2_500_000_000),
    ('budget', 2.5, ALIGNED): (f'limiter:{C}:*:budget:aligned:3600', 2_500_000_000),
}

PROJECT_KEYS = {
    FIXED: (f'limiter:{P}:*:budget:fixed:60', 3_250_000_000),
    ALIGNED: (f'limiter:{P}:*:budget:aligned:3600', 3_250_000_000),
}


@pytest.mark.parametrize(('category', 'window'), list(ROUTE_KEYS))
def test_route_key(category, window):
    assert route_key_and_maximum(category, window) == ROUTE_KEYS[(category, window)]


@pytest.mark.parametrize(('category', 'value', 'window'), list(CREDENTIAL_KEYS))
def test_credential_key(category, value, window):
    assert (
        credential_key_and_maximum(category, value, window)
        == CREDENTIAL_KEYS[(category, value, window)]
    )


@pytest.mark.parametrize('window', list(PROJECT_KEYS))
def test_project_key(window):
    assert project_key_and_maximum(3.25, window) == PROJECT_KEYS[window]


@pytest.mark.asyncio
@pytest.mark.parametrize(('category', 'value', 'window'), list(CREDENTIAL_KEYS))
async def test_clearing_a_credential_limit_deletes_its_key(category, value, window):
    key, _ = CREDENTIAL_KEYS[(category, value, window)]
    assert await cleared_credential_key(category, window) == key


@pytest.mark.asyncio
@pytest.mark.parametrize('window', list(PROJECT_KEYS))
async def test_clearing_a_project_limit_deletes_its_key(window):
    key, _ = PROJECT_KEYS[window]
    assert await cleared_project_key(window) == key


# ---------------------------------------------------------------------------
# Errors, log lines, events and metrics of a block
# ---------------------------------------------------------------------------

_ITEM = (
    "WindowConfig(limit={limit}, window_seconds=60, project_uuid='" + P + "', "
    "route_name='my-route', scenario_type=<ScenarioType.{name}: '{value}'>)"
)

BLOCKS = {
    ('route', 'request_rate'): (
        RequestRateLimitExceeded,
        (
            'Request rate limit exceeded: 1 requests per 1 minute. '
            'Please retry after 60 seconds.'
        ),
        (
            '[RATE LIMIT] [route=my-route] [kind=REQUEST] [limit=1] '
            '[window=1 minute] [remaining=0] [reset_s=60] [action=BLOCK]'
        ),
        EventType.RATE_LIMIT,
        'rate_limiting_counter',
    ),
    ('route', 'token_input'): (
        InputTokenLimitExceeded,
        (
            'Input token limit exceeded: 1 tokens per 1 minute. '
            'Please retry after 60 seconds.'
        ),
        '[TOKEN LIMIT] [route=my-route] [kind=TOKEN] [direction=INPUT] '
        '[attempted=1] [limit=1] [window=1 minute] [remaining=0] [reset_s=60] '
        '[item='
        + _ITEM.format(limit=1, name='TOKEN_INPUT', value='token_input')
        + '] [allowed=False] [action=BLOCK]',
        EventType.TOKEN_INPUT_LIMIT,
        'token_input_limiting_counter',
    ),
    ('route', 'token_output'): (
        OutputTokenLimitExceeded,
        (
            'Output token limit exceeded: 1 tokens per 1 minute. '
            'Please retry after 60 seconds.'
        ),
        (
            '[TOKEN LIMIT] [route=my-route] [kind=TOKEN] [direction=OUTPUT] '
            '[attempted=1] [limit=1] [window=1 minute] [remaining=0] [reset_s=60] '
            '[action=BLOCK]'
        ),
        EventType.TOKEN_OUTPUT_LIMIT,
        'token_output_limiting_counter',
    ),
    ('route', 'budget'): (
        BudgetLimitExceededError,
        (
            'Budget limit exceeded: $0.50 per 1 minute on route "my-route". '
            'Please retry after 60 seconds.'
        ),
        '[BUDGET LIMIT] [route=my-route] [kind=BUDGET] [attempted=1] '
        '[limit=0.5] [window=1 minute] [remaining=0] [reset_s=60] '
        '[item='
        + _ITEM.format(limit=500000000, name='BUDGET', value='budget')
        + '] [action=BLOCK]',
        EventType.BUDGET_LIMIT,
        None,
    ),
    ('route', 'audio_duration'): (
        AudioDurationLimitExceeded,
        (
            'Audio duration limit exceeded: 1.0 seconds per 1 minute. '
            'Please retry after 60 seconds.'
        ),
        (
            '[DURATION LIMIT] [route=my-route] [kind=AUDIO_DURATION] [attempted=1] '
            '[limit=1.0] [window=1 minute] [remaining=0] [reset_s=60] [action=BLOCK]'
        ),
        EventType.AUDIO_DURATION_LIMIT,
        'audio_duration_limiting_counter',
    ),
    ('credential', 'request_rate'): (
        RequestRateLimitExceeded,
        (
            'Credential rate limit exceeded: 1 requests per 1 minute on credential '
            '"my-cred". Please retry after 60 seconds.'
        ),
        (
            '[CREDENTIAL RATE LIMIT] [credential=my-cred] [limit=1] '
            '[window=1 minute] [reset_s=60] [action=BLOCK]'
        ),
        EventType.CREDENTIAL_RATE_LIMIT,
        'rate_limiting_counter',
    ),
    ('credential', 'token_input'): (
        InputTokenLimitExceeded,
        (
            'Credential input token limit exceeded: 1 tokens per 1 minute on '
            'credential "my-cred". Please retry after 60 seconds.'
        ),
        (
            '[CREDENTIAL TOKEN LIMIT] [credential=my-cred] [direction=INPUT] '
            '[attempted=1] [limit=1] [window=1 minute] [reset_s=60] [action=BLOCK]'
        ),
        EventType.CREDENTIAL_TOKEN_INPUT_LIMIT,
        'token_input_limiting_counter',
    ),
    ('credential', 'token_output'): (
        OutputTokenLimitExceeded,
        (
            'Credential output token limit exceeded: 1 tokens per 1 minute on '
            'credential "my-cred". Please retry after 60 seconds.'
        ),
        (
            '[CREDENTIAL TOKEN LIMIT] [credential=my-cred] [direction=OUTPUT] '
            '[limit=1] [window=1 minute] [reset_s=60] [action=BLOCK]'
        ),
        EventType.CREDENTIAL_TOKEN_OUTPUT_LIMIT,
        'token_output_limiting_counter',
    ),
    ('credential', 'budget'): (
        BudgetLimitExceededError,
        (
            'Credential budget limit exceeded: $0.50 per 1 minute on credential '
            '"my-cred". Please retry after 60 seconds.'
        ),
        (
            '[CREDENTIAL BUDGET LIMIT] [credential=my-cred] [limit=0.5] '
            '[window=1 minute] [reset_s=60] [action=BLOCK]'
        ),
        EventType.CREDENTIAL_BUDGET_LIMIT,
        None,
    ),
    ('project', 'budget'): (
        BudgetLimitExceededError,
        (
            'Project budget limit exceeded: $0.50 per 1 minute on project '
            '"my-project". Please retry after 60 seconds.'
        ),
        (
            '[PROJECT BUDGET LIMIT] [project=my-project] [limit=0.5] '
            '[window=1 minute] [reset_s=60] [action=BLOCK]'
        ),
        EventType.PROJECT_BUDGET_LIMIT,
        None,
    ),
}


@pytest.mark.asyncio
@pytest.mark.parametrize(('scope', 'category'), list(BLOCKS))
async def test_block(scope, category, events, metrics):
    error_type, message, log_message, event_type, metric = BLOCKS[(scope, category)]
    with frozen_clock(NOW):
        error = await block(scope, category)

    assert type(error) is error_type
    assert error.status_code == 429
    assert error.client_message == message
    assert error.log_message == log_message
    # Who blocked: the 429 names it in the X-RB-AIGATEWAY-LIMIT-SCOPE header.
    assert error.limit_scope == scope
    if error_type in (RequestRateLimitExceeded, AudioDurationLimitExceeded):
        assert error.param == ROUTE

    [event] = [e for e in events if e.event_type != EventType.LIMIT_THRESHOLD]
    maximum = 0.5 if category == 'budget' else 1
    assert event.model_dump(exclude={'window_id'}) == {
        'request_uuid': 'req-1',
        'event_type': event_type,
        'route_name': ROUTE,
        'value': 1.0,
        'api_key_uuid': C,
        'api_key_name': 'my-cred',
        'group_uuid': 'grp-1',
        'group_name': 'my-group',
        'cost': 0.0,
        'project_uuid': P,
        'project_name': 'my-project',
        'limit_scope': scope,
        'category': category,
        'window_seconds': 60,
        'maximum': maximum,
        'consumption': maximum,
        'reset_time': 1767225690,
        'threshold_percentage': None,
    }
    assert event.window_id is not None

    for name, mock in metrics.items():
        if name == metric:
            mock.assert_called_once_with(1, {'route_name': ROUTE})
        else:
            mock.assert_not_called()
