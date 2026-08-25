"""Tests for AlignedFixedWindowLimiter."""

import datetime

from freezegun import freeze_time
import pytest

from radicalbit_ai_gateway.limiter import (
    AlignedFixedWindowLimiter,
    InMemoryStorage,
    ScenarioType,
)
from radicalbit_ai_gateway.limiter.window_config import WindowConfig

_PROJECT_UUID = '2f1c6d4e-0000-4000-8000-0000000000aa'


@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


@pytest.fixture
def limiter(storage: InMemoryStorage) -> AlignedFixedWindowLimiter:
    return AlignedFixedWindowLimiter(storage)


@pytest.fixture
def config() -> WindowConfig:
    return WindowConfig(
        limit=10,
        window_seconds=60,
        project_uuid=_PROJECT_UUID,
        route_name='test-route',
        scenario_type=ScenarioType.REQUEST_RATE,
    )


class TestAlignedWindowBoundaries:
    """Tests for aligned window boundary calculations."""

    @pytest.mark.asyncio
    async def test_hourly_window_starts_at_minute_zero(
        self, limiter: AlignedFixedWindowLimiter
    ) -> None:
        """Verify 1-hour windows align to :00 minutes."""
        # Set time at 15:30:45 - should align to 15:00:00
        initial_datetime = datetime.datetime(
            year=2025, month=6, day=25, hour=15, minute=30, second=45
        )
        config = WindowConfig(
            limit=10,
            window_seconds=3600,
            project_uuid=_PROJECT_UUID,
            route_name='test',
            scenario_type=ScenarioType.REQUEST_RATE,
        )

        with freeze_time(initial_datetime):
            await limiter.hit(config)
            stats = await limiter.get_window_stats(config)

            # Reset time should be at 16:00:00 (next hour boundary)
            expected_reset = datetime.datetime(
                year=2025, month=6, day=25, hour=16, minute=0, second=0
            ).timestamp()
            assert abs(stats.reset_time - expected_reset) < 1

    @pytest.mark.asyncio
    async def test_daily_window_starts_at_midnight_utc(
        self, limiter: AlignedFixedWindowLimiter
    ) -> None:
        """Verify 1-day windows align to 00:00:00 UTC."""
        # Set time at 15:30:45 - should align to 00:00:00 UTC of that day
        initial_datetime = datetime.datetime(
            year=2025, month=6, day=25, hour=15, minute=30, second=45
        )
        config = WindowConfig(
            limit=10,
            window_seconds=86400,
            project_uuid=_PROJECT_UUID,
            route_name='test',
            scenario_type=ScenarioType.REQUEST_RATE,
        )

        with freeze_time(initial_datetime):
            await limiter.hit(config)
            stats = await limiter.get_window_stats(config)

            # Reset time should be at next day 00:00:00
            expected_reset = datetime.datetime(
                year=2025, month=6, day=26, hour=0, minute=0, second=0
            ).timestamp()
            assert abs(stats.reset_time - expected_reset) < 1

    @pytest.mark.asyncio
    async def test_twelve_hour_window_aligns_to_midnight_or_noon(
        self, limiter: AlignedFixedWindowLimiter
    ) -> None:
        """Verify 12-hour windows align to 00:00 or 12:00 UTC."""
        # Test at 8:30 AM - should align to 00:00
        morning_datetime = datetime.datetime(
            year=2025, month=6, day=25, hour=8, minute=30, second=0
        )
        config = WindowConfig(
            limit=10,
            window_seconds=43200,
            project_uuid=_PROJECT_UUID,
            route_name='test',
            scenario_type=ScenarioType.REQUEST_RATE,
        )

        with freeze_time(morning_datetime):
            await limiter.hit(config)
            stats = await limiter.get_window_stats(config)

            # Reset time should be at 12:00:00
            expected_reset = datetime.datetime(
                year=2025, month=6, day=25, hour=12, minute=0, second=0
            ).timestamp()
            assert abs(stats.reset_time - expected_reset) < 1

        # Test at 15:30 PM - should align to 12:00
        afternoon_datetime = datetime.datetime(
            year=2025, month=6, day=25, hour=15, minute=30, second=0
        )

        with freeze_time(afternoon_datetime):
            storage2 = InMemoryStorage()
            limiter2 = AlignedFixedWindowLimiter(storage2)
            await limiter2.hit(config)
            stats = await limiter2.get_window_stats(config)

            # Reset time should be at next day 00:00:00
            expected_reset = datetime.datetime(
                year=2025, month=6, day=26, hour=0, minute=0, second=0
            ).timestamp()
            assert abs(stats.reset_time - expected_reset) < 1

    @pytest.mark.asyncio
    async def test_window_resets_at_aligned_boundary(
        self, limiter: AlignedFixedWindowLimiter, config: WindowConfig
    ) -> None:
        """Counter resets at aligned boundary, not 60s after first hit."""
        # Set time at 15:00:30 (30 seconds into a 60-second window)
        initial_datetime = datetime.datetime(
            year=2025, month=6, day=25, hour=15, minute=0, second=30
        )

        with freeze_time(initial_datetime) as frozen_datetime:
            await limiter.hit(config, cost=5)
            stats = await limiter.get_window_stats(config)
            assert stats.remaining == 5

            # Advance 31 seconds to 15:01:01 (past the aligned boundary at 15:01:00)
            frozen_datetime.tick(31)

            # Window should have reset
            result = await limiter.test(config, cost=1)
            assert result is True  # Limit is available again

            await limiter.hit(config, cost=1)
            stats = await limiter.get_window_stats(config)
            assert stats.remaining == 9  # Only 1 consumed in new window

    @pytest.mark.asyncio
    async def test_different_window_start_resets_counter(
        self, limiter: AlignedFixedWindowLimiter, config: WindowConfig
    ) -> None:
        """Verify counter resets when window changes."""
        initial_datetime = datetime.datetime(
            year=2025, month=6, day=25, hour=15, minute=0, second=0
        )

        with freeze_time(initial_datetime) as frozen_datetime:
            # Consume in first window
            await limiter.hit(config, cost=7)
            stats1 = await limiter.get_window_stats(config)
            assert stats1.remaining == 3

            # Advance past window boundary
            frozen_datetime.tick(60)

            # New window should have full capacity
            await limiter.hit(config, cost=1)
            stats2 = await limiter.get_window_stats(config)
            assert stats2.remaining == 9


