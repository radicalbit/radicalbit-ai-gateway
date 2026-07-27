import unittest
from unittest.mock import MagicMock

import httpx
from openai import APIConnectionError, APIStatusError
from openai.types.audio.transcription import Transcription
from openai.types.audio.transcription_verbose import TranscriptionVerbose
import pytest

from tests.common.mocked_transcription_client import MockTranscriptionClient

from radicalbit_ai_gateway.invocation.transcription_model_invoker import (
    TranscriptionModelInvoker,
)
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.exceptions import (
    ModelInvokerBadRequest,
    ModelInvokerInternalError,
)

WHISPER_MODEL = Model(
    model_id='whisper', model='openai/whisper-1', credentials={'api_key': 'sk-test'}
)
GPT4O_TRANSCRIBE_MODEL = Model(
    model_id='gpt4o-transcribe',
    model='openai/gpt-4o-transcribe',
    credentials={'api_key': 'sk-test'},
)

WHISPER_VERBOSE_RESPONSE = TranscriptionVerbose(
    task='transcribe',
    language='italian',
    duration=8.25,
    text='Ciao, questo è un test.',
    segments=[],
    usage={'type': 'duration', 'seconds': 9},
)

GPT4O_JSON_RESPONSE = Transcription(
    text='Ciao, questo è un test.',
    usage={
        'type': 'tokens',
        'input_tokens': 82,
        'output_tokens': 38,
        'total_tokens': 120,
        'input_token_details': {'audio_tokens': 82, 'text_tokens': 0},
    },
)


