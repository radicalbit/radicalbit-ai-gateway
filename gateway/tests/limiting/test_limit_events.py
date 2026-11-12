"""What limits emit: a block names the limit and how far it had gone, and a
threshold event fires on the hit that crosses a global percentage.

Each test drives a request's limits through check/count on in-memory
storage and captures the event instead of sending it.
"""

from collections.abc import Iterator
import time
from unittest.mock import patch
from uuid import uuid4

import pytest

from tests.common.db_mock import API_KEY_UUID, GROUP_UUID, REQUEST_UUID

from radicalbit_ai_gateway.limiter import InMemoryStorage
from radicalbit_ai_gateway.limiting.limits import (
    Demand,
    InputEstimate,
    Limits,
    RequestLimits,
    RouteLimits,
    Usage,
)
from radicalbit_ai_gateway.models.credential_limiting import (
    CredentialLimitCategory,
    CredentialLimitOut,
)
from radicalbit_ai_gateway.models.event_payload import LimitEventPayload, LimitScope
from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.models.limiting import LimitingAlgorithmType
from radicalbit_ai_gateway.models.project_budget_limiting import ProjectBudgetLimitOut
from radicalbit_ai_gateway.models.request_identity import RequestIdentity
from radicalbit_ai_gateway.utils import BUDGET_MULTIPLIER
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import (
    AudioDurationLimitExceeded,
    BudgetLimitExceededError,
    InputTokenLimitExceeded,
    OutputTokenLimitExceeded,
    RequestRateLimitExceeded,
)

_PROJECT_UUID = '2f1c6d4e-0000-4000-8000-0000000000aa'
_CREDENTIAL_UUID = '7b9e1d2c-0000-4000-8000-0000000000cc'
_ROUTE = 'my-route'
_MODEL = 'openai/gpt-4o'

_IDENTITY = RequestIdentity(
    request_uuid=str(REQUEST_UUID),
    route_name=_ROUTE,
    api_key_uuid=str(API_KEY_UUID),
    api_key_name='caller-key',
    group_uuid=str(GROUP_UUID),
    group_name='team-a',
    project_uuid=_PROJECT_UUID,
    project_name='my-project',
)

# A credential's own limits are reached by requests it authenticates.
_CREDENTIAL_IDENTITY = RequestIdentity(
    request_uuid=str(REQUEST_UUID),
    route_name=_ROUTE,
    api_key_uuid=_CREDENTIAL_UUID,
    api_key_name='my-cred',
    group_uuid=str(GROUP_UUID),
    group_name='team-a',
    project_uuid=_PROJECT_UUID,
    project_name='my-project',
)

_EMITTERS = [
    'radicalbit_ai_gateway.limiting.limit_event.emit_event',
    'radicalbit_ai_gateway.limiting.limits.emit_event',
]


@pytest.fixture
def events() -> Iterator[list[LimitEventPayload]]:
    captured: list[LimitEventPayload] = []
    patches = [patch(target, new=captured.append) for target in _EMITTERS]
    for p in patches:
        p.start()
    yield captured
    for p in patches:
        p.stop()


def _blocks(events: list[LimitEventPayload]) -> list[LimitEventPayload]:
    return [e for e in events if e.event_type != EventType.LIMIT_THRESHOLD]


def _thresholds(events: list[LimitEventPayload]) -> list[LimitEventPayload]:
    return [e for e in events if e.event_type == EventType.LIMIT_THRESHOLD]


def _only(events: list[LimitEventPayload]) -> LimitEventPayload:
    """Return the one block event, ignoring the threshold events of the counts."""
    (event,) = _blocks(events)
    return event


def _assert_live_window(event: LimitEventPayload, window_seconds: int) -> None:
    now = int(time.time())
    assert event.window_seconds == window_seconds
    assert now < event.reset_time <= now + window_seconds
    assert event.window_id
    assert event.threshold_percentage is None


def _cost(units: float) -> Usage:
    """Return a usage costing ``units`` dollars."""
    return Usage(costs=(int(units * BUDGET_MULTIPLIER),))


def _route(**limits) -> RouteLimits:
    config = GatewayRouteConfig.model_validate(
        {'route_name': _ROUTE, 'chat_models': ['m'], **limits}
    )
    return RouteLimits.from_config(config, _PROJECT_UUID)


def _credential_limit(category: CredentialLimitCategory, value: float, window='1 hour'):
    return CredentialLimitOut(
        uuid=uuid4(),
        category=category,
        algorithm=LimitingAlgorithmType.FIXED_WINDOW,
        window_size=window,
        value=value,
        created_at='2026-01-01 00:00:00',
        updated_at='2026-01-01 00:00:00',
    )


