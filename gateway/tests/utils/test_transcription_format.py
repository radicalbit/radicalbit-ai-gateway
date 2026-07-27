from openai.types.audio.transcription import Transcription
from openai.types.audio.transcription_segment import TranscriptionSegment
from openai.types.audio.transcription_verbose import TranscriptionVerbose
import pytest

from radicalbit_ai_gateway.utils.exceptions import ModelInvokerBadRequest
from radicalbit_ai_gateway.utils.transcription_format import (
    build_srt,
    build_vtt,
    convert_transcription_response,
)


def _segment(seg_id: int, start: float, end: float, text: str) -> TranscriptionSegment:
    return TranscriptionSegment(
        id=seg_id,
        seek=0,
        start=start,
        end=end,
        text=text,
        tokens=[],
        temperature=0.0,
        avg_logprob=-0.1,
        compression_ratio=1.0,
        no_speech_prob=0.01,
    )


SEGMENTS = [
    _segment(0, 0.0, 1.5, 'Ciao mondo'),
    _segment(1, 1.5, 3.0, 'Secondo segmento'),
]

WHISPER_RESPONSE = TranscriptionVerbose(
    task='transcribe',
    language='italian',
    duration=3.0,
    text='Ciao mondo Secondo segmento',
    segments=SEGMENTS,
    usage={'type': 'duration', 'seconds': 3},
)

GPT4O_RESPONSE = Transcription(
    text='Ciao mondo',
    usage={
        'type': 'tokens',
        'input_tokens': 10,
        'output_tokens': 5,
        'total_tokens': 15,
        'input_token_details': {'audio_tokens': 10, 'text_tokens': 0},
    },
)


class TestBuildSrt:
    def test_build_srt_format(self):
        srt = build_srt(SEGMENTS)
        assert '1\n00:00:00,000 --> 00:00:01,500\nCiao mondo' in srt
        assert '2\n00:00:01,500 --> 00:00:03,000\nSecondo segmento' in srt

    def test_build_srt_empty_segments(self):
        assert build_srt([]) == '\n'


class TestBuildVtt:
    def test_build_vtt_format(self):
        vtt = build_vtt(SEGMENTS)
        assert vtt.startswith('WEBVTT\n')
        assert '00:00:00.000 --> 00:00:01.500\nCiao mondo' in vtt


class TestConvertTranscriptionResponseWhisper:
    def test_verbose_json_passthrough(self):
        body, content_type = convert_transcription_response(
            response=WHISPER_RESPONSE,
            requested_format='verbose_json',
            is_whisper=True,
        )
        assert content_type == 'application/json'
        assert body['duration'] == 3.0
        assert len(body['segments']) == 2

    def test_json_strips_down_to_text_and_usage(self):
        body, content_type = convert_transcription_response(
            response=WHISPER_RESPONSE,
            requested_format='json',
            is_whisper=True,
        )
        assert content_type == 'application/json'
        assert set(body.keys()) == {'text', 'usage'}

    def test_text_format(self):
        body, content_type = convert_transcription_response(
            response=WHISPER_RESPONSE,
            requested_format='text',
            is_whisper=True,
        )
        assert content_type == 'text/plain'
        assert body == WHISPER_RESPONSE.text

    def test_srt_format(self):
        body, content_type = convert_transcription_response(
            response=WHISPER_RESPONSE,
            requested_format='srt',
            is_whisper=True,
        )
        assert content_type == 'text/plain'
        assert '00:00:00,000' in body

    def test_vtt_format(self):
        body, content_type = convert_transcription_response(
            response=WHISPER_RESPONSE,
            requested_format='vtt',
            is_whisper=True,
        )
        assert content_type == 'text/plain'
        assert body.startswith('WEBVTT')


class TestConvertTranscriptionResponseGpt4o:
    def test_json_passthrough(self):
        body, content_type = convert_transcription_response(
            response=GPT4O_RESPONSE,
            requested_format='json',
            is_whisper=False,
        )
        assert content_type == 'application/json'
        assert body['text'] == 'Ciao mondo'
        assert body['usage'].type == 'tokens'

    def test_text_format(self):
        body, content_type = convert_transcription_response(
            response=GPT4O_RESPONSE,
            requested_format='text',
            is_whisper=False,
        )
        assert content_type == 'text/plain'
        assert body == GPT4O_RESPONSE.text

    def test_verbose_json_rejected(self):
        with pytest.raises(ModelInvokerBadRequest, match='verbose_json'):
            convert_transcription_response(
                response=GPT4O_RESPONSE,
                requested_format='verbose_json',
                is_whisper=False,
            )

    @pytest.mark.parametrize('fmt', ['srt', 'vtt'])
    def test_srt_vtt_rejected(self, fmt):
        with pytest.raises(ModelInvokerBadRequest, match='segment timing'):
            convert_transcription_response(
                response=GPT4O_RESPONSE,
                requested_format=fmt,
                is_whisper=False,
            )


def test_unsupported_response_format_rejected():
    with pytest.raises(ModelInvokerBadRequest, match='Unsupported response_format'):
        convert_transcription_response(
            response=GPT4O_RESPONSE,
            requested_format='xml',
            is_whisper=False,
        )
