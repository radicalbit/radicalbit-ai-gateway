"""Tests for FixedWindowLimiter and AlignedFixedWindowLimiter.

Both count a cost against a limit per window; they differ in where a window
starts. A fixed window starts at its first hit, an aligned one on the UTC clock.
"""

from datetime import UTC, datetime

from freezegun import freeze_time
import pytest

from radicalbit_ai_gateway.limiter import (
    AlignedFixedWindowLimiter,
    FixedWindowLimiter,
    InMemoryStorage,
    ScenarioType,
)
from radicalbit_ai_gateway.limiter.window_config import WindowConfig

_PROJECT_UUID = '2f1c6d4e-0000-4000-8000-0000000000aa'
_LIMITERS = {'fixed': FixedWindowLimiter, 'aligned': AlignedFixedWindowLimiter}
# Aligned to the minute, so both limiters' 60-second windows start here.
_T0 = datetime(2025, 6, 25, 15, 0, tzinfo=UTC)


def _config(
    limit: int = 10,
    window_seconds: int = 60,
    route_name: str = 'test-route',
    scenario_type: ScenarioType = ScenarioType.REQUEST_RATE,
    project_uuid: str = _PROJECT_UUID,
) -> WindowConfig:
    return WindowConfig(
        limit=limit,
        window_seconds=window_seconds,
        project_uuid=project_uuid,
        route_name=route_name,
        scenario_type=scenario_type,
    )


@pytest.fixture(params=list(_LIMITERS))
def kind(request) -> str:
    return request.param


@pytest.fixture
def limiter(kind: str) -> FixedWindowLimiter | AlignedFixedWindowLimiter:
    return _LIMITERS[kind](InMemoryStorage())


@pytest.fixture
def config() -> WindowConfig:
    return _config()


@pytest.mark.parametrize(
    ('cost', 'allowed'),
    [
        pytest.param(5, True, id='under-limit'),
        pytest.param(10, True, id='at-exact-limit'),
        pytest.param(11, False, id='over-limit'),
    ],
)
async def test_test_and_hit_allow_a_cost_up_to_the_limit(
    limiter, config, cost, allowed
):
    assert await limiter.test(config, cost=cost) is allowed
    assert await limiter.hit(config, cost=cost) is allowed


async def test_test_does_not_consume(limiter, config) -> None:
    await limiter.test(config, cost=5)

    stats = await limiter.get_window_stats(config)
    assert stats.remaining == 10
    assert stats.window_id is None


async def test_test_counts_what_hit_consumed(limiter, config) -> None:
    await limiter.hit(config, cost=7)

    assert await limiter.test(config, cost=3) is True
    assert await limiter.test(config, cost=4) is False


@pytest.mark.parametrize(
    ('costs', 'remaining'),
    [
        pytest.param([3], 7, id='consumes'),
        pytest.param([4], 6, id='consumes-more'),
        pytest.param([3, 4], 3, id='accumulates'),
        pytest.param([15], 0, id='consumes-past-the-limit-clamped-to-zero'),
    ],
)
async def test_hit_consumes_capacity_in_one_window(
    limiter, config, costs, remaining
) -> None:
    for cost in costs:
        await limiter.hit(config, cost=cost)

    stats = await limiter.get_window_stats(config)
    assert stats.remaining == remaining
    assert stats.window_id is not None


async def test_a_window_keeps_its_id_until_it_resets_to_full_capacity(
    limiter, config, kind
) -> None:
    with freeze_time(_T0) as frozen:
        await limiter.hit(config, cost=7)
        first = await limiter.get_window_stats(config)
        assert first.remaining == 3
        await limiter.hit(config, cost=3)
        assert (await limiter.get_window_stats(config)).window_id == first.window_id
        assert await limiter.test(config, cost=1) is False

        # The aligned window ends on the minute; the fixed one 60s after its hit.
        frozen.tick(60 if kind == 'aligned' else 61)

        assert await limiter.test(config, cost=1) is True
        await limiter.hit(config, cost=1)
        second = await limiter.get_window_stats(config)
        assert second.remaining == 9
        assert second.window_id is not None
        assert second.window_id != first.window_id


@pytest.mark.parametrize(
    ('kind', 'reset_at'),
    [
        pytest.param(
            'fixed',
            datetime(2025, 6, 25, 15, 1, 30, tzinfo=UTC),
            id='fixed-60s-after-now',
        ),
        pytest.param(
            'aligned',
            datetime(2025, 6, 25, 15, 1, tzinfo=UTC),
            id='aligned-on-the-minute',
        ),
    ],
)
async def test_a_window_resets_at_its_boundary_before_and_after_the_first_hit(
    limiter, config, reset_at
) -> None:
    with freeze_time(datetime(2025, 6, 25, 15, 0, 30, tzinfo=UTC)):
        empty = await limiter.get_window_stats(config)
        assert empty.remaining == 10
        assert empty.window_id is None
        assert abs(empty.reset_time - reset_at.timestamp()) < 1

        await limiter.hit(config, cost=1)

        stats = await limiter.get_window_stats(config)
        assert abs(stats.reset_time - reset_at.timestamp()) < 1