class TestHitMethod:
    """Tests for the hit() method."""

    @pytest.mark.asyncio
    async def test_hit_returns_true_when_under_limit(
        self, limiter: AlignedFixedWindowLimiter, config: WindowConfig
    ) -> None:
        result = await limiter.hit(config, cost=5)
        assert result is True

    @pytest.mark.asyncio
    async def test_hit_returns_true_at_exact_limit(
        self, limiter: AlignedFixedWindowLimiter, config: WindowConfig
    ) -> None:
        result = await limiter.hit(config, cost=10)
        assert result is True

    @pytest.mark.asyncio
    async def test_hit_returns_false_when_exceeds_limit(
        self, limiter: AlignedFixedWindowLimiter, config: WindowConfig
    ) -> None:
        result = await limiter.hit(config, cost=11)
        assert result is False

    @pytest.mark.asyncio
    async def test_hit_consumes_capacity(
        self, limiter: AlignedFixedWindowLimiter, config: WindowConfig
    ) -> None:
        await limiter.hit(config, cost=3)
        stats = await limiter.get_window_stats(config)
        assert stats.remaining == 7

    @pytest.mark.asyncio
    async def test_hit_accumulates(
        self, limiter: AlignedFixedWindowLimiter, config: WindowConfig
    ) -> None:
        await limiter.hit(config, cost=3)
        await limiter.hit(config, cost=4)
        stats = await limiter.get_window_stats(config)
        assert stats.remaining == 3

    @pytest.mark.asyncio
    async def test_hit_still_consumes_when_exceeds_limit(
        self, limiter: AlignedFixedWindowLimiter, config: WindowConfig
    ) -> None:
        # This is important: hit() still increments the counter even if limit exceeded
        result = await limiter.hit(config, cost=15)
        assert result is False  # Over limit

        stats = await limiter.get_window_stats(config)
        assert stats.remaining == 0  # Clamped to 0


