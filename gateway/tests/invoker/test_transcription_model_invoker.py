from decimal import Decimal
import unittest
from unittest.mock import MagicMock, patch

import httpx
from openai import APIConnectionError, APIStatusError
from openai.types.audio.transcription import Transcription
from openai.types.audio.transcription_text_delta_event import (
    TranscriptionTextDeltaEvent,
)
from openai.types.audio.transcription_text_done_event import TranscriptionTextDoneEvent
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


_COMMON_TRANSCRIBE_KWARGS = {
    'request_uuid': 'req',
    'api_key_uuid': 'key',
    'group_uuid': 'grp',
    'api_key_name': 'rb-key',
    'group_name': 'test-group',
    'route_name': 'test-route',
}


class TestTranscriptionModelInvoker(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.emit_event_patcher = patch(
            'radicalbit_ai_gateway.invocation.model_invoker.emit_event', autospec=True
        )
        cls.mock_emit_event = cls.emit_event_patcher.start()

    @classmethod
    def tearDownClass(cls):
        cls.emit_event_patcher.stop()

    def setUp(self):
        self.mock_emit_event.reset_mock()

    def _build_invoker(self, model: Model) -> TranscriptionModelInvoker:
        cost_service: CostService = MagicMock(spec_set=CostService)
        return TranscriptionModelInvoker(models=[model], cost_service=cost_service)

    async def test_transcribe_whisper_success_forces_verbose_json_upstream(self):
        invoker = self._build_invoker(WHISPER_MODEL)
        mock_client = MockTranscriptionClient(response=WHISPER_VERBOSE_RESPONSE)
        invoker.model_map['whisper'] = (WHISPER_MODEL, mock_client, [])

        result = await invoker.transcribe(
            **_COMMON_TRANSCRIBE_KWARGS,
            audio_bytes=b'fake-audio',
            filename='test.wav',
            content_type='audio/wav',
            model_id='whisper',
        )

        # Client asked for `json`, but the model is whisper-1: upstream call
        # must still use verbose_json (to guarantee usage). The response is
        # always a real OpenAI type, never a custom shape: built fresh as a
        # `Transcription` here since whisper's upstream call was verbose_json.
        assert mock_client.captured_kwargs['response_format'] == 'verbose_json'
        assert isinstance(result, Transcription)
        assert result.text == 'Ciao, questo è un test.'
        assert result.usage.model_dump() == WHISPER_VERBOSE_RESPONSE.usage.model_dump()
        assert result.usage.type == 'duration'

    async def test_transcribe_gpt4o_success_uses_json_upstream(self):
        invoker = self._build_invoker(GPT4O_TRANSCRIBE_MODEL)
        mock_client = MockTranscriptionClient(response=GPT4O_JSON_RESPONSE)
        invoker.model_map['gpt4o-transcribe'] = (
            GPT4O_TRANSCRIBE_MODEL,
            mock_client,
            [],
        )

        result = await invoker.transcribe(
            **_COMMON_TRANSCRIBE_KWARGS,
            audio_bytes=b'fake-audio',
            filename='test.wav',
            content_type='audio/wav',
            model_id='gpt4o-transcribe',
        )

        assert mock_client.captured_kwargs['response_format'] == 'json'
        # json matches gpt-4o-transcribe's upstream call exactly: the raw
        # Transcription is returned as-is, no conversion needed.
        assert result is GPT4O_JSON_RESPONSE
        assert result.usage.type == 'tokens'
        assert result.usage.input_token_details.audio_tokens == 82

    async def test_transcribe_whisper_sets_span_attributes_without_audio_bytes(self):
        invoker = self._build_invoker(WHISPER_MODEL)
        mock_client = MockTranscriptionClient(response=WHISPER_VERBOSE_RESPONSE)
        invoker.model_map['whisper'] = (WHISPER_MODEL, mock_client, [])

        mock_span = MagicMock()
        mock_span.is_recording.return_value = True

        with patch(
            'radicalbit_ai_gateway.invocation.transcription_model_invoker.trace.get_current_span',
            return_value=mock_span,
        ):
            await invoker.transcribe(
                **_COMMON_TRANSCRIBE_KWARGS,
                audio_bytes=b'fake-audio',
                filename='test.wav',
                content_type='audio/wav',
                model_id='whisper',
            )

        mock_span.set_attribute.assert_any_call(
            'transcription.request.filename', 'test.wav'
        )
        mock_span.set_attribute.assert_any_call(
            'transcription.request.content_type', 'audio/wav'
        )
        mock_span.set_attribute.assert_any_call(
            'transcription.request.audio_size_bytes', len(b'fake-audio')
        )
        mock_span.set_attribute.assert_any_call(
            'transcription.request.model_id', 'whisper'
        )
        mock_span.set_attribute.assert_any_call(
            'transcription.response.text_length', len('Ciao, questo è un test.')
        )
        mock_span.set_attribute.assert_any_call(
            'transcription.response.language', 'italian'
        )
        mock_span.set_attribute.assert_any_call(
            'transcription.response.duration_seconds', 8.25
        )
        mock_span.set_attribute.assert_any_call(
            'transcription.response.segment_count', 0
        )
        # AG-895: never the raw audio content, only its size.
        for call in mock_span.set_attribute.call_args_list:
            assert b'fake-audio' not in call.args

    async def test_transcribe_gpt4o_sets_span_attributes_without_whisper_fields(self):
        invoker = self._build_invoker(GPT4O_TRANSCRIBE_MODEL)
        mock_client = MockTranscriptionClient(response=GPT4O_JSON_RESPONSE)
        invoker.model_map['gpt4o-transcribe'] = (
            GPT4O_TRANSCRIBE_MODEL,
            mock_client,
            [],
        )

        mock_span = MagicMock()
        mock_span.is_recording.return_value = True

        with patch(
            'radicalbit_ai_gateway.invocation.transcription_model_invoker.trace.get_current_span',
            return_value=mock_span,
        ):
            await invoker.transcribe(
                **_COMMON_TRANSCRIBE_KWARGS,
                audio_bytes=b'fake-audio',
                filename='test.wav',
                content_type='audio/wav',
                model_id='gpt4o-transcribe',
            )

        mock_span.set_attribute.assert_any_call(
            'transcription.request.model_id', 'gpt4o-transcribe'
        )
        mock_span.set_attribute.assert_any_call(
            'transcription.response.text_length', len('Ciao, questo è un test.')
        )
        # gpt-4o-transcribe's Transcription has no language/duration/segments.
        set_attrs = {c.args[0] for c in mock_span.set_attribute.call_args_list}
        assert 'transcription.response.language' not in set_attrs
        assert 'transcription.response.duration_seconds' not in set_attrs
        assert 'transcription.response.segment_count' not in set_attrs

    async def test_transcribe_whisper_verbose_json_passthrough(self):
        invoker = self._build_invoker(WHISPER_MODEL)
        mock_client = MockTranscriptionClient(response=WHISPER_VERBOSE_RESPONSE)
        invoker.model_map['whisper'] = (WHISPER_MODEL, mock_client, [])

        result = await invoker.transcribe(
            **_COMMON_TRANSCRIBE_KWARGS,
            audio_bytes=b'fake-audio',
            filename='test.wav',
            content_type='audio/wav',
            model_id='whisper',
            requested_response_format='verbose_json',
        )

        # verbose_json matches whisper's upstream call exactly: the raw
        # TranscriptionVerbose is returned as-is, no conversion needed.
        assert result is WHISPER_VERBOSE_RESPONSE
        assert isinstance(result, TranscriptionVerbose)
        assert result.segments == []
        assert result.duration == 8.25

    async def test_transcribe_gpt4o_rejects_verbose_json(self):
        invoker = self._build_invoker(GPT4O_TRANSCRIBE_MODEL)
        mock_client = MockTranscriptionClient(response=GPT4O_JSON_RESPONSE)
        invoker.model_map['gpt4o-transcribe'] = (
            GPT4O_TRANSCRIBE_MODEL,
            mock_client,
            [],
        )

        with pytest.raises(
            ModelInvokerBadRequest, match='only supported for whisper-1'
        ):
            await invoker.transcribe(
                **_COMMON_TRANSCRIBE_KWARGS,
                audio_bytes=b'fake-audio',
                filename='test.wav',
                content_type='audio/wav',
                model_id='gpt4o-transcribe',
                requested_response_format='verbose_json',
            )

    async def test_transcribe_rejects_unsupported_response_format(self):
        invoker = self._build_invoker(WHISPER_MODEL)
        mock_client = MockTranscriptionClient(response=WHISPER_VERBOSE_RESPONSE)
        invoker.model_map['whisper'] = (WHISPER_MODEL, mock_client, [])

        with pytest.raises(ModelInvokerBadRequest, match='Unsupported response_format'):
            await invoker.transcribe(
                **_COMMON_TRANSCRIBE_KWARGS,
                audio_bytes=b'fake-audio',
                filename='test.wav',
                content_type='audio/wav',
                model_id='whisper',
                requested_response_format='text',
            )

    async def test_transcribe_unknown_model_id_raises_bad_request(self):
        invoker = self._build_invoker(WHISPER_MODEL)

        with pytest.raises(ModelInvokerBadRequest, match='not defined'):
            await invoker.transcribe(
                **_COMMON_TRANSCRIBE_KWARGS,
                audio_bytes=b'fake-audio',
                filename='test.wav',
                content_type='audio/wav',
                model_id='unknown-model',
            )

    async def test_transcribe_upstream_5xx_raises_internal_error(self):
        invoker = self._build_invoker(WHISPER_MODEL)
        request = httpx.Request(
            'POST', 'https://api.openai.com/v1/audio/transcriptions'
        )
        response = httpx.Response(status_code=503, request=request)
        exception = APIStatusError('Service unavailable', response=response, body=None)
        mock_client = MockTranscriptionClient(exception=exception)
        invoker.model_map['whisper'] = (WHISPER_MODEL, mock_client, [])

        with pytest.raises(ModelInvokerInternalError):
            await invoker.transcribe(
                **_COMMON_TRANSCRIBE_KWARGS,
                audio_bytes=b'fake-audio',
                filename='test.wav',
                content_type='audio/wav',
                model_id='whisper',
            )

    async def test_transcribe_upstream_4xx_raises_bad_request(self):
        invoker = self._build_invoker(WHISPER_MODEL)
        request = httpx.Request(
            'POST', 'https://api.openai.com/v1/audio/transcriptions'
        )
        response = httpx.Response(status_code=400, request=request)
        exception = APIStatusError('Invalid file', response=response, body=None)
        mock_client = MockTranscriptionClient(exception=exception)
        invoker.model_map['whisper'] = (WHISPER_MODEL, mock_client, [])

        with pytest.raises(ModelInvokerBadRequest):
            await invoker.transcribe(
                **_COMMON_TRANSCRIBE_KWARGS,
                audio_bytes=b'fake-audio',
                filename='test.wav',
                content_type='audio/wav',
                model_id='whisper',
            )

    async def test_transcribe_connection_error_raises_internal_error(self):
        invoker = self._build_invoker(WHISPER_MODEL)
        request = httpx.Request(
            'POST', 'https://api.openai.com/v1/audio/transcriptions'
        )
        exception = APIConnectionError(message='Connection failed', request=request)
        mock_client = MockTranscriptionClient(exception=exception)
        invoker.model_map['whisper'] = (WHISPER_MODEL, mock_client, [])

        with pytest.raises(ModelInvokerInternalError):
            await invoker.transcribe(
                **_COMMON_TRANSCRIBE_KWARGS,
                audio_bytes=b'fake-audio',
                filename='test.wav',
                content_type='audio/wav',
                model_id='whisper',
            )

    async def test_stream_whisper_rejects_before_any_upstream_call(self):
        invoker = self._build_invoker(WHISPER_MODEL)
        mock_client = MockTranscriptionClient(response=WHISPER_VERBOSE_RESPONSE)
        invoker.model_map['whisper'] = (WHISPER_MODEL, mock_client, [])

        with pytest.raises(ModelInvokerBadRequest, match='does not support streaming'):
            async for _ in invoker.stream(
                **_COMMON_TRANSCRIBE_KWARGS,
                audio_bytes=b'fake-audio',
                filename='test.wav',
                content_type='audio/wav',
                model_id='whisper',
            ):
                pass

        assert mock_client.captured_kwargs == {}

    async def test_stream_gpt4o_relays_events_and_records_usage_once(self):
        invoker = self._build_invoker(GPT4O_TRANSCRIBE_MODEL)
        invoker.cost_service.compute_cost.return_value = Decimal('0.000492')
        delta_1 = TranscriptionTextDeltaEvent(
            type='transcript.text.delta', delta='Ciao, '
        )
        delta_2 = TranscriptionTextDeltaEvent(
            type='transcript.text.delta', delta='questo è un test.'
        )
        done = TranscriptionTextDoneEvent(
            type='transcript.text.done',
            text='Ciao, questo è un test.',
            usage={
                'type': 'tokens',
                'input_tokens': 82,
                'output_tokens': 0,
                'total_tokens': 82,
                'input_token_details': {'audio_tokens': 82, 'text_tokens': 0},
            },
        )
        mock_client = MockTranscriptionClient(stream_events=[delta_1, delta_2, done])
        invoker.model_map['gpt4o-transcribe'] = (
            GPT4O_TRANSCRIBE_MODEL,
            mock_client,
            [],
        )

        events = [
            event
            async for event in invoker.stream(
                **_COMMON_TRANSCRIBE_KWARGS,
                audio_bytes=b'fake-audio',
                filename='test.wav',
                content_type='audio/wav',
                model_id='gpt4o-transcribe',
            )
        ]

        assert events == [delta_1, delta_2, done]
        assert mock_client.captured_kwargs['stream'] is True
        assert mock_client.captured_kwargs['response_format'] == 'json'
        # One MODEL_INVOCATION event (_record_metrics) + one cost event
        # (only the audio-token component is non-zero) — both emitted once,
        # after the stream ends, not per-chunk.
        assert self.mock_emit_event.call_count == 2
        invoker.cost_service.compute_cost.assert_called_once_with(
            model_id='gpt4o-transcribe', token_processed=82, where='audio'
        )
        cost_payload = self.mock_emit_event.call_args_list[1].args[0]
        assert cost_payload.cache_type == 'audio'
        assert cost_payload.value == 82

    async def test_stream_gpt4o_upstream_5xx_raises_internal_error(self):
        invoker = self._build_invoker(GPT4O_TRANSCRIBE_MODEL)
        request = httpx.Request(
            'POST', 'https://api.openai.com/v1/audio/transcriptions'
        )
        response = httpx.Response(status_code=503, request=request)
        exception = APIStatusError('Service unavailable', response=response, body=None)
        mock_client = MockTranscriptionClient(exception=exception)
        invoker.model_map['gpt4o-transcribe'] = (
            GPT4O_TRANSCRIBE_MODEL,
            mock_client,
            [],
        )

        with pytest.raises(ModelInvokerInternalError):
            async for _ in invoker.stream(
                **_COMMON_TRANSCRIBE_KWARGS,
                audio_bytes=b'fake-audio',
                filename='test.wav',
                content_type='audio/wav',
                model_id='gpt4o-transcribe',
            ):
                pass

    def test_model_map_initialization(self):
        invoker = self._build_invoker(WHISPER_MODEL)
        assert 'whisper' in invoker.model_map

    def test_record_transcription_usage_cost_duration(self):
        invoker = self._build_invoker(WHISPER_MODEL)
        invoker.cost_service.compute_cost.return_value = Decimal('0.000825')
        usage = MagicMock(type='duration', seconds=8.25)

        total_cost = invoker._record_transcription_usage_cost(
            request_uuid='req',
            api_key_uuid='key',
            api_key_name='rb-key',
            group_name='test-group',
            group_uuid='grp',
            route_name='test-route',
            model=WHISPER_MODEL,
            usage=usage,
        )

        assert total_cost == Decimal('0.000825')
        invoker.cost_service.compute_cost.assert_called_once_with(
            model_id='whisper', token_processed=8.25, where='duration'
        )
        assert self.mock_emit_event.call_count == 1
        payload = self.mock_emit_event.call_args.args[0]
        assert payload.cache_type == 'duration'
        assert payload.value == 8.25

    def test_record_transcription_usage_cost_tokens_with_details(self):
        invoker = self._build_invoker(GPT4O_TRANSCRIBE_MODEL)

        def _side_effect(**kwargs):
            return {
                'audio': Decimal('0.000492'),
                'input': Decimal('0.0000125'),
                'output': Decimal('0.00038'),
            }[kwargs['where']]

        invoker.cost_service.compute_cost.side_effect = _side_effect
        usage = MagicMock(
            type='tokens',
            input_tokens=87,
            output_tokens=38,
            input_token_details=MagicMock(audio_tokens=82, text_tokens=5),
        )

        total_cost = invoker._record_transcription_usage_cost(
            request_uuid='req',
            api_key_uuid='key',
            api_key_name='rb-key',
            group_name='test-group',
            group_uuid='grp',
            route_name='test-route',
            model=GPT4O_TRANSCRIBE_MODEL,
            usage=usage,
        )

        assert total_cost == (
            Decimal('0.000492') + Decimal('0.0000125') + Decimal('0.00038')
        )
        compute_calls = invoker.cost_service.compute_cost.call_args_list
        where_args = {c.kwargs['where'] for c in compute_calls}
        assert where_args == {'audio', 'input', 'output'}
        audio_call = next(c for c in compute_calls if c.kwargs['where'] == 'audio')
        assert audio_call.kwargs['token_processed'] == 82
        text_call = next(c for c in compute_calls if c.kwargs['where'] == 'input')
        assert text_call.kwargs['token_processed'] == 5
        output_call = next(c for c in compute_calls if c.kwargs['where'] == 'output')
        assert output_call.kwargs['token_processed'] == 38
        assert self.mock_emit_event.call_count == 3

    def test_record_transcription_usage_cost_tokens_without_details(self):
        invoker = self._build_invoker(GPT4O_TRANSCRIBE_MODEL)
        invoker.cost_service.compute_cost.return_value = Decimal('0.0001')
        usage = MagicMock(
            type='tokens',
            input_tokens=50,
            output_tokens=0,
            input_token_details=None,
        )

        total_cost = invoker._record_transcription_usage_cost(
            request_uuid='req',
            api_key_uuid='key',
            api_key_name='rb-key',
            group_name='test-group',
            group_uuid='grp',
            route_name='test-route',
            model=GPT4O_TRANSCRIBE_MODEL,
            usage=usage,
        )

        # No input_token_details: all input treated as text-priced;
        # output_tokens == 0 is skipped.
        invoker.cost_service.compute_cost.assert_called_once_with(
            model_id='gpt4o-transcribe', token_processed=50, where='input'
        )
        assert total_cost == Decimal('0.0001')
        assert self.mock_emit_event.call_count == 1

    def test_record_transcription_usage_cost_no_usage(self):
        invoker = self._build_invoker(WHISPER_MODEL)

        total_cost = invoker._record_transcription_usage_cost(
            request_uuid='req',
            api_key_uuid='key',
            api_key_name='rb-key',
            group_name='test-group',
            group_uuid='grp',
            route_name='test-route',
            model=WHISPER_MODEL,
            usage=None,
        )

        assert total_cost == Decimal(0)
        invoker.cost_service.compute_cost.assert_not_called()


if __name__ == '__main__':
    unittest.main()