def _project_limit(value: float) -> ProjectBudgetLimitOut:
    return ProjectBudgetLimitOut(
        uuid=uuid4(),
        algorithm=LimitingAlgorithmType.FIXED_WINDOW,
        window_size='1 day',
        value=value,
        created_at='2026-01-01 00:00:00',
        updated_at='2026-01-01 00:00:00',
    )


@pytest.fixture
def limits() -> Limits:
    return Limits(InMemoryStorage())


@pytest.fixture
def route_limits(limits):
    def resolve(**route) -> RequestLimits:
        return limits.resolve(_IDENTITY, _route(**route))

    return resolve


@pytest.fixture
def credential_limits(limits):
    def resolve(*credential: CredentialLimitOut) -> RequestLimits:
        return limits.resolve(_CREDENTIAL_IDENTITY, RouteLimits(), credential)

    return resolve


@pytest.fixture
def project_limits(limits):
    def resolve(value: float) -> RequestLimits:
        return limits.resolve(_IDENTITY, RouteLimits(), (), [_project_limit(value)])

    return resolve


RATE = {'rate_limiting': {'max_requests': 2, 'window_size': '1 minute'}}


class TestRouteLimits:
    @pytest.mark.asyncio
    async def test_rate_limit(self, events, route_limits):
        scope = route_limits(**RATE)
        await scope.check(Demand(request=True))
        await scope.check(Demand(request=True))
        with pytest.raises(RequestRateLimitExceeded):
            await scope.check(Demand(request=True))

        event = _only(events)
        assert event.event_type == EventType.RATE_LIMIT
        assert event.limit_scope == LimitScope.ROUTE
        assert event.category == 'request_rate'
        assert event.maximum == 2
        assert event.consumption == 2
        assert event.route_name == _ROUTE
        assert event.project_uuid == _PROJECT_UUID
        _assert_live_window(event, 60)

    @pytest.mark.asyncio
    async def test_token_input_limit(self, events, route_limits):
        scope = route_limits(
            token_limiting={'input': {'max_tokens': 100, 'window_size': '1 minute'}}
        )
        await scope.count(Usage(input_tokens=80))
        with (
            patch(
                'radicalbit_ai_gateway.limiting.limits.count_tokens', return_value=30
            ),
            pytest.raises(InputTokenLimitExceeded),
        ):
            await scope.check(Demand(input=InputEstimate('hello', _MODEL)))

        event = _only(events)
        assert event.event_type == EventType.TOKEN_INPUT_LIMIT
        assert event.limit_scope == LimitScope.ROUTE
        assert event.category == 'token_input'
        assert event.maximum == 100
        assert event.consumption == 80
        _assert_live_window(event, 60)

    @pytest.mark.asyncio
    async def test_token_output_limit(self, events, route_limits):
        scope = route_limits(
            token_limiting={'output': {'max_tokens': 50, 'window_size': '1 hour'}}
        )
        await scope.count(Usage(output_tokens=60))
        with pytest.raises(OutputTokenLimitExceeded):
            await scope.check(Demand(output_room=True))

        event = _only(events)
        assert event.event_type == EventType.TOKEN_OUTPUT_LIMIT
        assert event.limit_scope == LimitScope.ROUTE
        assert event.category == 'token_output'
        assert event.maximum == 50
        assert event.consumption == 60, 'an overshoot is reported, not clamped'
        _assert_live_window(event, 3600)

    @pytest.mark.asyncio
    async def test_audio_duration_limit(self, events, route_limits):
        scope = route_limits(
            duration_limiting={'max_duration_seconds': 10, 'window_size': '1 minute'}
        )
        await scope.check(Demand(audio_seconds=8.0))
        with pytest.raises(AudioDurationLimitExceeded):
            await scope.check(Demand(audio_seconds=5.0))

        event = _only(events)
        assert event.event_type == EventType.AUDIO_DURATION_LIMIT
        assert event.limit_scope == LimitScope.ROUTE
        assert event.category == 'audio_duration'
        assert event.maximum == 10
        assert event.consumption == 8
        _assert_live_window(event, 60)

    @pytest.mark.asyncio
    async def test_budget_limit(self, events, route_limits):
        scope = route_limits(
            budget_limiting={'max_budget': 1.0, 'window_size': '1 minute'}
        )
        await scope.count(_cost(1.5))
        with pytest.raises(BudgetLimitExceededError):
            await scope.check(Demand(cost_room=True))

        event = _only(events)
        assert event.event_type == EventType.BUDGET_LIMIT
        assert event.limit_scope == LimitScope.ROUTE
        assert event.category == 'budget'
        assert event.maximum == pytest.approx(1.0), 'in currency, not internal units'
        assert event.consumption == pytest.approx(1.5)
        assert event.route_name == _ROUTE
        assert event.api_key_uuid == str(API_KEY_UUID)
        _assert_live_window(event, 60)

    @pytest.mark.asyncio
    async def test_a_budget_within_limit_emits_nothing(self, events, route_limits):
        scope = route_limits(
            budget_limiting={'max_budget': 1.0, 'window_size': '1 minute'}
        )
        await scope.count(_cost(0.01))
        await scope.check(Demand(cost_room=True))

        assert events == []


