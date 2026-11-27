"""The body of an audio transcription request."""

from __future__ import annotations

from typing import Literal

from fastapi import UploadFile
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Audio transcriptions API (POST /v1/audio/transcriptions)
# ---------------------------------------------------------------------------
# This one is a `pydantic.BaseModel`, not a TypedDict: FastAPI's
# `Annotated[X, Form()]` multipart grouping only accepts a `BaseModel`.
# ---------------------------------------------------------------------------


class TranscriptionCreateParamsCustom(BaseModel):
    model: str
    """Gateway route name used to select the backend model."""

    file: UploadFile
    """The audio file to transcribe."""

    language: str | None = None
    """The language of the input audio, in ISO-639-1 format (e.g. `en`)."""

    prompt: str | None = None
    """An optional text to guide the model's style or continue a previous audio segment."""

    response_format: Literal['json', 'verbose_json'] = 'json'
    """The format of the transcript output. verbose_json is only supported for whisper-1;
    text/srt/vtt aren't supported yet."""

    stream: bool = False
    """Stream the transcript as it's generated via SSE. Only supported for the
    gpt-4o-transcribe family; whisper-1 does not support streaming."""

    temperature: float | None = None
    """Sampling temperature, between 0 and 1."""
