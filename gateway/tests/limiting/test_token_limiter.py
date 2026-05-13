import datetime
from unittest.mock import AsyncMock, Mock, patch

from freezegun import freeze_time
import pytest

from tests.common.db_mock import API_KEY_UUID, GROUP_UUID, REQUEST_UUID

from radicalbit_ai_gateway.limiter.fixed_aligned import AlignedFixedWindowLimiter
from radicalbit_ai_gateway.limiter.fixed_window import FixedWindowLimiter
from radicalbit_ai_gateway.limiting.token_limiter import (
    InputTokenLimitExceeded,
    OutputTokenLimitExceeded,
    TokenLimiter,
)
from radicalbit_ai_gateway.models.limiting import Limiting, LimitingAlgorithmType

TEST_MODEL = 'openai/gpt-4o'


@pytest.fixture(autouse=True)
def mock_emit_functions():
    """Mock emit_event and emit_notification for all tests to prevent real Celery calls."""
    mock_event = Mock()
    mock_notification = Mock()
    with (
        patch(
            'radicalbit_ai_gateway.limiting.token_limiter.emit_event',
            new=mock_event,
        ),
        patch(
            'radicalbit_ai_gateway.limiting.token_limiter.emit_notification',
            new=mock_notification,
        ),
    ):
        yield {
            'emit_event': mock_event,
            'emit_notification': mock_notification,
        }


@pytest.fixture
def emit_notification_mock(mock_emit_functions):
    """Return the notification mock for tests that need to verify calls."""
    return mock_emit_functions['emit_notification']