class TestCredentialLimits:
    """Credential windows are keyed on route '*'. The event still names the
    credential by uuid and the route that was actually called.
    """

    def _assert_credential_identity(self, event: LimitEventPayload) -> None:
        assert event.limit_scope == LimitScope.CREDENTIAL
        assert event.api_key_uuid == _CREDENTIAL_UUID
        assert event.api_key_name == 'my-cred'
        assert event.route_name == _ROUTE
        assert event.project_uuid == _PROJECT_UUID

    @pytest.mark.asyncio
    async def test_rate_limit(self, events, credential_limits):
        scope = credential_limits(_credential_limit(CredentialLimitCategory.RATE, 1))
        await scope.check(Demand(request=True))
        with pytest.raises(RequestRateLimitExceeded):
            await scope.check(Demand(request=True))

        event = _only(events)
        assert event.event_type == EventType.CREDENTIAL_RATE_LIMIT
        assert event.category == 'request_rate'
        assert event.maximum == 1
        assert event.consumption == 1
        self._assert_credential_identity(event)
        _assert_live_window(event, 3600)

    @pytest.mark.asyncio
    async def test_token_input_limit(self, events, credential_limits):
        scope = credential_limits(
            _credential_limit(CredentialLimitCategory.TOKEN_INPUT, 100)
        )
        await scope.count(Usage(input_tokens=90))
        with (
            patch(
                'radicalbit_ai_gateway.limiting.limits.count_tokens', return_value=20
            ),
            pytest.raises(InputTokenLimitExceeded),
        ):
            await scope.check(Demand(input=InputEstimate('hello', _MODEL)))

        event = _only(events)
        assert event.event_type == EventType.CREDENTIAL_TOKEN_INPUT_LIMIT
        assert event.category == 'token_input'
        assert event.maximum == 100
        assert event.consumption == 90
        self._assert_credential_identity(event)
        _assert_live_window(event, 3600)

    @pytest.mark.asyncio
    async def test_token_output_limit(self, events, credential_limits):
        scope = credential_limits(
            _credential_limit(CredentialLimitCategory.TOKEN_OUTPUT, 10)
        )
        await scope.count(Usage(output_tokens=10))
        with pytest.raises(OutputTokenLimitExceeded):
            await scope.check(Demand(output_room=True))

        event = _only(events)
        assert event.event_type == EventType.CREDENTIAL_TOKEN_OUTPUT_LIMIT
        assert event.category == 'token_output'
        assert event.maximum == 10
        assert event.consumption == 10
        self._assert_credential_identity(event)
        _assert_live_window(event, 3600)

    @pytest.mark.asyncio
    async def test_budget_limit(self, events, credential_limits):
        scope = credential_limits(
            _credential_limit(CredentialLimitCategory.BUDGET, 2.0)
        )
        await scope.count(_cost(2.5))
        with pytest.raises(BudgetLimitExceededError):
            await scope.check(Demand(cost_room=True))

        event = _only(events)
        assert event.event_type == EventType.CREDENTIAL_BUDGET_LIMIT
        assert event.category == 'budget'
        assert event.maximum == pytest.approx(2.0)
        assert event.consumption == pytest.approx(2.5)
        self._assert_credential_identity(event)
        _assert_live_window(event, 3600)


