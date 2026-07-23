"""Validation for audio uploads to the /v1/audio/transcriptions endpoint.

Limits mirror OpenAI's own constraints (see AG-835 analysis): 25MB max file
size, and the set of audio formats OpenAI's transcription API accepts. These
are fixed provider limits, not something exposed via gateway config (see
AG-885 analysis, section 4).

No infrastructure-level (ASGI/Starlette/uvicorn) body-size limit exists in
this repo (verified) — the same applicative, post-`file.read()` pattern
already used in `routes/project_route.py` for config imports is used here.
"""

from radicalbit_ai_gateway.utils.exceptions import GatewayBadRequest

MAX_TRANSCRIPTION_AUDIO_BYTES = 25 * 1024 * 1024  # 25 MB, OpenAI's hard limit
ALLOWED_AUDIO_EXTENSIONS = (
    '.mp3',
    '.mp4',
    '.mpeg',
    '.mpga',
    '.m4a',
    '.wav',
    '.webm',
)


def validate_audio_upload(
    filename: str | None, size: int | None, content: bytes
) -> None:
    """Validate an uploaded audio file's extension and size.

    `size` is the size reported by Starlette's `UploadFile` (may be `None`
    depending on the client); when unavailable, falls back to `len(content)`.
    """
    if not filename or not filename.lower().endswith(ALLOWED_AUDIO_EXTENSIONS):
        raise GatewayBadRequest(
            f'Unsupported audio format for file {filename!r}. '
            f'Supported extensions: {", ".join(ALLOWED_AUDIO_EXTENSIONS)}.'
        )

    effective_size = size if size is not None else len(content)
    if effective_size > MAX_TRANSCRIPTION_AUDIO_BYTES:
        raise GatewayBadRequest(
            f'Uploaded audio file exceeds the '
            f'{MAX_TRANSCRIPTION_AUDIO_BYTES // (1024 * 1024)} MB limit.'
        )
