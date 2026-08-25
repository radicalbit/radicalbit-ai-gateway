import datetime
from unittest.mock import AsyncMock, patch

from freezegun import freeze_time
import pytest

from tests.common.db_mock import API_KEY_UUID, GROUP_UUID, REQUEST_UUID

from radicalbit_ai_gateway.limiting.rate_limiter import RequestRateLimiter
from radicalbit_ai_gateway.models.limiting import LimitingAlgorithmType, RateLimiting
from radicalbit_ai_gateway.utils.exceptions import RequestRateLimitExceeded

_PROJECT_UUID = '2f1c6d4e-0000-4000-8000-0000000000aa'


@pytest.fixture(autouse=True)
def mock_emit_event():
    """Mock emit_event for all tests in this module."""
    with patch('radicalbit_ai_gateway.limiting.rate_limiter.emit_event', autospec=True):
        yield


class TestRequestRateLimiter:
    def test_init_without_config(self):
        """Test RequestRateLimiter initialization without any configuration."""
        limiter = RequestRateLimiter(
            project_uuid=_PROJECT_UUID, route_name='rb-gateway'
        )
        assert limiter.limiter is None

    def test_init_with_config(self):
        """Test RequestRateLimiter initialization with configuration."""
        config = RateLimiting(
            algorithm=LimitingAlgorithmType.FIXED_WINDOW,
            max_requests=10,
            window_size='1 minute',
        )
        limiter = RequestRateLimiter(
            project_uuid=_PROJECT_UUID,
            route_name='rb-gateway',
            rate_limiting_config=config,
        )
        assert limiter.limiter is not None

    def test_init_without_max_requests_raises_error(self):
        """Test that initialization without max_requests raises ValueError."""
        config = RateLimiting(window_size='1 minute')  # No max_requests set
        with pytest.raises(
            ValueError, match='max_requests must be set for rate limiting'
        ):
            RequestRateLimiter(
                project_uuid=_PROJECT_UUID,
                route_name='rb-gateway',
                rate_limiting_config=config,
            )

    @pytest.mark.asyncio
    async def test_check_request_no_config(self):
        """Test request checking without configuration does nothing."""
        limiter = RequestRateLimiter(
            project_uuid=_PROJECT_UUID, route_name='rb-gateway'
        )
        # Should not raise any exception
        await limiter._check_request(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            group_uuid=str(GROUP_UUID),
            api_key_name='fake-name',
            group_name='test-group',
        )
        # count_request with no config should also be a no-op
        await limiter._count_request()

    @pytest.mark.asyncio
    async def test_check_request_within_limit_and_count_consumes(self):
        """Test request checking within limit, and then count_request consumes."""
        config = RateLimiting(max_requests=5, window_size='1 minute')
        limiter = RequestRateLimiter(
            project_uuid=_PROJECT_UUID,
            route_name='rb-gateway',
            rate_limiting_config=config,
        )

        # check_request should NOT consume
        with patch.object(limiter.limiter, 'hit', new=AsyncMock()) as mock_hit:
            await limiter._check_request(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                group_name='test-group',
            )
            mock_hit.assert_not_called()

        # count_request should consume (hit)
        with patch.object(limiter.limiter, 'hit', new=AsyncMock()) as mock_hit2:
            await limiter._count_request()
            mock_hit2.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_request_exceeds_limit(self):
        """Test request checking that exceeds the limit (check-only, no hit)."""
        config = RateLimiting(max_requests=2, window_size='1 minute')
        limiter = RequestRateLimiter(
            project_uuid=_PROJECT_UUID,
            route_name='rb-gateway',
            rate_limiting_config=config,
        )

        # First request: check passes, then we consume
        await limiter._check_request(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            group_uuid=str(GROUP_UUID),
            api_key_name='fake-name',
            group_name='test-group',
        )
        await limiter._count_request()

        # Second request: check passes, then we consume
        await limiter._check_request(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            group_uuid=str(GROUP_UUID),
            api_key_name='fake-name',
            group_name='test-group',
        )
        await limiter._count_request()

        # Third: check should fail BEFORE consuming
        with pytest.raises(RequestRateLimitExceeded) as exc:
            await limiter._check_request(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                group_name='test-group',
            )

        msg = getattr(exc.value, 'log_message', str(exc.value))
        assert '[RATE LIMIT]' in msg
        assert '[route=rb-gateway]' in msg
        assert '[kind=REQUEST]' in msg
        assert '[limit=2]' in msg
        assert '[window=1 minute]' in msg
        assert '[action=BLOCK]' in msg

    @pytest.mark.asyncio
    async def test_request_accumulates_over_multiple_calls(self):
        """Test that consumption accumulates over multiple requests."""
        config = RateLimiting(max_requests=3, window_size='1 minute')
        limiter = RequestRateLimiter(
            project_uuid=_PROJECT_UUID,
            route_name='rb-gateway',
            rate_limiting_config=config,
        )

        # First 2: check passes, then we consume via count_request
        await limiter._check_request(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            group_uuid=str(GROUP_UUID),
            api_key_name='fake-name',
            group_name='test-group',
        )
        await limiter._count_request()

        await limiter._check_request(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            group_uuid=str(GROUP_UUID),
            api_key_name='fake-name',
            group_name='test-group',
        )
        await limiter._count_request()

        await limiter._check_request(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            group_uuid=str(GROUP_UUID),
            api_key_name='fake-name',
            group_name='test-group',
        )
        await limiter._count_request()

        # Fourth: check should fail BEFORE consuming
        with pytest.raises(RequestRateLimitExceeded):
            await limiter._check_request(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                group_name='test-group',
            )

    @pytest.mark.asyncio
    async def test_window_reset(self):
        """Test that the window resets after time passes."""
        initial_datetime = datetime.datetime(
            year=2025, month=6, day=25, hour=15, minute=0, second=0
        )
        with freeze_time(initial_datetime) as frozen_datetime:
            config = RateLimiting(max_requests=2, window_size='10 second')
            limiter = RequestRateLimiter(
                project_uuid=_PROJECT_UUID,
                route_name='rb-gateway',
                rate_limiting_config=config,
            )

            # Use up limit
            await limiter._check_request(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                group_name='test-group',
            )
            await limiter._count_request()

            await limiter._check_request(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                group_name='test-group',
            )
            await limiter._count_request()

            # Should be blocked
            with pytest.raises(RequestRateLimitExceeded):
                await limiter._check_request(
                    request_uuid=str(REQUEST_UUID),
                    api_key_uuid=str(API_KEY_UUID),
                    group_uuid=str(GROUP_UUID),
                    api_key_name='fake-name',
                    group_name='test-group',
                )

            # Advance past window
            frozen_datetime.tick(11)

            # Should work again
            await limiter._check_request(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                group_name='test-group',
            )
            await limiter._count_request()

    def test_window_size_formats(self):
        """Test different window size formats."""
        # Test with string format
        config = RateLimiting(max_requests=100, window_size='1 minute')
        limiter = RequestRateLimiter(
            project_uuid=_PROJECT_UUID,
            route_name='rb-gateway',
            rate_limiting_config=config,
        )
        assert limiter.limiter is not None

        # Test with per-second format
        config2 = RateLimiting(max_requests=100, window_size='100 seconds')
        limiter2 = RequestRateLimiter(
            project_uuid=_PROJECT_UUID,
            route_name='rb-gateway',
            rate_limiting_config=config2,
        )
        assert limiter2.limiter is not None


