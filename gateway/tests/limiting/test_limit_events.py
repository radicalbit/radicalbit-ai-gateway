"""What limits emit: a block names the limit and how far it had gone, and a
threshold event fires on the hit that crosses a global percentage.

Each test drives a real limiter through check/count on in-memory storage and
captures the event instead of sending it.
"""

from collections.abc import Iterator
import time
from unittest.mock import patch
from uuid import uuid4

import pytest

from tests.common.audio import make_wav_bytes
from tests.common.db_mock import API_KEY_UUID, GROUP_UUID, REQUEST_UUID

from radicalbit_ai_gateway.limiting.budget_limiting import BudgetLimiter
from radicalbit_ai_gateway.limiting.credential_limiter import CredentialLimiter
from radicalbit_ai_gateway.limiting.duration_limiter import DurationLimiter
from radicalbit_ai_gateway.limiting.project_budget_limiter import ProjectBudgetLimiter
from radicalbit_ai_gateway.limiting.rate_limiter import RequestRateLimiter
from radicalbit_ai_gateway.limiting.token_limiter import TokenLimiter
from radicalbit_ai_gateway.models.credential_limiting import (
    CredentialLimitCategory,
    CredentialLimitOut,
)
from radicalbit_ai_gateway.models.event_payload import LimitEventPayload, LimitScope
from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.models.limiting import (
    AudioDurationLimiting,
    Limiting,
    LimitingAlgorithmType,
    RateLimiting,
)
from radicalbit_ai_gateway.models.project_budget_limiting import ProjectBudgetLimitOut
from radicalbit_ai_gateway.models.request_identity import RequestIdentity
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

_ROUTE_CALL_ARGS = {
    'request_uuid': str(REQUEST_UUID),
    'api_key_uuid': str(API_KEY_UUID),
    'group_uuid': str(GROUP_UUID),
    'api_key_name': 'caller-key',
    'group_name': 'team-a',
    'project_uuid': _PROJECT_UUID,
    'project_name': 'my-project',
}
_CREDENTIAL_CALL_ARGS = {
    'request_uuid': str(REQUEST_UUID),
    'group_uuid': str(GROUP_UUID),
    'group_name': 'team-a',
    'route_name': _ROUTE,
    'project_uuid': _PROJECT_UUID,
    'project_name': 'my-project',
}
_PROJECT_CALL_ARGS = {
    'request_uuid': str(REQUEST_UUID),
    'api_key_uuid': str(API_KEY_UUID),
    'api_key_name': 'caller-key',
    'group_uuid': str(GROUP_UUID),
    'group_name': 'team-a',
    'route_name': _ROUTE,
}

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
    'radicalbit_ai_gateway.limiting.rate_limiter.emit_event',
    'radicalbit_ai_gateway.limiting.token_limiter.emit_event',
    'radicalbit_ai_gateway.limiting.duration_limiter.emit_event',
    'radicalbit_ai_gateway.limiting.budget_limiting.emit_event',
    'radicalbit_ai_gateway.limiting.credential_limiter.emit_event',
    'radicalbit_ai_gateway.limiting.project_budget_limiter.emit_event',
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


def _credential_limit(category: CredentialLimitCategory, value: float):
    return CredentialLimitOut(
        uuid=uuid4(),
        category=category,
        algorithm=LimitingAlgorithmType.FIXED_WINDOW,
        window_size='1 hour',
        value=value,
        created_at='2026-01-01 00:00:00',
        updated_at='2026-01-01 00:00:00',
    )


def _credential_limiter(category: CredentialLimitCategory, value: float):
    return CredentialLimiter(
        credential_uuid=_CREDENTIAL_UUID,
        credential_name='my-cred',
        limits=[_credential_limit(category, value)],
    )