class TestTestMethod:
    """Tests for the test() method."""

    @pytest.mark.asyncio
    async def test_test_allowed_when_under_limit(
        self, limiter: AlignedFixedWindowLimiter, config: WindowConfig
    ) -> None:
        result = await limiter.test(config, cost=5)
        assert result is True

    @pytest.mark.asyncio
    async def test_test_denied_when_exceeds_limit(
        self, limiter: AlignedFixedWindowLimiter, config: WindowConfig
    ) -> None:
        result = await limiter.test(config, cost=11)
        assert result is False

    @pytest.mark.asyncio
    async def test_test_allowed_at_exact_limit(
        self, limiter: AlignedFixedWindowLimiter, config: WindowConfig
    ) -> None:
        result = await limiter.test(config, cost=10)
        assert result is True

    @pytest.mark.asyncio
    async def test_test_does_not_consume(
        self, limiter: AlignedFixedWindowLimiter, config: WindowConfig
    ) -> None:
        # Test should not consume
        await limiter.test(config, cost=5)
        stats = await limiter.get_window_stats(config)
        assert stats.remaining == 10  # Still full capacity
        assert stats.window_id is None  # No window created

    @pytest.mark.asyncio
    async def test_test_after_hit(
        self, limiter: AlignedFixedWindowLimiter, config: WindowConfig
    ) -> None:
        # Consume 7
        await limiter.hit(config, cost=7)

        # Test if 3 more is allowed (7 + 3 = 10, should be allowed)
        result = await limiter.test(config, cost=3)
        assert result is True

        # Test if 4 more is allowed (7 + 4 = 11, should be denied)
        result = await limiter.test(config, cost=4)
        assert result is False


class TestGetWindowStats:
    """Tests for the get_window_stats() method."""

    @pytest.mark.asyncio
    async def test_stats_for_new_window(
        self, limiter: AlignedFixedWindowLimiter, config: WindowConfig
    ) -> None:
        initial_datetime = datetime.datetime(
            year=2025, month=6, day=25, hour=15, minute=0, second=30
        )
        with freeze_time(initial_datetime):
            stats = await limiter.get_window_stats(config)
            assert stats.remaining == 10
            assert stats.window_id is None  # No window exists yet
            # reset_time should be at aligned boundary (15:01:00)
            expected_reset = datetime.datetime(
                year=2025, month=6, day=25, hour=15, minute=1, second=0
            ).timestamp()
            assert abs(stats.reset_time - expected_reset) < 1

    @pytest.mark.asyncio
    async def test_stats_after_consumption(
        self, limiter: AlignedFixedWindowLimiter, config: WindowConfig
    ) -> None:
        await limiter.hit(config, cost=4)
        stats = await limiter.get_window_stats(config)
        assert stats.remaining == 6
        assert stats.window_id is not None  # Window created

    @pytest.mark.asyncio
    async def test_stats_reset_time_is_aligned(
        self, limiter: AlignedFixedWindowLimiter, config: WindowConfig
    ) -> None:
        """Reset time is aligned boundary, not now + window_seconds."""
        initial_datetime = datetime.datetime(
            year=2025, month=6, day=25, hour=15, minute=0, second=30
        )
        with freeze_time(initial_datetime):
            await limiter.hit(config, cost=1)
            stats = await limiter.get_window_stats(config)
            # reset_time should be at 15:01:00, not 15:01:30
            expected_reset = datetime.datetime(
                year=2025, month=6, day=25, hour=15, minute=1, second=0
            ).timestamp()
            assert abs(stats.reset_time - expected_reset) < 1

    @pytest.mark.asyncio
    async def test_window_id_remains_constant_within_window(
        self, limiter: AlignedFixedWindowLimiter, config: WindowConfig
    ) -> None:
        await limiter.hit(config, cost=1)
        stats1 = await limiter.get_window_stats(config)

        await limiter.hit(config, cost=2)
        stats2 = await limiter.get_window_stats(config)

        assert stats1.window_id == stats2.window_id

    @pytest.mark.asyncio
    async def test_new_window_id_after_aligned_reset(
        self, limiter: AlignedFixedWindowLimiter, config: WindowConfig
    ) -> None:
        initial_datetime = datetime.datetime(
            year=2025, month=6, day=25, hour=15, minute=0, second=0
        )
        with freeze_time(initial_datetime) as frozen_datetime:
            await limiter.hit(config, cost=1)
            stats1 = await limiter.get_window_stats(config)
            assert stats1.window_id is not None

            # Advance past window boundary
            frozen_datetime.tick(60)

            # Create new window
            await limiter.hit(config, cost=1)
            stats2 = await limiter.get_window_stats(config)
            assert stats2.window_id is not None
            assert stats1.window_id != stats2.window_id


