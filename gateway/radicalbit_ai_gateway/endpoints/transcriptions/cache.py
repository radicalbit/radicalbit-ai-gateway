"""How a transcription request is cached."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from openai.types.audio.transcription import Transcription
from openai.types.audio.transcription_verbose import TranscriptionVerbose

from radicalbit_ai_gateway.caching.route_cache import ExactEntry, Hit


@dataclass(frozen=True)
class TranscriptionEntry(ExactEntry):
    """A transcription request, keyed on the audio's hash, the model and the
    request's parameters.
    """

    audio_bytes: bytes
    model_id: str
    response_format: str
    language: str | None = None
    prompt: str | None = None
    temperature: float | None = None

    hit_log = 'Transcription cache hit. Key: %s'

    def signature(self) -> str:
        # The audio is hashed, never embedded raw: it is binary, and would
        # dominate the signature's size.
        audio_hash = hashlib.sha256(self.audio_bytes).hexdigest()
        params = {
            'model_id': self.model_id,
            'response_format': self.response_format,
            'language': self.language,
            'prompt': self.prompt,
            'temperature': self.temperature,
        }
        return f'audio_hash:{audio_hash};extra_args:{json.dumps(params)}'

    def parse(self, raw: str) -> Transcription | TranscriptionVerbose:
        if self.response_format == 'verbose_json':
            return TranscriptionVerbose.model_validate_json(raw)
        return Transcription.model_validate_json(raw)

    def dump(self, value: Transcription | TranscriptionVerbose) -> str:
        return value.model_dump_json(indent=None)

    def hit(self, value) -> Hit:
        return Hit(self.model_id)