class TestTranscriptionModelInvoker(unittest.IsolatedAsyncioTestCase):
    def _build_invoker(self, model: Model) -> TranscriptionModelInvoker:
        cost_service: CostService = MagicMock(spec_set=CostService)
        return TranscriptionModelInvoker(models=[model], cost_service=cost_service)

    async def test_transcribe_whisper_success_forces_verbose_json_upstream(self):
        invoker = self._build_invoker(WHISPER_MODEL)
        mock_client = MockTranscriptionClient(response=WHISPER_VERBOSE_RESPONSE)
        invoker.model_map['whisper'] = (WHISPER_MODEL, mock_client, [])

        result = await invoker.transcribe(
            audio_bytes=b'fake-audio',
            filename='test.wav',
            content_type='audio/wav',
            model_id='whisper',
            requested_response_format='json',
        )

        # Client asked for `json`, but the model is whisper-1: upstream call
        # must still use verbose_json (to guarantee usage + segments).
        assert mock_client.captured_kwargs['response_format'] == 'verbose_json'
        assert result.body == {
            'text': 'Ciao, questo è un test.',
            'usage': WHISPER_VERBOSE_RESPONSE.usage,
        }
        assert result.content_type == 'application/json'
        assert result.usage.type == 'duration'
        assert result.model_invoked.model_id == 'whisper'

    async def test_transcribe_whisper_verbose_json_passthrough(self):
        invoker = self._build_invoker(WHISPER_MODEL)
        mock_client = MockTranscriptionClient(response=WHISPER_VERBOSE_RESPONSE)
        invoker.model_map['whisper'] = (WHISPER_MODEL, mock_client, [])

        result = await invoker.transcribe(
            audio_bytes=b'fake-audio',
            filename='test.wav',
            content_type='audio/wav',
            model_id='whisper',
            requested_response_format='verbose_json',
        )

        assert result.body['segments'] == []
        assert result.body['duration'] == 8.25

    async def test_transcribe_gpt4o_success_uses_json_upstream(self):
        invoker = self._build_invoker(GPT4O_TRANSCRIBE_MODEL)
        mock_client = MockTranscriptionClient(response=GPT4O_JSON_RESPONSE)
        invoker.model_map['gpt4o-transcribe'] = (GPT4O_TRANSCRIBE_MODEL, mock_client, [])

        result = await invoker.transcribe(
            audio_bytes=b'fake-audio',
            filename='test.wav',
            content_type='audio/wav',
            model_id='gpt4o-transcribe',
            requested_response_format='json',
        )

        assert mock_client.captured_kwargs['response_format'] == 'json'
        assert result.usage.type == 'tokens'
        assert result.usage.input_token_details.audio_tokens == 82

    async def test_transcribe_gpt4o_rejects_verbose_json(self):
        invoker = self._build_invoker(GPT4O_TRANSCRIBE_MODEL)
        mock_client = MockTranscriptionClient(response=GPT4O_JSON_RESPONSE)
        invoker.model_map['gpt4o-transcribe'] = (GPT4O_TRANSCRIBE_MODEL, mock_client, [])

        with pytest.raises(ModelInvokerBadRequest, match='verbose_json'):
            await invoker.transcribe(
                audio_bytes=b'fake-audio',
                filename='test.wav',
                content_type='audio/wav',
                model_id='gpt4o-transcribe',
                requested_response_format='verbose_json',
            )

    async def test_transcribe_gpt4o_rejects_srt(self):
        invoker = self._build_invoker(GPT4O_TRANSCRIBE_MODEL)
        mock_client = MockTranscriptionClient(response=GPT4O_JSON_RESPONSE)
        invoker.model_map['gpt4o-transcribe'] = (GPT4O_TRANSCRIBE_MODEL, mock_client, [])

        with pytest.raises(ModelInvokerBadRequest, match='segment timing'):
            await invoker.transcribe(
                audio_bytes=b'fake-audio',
                filename='test.wav',
                content_type='audio/wav',
                model_id='gpt4o-transcribe',
                requested_response_format='srt',
            )

    async def test_transcribe_unknown_model_id_raises_bad_request(self):
        invoker = self._build_invoker(WHISPER_MODEL)

        with pytest.raises(ModelInvokerBadRequest, match='not defined'):
            await invoker.transcribe(
                audio_bytes=b'fake-audio',
                filename='test.wav',
                content_type='audio/wav',
                model_id='unknown-model',
                requested_response_format='json',
            )

    async def test_transcribe_upstream_5xx_raises_internal_error(self):
        invoker = self._build_invoker(WHISPER_MODEL)
        request = httpx.Request('POST', 'https://api.openai.com/v1/audio/transcriptions')
        response = httpx.Response(status_code=503, request=request)
        exception = APIStatusError(
            'Service unavailable', response=response, body=None
        )
        mock_client = MockTranscriptionClient(exception=exception)
        invoker.model_map['whisper'] = (WHISPER_MODEL, mock_client, [])

        with pytest.raises(ModelInvokerInternalError):
            await invoker.transcribe(
                audio_bytes=b'fake-audio',
                filename='test.wav',
                content_type='audio/wav',
                model_id='whisper',
                requested_response_format='json',
            )

    async def test_transcribe_upstream_4xx_raises_bad_request(self):
        invoker = self._build_invoker(WHISPER_MODEL)
        request = httpx.Request('POST', 'https://api.openai.com/v1/audio/transcriptions')
        response = httpx.Response(status_code=400, request=request)
        exception = APIStatusError('Invalid file', response=response, body=None)
        mock_client = MockTranscriptionClient(exception=exception)
        invoker.model_map['whisper'] = (WHISPER_MODEL, mock_client, [])

        with pytest.raises(ModelInvokerBadRequest):
            await invoker.transcribe(
                audio_bytes=b'fake-audio',
                filename='test.wav',
                content_type='audio/wav',
                model_id='whisper',
                requested_response_format='json',
            )

    async def test_transcribe_connection_error_raises_internal_error(self):
        invoker = self._build_invoker(WHISPER_MODEL)
        request = httpx.Request('POST', 'https://api.openai.com/v1/audio/transcriptions')
        exception = APIConnectionError(message='Connection failed', request=request)
        mock_client = MockTranscriptionClient(exception=exception)
        invoker.model_map['whisper'] = (WHISPER_MODEL, mock_client, [])

        with pytest.raises(ModelInvokerInternalError):
            await invoker.transcribe(
                audio_bytes=b'fake-audio',
                filename='test.wav',
                content_type='audio/wav',
                model_id='whisper',
                requested_response_format='json',
            )

    def test_model_map_initialization(self):
        invoker = self._build_invoker(WHISPER_MODEL)
        assert 'whisper' in invoker.model_map


if __name__ == '__main__':
    unittest.main()
