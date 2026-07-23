import pytest

from radicalbit_ai_gateway.utils.audio_validation import (
    MAX_TRANSCRIPTION_AUDIO_BYTES,
    validate_audio_upload,
)
from radicalbit_ai_gateway.utils.exceptions import GatewayBadRequest


def test_valid_upload_passes():
    validate_audio_upload(filename='audio.mp3', size=1024, content=b'x' * 1024)


@pytest.mark.parametrize(
    'filename', ['audio.mp3', 'audio.MP3', 'audio.wav', 'audio.m4a', 'audio.webm']
)
def test_valid_extensions_case_insensitive(filename):
    validate_audio_upload(filename=filename, size=10, content=b'x' * 10)


def test_missing_filename_rejected():
    with pytest.raises(GatewayBadRequest, match='Unsupported audio format'):
        validate_audio_upload(filename=None, size=10, content=b'x' * 10)


def test_unsupported_extension_rejected():
    with pytest.raises(GatewayBadRequest, match='Unsupported audio format'):
        validate_audio_upload(filename='audio.txt', size=10, content=b'x' * 10)


def test_oversized_file_rejected_by_reported_size():
    with pytest.raises(GatewayBadRequest, match='exceeds the 25 MB limit'):
        validate_audio_upload(
            filename='audio.mp3',
            size=MAX_TRANSCRIPTION_AUDIO_BYTES + 1,
            content=b'',
        )


def test_size_none_falls_back_to_content_length():
    oversized_content = b'x' * (MAX_TRANSCRIPTION_AUDIO_BYTES + 1)
    with pytest.raises(GatewayBadRequest, match='exceeds the 25 MB limit'):
        validate_audio_upload(filename='audio.mp3', size=None, content=oversized_content)


def test_size_none_within_limit_passes():
    validate_audio_upload(filename='audio.mp3', size=None, content=b'x' * 100)