class TestKeyIsolation:
    """Tests for key isolation between routes and scenarios."""

    @pytest.mark.asyncio
    async def test_different_routes_are_isolated(
        self, limiter: AlignedFixedWindowLimiter
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


class TestWindowReset:
    """Tests for window reset behavior."""

    @pytest.mark.asyncio
    async def test_window_resets_after_ttl(
        self, limiter: AlignedFixedWindowLimiter, config: WindowConfig
    ) -> None:
        # Use an aligned time for predictable window boundaries
        initial_datetime = datetime.datetime(
            year=2025, month=6, day=25, hour=15, minute=0, second=0
        )
        with freeze_time(initial_datetime) as frozen_datetime:
            # Use up the limit
            await limiter.hit(config, cost=10)

            # Should be blocked
            result = await limiter.test(config, cost=1)
            assert result is False

            # Advance past window boundary (60 seconds for this config)
            frozen_datetime.tick(61)

            # Should be allowed again
            result = await limiter.test(config, cost=1)
            assert result is True

    @pytest.mark.asyncio
    async def test_remaining_shows_zero_when_exceeded(
        self, limiter: AlignedFixedWindowLimiter, config: WindowConfig
    ) -> None:
        await limiter.hit(config, cost=15)  # Exceeds limit
        stats = await limiter.get_window_stats(config)
        assert stats.remaining == 0


class TestKeyStructure:
    """Tests for the Redis key structure."""

    def test_build_key_format(self, limiter: AlignedFixedWindowLimiter) -> None:
        """A config with no project falls back to the unscoped key format."""
        config = WindowConfig(
            limit=10,
            window_seconds=60,
            project_uuid=_PROJECT_UUID,
            route_name='gpt-4',
            scenario_type=ScenarioType.TOKEN_INPUT,
        )
        key = limiter._build_key(config)
        assert key == f'limiter:{_PROJECT_UUID}:gpt-4:token_input:aligned:60'

    def test_build_key_with_different_scenario(
        self, limiter: AlignedFixedWindowLimiter
    ) -> None:
        config = WindowConfig(
            limit=10,
            window_seconds=3600,
            project_uuid=_PROJECT_UUID,
            route_name='claude-3-sonnet',
            scenario_type=ScenarioType.REQUEST_RATE,
        )
        key = limiter._build_key(config)
        assert (
            key == f'limiter:{_PROJECT_UUID}:claude-3-sonnet:request_rate:aligned:3600'
        )

    def test_build_key_includes_project_uuid(
        self, limiter: AlignedFixedWindowLimiter
    ) -> None:
        """A project-scoped config puts the project ahead of the route."""
        config = WindowConfig(
            limit=10,
            window_seconds=3600,
            route_name='my-route',
            scenario_type=ScenarioType.BUDGET,
            project_uuid='2f1c6d4e-0000-4000-8000-000000000001',
        )
        key = limiter._build_key(config)
        assert (
            key
            == 'limiter:2f1c6d4e-0000-4000-8000-000000000001:my-route:budget:aligned:3600'
        )

    def test_same_route_name_in_two_projects_gets_distinct_keys(
        self, limiter: AlignedFixedWindowLimiter
    ) -> None:
        """Regression: route names are unique only within a project."""
        first, second = (
            WindowConfig(
                limit=10,
                window_seconds=3600,
                route_name='default',
                scenario_type=ScenarioType.TOKEN_INPUT,
                project_uuid=uuid,
            )
            for uuid in (
                '2f1c6d4e-0000-4000-8000-000000000001',
                '2f1c6d4e-0000-4000-8000-000000000002',
            )
        )
        assert limiter._build_key(first) != limiter._build_key(second)
