import datetime
from unittest.mock import patch

from freezegun import freeze_time
import pytest

from tests.common.db_mock import API_KEY_UUID, GROUP_UUID, REQUEST_UUID
from tests.common.request_identity import IDENTITY

from radicalbit_ai_gateway.limiting.budget_limiting import BudgetLimiter
from radicalbit_ai_gateway.models.limiting import Limiting, LimitingAlgorithmType
from radicalbit_ai_gateway.utils.exceptions import BudgetLimitExceededError

_PROJECT_UUID = '2f1c6d4e-0000-4000-8000-0000000000aa'

_CALL_ARGS = {
    'request_uuid': str(REQUEST_UUID),
    'api_key_uuid': str(API_KEY_UUID),
    'group_uuid': str(GROUP_UUID),
    'api_key_name': 'test-key',
    'group_name': 'test-group',
}


@pytest.fixture(autouse=True)
def mock_emit_event():
    """Mock emit_event for all tests in this module."""
    with patch(
        'radicalbit_ai_gateway.limiting.budget_limiting.emit_event', autospec=True
    ):
        yield


class TestBudgetLimiter:
    def test_init_without_config(self):
        limiter = BudgetLimiter(project_uuid=_PROJECT_UUID, route_name='rb-gateway')
        assert limiter.limiter is None
        assert limiter.item is None

    def test_init_with_config(self):
        config = Limiting(
            algorithm=LimitingAlgorithmType.FIXED_WINDOW,
            window_size='1 minute',
            max_budget=10,
        )
        limiter = BudgetLimiter(
            project_uuid=_PROJECT_UUID, route_name='rb-gateway', config=config
        )
        assert limiter.limiter is not None
        assert limiter.item is not None

    def test_init_without_max_budget_raises_error(self):
        config = Limiting(window_size='1 minute')
        with pytest.raises(
            ValueError, match='max_budget must be set for budget limiting'
        ):
            BudgetLimiter(
                project_uuid=_PROJECT_UUID, route_name='rb-gateway', config=config
            )

    @pytest.mark.asyncio
    async def test_check_and_count_no_config(self):
        limiter = BudgetLimiter(project_uuid=_PROJECT_UUID, route_name='rb-gateway')
        await limiter.count_input(10, 2.5e-06, identity=IDENTITY)
        await limiter.count_output(10, 2.5e-06, identity=IDENTITY)
        await limiter.check_budget(**_CALL_ARGS)

    @pytest.mark.asyncio
    async def test_check_and_count_within_limit(self):
        config = Limiting(max_budget=1, window_size='1 minute')
        limiter = BudgetLimiter(
            project_uuid=_PROJECT_UUID, route_name='rb-gateway', config=config
        )
        await limiter.count_input(10, 2.5e-06, identity=IDENTITY)
        await limiter.count_output(10, 2.5e-06, identity=IDENTITY)
        await limiter.check_budget(**_CALL_ARGS)

    @pytest.mark.asyncio
    async def test_count_input_exceeds_limit(self):
        config = Limiting(max_budget=3.46, window_size='1 minute')
        limiter = BudgetLimiter(
            project_uuid=_PROJECT_UUID, route_name='rb-gateway', config=config
        )

        with pytest.raises(BudgetLimitExceededError) as exc:
            await limiter.count_input(10_000_000, 2.5e-06, identity=IDENTITY)
            await limiter.check_budget(**_CALL_ARGS)

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
        limiter = BudgetLimiter(
            project_uuid=_PROJECT_UUID, route_name='rb-gateway', config=config
        )

        await limiter.count_output(100000, 2.51e-06, identity=IDENTITY)

        with pytest.raises(BudgetLimitExceededError) as exc:
            await limiter.check_budget(**_CALL_ARGS)

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
    async def test_count_duration_exceeds_limit(self):
        """count_duration is a dedicated method for whisper-1-style duration
        billing, where both operands are floats — unlike count_input/count_output's
        int token counts.
        """
        config = Limiting(max_budget=0.0005, window_size='1 minute')
        limiter = BudgetLimiter(
            project_uuid=_PROJECT_UUID, route_name='rb-gateway', config=config
        )

        await limiter.count_duration(8.25, 0.0001, identity=IDENTITY)

        with pytest.raises(BudgetLimitExceededError) as exc:
            await limiter.check_budget(**_CALL_ARGS)

        msg = getattr(exc.value, 'log_message', str(exc.value))
        assert '[BUDGET LIMIT]' in msg
        assert '[route=rb-gateway]' in msg
        assert '[limit=0.0005]' in msg

    @pytest.mark.asyncio
    async def test_combined_input_output_exhausts_budget(self):
        """Input + output costs together exhaust the shared budget."""
        config = Limiting(max_budget=1, window_size='1 minute')
        limiter = BudgetLimiter(
            project_uuid=_PROJECT_UUID, route_name='rb-gateway', config=config
        )

        # Each call spends ~0.25, three calls = 0.75 — still under 1.0
        await limiter.count_input(100000, 2.5e-06, identity=IDENTITY)
        await limiter.check_budget(**_CALL_ARGS)
        await limiter.count_output(100000, 2.5e-06, identity=IDENTITY)
        await limiter.check_budget(**_CALL_ARGS)
        await limiter.count_input(100000, 2.5e-06, identity=IDENTITY)
        await limiter.check_budget(**_CALL_ARGS)

        # 4th call puts combined total over 1.0
        with pytest.raises(BudgetLimitExceededError) as exc:
            await limiter.count_output(100000, 2.51e-06, identity=IDENTITY)
            await limiter.check_budget(**_CALL_ARGS)

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
        limiter = BudgetLimiter(
            project_uuid=_PROJECT_UUID, route_name='rb-gateway', config=config
        )

        await limiter.count_input(100000, 2.5e-06, identity=IDENTITY)
        await limiter.check_budget(**_CALL_ARGS)

        await limiter.count_output(100000, 2.5e-06, identity=IDENTITY)
        await limiter.check_budget(**_CALL_ARGS)

        await limiter.count_input(100000, 2.5e-06, identity=IDENTITY)
        await limiter.check_budget(**_CALL_ARGS)

        with pytest.raises(BudgetLimitExceededError) as exc:
            await limiter.count_input(100000, 2.51e-06, identity=IDENTITY)
            await limiter.check_budget(**_CALL_ARGS)

        msg = getattr(exc.value, 'log_message', str(exc.value))
        assert '[limit=1.0]' in msg
        assert '[remaining=0]' in msg
        assert '[action=BLOCK]' in msg

    @pytest.mark.asyncio
    async def test_budget_accumulates_with_reset_time(self):
        config = Limiting(max_budget=1, window_size='1 minute')
        limiter = BudgetLimiter(
            project_uuid=_PROJECT_UUID, route_name='rb-gateway', config=config
        )

        initial_datetime = datetime.datetime(
            year=2025, month=6, day=25, hour=15, minute=0, second=0
        )
        with freeze_time(initial_datetime) as frozen_datetime:
            assert frozen_datetime() == initial_datetime

            await limiter.count_output(100000, 2.5e-06, identity=IDENTITY)
            await limiter.count_output(100000, 2.5e-06, identity=IDENTITY)
            await limiter.count_output(100000, 5.1e-06, identity=IDENTITY)

            with pytest.raises(BudgetLimitExceededError) as exc:
                await limiter.check_budget(**_CALL_ARGS)

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
            limiter = BudgetLimiter(
                project_uuid=_PROJECT_UUID, route_name='rb-gateway', config=config
            )

            await limiter.count_input(100000, 2.4e-06, identity=IDENTITY)
            await limiter.check_budget(**_CALL_ARGS)

            with pytest.raises(BudgetLimitExceededError) as exc1:
                await limiter.count_input(100000, 2.4e-06, identity=IDENTITY)
                await limiter.check_budget(**_CALL_ARGS)

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
                await limiter.count_input(100000, 2.4e-06, identity=IDENTITY)
                await limiter.check_budget(**_CALL_ARGS)

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
            await limiter.count_input(100000, 2.4e-06, identity=IDENTITY)
            await limiter.check_budget(**_CALL_ARGS)
