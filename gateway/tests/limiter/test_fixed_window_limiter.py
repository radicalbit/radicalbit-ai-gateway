"""Tests for FixedWindowLimiter."""

import datetime
import time

from freezegun import freeze_time
import pytest

from radicalbit_ai_gateway.limiter import (
    FixedWindowLimiter,
    InMemoryStorage,
    ScenarioType,
)
from radicalbit_ai_gateway.limiter.window_config import WindowConfig

_PROJECT_UUID = '2f1c6d4e-0000-4000-8000-0000000000aa'


@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


@pytest.fixture
def limiter(storage: InMemoryStorage) -> FixedWindowLimiter:
    return FixedWindowLimiter(storage)


@pytest.fixture
def config() -> WindowConfig:
    return WindowConfig(
        limit=10,
        window_seconds=60,
        project_uuid=_PROJECT_UUID,
        route_name='test-route',
        scenario_type=ScenarioType.REQUEST_RATE,
    )


class TestTestMethod:
    """Tests for the test() method."""

    @pytest.mark.asyncio
    async def test_test_allowed_when_under_limit(
        self, limiter: FixedWindowLimiter, config: WindowConfig
    ) -> None:
        result = await limiter.test(config, cost=5)
        assert result is True

    @pytest.mark.asyncio
    async def test_test_allowed_at_exact_limit(
        self, limiter: FixedWindowLimiter, config: WindowConfig
    ) -> None:
        result = await limiter.test(config, cost=10)
        assert result is True

    @pytest.mark.asyncio
    async def test_test_denied_when_exceeds_limit(
        self, limiter: FixedWindowLimiter, config: WindowConfig
    ) -> None:
        result = await limiter.test(config, cost=11)
        assert result is False

    @pytest.mark.asyncio
    async def test_test_does_not_consume(
        self, limiter: FixedWindowLimiter, config: WindowConfig
    ) -> None:
        # Test should not consume
        await limiter.test(config, cost=5)
        stats = await limiter.get_window_stats(config)
        assert stats.remaining == 10  # Still full capacity
        assert stats.window_id is None  # No window created

    @pytest.mark.asyncio
    async def test_test_after_hit(
        self, limiter: FixedWindowLimiter, config: WindowConfig
    ) -> None:
        # Consume 7
        await limiter.hit(config, cost=7)

        # Test if 3 more is allowed (7 + 3 = 10, should be allowed)
        result = await limiter.test(config, cost=3)
        assert result is True

        # Test if 4 more is allowed (7 + 4 = 11, should be denied)
        result = await limiter.test(config, cost=4)
        assert result is False


class TestHitMethod:
    """Tests for the hit() method."""

    @pytest.mark.asyncio
    async def test_hit_returns_true_when_under_limit(
        self, limiter: FixedWindowLimiter, config: WindowConfig
    ) -> None:
        result = await limiter.hit(config, cost=5)
        assert result is True

    @pytest.mark.asyncio
    async def test_hit_returns_true_at_exact_limit(
        self, limiter: FixedWindowLimiter, config: WindowConfig
    ) -> None:
        result = await limiter.hit(config, cost=10)
        assert result is True

    @pytest.mark.asyncio
    async def test_hit_returns_false_when_exceeds_limit(
        self, limiter: FixedWindowLimiter, config: WindowConfig
    ) -> None:
        result = await limiter.hit(config, cost=11)
        assert result is False

    @pytest.mark.asyncio
    async def test_hit_consumes_capacity(
        self, limiter: FixedWindowLimiter, config: WindowConfig
    ) -> None:
        await limiter.hit(config, cost=3)
        stats = await limiter.get_window_stats(config)
        assert stats.remaining == 7

    @pytest.mark.asyncio
    async def test_hit_accumulates(
        self, limiter: FixedWindowLimiter, config: WindowConfig
    ) -> None:
        await limiter.hit(config, cost=3)
        await limiter.hit(config, cost=4)
        stats = await limiter.get_window_stats(config)
        assert stats.remaining == 3

    @pytest.mark.asyncio
    async def test_hit_still_consumes_when_exceeds_limit(
        self, limiter: FixedWindowLimiter, config: WindowConfig
    ) -> None:
        # This is important: hit() still increments the counter even if limit exceeded
        result = await limiter.hit(config, cost=15)
        assert result is False  # Over limit

        stats = await limiter.get_window_stats(config)
        assert stats.remaining == 0  # Clamped to 0