class TestRouteLimits:
    @pytest.mark.asyncio
    async def test_rate_limit(self, events):
        limiter = RequestRateLimiter(
            project_uuid=_PROJECT_UUID,
            route_name=_ROUTE,
            rate_limiting_config=RateLimiting(max_requests=2, window_size='1 minute'),
        )
        await limiter.check_and_count_request(**_ROUTE_CALL_ARGS)
        await limiter.check_and_count_request(**_ROUTE_CALL_ARGS)
        with pytest.raises(RequestRateLimitExceeded):
            await limiter.check_and_count_request(**_ROUTE_CALL_ARGS)

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
    async def test_token_input_limit(self, events):
        limiter = TokenLimiter(
            project_uuid=_PROJECT_UUID,
            route_name=_ROUTE,
            input_config=Limiting(max_tokens=100, window_size='1 minute'),
        )
        await limiter.count_input(prompt_tokens=80, identity=_IDENTITY)
        with (
            patch(
                'radicalbit_ai_gateway.limiting.token_limiter.count_tokens',
                return_value=30,
            ),
            pytest.raises(InputTokenLimitExceeded),
        ):
            await limiter.check_input(
                text='hello', model_string=_MODEL, **_ROUTE_CALL_ARGS
            )

        event = _only(events)
        assert event.event_type == EventType.TOKEN_INPUT_LIMIT
        assert event.limit_scope == LimitScope.ROUTE
        assert event.category == 'token_input'
        assert event.maximum == 100
        assert event.consumption == 80
        _assert_live_window(event, 60)

    @pytest.mark.asyncio
    async def test_token_output_limit(self, events):
        limiter = TokenLimiter(
            project_uuid=_PROJECT_UUID,
            route_name=_ROUTE,
            output_config=Limiting(max_tokens=50, window_size='1 hour'),
        )
        await limiter.count_output(token_count=60, identity=_IDENTITY)
        with pytest.raises(OutputTokenLimitExceeded):
            await limiter.check_output(**_ROUTE_CALL_ARGS)

        event = _only(events)
        assert event.event_type == EventType.TOKEN_OUTPUT_LIMIT
        assert event.limit_scope == LimitScope.ROUTE
        assert event.category == 'token_output'
        assert event.maximum == 50
        assert event.consumption == 60, 'an overshoot is reported, not clamped'
        _assert_live_window(event, 3600)

    @pytest.mark.asyncio
    async def test_audio_duration_limit(self, events):
        limiter = DurationLimiter(
            project_uuid=_PROJECT_UUID,
            route_name=_ROUTE,
            config=AudioDurationLimiting(
                max_duration_seconds=10, window_size='1 minute'
            ),
        )
        await limiter.check_and_count_duration(
            audio_bytes=make_wav_bytes(8.0), **_ROUTE_CALL_ARGS
        )
        with pytest.raises(AudioDurationLimitExceeded):
            await limiter.check_and_count_duration(
                audio_bytes=make_wav_bytes(5.0), **_ROUTE_CALL_ARGS
            )

        event = _only(events)
        assert event.event_type == EventType.AUDIO_DURATION_LIMIT
        assert event.limit_scope == LimitScope.ROUTE
        assert event.category == 'audio_duration'
        assert event.maximum == 10
        assert event.consumption == 8
        _assert_live_window(event, 60)

    @pytest.mark.asyncio
    async def test_budget_limit(self, events):
        limiter = BudgetLimiter(
            project_uuid=_PROJECT_UUID,
            route_name=_ROUTE,
            config=Limiting(max_budget=1.0, window_size='1 minute'),
        )
        await limiter.count_input(
            token_count=1500, input_cost_per_token=0.001, identity=_IDENTITY
        )
        with pytest.raises(BudgetLimitExceededError):
            await limiter.check_budget(**_ROUTE_CALL_ARGS)

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
    async def test_a_budget_within_limit_emits_nothing(self, events):
        limiter = BudgetLimiter(
            project_uuid=_PROJECT_UUID,
            route_name=_ROUTE,
            config=Limiting(max_budget=1.0, window_size='1 minute'),
        )
        await limiter.count_input(
            token_count=10, input_cost_per_token=0.001, identity=_IDENTITY
        )
        await limiter.check_budget(**_ROUTE_CALL_ARGS)

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
    async def test_rate_limit(self, events):
        limiter = _credential_limiter(CredentialLimitCategory.RATE, 1)
        await limiter.check_and_count_request(**_CREDENTIAL_CALL_ARGS)
        with pytest.raises(RequestRateLimitExceeded):
            await limiter.check_and_count_request(**_CREDENTIAL_CALL_ARGS)

        event = _only(events)
        assert event.event_type == EventType.CREDENTIAL_RATE_LIMIT
        assert event.category == 'request_rate'
        assert event.maximum == 1
        assert event.consumption == 1
        self._assert_credential_identity(event)
        _assert_live_window(event, 3600)

    @pytest.mark.asyncio
    async def test_token_input_limit(self, events):
        limiter = _credential_limiter(CredentialLimitCategory.TOKEN_INPUT, 100)
        await limiter.count_input_tokens(90, identity=_CREDENTIAL_IDENTITY)
        with (
            patch(
                'radicalbit_ai_gateway.limiting.credential_limiter.count_tokens',
                return_value=20,
            ),
            pytest.raises(InputTokenLimitExceeded),
        ):
            await limiter.check_input_tokens(
                text='hello', model_string=_MODEL, **_CREDENTIAL_CALL_ARGS
            )

        event = _only(events)
        assert event.event_type == EventType.CREDENTIAL_TOKEN_INPUT_LIMIT
        assert event.category == 'token_input'
        assert event.maximum == 100
        assert event.consumption == 90
        self._assert_credential_identity(event)
        _assert_live_window(event, 3600)

    @pytest.mark.asyncio
    async def test_token_output_limit(self, events):
        limiter = _credential_limiter(CredentialLimitCategory.TOKEN_OUTPUT, 10)
        await limiter.count_output_tokens(10, identity=_CREDENTIAL_IDENTITY)
        with pytest.raises(OutputTokenLimitExceeded):
            await limiter.check_output_tokens(**_CREDENTIAL_CALL_ARGS)

        event = _only(events)
        assert event.event_type == EventType.CREDENTIAL_TOKEN_OUTPUT_LIMIT
        assert event.category == 'token_output'
        assert event.maximum == 10
        assert event.consumption == 10
        self._assert_credential_identity(event)
        _assert_live_window(event, 3600)

    @pytest.mark.asyncio
    async def test_budget_limit(self, events):
        limiter = _credential_limiter(CredentialLimitCategory.BUDGET, 2.0)
        await limiter.count_budget_input(
            token_count=2500,
            input_cost_per_token=0.001,
            identity=_CREDENTIAL_IDENTITY,
        )
        with pytest.raises(BudgetLimitExceededError):
            await limiter.check_budget(**_CREDENTIAL_CALL_ARGS)

        event = _only(events)
        assert event.event_type == EventType.CREDENTIAL_BUDGET_LIMIT
        assert event.category == 'budget'
        assert event.maximum == pytest.approx(2.0)
        assert event.consumption == pytest.approx(2.5)
        self._assert_credential_identity(event)
        _assert_live_window(event, 3600)