class TestProjectLimits:
    @pytest.mark.asyncio
    async def test_budget_limit(self, events, project_limits):
        scope = project_limits(5.0)
        await scope.count(_cost(6.0))
        with pytest.raises(BudgetLimitExceededError):
            await scope.check(Demand(cost_room=True))

        event = _only(events)
        assert event.event_type == EventType.PROJECT_BUDGET_LIMIT
        assert event.limit_scope == LimitScope.PROJECT
        assert event.category == 'budget'
        assert event.maximum == pytest.approx(5.0)
        assert event.consumption == pytest.approx(6.0)
        assert event.project_uuid == _PROJECT_UUID
        assert event.project_name == 'my-project'
        assert event.route_name == _ROUTE, 'the route called, not the "*" key'
        assert event.api_key_uuid == str(API_KEY_UUID)
        _assert_live_window(event, 86400)


class TestWhatReachesClickHouse:
    """The limit fields land in the event row's ATTRIBUTES map as strings."""

    @pytest.mark.asyncio
    async def test_the_limit_fields_are_written_as_plain_values(self, route_limits):
        scope = route_limits(
            budget_limiting={'max_budget': 1.0, 'window_size': '1 minute'}
        )
        with patch(
            'radicalbit_ai_gateway.events.events_processor._events_buffer'
        ) as buf:
            await scope.count(_cost(1.5))
            with pytest.raises(BudgetLimitExceededError):
                await scope.check(Demand(cost_room=True))

        attributes = buf.add.call_args.args[0]['ATTRIBUTES']
        assert attributes['limit_scope'] == 'route'
        assert attributes['category'] == 'budget'
        assert attributes['window_seconds'] == '60'
        assert attributes['maximum'] == '1.0'
        assert float(attributes['consumption']) == pytest.approx(1.5)
        assert int(attributes['reset_time']) > 0
        assert attributes['window_id']
        assert 'threshold_percentage' not in attributes


@pytest.fixture
def percentages():
    """Set the global threshold percentages for one test."""
    alert_config = get_app_config().alert_config
    original = alert_config.alert_threshold_percentages

    def set_to(values: list[int]) -> None:
        alert_config.alert_threshold_percentages = values

    set_to([75, 98])
    yield set_to
    alert_config.alert_threshold_percentages = original


RATE_OF_4 = {'rate_limiting': {'max_requests': 4, 'window_size': '1 minute'}}
INPUT_OF_100 = {
    'token_limiting': {'input': {'max_tokens': 100, 'window_size': '1 minute'}}
}


