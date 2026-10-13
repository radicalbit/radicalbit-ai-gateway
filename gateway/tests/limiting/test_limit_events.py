"""What a limit block emits: which limit it was and how far it had gone.

Each test drives a real limiter through check/count on in-memory storage and
captures the event instead of sending it.
"""

from collections.abc import Iterator
import time
from unittest.mock import Mock, patch
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

_EMITTERS = [
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
    patches.append(
        patch('radicalbit_ai_gateway.limiting.token_limiter.emit_notification', Mock())
    )
    for p in patches:
        p.start()
    yield captured
    for p in patches:
        p.stop()


def _only(events: list[LimitEventPayload]) -> LimitEventPayload:
    (event,) = events
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
        await limiter.count_input(prompt_tokens=80)
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
        await limiter.count_output(token_count=60)
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
        await limiter.count_input(token_count=1500, input_cost_per_token=0.001)
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
        await limiter.count_input(token_count=10, input_cost_per_token=0.001)
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
        await limiter.count_input_tokens(90)
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
        await limiter.count_output_tokens(10)
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
        await limiter.count_budget_input(token_count=2500, input_cost_per_token=0.001)
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
        await limiter.count_output(token_count=6000, output_cost_per_token=0.001)
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
        await limiter.count_input(token_count=1500, input_cost_per_token=0.001)
        with (
            patch(
                'radicalbit_ai_gateway.events.events_processor._events_buffer'
            ) as buf,
            pytest.raises(BudgetLimitExceededError),
        ):
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