class TestGetWindowStats:
    """Tests for the get_window_stats() method."""

    @pytest.mark.asyncio
    async def test_stats_for_new_window(
        self, limiter: FixedWindowLimiter, config: WindowConfig
    ) -> None:
        initial_datetime = datetime.datetime(
            year=2025, month=6, day=25, hour=15, minute=0, second=0
        )
        with freeze_time(initial_datetime):
            stats = await limiter.get_window_stats(config)
            assert stats.remaining == 10
            assert stats.window_id is None  # No window exists yet
            # reset_time should be approximately 60 seconds from now
            expected_reset = time.time() + 60
            assert abs(stats.reset_time - expected_reset) < 1

    @pytest.mark.asyncio
    async def test_stats_after_consumption(
        self, limiter: FixedWindowLimiter, config: WindowConfig
    ) -> None:
        await limiter.hit(config, cost=4)
        stats = await limiter.get_window_stats(config)
        assert stats.remaining == 6
        assert stats.window_id is not None  # Window created

    @pytest.mark.asyncio
    async def test_stats_reset_time_is_set_on_first_hit(
        self, limiter: FixedWindowLimiter, config: WindowConfig
    ) -> None:
        initial_datetime = datetime.datetime(
            year=2025, month=6, day=25, hour=15, minute=0, second=0
        )
        with freeze_time(initial_datetime):
            await limiter.hit(config, cost=1)
            stats = await limiter.get_window_stats(config)
            # reset_time should be approximately 60 seconds from now
            expected_reset = time.time() + 60
            assert abs(stats.reset_time - expected_reset) < 1

    @pytest.mark.asyncio
    async def test_window_id_remains_constant_within_window(
        self, limiter: FixedWindowLimiter, config: WindowConfig
    ) -> None:
        await limiter.hit(config, cost=1)
        stats1 = await limiter.get_window_stats(config)

        await limiter.hit(config, cost=2)
        stats2 = await limiter.get_window_stats(config)

        assert stats1.window_id == stats2.window_id

    @pytest.mark.asyncio
    async def test_new_window_id_after_reset(
        self, limiter: FixedWindowLimiter, config: WindowConfig
    ) -> None:
        initial_datetime = datetime.datetime(
            year=2025, month=6, day=25, hour=15, minute=0, second=0
        )
        with freeze_time(initial_datetime) as frozen_datetime:
            await limiter.hit(config, cost=1)
            stats1 = await limiter.get_window_stats(config)
            assert stats1.window_id is not None

            # Advance past window
            frozen_datetime.tick(61)

            # Create new window
            await limiter.hit(config, cost=1)
            stats2 = await limiter.get_window_stats(config)
            assert stats2.window_id is not None
            assert stats1.window_id != stats2.window_id


class TestWindowReset:
    """Tests for window reset behavior."""

    @pytest.mark.asyncio
    async def test_window_resets_after_ttl(
        self, limiter: FixedWindowLimiter, config: WindowConfig
    ) -> None:
        initial_datetime = datetime.datetime(
            year=2025, month=6, day=25, hour=15, minute=0, second=0
        )
        with freeze_time(initial_datetime) as frozen_datetime:
            # Use up the limit
            await limiter.hit(config, cost=10)

            # Should be blocked
            result = await limiter.test(config, cost=1)
            assert result is False

            # Advance past window
            frozen_datetime.tick(61)

            # Should be allowed again
            result = await limiter.test(config, cost=1)
            assert result is True

    @pytest.mark.asyncio
    async def test_remaining_shows_zero_when_exceeded(
        self, limiter: FixedWindowLimiter, config: WindowConfig
    ) -> None:
        await limiter.hit(config, cost=15)  # Exceeds limit
        stats = await limiter.get_window_stats(config)
        assert stats.remaining == 0


class TestKeyIsolation:
    """Tests for key isolation between routes and scenarios."""

    @pytest.mark.asyncio
    async def test_different_routes_are_isolated(
        self, limiter: FixedWindowLimiter
    ) -> None:
        config1 = WindowConfig(
            limit=10,
            window_seconds=60,
            project_uuid=_PROJECT_UUID,
            route_name='route-a',
            scenario_type=ScenarioType.REQUEST_RATE,
        )
        config2 = WindowConfig(
            limit=10,
            window_seconds=60,
            project_uuid=_PROJECT_UUID,
            route_name='route-b',
            scenario_type=ScenarioType.REQUEST_RATE,
        )

        await limiter.hit(config1, cost=5)

        stats1 = await limiter.get_window_stats(config1)
        stats2 = await limiter.get_window_stats(config2)

        assert stats1.remaining == 5
        assert stats2.remaining == 10  # Different route, full capacity

    @pytest.mark.asyncio
    async def test_different_scenario_types_are_isolated(
        self, limiter: FixedWindowLimiter
    ) -> None:
        config_request = WindowConfig(
            limit=10,
            window_seconds=60,
            project_uuid=_PROJECT_UUID,
            route_name='gpt-4',
            scenario_type=ScenarioType.REQUEST_RATE,
        )
        config_input = WindowConfig(
            limit=1000,
            window_seconds=60,
            project_uuid=_PROJECT_UUID,
            route_name='gpt-4',
            scenario_type=ScenarioType.TOKEN_INPUT,
        )
        config_output = WindowConfig(
            limit=500,
            window_seconds=60,
            project_uuid=_PROJECT_UUID,
            route_name='gpt-4',
            scenario_type=ScenarioType.TOKEN_OUTPUT,
        )

        await limiter.hit(config_request, cost=5)
        await limiter.hit(config_input, cost=100)

        stats_request = await limiter.get_window_stats(config_request)
        stats_input = await limiter.get_window_stats(config_input)
        stats_output = await limiter.get_window_stats(config_output)

        assert stats_request.remaining == 5
        assert stats_input.remaining == 900
        assert stats_output.remaining == 500  # Not touched, full capacity


