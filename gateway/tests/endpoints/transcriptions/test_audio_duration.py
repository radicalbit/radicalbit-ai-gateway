import pytest

from tests.common.audio import make_wav_bytes

from radicalbit_ai_gateway.endpoints.transcriptions.audio_duration import (
    estimate_audio_duration_seconds,
)


def test_wav_duration_is_accurate():
    duration = estimate_audio_duration_seconds(make_wav_bytes(3.0))
    assert duration == pytest.approx(3.0, abs=0.01)


def test_unrecognized_format_returns_none():
    assert estimate_audio_duration_seconds(b'not-an-audio-file' * 20) is None


def test_empty_bytes_returns_none():
    assert estimate_audio_duration_seconds(b'') is None
