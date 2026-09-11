import datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from radicalbit_ai_gateway.db.dao.project_budget_limit_dao import ProjectBudgetLimitDAO
from radicalbit_ai_gateway.db.tables.project_budget_limit_table import (
    ProjectBudgetLimit,
)
from radicalbit_ai_gateway.limiting.project_budget_limiter import (
    ProjectBudgetLimiter,
    clear_project_budget_limit_counter,
    load_project_budget_limiter,
)
from radicalbit_ai_gateway.models.limiting import LimitingAlgorithmType
from radicalbit_ai_gateway.models.project_budget_limiting import ProjectBudgetLimitOut
from radicalbit_ai_gateway.utils.exceptions import BudgetLimitExceededError

_PROJECT_UUID = '3a2c6d4e-0000-4000-8000-0000000000bb'


def _limit(
    value: float,
    window_size: str = '1 minute',
    algorithm: LimitingAlgorithmType = LimitingAlgorithmType.FIXED_WINDOW,
) -> ProjectBudgetLimitOut:
    return ProjectBudgetLimitOut(
        uuid=uuid4(),
        algorithm=algorithm,
        window_size=window_size,
        value=value,
        created_at='2026-01-01 00:00:00',
        updated_at='2026-01-01 00:00:00',
    )


def _limiter(limits: list[ProjectBudgetLimitOut]) -> ProjectBudgetLimiter:
    return ProjectBudgetLimiter(
        project_uuid=_PROJECT_UUID,
        project_name='my-project',
        limits=limits,
    )


class TestNoLimitsConfigured:
    @pytest.mark.asyncio
    async def test_all_calls_are_noop(self):
        limiter = _limiter([])
        await limiter.check_budget()
        await limiter.count_input(100, 0.01)
        await limiter.count_output(100, 0.01)
        await limiter.count_duration(10.0, 0.01)


class TestBudgetLimiting:
    @pytest.mark.asyncio
    async def test_blocks_after_limit_reached(self):
        limiter = _limiter([_limit(1.0)])
        await limiter.count_input(token_count=1000, input_cost_per_token=0.001)
        with pytest.raises(BudgetLimitExceededError) as exc:
            await limiter.check_budget()
        assert 'my-project' in str(exc.value)

    @pytest.mark.asyncio
    async def test_count_output_and_duration_consume_same_window(self):
        limiter = _limiter([_limit(10.0)])
        await limiter.count_output(token_count=1000, output_cost_per_token=0.002)
        await limiter.count_duration(seconds=5.0, cost_per_second=0.1)
        await limiter.check_budget()  # still within limit

    @pytest.mark.asyncio
    async def test_and_semantics_across_multiple_windows(self):
        """Two budget limits, different windows: the already-exhausted one
        blocks first, and checking (test-only, no hit) never consumes the
        other window's capacity.
        """
        limiter = _limiter(
            [
                _limit(0.0, window_size='1 minute'),
                _limit(1000.0, window_size='1 hour'),
            ]
        )
        with pytest.raises(BudgetLimitExceededError):
            await limiter.check_budget()

        hourly_entry = limiter._entries[1]
        stats = await hourly_entry.limiter.get_window_stats(hourly_entry.window)
        assert stats.remaining == hourly_entry.window.limit


class TestProjectScoping:
    def test_window_key_is_scoped_by_project_uuid_with_sentinel_route(self):
        limiter = _limiter([_limit(5.0)])
        entry = limiter._entries[0]
        assert entry.window.project_uuid == _PROJECT_UUID
        assert entry.window.route_name == '*'
        key = entry.limiter._build_key(entry.window)
        assert key.startswith(f'limiter:{_PROJECT_UUID}:*:budget:')

    @pytest.mark.asyncio
    async def test_two_projects_do_not_share_the_window(self):
        limiter_a = ProjectBudgetLimiter(
            project_uuid='3a2c6d4e-0000-4000-8000-00000000000a',
            project_name='project-a',
            limits=[_limit(1.0)],
        )
        limiter_b = ProjectBudgetLimiter(
            project_uuid='3a2c6d4e-0000-4000-8000-00000000000b',
            project_name='project-b',
            limits=[_limit(1.0)],
        )
        entry_a = limiter_a._entries[0]
        entry_b = limiter_b._entries[0]
        entry_b.limiter._storage = entry_a.limiter._storage

        await limiter_a.count_input(token_count=1000, input_cost_per_token=0.001)
        with pytest.raises(BudgetLimitExceededError):
            await limiter_a.check_budget()

        # project B, same storage, untouched
        await limiter_b.check_budget()