class TestKeyStructure:
    """Tests for the Redis key structure."""

    def test_build_key_format(self, limiter: FixedWindowLimiter) -> None:
        """A config with no project falls back to the unscoped key format."""
        config = WindowConfig(
            limit=10,
            window_seconds=60,
            project_uuid=_PROJECT_UUID,
            route_name='gpt-4',
            scenario_type=ScenarioType.TOKEN_INPUT,
        )
        key = limiter._build_key(config)
        assert key == f'limiter:{_PROJECT_UUID}:gpt-4:token_input:fixed:60'

    def test_build_key_with_different_scenario(
        self, limiter: FixedWindowLimiter
    ) -> None:
        config = WindowConfig(
            limit=10,
            window_seconds=3600,
            project_uuid=_PROJECT_UUID,
            route_name='claude-3-sonnet',
            scenario_type=ScenarioType.REQUEST_RATE,
        )
        key = limiter._build_key(config)
        assert key == f'limiter:{_PROJECT_UUID}:claude-3-sonnet:request_rate:fixed:3600'

    def test_build_key_with_token_output(self, limiter: FixedWindowLimiter) -> None:
        config = WindowConfig(
            limit=500,
            window_seconds=120,
            project_uuid=_PROJECT_UUID,
            route_name='my-model',
            scenario_type=ScenarioType.TOKEN_OUTPUT,
        )
        key = limiter._build_key(config)
        assert key == f'limiter:{_PROJECT_UUID}:my-model:token_output:fixed:120'

    def test_build_key_includes_project_uuid(self, limiter: FixedWindowLimiter) -> None:
        """A project-scoped config puts the project ahead of the route."""
        config = WindowConfig(
            limit=10,
            window_seconds=60,
            route_name='my-route',
            scenario_type=ScenarioType.REQUEST_RATE,
            project_uuid='2f1c6d4e-0000-4000-8000-000000000001',
        )
        key = limiter._build_key(config)
        assert (
            key
            == 'limiter:2f1c6d4e-0000-4000-8000-000000000001:my-route:request_rate:fixed:60'
        )

    def test_same_route_name_in_two_projects_gets_distinct_keys(
        self, limiter: FixedWindowLimiter
    ) -> None:
        """Regression: route names are unique only within a project."""
        first, second = (
            WindowConfig(
                limit=10,
                window_seconds=60,
                route_name='default',
                scenario_type=ScenarioType.REQUEST_RATE,
                project_uuid=uuid,
            )
            for uuid in (
                '2f1c6d4e-0000-4000-8000-000000000001',
                '2f1c6d4e-0000-4000-8000-000000000002',
            )
        )
        assert limiter._build_key(first) != limiter._build_key(second)


class TestProjectIsolation:
    """Two projects sharing a route name must not share a window."""

    @staticmethod
    def _config(project_uuid: str) -> WindowConfig:
        return WindowConfig(
            limit=2,
            window_seconds=60,
            route_name='default',
            scenario_type=ScenarioType.REQUEST_RATE,
            project_uuid=project_uuid,
        )

    @pytest.mark.asyncio
    async def test_windows_are_independent(self, limiter: FixedWindowLimiter) -> None:
        project_a = self._config('2f1c6d4e-0000-4000-8000-00000000000a')
        project_b = self._config('2f1c6d4e-0000-4000-8000-00000000000b')

        # Exhaust project A's window.
        assert await limiter.hit(project_a) is True
        assert await limiter.hit(project_a) is True
        assert await limiter.hit(project_a) is False

        # Project B is untouched and still has its full allowance.
        stats_b = await limiter.get_window_stats(project_b)
        assert stats_b.remaining == 2
        assert await limiter.hit(project_b) is True

    @pytest.mark.asyncio
    async def test_unscoped_configs_still_share_a_window(
        self, limiter: FixedWindowLimiter
    ) -> None:
        """Without a project the pre-fix behaviour is preserved deliberately."""
        first = WindowConfig(
            limit=2,
            window_seconds=60,
            project_uuid=_PROJECT_UUID,
            route_name='default',
            scenario_type=ScenarioType.REQUEST_RATE,
        )
        second = WindowConfig(
            limit=2,
            window_seconds=60,
            project_uuid=_PROJECT_UUID,
            route_name='default',
            scenario_type=ScenarioType.REQUEST_RATE,
        )
        await limiter.hit(first)
        stats = await limiter.get_window_stats(second)
        assert stats.remaining == 1