class TestProjectScoping:
    """Route names are unique only within a project, so keys must carry it."""

    @staticmethod
    def _limiter(project_uuid: str) -> RequestRateLimiter:
        return RequestRateLimiter(
            project_uuid=project_uuid,
            route_name='default',
            rate_limiting_config=RateLimiting(max_requests=2, window_size='1 minute'),
        )

    def test_project_uuid_scopes_the_key_but_not_the_route_name(self):
        """Telemetry keeps reporting the bare route; only the key is scoped."""
        project_uuid = '2f1c6d4e-0000-4000-8000-00000000000a'
        limiter = self._limiter(project_uuid)

        assert limiter.route_name == 'default'
        assert limiter.item.route_name == 'default'
        assert limiter.item.project_uuid == project_uuid
        assert limiter.limiter._build_key(limiter.item).startswith(
            f'limiter:{project_uuid}:default:request_rate:'
        )

    def test_project_uuid_is_mandatory(self):
        """There is no unscoped window: the key always names a project."""
        with pytest.raises(TypeError):
            RequestRateLimiter(
                route_name='default',
                rate_limiting_config=RateLimiting(
                    max_requests=2, window_size='1 minute'
                ),
            )

    @pytest.mark.asyncio
    async def test_two_projects_do_not_share_the_window(self):
        """Regression for the cross-project window collision."""
        project_a = self._limiter('2f1c6d4e-0000-4000-8000-00000000000a')
        project_b = self._limiter('2f1c6d4e-0000-4000-8000-00000000000b')
        # Both limiters must talk to the same storage for the test to mean
        # anything — in production that is the shared Redis.
        project_b.storage = project_a.storage
        project_b.limiter._storage = project_a.limiter._storage

        args = {
            'request_uuid': str(REQUEST_UUID),
            'api_key_uuid': str(API_KEY_UUID),
            'group_uuid': str(GROUP_UUID),
            'api_key_name': 'fake-name',
            'group_name': 'test-group',
        }

        # Exhaust project A's allowance of 2.
        await project_a.check_and_count_request(**args)
        await project_a.check_and_count_request(**args)
        with pytest.raises(RequestRateLimitExceeded):
            await project_a.check_and_count_request(**args)

        # Project B, same route name, is untouched.
        await project_b.check_and_count_request(**args)
        await project_b.check_and_count_request(**args)
        with pytest.raises(RequestRateLimitExceeded):
            await project_b.check_and_count_request(**args)