class TestProjectLimits:
    @pytest.mark.asyncio
    async def test_budget_limit(self, events):
        limiter = ProjectBudgetLimiter(
            project_uuid=_PROJECT_UUID,
            project_name='my-project',
            limits=[
                ProjectBudgetLimitOut(
                    uuid=uuid4(),
                    algorithm=LimitingAlgorithmType.FIXED_WINDOW,
                    window_size='1 day',
                    value=5.0,
                    created_at='2026-01-01 00:00:00',
                    updated_at='2026-01-01 00:00:00',
                )
            ],
        )
        await limiter.count_output(
            token_count=6000, output_cost_per_token=0.001, identity=_IDENTITY
        )
        with pytest.raises(BudgetLimitExceededError):
            await limiter.check_budget(**_PROJECT_CALL_ARGS)

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
    async def test_the_limit_fields_are_written_as_plain_values(self):
        limiter = BudgetLimiter(
            project_uuid=_PROJECT_UUID,
            route_name=_ROUTE,
            config=Limiting(max_budget=1.0, window_size='1 minute'),
        )
        with patch(
            'radicalbit_ai_gateway.events.events_processor._events_buffer'
        ) as buf:
            await limiter.count_input(
                token_count=1500, input_cost_per_token=0.001, identity=_IDENTITY
            )
            with pytest.raises(BudgetLimitExceededError):
                await limiter.check_budget(**_ROUTE_CALL_ARGS)

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