class TestThresholdEvents:
    @pytest.mark.asyncio
    async def test_a_threshold_fires_on_the_crossing_hit_only(
        self, events, percentages, route_limits
    ):
        scope = route_limits(**RATE_OF_4)

        fired_after_each_request = []
        for _ in range(4):
            await scope.check(Demand(request=True))
            fired_after_each_request.append(
                [e.threshold_percentage for e in _thresholds(events)]
            )
            events.clear()

        assert fired_after_each_request == [[], [], [75], [98]]

    @pytest.mark.asyncio
    async def test_a_threshold_event_carries_the_limit_and_the_request(
        self, events, percentages, route_limits
    ):
        scope = route_limits(**RATE_OF_4)
        for _ in range(3):
            await scope.check(Demand(request=True))

        (event,) = _thresholds(events)
        assert event.event_type == EventType.LIMIT_THRESHOLD
        assert event.threshold_percentage == 75
        assert event.limit_scope == LimitScope.ROUTE
        assert event.category == 'request_rate'
        assert event.maximum == 4
        assert event.consumption == 3
        assert event.request_uuid == str(REQUEST_UUID)
        assert event.api_key_uuid == str(API_KEY_UUID)
        assert event.group_name == 'team-a'
        assert event.route_name == _ROUTE
        assert event.project_uuid == _PROJECT_UUID
        assert event.project_name == 'my-project'
        now = int(time.time())
        assert event.window_seconds == 60
        assert now < event.reset_time <= now + 60
        assert event.window_id

    @pytest.mark.asyncio
    async def test_one_hit_crossing_both_percentages_emits_both(
        self, events, percentages, route_limits
    ):
        await route_limits(**INPUT_OF_100).count(Usage(input_tokens=99))

        assert sorted(e.threshold_percentage for e in _thresholds(events)) == [75, 98]

    @pytest.mark.asyncio
    async def test_a_crossed_threshold_does_not_fire_again_in_the_window(
        self, events, percentages, route_limits
    ):
        scope = route_limits(**INPUT_OF_100)
        await scope.count(Usage(input_tokens=80))
        events.clear()

        await scope.count(Usage(input_tokens=10))

        assert _thresholds(events) == []

    @pytest.mark.asyncio
    async def test_a_zero_cost_hit_crosses_nothing(
        self, events, percentages, route_limits
    ):
        scope = route_limits(
            token_limiting={'output': {'max_tokens': 100, 'window_size': '1 minute'}}
        )
        await scope.count(Usage(output_tokens=75))
        events.clear()

        await scope.count(Usage(output_tokens=0))

        assert _thresholds(events) == []

    @pytest.mark.asyncio
    async def test_the_percentages_come_from_the_alert_config(
        self, events, percentages, route_limits
    ):
        percentages([50])
        scope = route_limits(**RATE_OF_4)

        for _ in range(4):
            await scope.check(Demand(request=True))

        assert [e.threshold_percentage for e in _thresholds(events)] == [50]

    @pytest.mark.asyncio
    async def test_route_token_output(self, events, percentages, route_limits):
        scope = route_limits(
            token_limiting={'output': {'max_tokens': 100, 'window_size': '1 hour'}}
        )

        await scope.count(Usage(output_tokens=80))

        (event,) = _thresholds(events)
        assert event.category == 'token_output'
        assert event.consumption == 80
        assert event.window_seconds == 3600

    @pytest.mark.asyncio
    async def test_route_audio_duration(self, events, percentages, route_limits):
        scope = route_limits(
            duration_limiting={'max_duration_seconds': 10, 'window_size': '1 minute'}
        )

        await scope.check(Demand(audio_seconds=8.0))

        (event,) = _thresholds(events)
        assert event.category == 'audio_duration'
        assert event.threshold_percentage == 75
        assert event.consumption == 8
        assert event.api_key_uuid == str(API_KEY_UUID)

    @pytest.mark.asyncio
    async def test_route_budget_in_currency(self, events, percentages, route_limits):
        scope = route_limits(
            budget_limiting={'max_budget': 1.0, 'window_size': '1 minute'}
        )

        await scope.count(_cost(0.8))
        await scope.count(_cost(0.2))

        crossed = _thresholds(events)
        assert [e.threshold_percentage for e in crossed] == [75, 98]
        assert crossed[0].category == 'budget'
        assert crossed[0].maximum == pytest.approx(1.0)
        assert crossed[0].consumption == pytest.approx(0.8)
        assert crossed[1].consumption == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_credential_limits_emit_with_the_credential_scope(
        self, events, percentages, credential_limits
    ):
        scope = credential_limits(
            _credential_limit(CredentialLimitCategory.TOKEN_INPUT, 100)
        )

        await scope.count(Usage(input_tokens=80))

        (event,) = _thresholds(events)
        assert event.limit_scope == LimitScope.CREDENTIAL
        assert event.category == 'token_input'
        assert event.api_key_uuid == _CREDENTIAL_UUID
        assert event.route_name == _ROUTE, 'the route called, not the "*" key'

    @pytest.mark.asyncio
    async def test_every_window_of_a_credential_category_emits(
        self, events, percentages, credential_limits
    ):
        scope = credential_limits(
            _credential_limit(CredentialLimitCategory.TOKEN_OUTPUT, 100),
            _credential_limit(CredentialLimitCategory.TOKEN_OUTPUT, 100, '1 day'),
        )

        await scope.count(Usage(output_tokens=80))

        assert sorted(e.window_seconds for e in _thresholds(events)) == [3600, 86400]

    @pytest.mark.asyncio
    async def test_credential_rate_and_budget(
        self, events, percentages, credential_limits
    ):
        scope = credential_limits(
            _credential_limit(CredentialLimitCategory.RATE, 4),
            _credential_limit(CredentialLimitCategory.BUDGET, 1.0),
        )

        for _ in range(3):
            await scope.check(Demand(request=True))
        await scope.count(_cost(0.5))
        await scope.count(_cost(0.3))

        by_category = {e.category: e for e in _thresholds(events)}
        assert by_category['request_rate'].consumption == 3
        assert by_category['request_rate'].api_key_uuid == _CREDENTIAL_UUID
        assert by_category['budget'].consumption == pytest.approx(0.8)
        assert by_category['budget'].maximum == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_project_budget_emits_with_the_project_scope(
        self, events, percentages, project_limits
    ):
        scope = project_limits(1.0)

        await scope.count(_cost(0.5))
        await scope.count(_cost(0.3))

        (event,) = _thresholds(events)
        assert event.limit_scope == LimitScope.PROJECT
        assert event.threshold_percentage == 75
        assert event.consumption == pytest.approx(0.8)
        assert event.project_uuid == _PROJECT_UUID
        assert event.route_name == _ROUTE
