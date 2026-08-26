import datetime
import io
from unittest.mock import AsyncMock, patch
import wave

from freezegun import freeze_time
import pytest

from tests.common.db_mock import API_KEY_UUID, GROUP_UUID, REQUEST_UUID

from radicalbit_ai_gateway.limiting.duration_limiter import (
    DurationLimiter,
    estimate_audio_duration_seconds,
)
from radicalbit_ai_gateway.models.limiting import (
    AudioDurationLimiting,
    LimitingAlgorithmType,
)
from radicalbit_ai_gateway.utils.exceptions import AudioDurationLimitExceeded

_PROJECT_UUID = '2f1c6d4e-0000-4000-8000-0000000000aa'


def _make_wav_bytes(duration_seconds: float, sample_rate: int = 8000) -> bytes:
    n_frames = int(duration_seconds * sample_rate)
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b'\x00\x00' * n_frames)
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def mock_emit_event():
    """Mock emit_event for all tests in this module."""
    with patch(
        'radicalbit_ai_gateway.limiting.duration_limiter.emit_event', autospec=True
    ):
        yield


class TestEstimateAudioDurationSeconds:
    def test_wav_duration_is_accurate(self):
        audio_bytes = _make_wav_bytes(3.0)
        duration = estimate_audio_duration_seconds(audio_bytes)
        assert duration == pytest.approx(3.0, abs=0.01)

    def test_unrecognized_format_returns_none(self):
        garbage = b'not-an-audio-file' * 20
        assert estimate_audio_duration_seconds(garbage) is None

    def test_empty_bytes_returns_none(self):
        assert estimate_audio_duration_seconds(b'') is None


class TestDurationLimiter:
    def test_init_without_config(self):
        limiter = DurationLimiter(project_uuid=_PROJECT_UUID, route_name='rb-gateway')
        assert limiter.limiter is None

    def test_init_with_config(self):
        config = AudioDurationLimiting(
            algorithm=LimitingAlgorithmType.FIXED_WINDOW,
            max_duration_seconds=60,
            window_size='1 minute',
        )
        limiter = DurationLimiter(
            project_uuid=_PROJECT_UUID, route_name='rb-gateway', config=config
        )
        assert limiter.limiter is not None

    def test_init_without_max_duration_seconds_raises_error(self):
        config = AudioDurationLimiting(window_size='1 minute')
        with pytest.raises(
            ValueError, match='max_duration_seconds must be set for duration limiting'
        ):
            DurationLimiter(
                project_uuid=_PROJECT_UUID, route_name='rb-gateway', config=config
            )

    @pytest.mark.asyncio
    async def test_check_and_count_duration_no_config_is_noop(self):
        limiter = DurationLimiter(project_uuid=_PROJECT_UUID, route_name='rb-gateway')
        await limiter.check_and_count_duration(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            group_uuid=str(GROUP_UUID),
            api_key_name='fake-name',
            group_name='test-group',
            audio_bytes=_make_wav_bytes(5.0),
        )

    @pytest.mark.asyncio
    async def test_check_and_count_duration_within_limit_consumes(self):
        config = AudioDurationLimiting(max_duration_seconds=60, window_size='1 minute')
        limiter = DurationLimiter(
            project_uuid=_PROJECT_UUID, route_name='rb-gateway', config=config
        )

        with patch.object(limiter.limiter, 'hit', new=AsyncMock()) as mock_hit:
            await limiter.check_and_count_duration(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                group_name='test-group',
                audio_bytes=_make_wav_bytes(10.0),
            )
            mock_hit.assert_called_once()
            assert mock_hit.call_args.kwargs['cost'] == 10

    @pytest.mark.asyncio
    async def test_check_and_count_duration_exceeds_limit_raises(self):
        config = AudioDurationLimiting(max_duration_seconds=15, window_size='1 minute')
        limiter = DurationLimiter(
            project_uuid=_PROJECT_UUID, route_name='rb-gateway', config=config
        )

        await limiter.check_and_count_duration(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            group_uuid=str(GROUP_UUID),
            api_key_name='fake-name',
            group_name='test-group',
            audio_bytes=_make_wav_bytes(10.0),
        )

        with pytest.raises(AudioDurationLimitExceeded) as exc:
            await limiter.check_and_count_duration(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                group_name='test-group',
                audio_bytes=_make_wav_bytes(10.0),
            )

        msg = getattr(exc.value, 'log_message', str(exc.value))
        assert '[DURATION LIMIT]' in msg
        assert '[route=rb-gateway]' in msg
        assert '[kind=AUDIO_DURATION]' in msg
        assert '[limit=15.0]' in msg
        assert '[action=BLOCK]' in msg

    @pytest.mark.asyncio
    async def test_check_and_count_duration_unknown_duration_skips_uncounted(self):
        config = AudioDurationLimiting(max_duration_seconds=15, window_size='1 minute')
        limiter = DurationLimiter(
            project_uuid=_PROJECT_UUID, route_name='rb-gateway', config=config
        )

        with patch.object(limiter.limiter, 'hit', new=AsyncMock()) as mock_hit:
            await limiter.check_and_count_duration(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                group_name='test-group',
                audio_bytes=b'not-an-audio-file' * 20,
            )
            mock_hit.assert_not_called()

        # A follow-up call with a real, large file must still be evaluated
        # against the (still-empty) window rather than being blocked by the
        # unmeasurable one above.
        await limiter.check_and_count_duration(
            request_uuid=str(REQUEST_UUID),
            api_key_uuid=str(API_KEY_UUID),
            group_uuid=str(GROUP_UUID),
            api_key_name='fake-name',
            group_name='test-group',
            audio_bytes=_make_wav_bytes(10.0),
        )

    @pytest.mark.asyncio
    async def test_window_reset(self):
        initial_datetime = datetime.datetime(
            year=2025, month=6, day=25, hour=15, minute=0, second=0
        )
        with freeze_time(initial_datetime) as frozen_datetime:
            config = AudioDurationLimiting(
                max_duration_seconds=10, window_size='10 second'
            )
            limiter = DurationLimiter(
                project_uuid=_PROJECT_UUID, route_name='rb-gateway', config=config
            )

            await limiter.check_and_count_duration(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                group_name='test-group',
                audio_bytes=_make_wav_bytes(10.0),
            )

            with pytest.raises(AudioDurationLimitExceeded):
                await limiter.check_and_count_duration(
                    request_uuid=str(REQUEST_UUID),
                    api_key_uuid=str(API_KEY_UUID),
                    group_uuid=str(GROUP_UUID),
                    api_key_name='fake-name',
                    group_name='test-group',
                    audio_bytes=_make_wav_bytes(1.0),
                )

            frozen_datetime.tick(11)

            await limiter.check_and_count_duration(
                request_uuid=str(REQUEST_UUID),
                api_key_uuid=str(API_KEY_UUID),
                group_uuid=str(GROUP_UUID),
                api_key_name='fake-name',
                group_name='test-group',
                audio_bytes=_make_wav_bytes(5.0),
            )
