"""The length of an audio file, read without decoding it."""

import io
import wave


def estimate_audio_duration_seconds(audio_bytes: bytes) -> float | None:
    """Header-only duration estimate, no upstream call and no full decode.

    WAV only (stdlib `wave` module — no external dependency). Returns None
    for any other format, or a malformed WAV — callers must treat that as
    "unknown", not as zero.
    """
    try:
        with wave.open(io.BytesIO(audio_bytes), 'rb') as wav_file:
            frames = wav_file.getnframes()
            rate = wav_file.getframerate()
    except Exception:
        return None
    if not rate:
        return None
    return frames / rate
