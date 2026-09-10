from unittest.mock import patch
from uuid import uuid4

import pytest

from tests.common.db_mock import GROUP_UUID, REQUEST_UUID

from radicalbit_ai_gateway.limiting.credential_limiter import (
    CredentialLimiter,
    clear_limit_counter,
)
from radicalbit_ai_gateway.models.credential_limiting import (
    CredentialLimitCategory,
    CredentialLimitOut,
)
from radicalbit_ai_gateway.models.limiting import LimitingAlgorithmType
from radicalbit_ai_gateway.utils.exceptions import (
    BudgetLimitExceededError,
    InputTokenLimitExceeded,
    OutputTokenLimitExceeded,
    RequestRateLimitExceeded,
)

_CREDENTIAL_UUID = '2f1c6d4e-0000-4000-8000-0000000000aa'
TEST_MODEL = 'openai/gpt-4o'

_CALL_ARGS = {
    'request_uuid': str(REQUEST_UUID),
    'group_uuid': str(GROUP_UUID),
    'group_name': 'test-group',
    'route_name': 'my-route',
}


def _limit(
    category: CredentialLimitCategory,
    value: float,
    window_size: str = '1 minute',
    algorithm: LimitingAlgorithmType = LimitingAlgorithmType.FIXED_WINDOW,
) -> CredentialLimitOut:
    return CredentialLimitOut(
        uuid=uuid4(),
        category=category,
        algorithm=algorithm,
        window_size=window_size,
        value=value,
        created_at='2026-01-01 00:00:00',
        updated_at='2026-01-01 00:00:00',
    )


def _limiter(limits: list[CredentialLimitOut]) -> CredentialLimiter:
    return CredentialLimiter(
        credential_uuid=_CREDENTIAL_UUID,
        credential_name='my-cred',
        limits=limits,
    )


@pytest.fixture(autouse=True)
def mock_emit_event():
    with patch(
        'radicalbit_ai_gateway.limiting.credential_limiter.emit_event', autospec=True
    ) as mock:
        yield mock


class TestNoLimitsConfigured:
    @pytest.mark.asyncio
    async def test_all_checks_are_noop(self):
        limiter = _limiter([])
        await limiter.check_and_count_request(**_CALL_ARGS)
        await limiter.check_input_tokens(
            text='hello', model_string=TEST_MODEL, **_CALL_ARGS
        )
        await limiter.count_input_tokens(100)
        await limiter.check_output_tokens(**_CALL_ARGS)
        await limiter.count_output_tokens(100)
        await limiter.check_budget()
        await limiter.count_budget_input(100, 0.01)
        await limiter.count_budget_output(100, 0.01)
        await limiter.count_budget_duration(10.0, 0.01)

    def test_has_category_is_false_for_every_category(self):
        limiter = _limiter([])
        for category in CredentialLimitCategory:
            assert not limiter.has_category(category)


class TestRateLimiting:
    @pytest.mark.asyncio
    async def test_blocks_after_limit_reached(self, mock_emit_event):
        limiter = _limiter([_limit(CredentialLimitCategory.RATE, 2)])
        await limiter.check_and_count_request(**_CALL_ARGS)
        await limiter.check_and_count_request(**_CALL_ARGS)
        with pytest.raises(RequestRateLimitExceeded) as exc:
            await limiter.check_and_count_request(**_CALL_ARGS)
        assert 'my-cred' in str(exc.value)
        mock_emit_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_and_semantics_across_multiple_windows(self):
        """Two rate limits, different windows: the tighter one blocks first,
        and no capacity is consumed on either when blocked.
        """
        limiter = _limiter(
            [
                _limit(CredentialLimitCategory.RATE, 1, window_size='1 minute'),
                _limit(CredentialLimitCategory.RATE, 100, window_size='1 hour'),
            ]
        )
        await limiter.check_and_count_request(**_CALL_ARGS)
        with pytest.raises(RequestRateLimitExceeded):
            await limiter.check_and_count_request(**_CALL_ARGS)

        hourly_entry = limiter._entries[CredentialLimitCategory.RATE][1]
        stats = await hourly_entry.limiter.get_window_stats(hourly_entry.window)
        assert stats.remaining == 99


class TestTokenInputLimiting:
    @pytest.mark.asyncio
    async def test_check_does_not_consume(self):
        limiter = _limiter([_limit(CredentialLimitCategory.TOKEN_INPUT, 100)])
        with patch(
            'radicalbit_ai_gateway.limiting.credential_limiter.count_tokens',
            return_value=50,
        ):
            await limiter.check_input_tokens(
                text='hello', model_string=TEST_MODEL, **_CALL_ARGS
            )
        entry = limiter._entries[CredentialLimitCategory.TOKEN_INPUT][0]
        stats = await entry.limiter.get_window_stats(entry.window)
        assert stats.remaining == 100

    @pytest.mark.asyncio
    async def test_check_raises_and_count_consumes(self):
        limiter = _limiter([_limit(CredentialLimitCategory.TOKEN_INPUT, 100)])
        with (
            patch(
                'radicalbit_ai_gateway.limiting.credential_limiter.count_tokens',
                return_value=150,
            ),
            pytest.raises(InputTokenLimitExceeded),
        ):
            await limiter.check_input_tokens(
                text='hello', model_string=TEST_MODEL, **_CALL_ARGS
            )

        await limiter.count_input_tokens(30)
        entry = limiter._entries[CredentialLimitCategory.TOKEN_INPUT][0]
        stats = await entry.limiter.get_window_stats(entry.window)
        assert stats.remaining == 70


