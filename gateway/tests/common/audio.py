import io
import wave


def make_wav_bytes(duration_seconds: float, sample_rate: int = 8000) -> bytes:
    n_frames = int(duration_seconds * sample_rate)
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b'\x00\x00' * n_frames)
    return buffer.getvalue()