def _rate_limiter(max_requests: int) -> RequestRateLimiter:
    return RequestRateLimiter(
        project_uuid=_PROJECT_UUID,
        route_name=_ROUTE,
        rate_limiting_config=RateLimiting(
            max_requests=max_requests, window_size='1 minute'
        ),
    )


class TestThresholdEvents:
    @pytest.mark.asyncio
    async def test_a_threshold_fires_on_the_crossing_hit_only(
        self, events, percentages
    ):
        limiter = _rate_limiter(max_requests=4)

        fired_after_each_request = []
        for _ in range(4):
            await limiter.check_and_count_request(**_ROUTE_CALL_ARGS)
            fired_after_each_request.append(
                [e.threshold_percentage for e in _thresholds(events)]
            )
            events.clear()

        assert fired_after_each_request == [[], [], [75], [98]]

    @pytest.mark.asyncio
    async def test_a_threshold_event_carries_the_limit_and_the_request(
        self, events, percentages
    ):
        limiter = _rate_limiter(max_requests=4)
        for _ in range(3):
            await limiter.check_and_count_request(**_ROUTE_CALL_ARGS)

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
        self, events, percentages
    ):
        limiter = TokenLimiter(
            project_uuid=_PROJECT_UUID,
            route_name=_ROUTE,
            input_config=Limiting(max_tokens=100, window_size='1 minute'),
        )

        await limiter.count_input(prompt_tokens=99, identity=_IDENTITY)

        assert sorted(e.threshold_percentage for e in _thresholds(events)) == [75, 98]

    @pytest.mark.asyncio
    async def test_a_crossed_threshold_does_not_fire_again_in_the_window(
        self, events, percentages
    ):
        limiter = TokenLimiter(
            project_uuid=_PROJECT_UUID,
            route_name=_ROUTE,
            input_config=Limiting(max_tokens=100, window_size='1 minute'),
        )
        await limiter.count_input(prompt_tokens=80, identity=_IDENTITY)
        events.clear()

        await limiter.count_input(prompt_tokens=10, identity=_IDENTITY)

        assert _thresholds(events) == []

    @pytest.mark.asyncio
    async def test_a_zero_cost_hit_crosses_nothing(self, events, percentages):
        limiter = TokenLimiter(
            project_uuid=_PROJECT_UUID,
            route_name=_ROUTE,
            output_config=Limiting(max_tokens=100, window_size='1 minute'),
        )
        await limiter.count_output(token_count=75, identity=_IDENTITY)
        events.clear()

        await limiter.count_output(token_count=0, identity=_IDENTITY)

        assert _thresholds(events) == []

    @pytest.mark.asyncio
    async def test_the_percentages_come_from_the_alert_config(
        self, events, percentages
    ):
        percentages([50])
        limiter = _rate_limiter(max_requests=4)

        for _ in range(4):
            await limiter.check_and_count_request(**_ROUTE_CALL_ARGS)

        assert [e.threshold_percentage for e in _thresholds(events)] == [50]

    @pytest.mark.asyncio
    async def test_route_token_output(self, events, percentages):
        limiter = TokenLimiter(
            project_uuid=_PROJECT_UUID,
            route_name=_ROUTE,
            output_config=Limiting(max_tokens=100, window_size='1 hour'),
        )

        await limiter.count_output(token_count=80, identity=_IDENTITY)

        (event,) = _thresholds(events)
        assert event.category == 'token_output'
        assert event.consumption == 80
        assert event.window_seconds == 3600

    @pytest.mark.asyncio
    async def test_route_audio_duration(self, events, percentages):
        limiter = DurationLimiter(
            project_uuid=_PROJECT_UUID,
            route_name=_ROUTE,
            config=AudioDurationLimiting(
                max_duration_seconds=10, window_size='1 minute'
            ),
        )

        await limiter.check_and_count_duration(
            audio_bytes=make_wav_bytes(8.0), **_ROUTE_CALL_ARGS
        )

        (event,) = _thresholds(events)
        assert event.category == 'audio_duration'
        assert event.threshold_percentage == 75
        assert event.consumption == 8
        assert event.api_key_uuid == str(API_KEY_UUID)

    @pytest.mark.asyncio
    async def test_route_budget_in_currency(self, events, percentages):
        limiter = BudgetLimiter(
            project_uuid=_PROJECT_UUID,
            route_name=_ROUTE,
            config=Limiting(max_budget=1.0, window_size='1 minute'),
        )

        await limiter.count_output(
            token_count=800, output_cost_per_token=0.001, identity=_IDENTITY
        )
        await limiter.count_duration(
            seconds=200, cost_per_second=0.001, identity=_IDENTITY
        )

        crossed = _thresholds(events)
        assert [e.threshold_percentage for e in crossed] == [75, 98]
        assert crossed[0].category == 'budget'
        assert crossed[0].maximum == pytest.approx(1.0)
        assert crossed[0].consumption == pytest.approx(0.8)
        assert crossed[1].consumption == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_credential_limits_emit_with_the_credential_scope(
        self, events, percentages
    ):
        limiter = _credential_limiter(CredentialLimitCategory.TOKEN_INPUT, 100)

        await limiter.count_input_tokens(80, identity=_CREDENTIAL_IDENTITY)

        (event,) = _thresholds(events)
        assert event.limit_scope == LimitScope.CREDENTIAL
        assert event.category == 'token_input'
        assert event.api_key_uuid == _CREDENTIAL_UUID
        assert event.route_name == _ROUTE, 'the route called, not the "*" key'

    @pytest.mark.asyncio
    async def test_every_window_of_a_credential_category_emits(
        self, events, percentages
    ):
        hourly = _credential_limit(CredentialLimitCategory.TOKEN_OUTPUT, 100)
        daily = _credential_limit(CredentialLimitCategory.TOKEN_OUTPUT, 100)
        daily = daily.model_copy(update={'window_size': '1 day'})
        limiter = CredentialLimiter(
            credential_uuid=_CREDENTIAL_UUID,
            credential_name='my-cred',
            limits=[hourly, daily],
        )

        await limiter.count_output_tokens(80, identity=_CREDENTIAL_IDENTITY)

        assert sorted(e.window_seconds for e in _thresholds(events)) == [3600, 86400]

    @pytest.mark.asyncio
    async def test_credential_rate_and_budget(self, events, percentages):
        rate = _credential_limiter(CredentialLimitCategory.RATE, 4)
        budget = _credential_limiter(CredentialLimitCategory.BUDGET, 1.0)

        for _ in range(3):
            await rate.check_and_count_request(**_CREDENTIAL_CALL_ARGS)
        await budget.count_budget_output(
            token_count=500,
            output_cost_per_token=0.001,
            identity=_CREDENTIAL_IDENTITY,
        )
        await budget.count_budget_duration(
            seconds=300, cost_per_second=0.001, identity=_CREDENTIAL_IDENTITY
        )

        by_category = {e.category: e for e in _thresholds(events)}
        assert by_category['request_rate'].consumption == 3
        assert by_category['request_rate'].api_key_uuid == _CREDENTIAL_UUID
        assert by_category['budget'].consumption == pytest.approx(0.8)
        assert by_category['budget'].maximum == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_project_budget_emits_with_the_project_scope(
        self, events, percentages
    ):
        limiter = ProjectBudgetLimiter(
            project_uuid=_PROJECT_UUID,
            project_name='my-project',
            limits=[
                ProjectBudgetLimitOut(
                    uuid=uuid4(),
                    algorithm=LimitingAlgorithmType.FIXED_WINDOW,
                    window_size='1 day',
                    value=1.0,
                    created_at='2026-01-01 00:00:00',
                    updated_at='2026-01-01 00:00:00',
                )
            ],
        )

        await limiter.count_input(
            token_count=500, input_cost_per_token=0.001, identity=_IDENTITY
        )
        await limiter.count_duration(
            seconds=300, cost_per_second=0.001, identity=_IDENTITY
        )

        (event,) = _thresholds(events)
        assert event.limit_scope == LimitScope.PROJECT
        assert event.threshold_percentage == 75
        assert event.consumption == pytest.approx(0.8)
        assert event.project_uuid == _PROJECT_UUID
        assert event.route_name == _ROUTE