class TestTokenOutputLimiting:
    @pytest.mark.asyncio
    async def test_check_and_count_are_independent(self):
        limiter = _limiter([_limit(CredentialLimitCategory.TOKEN_OUTPUT, 10)])
        await limiter.check_output_tokens(**_CALL_ARGS)
        await limiter.count_output_tokens(10)
        with pytest.raises(OutputTokenLimitExceeded):
            await limiter.check_output_tokens(**_CALL_ARGS)


class TestBudgetLimiting:
    @pytest.mark.asyncio
    async def test_check_budget_blocks_without_emitting_event(self, mock_emit_event):
        limiter = _limiter([_limit(CredentialLimitCategory.BUDGET, 1.0)])
        await limiter.count_budget_input(token_count=1000, input_cost_per_token=0.001)
        with pytest.raises(BudgetLimitExceededError):
            await limiter.check_budget()
        mock_emit_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_count_budget_output_and_duration_consume_same_window(self):
        limiter = _limiter([_limit(CredentialLimitCategory.BUDGET, 10.0)])
        await limiter.count_budget_output(token_count=1000, output_cost_per_token=0.002)
        await limiter.count_budget_duration(seconds=5.0, cost_per_second=0.1)
        await limiter.check_budget()  # still within limit


class TestCredentialScoping:
    def test_window_key_is_scoped_by_credential_uuid_with_sentinel_route(self):
        limiter = _limiter([_limit(CredentialLimitCategory.RATE, 5)])
        entry = limiter._entries[CredentialLimitCategory.RATE][0]
        assert entry.window.project_uuid == _CREDENTIAL_UUID
        assert entry.window.route_name == '*'
        key = entry.limiter._build_key(entry.window)
        assert key.startswith(f'limiter:{_CREDENTIAL_UUID}:*:request_rate:')

    @pytest.mark.asyncio
    async def test_two_credentials_do_not_share_the_window(self):
        limiter_a = CredentialLimiter(
            credential_uuid='2f1c6d4e-0000-4000-8000-00000000000a',
            credential_name='cred-a',
            limits=[_limit(CredentialLimitCategory.RATE, 1)],
        )
        limiter_b = CredentialLimiter(
            credential_uuid='2f1c6d4e-0000-4000-8000-00000000000b',
            credential_name='cred-b',
            limits=[_limit(CredentialLimitCategory.RATE, 1)],
        )
        entry_a = limiter_a._entries[CredentialLimitCategory.RATE][0]
        entry_b = limiter_b._entries[CredentialLimitCategory.RATE][0]
        entry_b.limiter._storage = entry_a.limiter._storage

        await limiter_a.check_and_count_request(**_CALL_ARGS)
        with pytest.raises(RequestRateLimitExceeded):
            await limiter_a.check_and_count_request(**_CALL_ARGS)

        # credential B, same route, untouched
        await limiter_b.check_and_count_request(**_CALL_ARGS)


class TestClearLimitCounter:
    @pytest.mark.asyncio
    async def test_clears_the_same_key_the_limiter_uses(self):
        limiter = _limiter(
            [_limit(CredentialLimitCategory.RATE, 2, window_size='1 minute')]
        )
        entry = limiter._entries[CredentialLimitCategory.RATE][0]
        await entry.limiter.hit(entry.window, cost=1)
        assert (await entry.limiter.get_window_stats(entry.window)).remaining == 1

        with patch(
            'radicalbit_ai_gateway.limiting.credential_limiter.InMemoryStorage',
            return_value=entry.limiter._storage,
        ):
            await clear_limit_counter(
                credential_uuid=_CREDENTIAL_UUID,
                category=CredentialLimitCategory.RATE.value,
                algorithm=LimitingAlgorithmType.FIXED_WINDOW.value,
                window_size='1 minute',
            )

        stats = await entry.limiter.get_window_stats(entry.window)
        assert stats.remaining == 2  # back to full capacity

    @pytest.mark.asyncio
    async def test_matches_aligned_fixed_window_key(self):
        limiter = _limiter(
            [
                _limit(
                    CredentialLimitCategory.BUDGET,
                    5,
                    window_size='1 hour',
                    algorithm=LimitingAlgorithmType.ALIGNED_FIXED_WINDOW,
                )
            ]
        )
        entry = limiter._entries[CredentialLimitCategory.BUDGET][0]
        await entry.limiter.hit(entry.window, cost=1)

        with patch(
            'radicalbit_ai_gateway.limiting.credential_limiter.InMemoryStorage',
            return_value=entry.limiter._storage,
        ):
            await clear_limit_counter(
                credential_uuid=_CREDENTIAL_UUID,
                category=CredentialLimitCategory.BUDGET.value,
                algorithm=LimitingAlgorithmType.ALIGNED_FIXED_WINDOW.value,
                window_size='1 hour',
            )

        stats = await entry.limiter.get_window_stats(entry.window)
        # BUDGET values are stored in micro-units (BUDGET_MULTIPLIER).
        assert stats.remaining == entry.window.limit

    @pytest.mark.asyncio
    async def test_clearing_a_never_hit_counter_does_not_raise(self):
        await clear_limit_counter(
            credential_uuid=str(uuid4()),
            category=CredentialLimitCategory.RATE.value,
            algorithm=LimitingAlgorithmType.FIXED_WINDOW.value,
            window_size='1 minute',
        )