@pytest.mark.parametrize(
    ('window_seconds', 'now', 'reset_at'),
    [
        pytest.param(
            3600,
            datetime(2025, 6, 25, 15, 30, 45),
            datetime(2025, 6, 25, 16),
            id='hour-at-minute-zero',
        ),
        pytest.param(
            86400,
            datetime(2025, 6, 25, 15, 30, 45),
            datetime(2025, 6, 26),
            id='day-at-midnight-utc',
        ),
        pytest.param(
            43200,
            datetime(2025, 6, 25, 8, 30),
            datetime(2025, 6, 25, 12),
            id='twelve-hours-at-noon',
        ),
        pytest.param(
            43200,
            datetime(2025, 6, 25, 15, 30),
            datetime(2025, 6, 26),
            id='twelve-hours-at-midnight',
        ),
    ],
)
async def test_an_aligned_window_resets_on_the_utc_clock(
    window_seconds, now, reset_at
) -> None:
    limiter = AlignedFixedWindowLimiter(InMemoryStorage())
    config = _config(window_seconds=window_seconds)

    with freeze_time(now.replace(tzinfo=UTC)):
        await limiter.hit(config)
        stats = await limiter.get_window_stats(config)

    assert abs(stats.reset_time - reset_at.replace(tzinfo=UTC).timestamp()) < 1


async def test_an_aligned_window_resets_at_the_boundary_not_60s_after_the_first_hit() -> (
    None
):
    limiter = AlignedFixedWindowLimiter(InMemoryStorage())
    config = _config()

    with freeze_time(datetime(2025, 6, 25, 15, 0, 30, tzinfo=UTC)) as frozen:
        await limiter.hit(config, cost=5)
        assert (await limiter.get_window_stats(config)).remaining == 5

        frozen.tick(31)  # 15:01:01, past the boundary at 15:01:00

        assert await limiter.test(config, cost=1) is True
        await limiter.hit(config, cost=1)
        assert (await limiter.get_window_stats(config)).remaining == 9


async def test_routes_and_scenarios_have_their_own_windows(limiter) -> None:
    request = _config(route_name='route-a')
    other_route = _config(route_name='route-b')
    token_input = _config(
        limit=1000, route_name='route-a', scenario_type=ScenarioType.TOKEN_INPUT
    )
    token_output = _config(
        limit=500, route_name='route-a', scenario_type=ScenarioType.TOKEN_OUTPUT
    )

    await limiter.hit(request, cost=5)
    await limiter.hit(token_input, cost=100)

    assert (await limiter.get_window_stats(request)).remaining == 5
    assert (await limiter.get_window_stats(other_route)).remaining == 10
    assert (await limiter.get_window_stats(token_input)).remaining == 900
    assert (await limiter.get_window_stats(token_output)).remaining == 500


async def test_two_projects_sharing_a_route_name_have_their_own_windows(
    limiter,
) -> None:
    project_a = _config(
        limit=2,
        route_name='default',
        project_uuid='2f1c6d4e-0000-4000-8000-00000000000a',
    )
    project_b = _config(
        limit=2,
        route_name='default',
        project_uuid='2f1c6d4e-0000-4000-8000-00000000000b',
    )

    assert await limiter.hit(project_a) is True
    assert await limiter.hit(project_a) is True
    assert await limiter.hit(project_a) is False

    assert (await limiter.get_window_stats(project_b)).remaining == 2
    assert await limiter.hit(project_b) is True


async def test_the_same_project_and_route_share_a_window(limiter) -> None:
    """The counterpart to isolation: scoping must not over-isolate."""
    await limiter.hit(_config(limit=2, route_name='default'))

    stats = await limiter.get_window_stats(_config(limit=2, route_name='default'))
    assert stats.remaining == 1


@pytest.mark.parametrize(
    ('config', 'key'),
    [
        pytest.param(
            _config(route_name='gpt-4', scenario_type=ScenarioType.TOKEN_INPUT),
            f'limiter:{_PROJECT_UUID}:gpt-4:token_input:{{kind}}:60',
            id='token-input',
        ),
        pytest.param(
            _config(window_seconds=3600, route_name='claude-3-sonnet'),
            f'limiter:{_PROJECT_UUID}:claude-3-sonnet:request_rate:{{kind}}:3600',
            id='request-rate',
        ),
        pytest.param(
            _config(
                limit=500,
                window_seconds=120,
                route_name='my-model',
                scenario_type=ScenarioType.TOKEN_OUTPUT,
            ),
            f'limiter:{_PROJECT_UUID}:my-model:token_output:{{kind}}:120',
            id='token-output',
        ),
        pytest.param(
            _config(
                window_seconds=3600,
                route_name='my-route',
                scenario_type=ScenarioType.BUDGET,
                project_uuid='2f1c6d4e-0000-4000-8000-000000000001',
            ),
            'limiter:2f1c6d4e-0000-4000-8000-000000000001:my-route:budget:{kind}:3600',
            id='budget-project-ahead-of-route',
        ),
    ],
)
def test_the_key_is_project_route_scenario_window_type_and_seconds(
    limiter, kind, config, key
) -> None:
    assert limiter._build_key(config) == key.format(kind=kind)


def test_the_same_route_name_in_two_projects_gets_distinct_keys(limiter) -> None:
    """Regression: route names are unique only within a project."""
    first, second = (
        _config(
            route_name='default', project_uuid=f'2f1c6d4e-0000-4000-8000-00000000000{n}'
        )
        for n in (1, 2)
    )

    assert limiter._build_key(first) != limiter._build_key(second)