class TestTokenLimiter:
    def test_init_without_config(self):
        """Test TokenLimiter initialization without any configuration."""
        limiter = TokenLimiter(route_name='rb-gateway')
        assert limiter.input_limiter is None
        assert limiter.output_limiter is None

    def test_init_with_input_config(self):
        """Test TokenLimiter initialization with input configuration."""
        input_config = Limiting(
            algorithm=LimitingAlgorithmType.FIXED_WINDOW,
            window_size='1 minute',
            max_tokens=1000,
        )
        limiter = TokenLimiter(route_name='rb-gateway', input_config=input_config)
        assert limiter.input_limiter is not None
        assert limiter.output_limiter is None

    def test_init_with_output_config(self):
        """Test TokenLimiter initialization with output configuration."""
        output_config = Limiting(
            algorithm=LimitingAlgorithmType.FIXED_WINDOW,
            window_size='30 seconds',
            max_tokens=500,
        )
        limiter = TokenLimiter(route_name='rb-gateway', output_config=output_config)
        assert limiter.input_limiter is None
        assert limiter.output_limiter is not None

    def test_init_with_both_configs(self):
        """Test TokenLimiter initialization with both input and output configurations."""
        input_config = Limiting(max_tokens=1000, window_size='1 minute')
        output_config = Limiting(max_tokens=500, window_size='30 seconds')
        limiter = TokenLimiter(
            route_name='rb-gateway',
            input_config=input_config,
            output_config=output_config,
        )
        assert limiter.input_limiter is not None
        assert limiter.output_limiter is not None

    def test_init_without_max_tokens_raises_error(self):
        """Test that initialization without max_tokens raises ValueError."""
        config = Limiting(window_size='1 minute')  # No max_tokens set
        with pytest.raises(
            ValueError, match='max_tokens must be set for token limiting'
        ):
            TokenLimiter(route_name='rb-gateway', input_config=config)

    @pytest.mark.asyncio
    async def test_check_input_no_config(self):
        """Test input checking without configuration does nothing."""
        limiter = TokenLimiter(route_name='rb-gateway')
        # Should not raise any exception
        await limiter.check_input(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            group_uuid=str(GROUP_UUID),
            api_key_name='fake-name',
            group_name='test-group',
            text='This is a test message',
            model_string=TEST_MODEL,
        )
        # count_input with no config should also be a no-op
        await limiter.count_input(prompt_tokens=10)

    @pytest.mark.asyncio
    async def test_check_input_within_limit_and_count_consumes(self):
        """Test input checking within limit, and then count_input consumes window."""
        input_config = Limiting(max_tokens=100, window_size='1 minute')
        limiter = TokenLimiter(route_name='rb-gateway', input_config=input_config)

        # Make token estimation deterministic
        with patch(
            'radicalbit_ai_gateway.limiting.token_limiter.count_tokens',
            return_value=5,
        ):
            # check_input should NOT consume
            with patch.object(
                limiter.input_limiter, 'hit', new=AsyncMock()
            ) as mock_hit:
                await limiter.check_input(
                    request_uuid=str(REQUEST_UUID),
                    api_key_uuid=str(API_KEY_UUID),
                    group_uuid=str(GROUP_UUID),
                    api_key_name='fake-name',
                    group_name='test-group',
                    text='Hello world',
                    model_string=TEST_MODEL,
                )
                mock_hit.assert_not_called()

            # count_input should consume (hit)
            with patch.object(
                limiter.input_limiter, 'hit', new=AsyncMock()
            ) as mock_hit2:
                await limiter.count_input(prompt_tokens=5)
                mock_hit2.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_input_exceeds_limit(self):
        """Test input checking that exceeds the token limit (check-only, no hit)."""
        input_config = Limiting(max_tokens=10, window_size='1 minute')
        limiter = TokenLimiter(route_name='rb-gateway', input_config=input_config)

        # Deterministic token count so we can assert attempted
        with (
            patch(
                'radicalbit_ai_gateway.limiting.token_limiter.count_tokens',
                return_value=17,
            ),
            patch.object(limiter.input_limiter, 'hit', new=AsyncMock()) as mock_hit,
        ):
            with pytest.raises(InputTokenLimitExceeded) as exc:
                await limiter.check_input(
                    request_uuid=str(REQUEST_UUID),
                    api_key_uuid=str(API_KEY_UUID),
                    group_uuid=str(GROUP_UUID),
                    api_key_name='fake-name',
                    group_name='test-group',
                    text='long_message_does_not_matter_because_mocked',
                    model_string=TEST_MODEL,
                )

            mock_hit.assert_not_called()

        msg = getattr(exc.value, 'log_message', str(exc.value))
        assert '[TOKEN LIMIT]' in msg
        assert '[route=rb-gateway]' in msg
        assert '[kind=TOKEN]' in msg
        assert '[direction=INPUT]' in msg
        assert '[attempted=17]' in msg
        assert '[limit=10]' in msg
        assert '[window=1 minute]' in msg
        assert '[action=BLOCK]' in msg

    @pytest.mark.asyncio
    async def test_input_accumulates_over_multiple_calls(self):
        """Test that consumption accumulates over multiple provider invocations."""
        input_config = Limiting(max_tokens=20, window_size='1 minute')
        limiter = TokenLimiter(route_name='rb-gateway', input_config=input_config)

        # token estimate sequence for check_input calls
        # 6 + 6 + 6 = 18 (consumed), next attempted 8 => test should fail (> 20)
        with patch(
            'radicalbit_ai_gateway.limiting.token_limiter.count_tokens',
            side_effect=[6, 6, 6, 8],
        ):
            # First 3: check passes, then we consume via count_input (prompt_tokens)
            await limiter.check_input(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                group_name='test-group',
                text='A',
                model_string=TEST_MODEL,
            )
            await limiter.count_input(prompt_tokens=6)

            await limiter.check_input(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                group_name='test-group',
                text='B',
                model_string=TEST_MODEL,
            )
            await limiter.count_input(prompt_tokens=6)

            await limiter.check_input(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                group_name='test-group',
                text='C',
                model_string=TEST_MODEL,
            )
            await limiter.count_input(prompt_tokens=6)

            # Fourth: check should fail BEFORE consuming
            with pytest.raises(InputTokenLimitExceeded) as exc:
                await limiter.check_input(
                    request_uuid=str(REQUEST_UUID),
                    api_key_uuid=str(API_KEY_UUID),
                    group_uuid=str(GROUP_UUID),
                    api_key_name='fake-name',
                    group_name='test-group',
                    text='D',
                    model_string=TEST_MODEL,
                )

        msg = getattr(exc.value, 'log_message', str(exc.value))
        assert '[TOKEN LIMIT]' in msg
        assert '[route=rb-gateway]' in msg
        assert '[kind=TOKEN]' in msg
        assert '[direction=INPUT]' in msg
        assert '[attempted=8]' in msg  # ultimo tentativo stimato
        assert '[limit=20]' in msg
        assert '[window=1 minute]' in msg
        assert '[action=BLOCK]' in msg

    @pytest.mark.asyncio
    async def test_count_output_no_config(self):
        """Test output counting without configuration does nothing."""
        limiter = TokenLimiter(route_name='rb-gateway')
        # Should not raise any exception
        await limiter.count_output(
            token_count=100,
        )
        await limiter.check_output(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            group_uuid=str(GROUP_UUID),
            api_key_name='fake-name',
            group_name='test-group',
        )

    @pytest.mark.asyncio
    async def test_count_output_within_limit(self):
        """Test output counting within the token limit."""
        output_config = Limiting(max_tokens=100, window_size='1 minute')
        limiter = TokenLimiter(route_name='rb-gateway', output_config=output_config)

        # Should be within limit
        await limiter.count_output(
            token_count=50,
        )
        await limiter.check_output(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            group_uuid=str(GROUP_UUID),
            api_key_name='fake-name',
            group_name='test-group',
        )

    @pytest.mark.asyncio
    async def test_count_output_exceeds_limit(self):
        """Test output counting that exceeds the token limit."""
        output_config = Limiting(max_tokens=50, window_size='1 minute')
        limiter = TokenLimiter(route_name='rb-gateway', output_config=output_config)

        await limiter.count_output(
            token_count=100,
        )

        with pytest.raises(OutputTokenLimitExceeded) as exc:
            await limiter.check_output(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                group_name='test-group',
            )

        msg = getattr(exc.value, 'log_message', str(exc.value))
        assert '[TOKEN LIMIT]' in msg
        assert '[route=rb-gateway]' in msg
        assert '[kind=TOKEN]' in msg
        assert '[direction=OUTPUT]' in msg
        assert '[attempted=1]' in msg
        assert '[limit=50]' in msg
        assert '[window=1 minute]' in msg
        assert '[remaining=0]' in msg
        assert '[action=BLOCK]' in msg

    @pytest.mark.asyncio
    async def test_count_output_accumulates(self):
        """Test that output token counting accumulates over multiple calls."""
        output_config = Limiting(max_tokens=100, window_size='1 minute')
        limiter = TokenLimiter(route_name='rb-gateway', output_config=output_config)

        initial_datetime = datetime.datetime(
            year=2025, month=6, day=25, hour=15, minute=0, second=0
        )
        with freeze_time(initial_datetime) as frozen_datetime:
            assert frozen_datetime() == initial_datetime

            await limiter.count_output(
                token_count=50,
            )
            await limiter.count_output(
                token_count=100,
            )
            await limiter.count_output(
                token_count=50,
            )

            with pytest.raises(OutputTokenLimitExceeded) as exc:
                await limiter.check_output(
                    request_uuid=str(REQUEST_UUID),
                    api_key_uuid=str(API_KEY_UUID),
                    group_uuid=str(GROUP_UUID),
                    api_key_name='fake-name',
                    group_name='test-group',
                )

            msg = getattr(exc.value, 'log_message', str(exc.value))
            assert '[TOKEN LIMIT]' in msg
            assert '[route=rb-gateway]' in msg
            assert '[kind=TOKEN]' in msg
            assert '[direction=OUTPUT]' in msg
            assert '[attempted=1]' in msg
            assert '[limit=100]' in msg
            assert '[window=1 minute]' in msg
            assert '[remaining=0]' in msg
            assert '[reset_s=60]' in msg
            assert '[action=BLOCK]' in msg

    @pytest.mark.asyncio
    async def test_window_with_fixed_time_input_split(self):
        """Same semantics as the old window test, but using:
        - check_input (test-only)
        - count_input (hit-only)
        """
        initial_datetime = datetime.datetime(
            year=2025, month=6, day=25, hour=15, minute=0, second=0
        )
        with freeze_time(initial_datetime) as frozen_datetime:
            assert frozen_datetime() == initial_datetime

            input_config = Limiting(
                algorithm=LimitingAlgorithmType.FIXED_WINDOW,
                max_tokens=5,
                window_size='10 second',
            )
            limiter = TokenLimiter(route_name='rb-gateway', input_config=input_config)

            # Deterministic token estimation for the 4 check_input calls:
            # 1) first allowed and consumed = 4 -> remaining becomes 1
            # 2) attempted=3 blocked
            # 3) after +3s attempted=4 blocked (remaining still 1, reset_s=7)
            # 4) after +7s (window reset) attempted=3 allowed and consumed
            with patch(
                'radicalbit_ai_gateway.limiting.token_limiter.count_tokens',
                side_effect=[4, 3, 4, 3],
            ):
                # 1) Allowed then consume
                await limiter.check_input(
                    request_uuid=str(REQUEST_UUID),
                    api_key_uuid=str(API_KEY_UUID),
                    group_uuid=str(GROUP_UUID),
                    api_key_name='fake-name',
                    group_name='test-group',
                    text='Hello world test message',
                    model_string=TEST_MODEL,
                )
                await limiter.count_input(prompt_tokens=4)

                # 2) Blocked (no consume)
                with pytest.raises(InputTokenLimitExceeded) as exc1:
                    await limiter.check_input(
                        request_uuid=str(REQUEST_UUID),
                        api_key_uuid=str(API_KEY_UUID),
                        group_uuid=str(GROUP_UUID),
                        api_key_name='fake-name',
                        group_name='test-group',
                        text='This will break',
                        model_string=TEST_MODEL,
                    )

                msg1 = getattr(exc1.value, 'log_message', str(exc1.value))
                assert '[TOKEN LIMIT]' in msg1
                assert '[route=rb-gateway]' in msg1
                assert '[direction=INPUT]' in msg1
                assert '[attempted=3]' in msg1
                assert '[limit=5]' in msg1
                assert '[window=10 second]' in msg1
                assert '[remaining=1]' in msg1
                assert '[reset_s=10]' in msg1
                assert '[action=BLOCK]' in msg1

                frozen_datetime.tick(3)

                # 3) Still blocked
                with pytest.raises(InputTokenLimitExceeded) as exc2:
                    await limiter.check_input(
                        request_uuid=str(REQUEST_UUID),
                        api_key_uuid=str(API_KEY_UUID),
                        group_uuid=str(GROUP_UUID),
                        api_key_name='fake-name',
                        group_name='test-group',
                        text='This will not work',
                        model_string=TEST_MODEL,
                    )

                msg2 = getattr(exc2.value, 'log_message', str(exc2.value))
                assert '[TOKEN LIMIT]' in msg2
                assert '[route=rb-gateway]' in msg2
                assert '[direction=INPUT]' in msg2
                assert '[attempted=4]' in msg2
                assert '[limit=5]' in msg2
                assert '[window=10 second]' in msg2
                assert '[remaining=1]' in msg2
                assert '[reset_s=7]' in msg2
                assert '[action=BLOCK]' in msg2

                frozen_datetime.tick(7)

                # 4) New window -> allowed and consume
                await limiter.check_input(
                    request_uuid=str(REQUEST_UUID),
                    api_key_uuid=str(API_KEY_UUID),
                    group_uuid=str(GROUP_UUID),
                    api_key_name='fake-name',
                    group_name='test-group',
                    text='This will work',
                    model_string=TEST_MODEL,
                )
                await limiter.count_input(prompt_tokens=3)

    def test_window_size_formats(self):
        """Test different window size formats."""
        # Test with string format
        config2 = Limiting(max_tokens=100, window_size='1 minute')
        limiter2 = TokenLimiter(route_name='rb-gateway', input_config=config2)
        assert limiter2.input_limiter is not None

        # Test with per-second format
        config3 = Limiting(max_tokens=100, window_size='100 seconds')
        limiter3 = TokenLimiter(route_name='rb-gateway', input_config=config3)
        assert limiter3.input_limiter is not None

    def test_init_with_aligned_fixed_window(self):
        """Test TokenLimiter uses AlignedFixedWindowLimiter when configured."""
        input_config = Limiting(
            algorithm=LimitingAlgorithmType.ALIGNED_FIXED_WINDOW,
            window_size='1 minute',
            max_tokens=1000,
        )
        limiter = TokenLimiter(route_name='rb-gateway', input_config=input_config)
        assert limiter.input_limiter is not None
        assert isinstance(limiter.input_limiter, AlignedFixedWindowLimiter)

    def test_init_with_fixed_window_creates_correct_type(self):
        """Test TokenLimiter uses FixedWindowLimiter when configured."""
        input_config = Limiting(
            algorithm=LimitingAlgorithmType.FIXED_WINDOW,
            window_size='1 minute',
            max_tokens=1000,
        )
        limiter = TokenLimiter(route_name='rb-gateway', input_config=input_config)
        assert limiter.input_limiter is not None
        assert isinstance(limiter.input_limiter, FixedWindowLimiter)

    @pytest.mark.asyncio
    async def test_count_input_sends_notification(self, emit_notification_mock):
        """Test that count_input sends notification with correct parameters after deduction."""
        input_config = Limiting(max_tokens=100, window_size='1 minute')
        limiter = TokenLimiter(route_name='rb-gateway', input_config=input_config)

        await limiter.count_input(prompt_tokens=42)

        # Verify emit_notification was called with correct parameters
        emit_notification_mock.assert_called_once()
        call_kwargs = emit_notification_mock.call_args.kwargs
        assert call_kwargs['route_name'] == 'rb-gateway'
        assert call_kwargs['direction'] == 'input'
        assert call_kwargs['window_size'] == 60
        assert call_kwargs['max_tokens'] == 100
        assert call_kwargs['current_usage'] == 42
        # reset_time is dynamic
        assert 'reset_time' in call_kwargs

    @pytest.mark.asyncio
    async def test_count_output_sends_notification(self, emit_notification_mock):
        """Test that count_output sends notification with correct parameters after deduction."""
        output_config = Limiting(max_tokens=50, window_size='1 minute')
        limiter = TokenLimiter(route_name='rb-gateway', output_config=output_config)

        await limiter.count_output(token_count=17)

        # Verify emit_notification was called with correct parameters
        emit_notification_mock.assert_called_once()
        call_kwargs = emit_notification_mock.call_args.kwargs
        assert call_kwargs['route_name'] == 'rb-gateway'
        assert call_kwargs['direction'] == 'output'
        assert call_kwargs['window_size'] == 60
        assert call_kwargs['max_tokens'] == 50
        assert call_kwargs['current_usage'] == 17
        # reset_time is dynamic
        assert 'reset_time' in call_kwargs