def _fake_dao(rows: list[ProjectBudgetLimit]) -> ProjectBudgetLimitDAO:
    dao = MagicMock(spec_set=ProjectBudgetLimitDAO)
    dao.get_by_project_uuid = MagicMock(return_value=rows)
    return dao


class TestLoadProjectBudgetLimiter:
    def test_returns_none_when_project_has_no_limits(self):
        dao = _fake_dao([])
        assert load_project_budget_limiter(_PROJECT_UUID, 'my-project', dao) is None

    def test_returns_none_for_empty_project_uuid(self):
        dao = _fake_dao([_raw_limit()])
        assert load_project_budget_limiter('', 'my-project', dao) is None

    def test_builds_limiter_from_dao_rows(self):
        dao = _fake_dao([_raw_limit()])
        limiter = load_project_budget_limiter(_PROJECT_UUID, 'my-project', dao)
        assert limiter is not None
        assert len(limiter._entries) == 1


def _raw_limit():
    now = datetime.datetime.now(tz=datetime.UTC)
    return ProjectBudgetLimit(
        uuid=uuid4(),
        project_uuid=uuid4(),
        algorithm=LimitingAlgorithmType.FIXED_WINDOW.value,
        window_size='1 day',
        max_value=10.0,
        created_at=now,
        updated_at=now,
    )


class TestClearProjectBudgetLimitCounter:
    @pytest.mark.asyncio
    async def test_clears_the_same_key_the_limiter_uses(self):
        limiter = _limiter([_limit(2.0, window_size='1 minute')])
        entry = limiter._entries[0]
        await entry.limiter.hit(entry.window, cost=1)
        assert (await entry.limiter.get_window_stats(entry.window)).remaining == (
            entry.window.limit - 1
        )

        with patch(
            'radicalbit_ai_gateway.limiting.project_budget_limiter.InMemoryStorage',
            return_value=entry.limiter._storage,
        ):
            await clear_project_budget_limit_counter(
                project_uuid=_PROJECT_UUID,
                algorithm=LimitingAlgorithmType.FIXED_WINDOW.value,
                window_size='1 minute',
            )

        stats = await entry.limiter.get_window_stats(entry.window)
        assert stats.remaining == entry.window.limit  # back to full capacity

    @pytest.mark.asyncio
    async def test_matches_aligned_fixed_window_key(self):
        limiter = _limiter(
            [
                _limit(
                    5,
                    window_size='1 hour',
                    algorithm=LimitingAlgorithmType.ALIGNED_FIXED_WINDOW,
                )
            ]
        )
        entry = limiter._entries[0]
        await entry.limiter.hit(entry.window, cost=1)

        with patch(
            'radicalbit_ai_gateway.limiting.project_budget_limiter.InMemoryStorage',
            return_value=entry.limiter._storage,
        ):
            await clear_project_budget_limit_counter(
                project_uuid=_PROJECT_UUID,
                algorithm=LimitingAlgorithmType.ALIGNED_FIXED_WINDOW.value,
                window_size='1 hour',
            )

        stats = await entry.limiter.get_window_stats(entry.window)
        assert stats.remaining == entry.window.limit

    @pytest.mark.asyncio
    async def test_clearing_a_never_hit_counter_does_not_raise(self):
        await clear_project_budget_limit_counter(
            project_uuid=str(uuid4()),
            algorithm=LimitingAlgorithmType.FIXED_WINDOW.value,
            window_size='1 minute',
        )
