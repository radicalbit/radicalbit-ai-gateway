import datetime

from freezegun import freeze_time
import pytest

from radicalbit_ai_gateway.limiting.budget_limiting import BudgetLimiter
from radicalbit_ai_gateway.models.limiting import Limiting, LimitingAlgorithmType
from radicalbit_ai_gateway.utils.exceptions import BudgetLimitExceededError


class TestBudgetLimiter:
    def test_init_without_config(self):
        limiter = BudgetLimiter(route_name='rb-gateway')
        assert limiter.limiter is None
        assert limiter.item is None

    def test_init_with_config(self):
        config = Limiting(
            algorithm=LimitingAlgorithmType.FIXED_WINDOW,
            window_size='1 minute',
            max_budget=10,
        )
        limiter = BudgetLimiter(route_name='rb-gateway', config=config)
        assert limiter.limiter is not None
        assert limiter.item is not None

    def test_init_without_max_budget_raises_error(self):
        config = Limiting(window_size='1 minute')
        with pytest.raises(
            ValueError, match='max_budget must be set for budget limiting'
        ):
            BudgetLimiter(route_name='rb-gateway', config=config)

    @pytest.mark.asyncio
    async def test_check_and_count_no_config(self):
        limiter = BudgetLimiter(route_name='rb-gateway')
        await limiter.count_input(10, 2.5e-06)
        await limiter.count_output(10, 2.5e-06)
        await limiter.check_budget()

    @pytest.mark.asyncio
    async def test_check_and_count_within_limit(self):
        config = Limiting(max_budget=1, window_size='1 minute')
        limiter = BudgetLimiter(route_name='rb-gateway', config=config)
        await limiter.count_input(10, 2.5e-06)
        await limiter.count_output(10, 2.5e-06)
        await limiter.check_budget()

    @pytest.mark.asyncio
    async def test_count_input_exceeds_limit(self):
        config = Limiting(max_budget=3.46, window_size='1 minute')
        limiter = BudgetLimiter(route_name='rb-gateway', config=config)

        with pytest.raises(BudgetLimitExceededError) as exc:
            await limiter.count_input(10_000_000, 2.5e-06)
            await limiter.check_budget()

        msg = getattr(exc.value, 'log_message', str(exc.value))
        assert '[BUDGET LIMIT]' in msg
        assert '[route=rb-gateway]' in msg
        assert '[kind=BUDGET]' in msg
        assert '[attempted=1]' in msg
        assert '[limit=3.46]' in msg
        assert '[window=1 minute]' in msg
        assert '[remaining=0]' in msg
        assert '[action=BLOCK]' in msg

    @pytest.mark.asyncio
    async def test_count_output_exceeds_limit(self):
        config = Limiting(max_budget=0.25, window_size='1 minute')
        limiter = BudgetLimiter(route_name='rb-gateway', config=config)

        await limiter.count_output(100000, 2.51e-06)

        with pytest.raises(BudgetLimitExceededError) as exc:
            await limiter.check_budget()

        msg = getattr(exc.value, 'log_message', str(exc.value))
        assert '[BUDGET LIMIT]' in msg
        assert '[route=rb-gateway]' in msg
        assert '[kind=BUDGET]' in msg
        assert '[attempted=1]' in msg
        assert '[limit=0.25]' in msg
        assert '[window=1 minute]' in msg
        assert '[remaining=0]' in msg
        assert '[action=BLOCK]' in msg

    @pytest.mark.asyncio
    async def test_combined_input_output_exhausts_budget(self):
        """Input + output costs together exhaust the shared budget."""
        config = Limiting(max_budget=1, window_size='1 minute')
        limiter = BudgetLimiter(route_name='rb-gateway', config=config)

        # Each call spends ~0.25, three calls = 0.75 — still under 1.0
        await limiter.count_input(100000, 2.5e-06)
        await limiter.check_budget()
        await limiter.count_output(100000, 2.5e-06)
        await limiter.check_budget()
        await limiter.count_input(100000, 2.5e-06)
        await limiter.check_budget()

        # 4th call puts combined total over 1.0
        with pytest.raises(BudgetLimitExceededError) as exc:
            await limiter.count_output(100000, 2.51e-06)
            await limiter.check_budget()

        msg = getattr(exc.value, 'log_message', str(exc.value))
        assert '[BUDGET LIMIT]' in msg
        assert '[route=rb-gateway]' in msg
        assert '[kind=BUDGET]' in msg
        assert '[limit=1.0]' in msg
        assert '[window=1 minute]' in msg
        assert '[remaining=0]' in msg
        assert '[action=BLOCK]' in msg

    @pytest.mark.asyncio
    async def test_budget_accumulates(self):
        config = Limiting(max_budget=1, window_size='1 minute')
        limiter = BudgetLimiter(route_name='rb-gateway', config=config)

        await limiter.count_input(100000, 2.5e-06)
        await limiter.check_budget()

        await limiter.count_output(100000, 2.5e-06)
        await limiter.check_budget()

        await limiter.count_input(100000, 2.5e-06)
        await limiter.check_budget()

        with pytest.raises(BudgetLimitExceededError) as exc:
            await limiter.count_input(100000, 2.51e-06)
            await limiter.check_budget()

        msg = getattr(exc.value, 'log_message', str(exc.value))
        assert '[limit=1.0]' in msg
        assert '[remaining=0]' in msg
        assert '[action=BLOCK]' in msg

    @pytest.mark.asyncio
    async def test_budget_accumulates_with_reset_time(self):
        config = Limiting(max_budget=1, window_size='1 minute')
        limiter = BudgetLimiter(route_name='rb-gateway', config=config)

        initial_datetime = datetime.datetime(
            year=2025, month=6, day=25, hour=15, minute=0, second=0
        )
        with freeze_time(initial_datetime) as frozen_datetime:
            assert frozen_datetime() == initial_datetime

            await limiter.count_output(100000, 2.5e-06)
            await limiter.count_output(100000, 2.5e-06)
            await limiter.count_output(100000, 5.1e-06)

            with pytest.raises(BudgetLimitExceededError) as exc:
                await limiter.check_budget()

            msg = getattr(exc.value, 'log_message', str(exc.value))
            assert '[BUDGET LIMIT]' in msg
            assert '[route=rb-gateway]' in msg
            assert '[kind=BUDGET]' in msg
            assert '[attempted=1]' in msg
            assert '[limit=1.0]' in msg
            assert '[window=1 minute]' in msg
            assert '[remaining=0]' in msg
            assert '[reset_s=60]' in msg
            assert '[action=BLOCK]' in msg

    @pytest.mark.asyncio
    async def test_window_with_fixed_time(self):
        initial_datetime = datetime.datetime(
            year=2025, month=6, day=25, hour=15, minute=0, second=0
        )
        with freeze_time(initial_datetime) as frozen_datetime:
            assert frozen_datetime() == initial_datetime

            config = Limiting(
                algorithm=LimitingAlgorithmType.FIXED_WINDOW,
                max_budget=0.25,
                window_size='10 second',
            )
            limiter = BudgetLimiter(route_name='rb-gateway', config=config)

            await limiter.count_input(100000, 2.4e-06)
            await limiter.check_budget()

            with pytest.raises(BudgetLimitExceededError) as exc1:
                await limiter.count_input(100000, 2.4e-06)
                await limiter.check_budget()

            msg1 = getattr(exc1.value, 'log_message', str(exc1.value))
            assert '[BUDGET LIMIT]' in msg1
            assert '[route=rb-gateway]' in msg1
            assert '[kind=BUDGET]' in msg1
            assert '[attempted=1]' in msg1
            assert '[limit=0.25]' in msg1
            assert '[window=10 second]' in msg1
            assert '[remaining=0]' in msg1
            assert '[reset_s=10]' in msg1
            assert '[action=BLOCK]' in msg1

            frozen_datetime.tick(3)

            with pytest.raises(BudgetLimitExceededError) as exc2:
                await limiter.count_input(100000, 2.4e-06)
                await limiter.check_budget()

            msg2 = getattr(exc2.value, 'log_message', str(exc2.value))
            assert '[BUDGET LIMIT]' in msg2
            assert '[route=rb-gateway]' in msg2
            assert '[attempted=1]' in msg2
            assert '[limit=0.25]' in msg2
            assert '[window=10 second]' in msg2
            assert '[remaining=0]' in msg2
            assert '[reset_s=7]' in msg2
            assert '[action=BLOCK]' in msg2

            frozen_datetime.tick(7)
            await limiter.count_input(100000, 2.4e-06)
            await limiter.check_budget()
