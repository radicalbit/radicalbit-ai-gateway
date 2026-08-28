import datetime
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient
from freezegun import freeze_time
from langchain_core.messages import HumanMessage, SystemMessage
from openai.types.audio.transcription import Transcription
from openai.types.audio.transcription_text_delta_event import (
    TranscriptionTextDeltaEvent,
)
from openai.types.audio.transcription_text_done_event import TranscriptionTextDoneEvent
from openai.types.audio.transcription_verbose import TranscriptionVerbose
from openai.types.create_embedding_response import CreateEmbeddingResponse, Usage
from openai.types.embedding import Embedding
import pook
from starlette.requests import Request

from tests.common import db_mock
from tests.common.mocked_build_openai_chat_completion import (
    to_mock_openai_chat_completion,
)
from tests.common.mocked_gateway_config_openai import get_gateway_openai_cached
from tests.common.resolve_route_models import resolve_route_models

from radicalbit_ai_gateway.ai_gateway import GatewayRoute, InvokeResponse
from radicalbit_ai_gateway.caching.gateway_cache import GatewayCache
from radicalbit_ai_gateway.caching.in_memory_cache import CacheToolsInMemory
from radicalbit_ai_gateway.guardrails.guardrail_engine import GuardrailEngine
from radicalbit_ai_gateway.guardrails.judges.judge_engine import JudgeEngine
from radicalbit_ai_gateway.guardrails.presidio import PresidioEngine
from radicalbit_ai_gateway.models.event_dto import WindowStatus
from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.server import app, group_service, key_service
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.dependencies import get_request_uuid
from radicalbit_ai_gateway.utils.exceptions import (
    GatewayBadRequest,
    GatewayInternalError,
    InputTokenLimitExceeded,
    ModelInvokerBadRequest,
    ModelInvokerInternalError,
    OutputTokenLimitExceeded,
    RequestRateLimitExceeded,
)

key = db_mock.get_sample_key_full_out()


def mock_request_uuid(request: Request):
    request.state.request_uuid = str(db_mock.REQUEST_UUID)
    return str(db_mock.REQUEST_UUID)


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gateways_mock = {'rb-gateway': cls._create_mock_gateway()}
        cls.cost_service: CostService = MagicMock(spec_set=CostService)
        cls.prompt_manager: PromptManager = MagicMock(spec_set=PromptManager)
        app.state.routes = cls.gateways_mock
        app.dependency_overrides[get_request_uuid] = mock_request_uuid
        cls.client = TestClient(app)
        cls.headers = {'Authorization': f'Bearer {db_mock.PLAIN_KEY}'}
        cls.hashed_api_key = db_mock.HASHED_KEY
        cls.emit_event_patcher = patch(
            'radicalbit_ai_gateway.limiting.rate_limiter.emit_event', autospec=True
        )
        cls.emit_event_patcher.start()

    @staticmethod
    def _create_mock_gateway():
        """Create a properly configured mock GatewayRoute with request_rate_limiter."""
        mock_gateway = MagicMock(spec=GatewayRoute)
        mock_rate_limiter = MagicMock()
        mock_rate_limiter.check_request = AsyncMock()
        mock_rate_limiter.count_request = AsyncMock()
        mock_rate_limiter.check_and_count_request = AsyncMock()
        mock_gateway.request_rate_limiter = mock_rate_limiter
        mock_gateway.gateway_route_config = MagicMock()
        mock_gateway.gateway_route_config.route_name = 'rb-gateway'
        mock_gateway.project_uuid = ''
        mock_gateway.project_name = ''
        return mock_gateway

    def setUp(self):
        self.gateways_mock['rb-gateway'] = self._create_mock_gateway()
        app.state.routes = self.gateways_mock

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides = {}
        cls.emit_event_patcher.stop()

    def test_health_check(self):
        response = self.client.get('/health')
        assert response.status_code == 200
        data = response.json()
        assert data['status'] == WindowStatus.OK
        assert data['service'] == 'Radicalbit AI Gateway'
        assert data['gateway_initialized']

    def test_chat_completions(self):
        api_key = db_mock.get_sample_key_with_group(group_uuid=db_mock.GROUP_UUID)
        key_service.get_key_by_hashed_key = MagicMock(return_value=api_key)
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)
        mock_chat_completion = to_mock_openai_chat_completion(content='Hi')
        # invoke() now returns InvokeResponse with content and headers
        invoke_response = InvokeResponse(
            content=mock_chat_completion,
            headers={},
        )
        self.gateways_mock['rb-gateway'].invoke.return_value = invoke_response

        request_data = {
            'model': 'rb-gateway',
            'messages': [
                {'role': 'system', 'content': 'You are a helpful assistant.'},
                {'role': 'user', 'content': 'Hello!'},
            ],
        }
        expected_response = jsonable_encoder(mock_chat_completion)
        response = self.client.post(
            '/v1/chat/completions', json=request_data, headers=self.headers
        )
        assert response.status_code == 200
        assert response.json() == expected_response
        # Verify invoke was called with all parameters including request
        call_args = self.gateways_mock['rb-gateway'].invoke.call_args
        assert call_args is not None
        assert call_args.kwargs['messages'] == [
            SystemMessage(content='You are a helpful assistant.'),
            HumanMessage(content='Hello!'),
        ]
        assert call_args.kwargs['route_name'] == 'rb-gateway'
        assert call_args.kwargs['tools'] == []
        assert call_args.kwargs['tool_choice'] == 'auto'
        assert call_args.kwargs['request_uuid'] == str(db_mock.REQUEST_UUID)
        assert call_args.kwargs['api_key_uuid'] == str(api_key.uuid)
        assert call_args.kwargs['api_key_name'] == api_key.name

    def test_wrong_model_name(self):
        key_service.get_key_by_hashed_key = MagicMock(
            return_value=db_mock.get_sample_key_with_group(
                group_uuid=db_mock.GROUP_UUID
            )
        )
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)
        self.gateways_mock['rb-gateway'].invoke.side_effect = GatewayBadRequest(
            'The model_id openai must be the route name'
        )
        request_data = {
            'model': 'openai',
            'messages': [
                {'role': 'system', 'content': 'You are a helpful assistant.'},
                {'role': 'user', 'content': 'Hello!'},
            ],
        }
        response = self.client.post(
            '/v1/chat/completions', json=request_data, headers=self.headers
        )
        assert response.status_code == 400

    def test_token_input_limiting(self):
        key_service.get_key_by_hashed_key = MagicMock(
            return_value=db_mock.get_sample_key_with_group(
                group_uuid=db_mock.GROUP_UUID
            )
        )
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)
        self.gateways_mock['rb-gateway'].invoke.side_effect = InputTokenLimitExceeded(
            'Input token limit exceeded'
        )
        request_data = {
            'model': 'rb-gateway',
            'messages': [
                {'role': 'system', 'content': 'You are a helpful assistant.'},
                {'role': 'user', 'content': 'Hello!'},
            ],
        }
        response = self.client.post(
            '/v1/chat/completions', json=request_data, headers=self.headers
        )
        assert response.status_code == 429

    def test_token_output_limiting(self):
        key_service.get_key_by_hashed_key = MagicMock(
            return_value=db_mock.get_sample_key_with_group(
                group_uuid=db_mock.GROUP_UUID
            )
        )
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)
        self.gateways_mock['rb-gateway'].invoke.side_effect = OutputTokenLimitExceeded(
            'Output token limit exceeded'
        )
        request_data = {
            'model': 'rb-gateway',
            'messages': [
                {'role': 'system', 'content': 'You are a helpful assistant.'},
                {'role': 'user', 'content': 'Hello!'},
            ],
        }
        response = self.client.post(
            '/v1/chat/completions', json=request_data, headers=self.headers
        )
        assert response.status_code == 429

    def test_rate_input_limiting(self):
        key_service.get_key_by_hashed_key = MagicMock(
            return_value=db_mock.get_sample_key_with_group(
                group_uuid=db_mock.GROUP_UUID
            )
        )
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)
        self.gateways_mock['rb-gateway'].invoke.side_effect = RequestRateLimitExceeded(
            'Request rate limit exceeded for route rb-gateway'
        )
        request_data = {
            'model': 'rb-gateway',
            'messages': [
                {'role': 'system', 'content': 'You are a helpful assistant.'},
                {'role': 'user', 'content': 'Hello!'},
            ],
        }
        response = self.client.post(
            '/v1/chat/completions', json=request_data, headers=self.headers
        )
        assert response.status_code == 429

    def test_rate_output_limiting(self):
        key_service.get_key_by_hashed_key = MagicMock(
            return_value=db_mock.get_sample_key_with_group(
                group_uuid=db_mock.GROUP_UUID
            )
        )
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)
        self.gateways_mock['rb-gateway'].invoke.side_effect = RequestRateLimitExceeded(
            'Request rate limit exceeded for route rb-gateway'
        )
        request_data = {
            'model': 'rb-gateway',
            'messages': [
                {'role': 'system', 'content': 'You are a helpful assistant.'},
                {'role': 'user', 'content': 'Hello!'},
            ],
        }
        response = self.client.post(
            '/v1/chat/completions', json=request_data, headers=self.headers
        )
        assert response.status_code == 429

    def test_runtime_error_on_routing_select_model(self):
        key_service.get_key_by_hashed_key = MagicMock(
            return_value=db_mock.get_sample_key_with_group(
                group_uuid=db_mock.GROUP_UUID
            )
        )
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)
        self.gateways_mock['rb-gateway'].invoke.side_effect = GatewayInternalError(
            'Setup routing before selecting the model'
        )
        request_data = {
            'model': 'rb-gateway',
            'messages': [
                {'role': 'system', 'content': 'You are a helpful assistant.'},
                {'role': 'user', 'content': 'Hello!'},
            ],
        }
        response = self.client.post(
            '/v1/chat/completions', json=request_data, headers=self.headers
        )
        assert response.status_code == 500

    def test_model_not_defined(self):
        key_service.get_key_by_hashed_key = MagicMock(
            return_value=db_mock.get_sample_key_with_group(
                group_uuid=db_mock.GROUP_UUID
            )
        )
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)
        self.gateways_mock['rb-gateway'].invoke.side_effect = ModelInvokerBadRequest(
            "Model 'undefined-model' is not defined."
        )
        request_data = {
            'model': 'openai/claude',
            'messages': [
                {'role': 'system', 'content': 'You are a helpful assistant.'},
                {'role': 'user', 'content': 'Hello!'},
            ],
        }
        response = self.client.post(
            '/v1/chat/completions', json=request_data, headers=self.headers
        )
        assert response.status_code == 400

    def test_invalid_model_format(self):
        key_service.get_key_by_hashed_key = MagicMock(
            return_value=db_mock.get_sample_key_with_group(
                group_uuid=db_mock.GROUP_UUID
            )
        )
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)
        self.gateways_mock['rb-gateway'].invoke.side_effect = ModelInvokerBadRequest(
            "Model field must be in format '<provider>/<model>', got: 'invalid-format'"
        )
        request_data = {
            'model': 'invalid-format',
            'messages': [
                {'role': 'system', 'content': 'You are a helpful assistant.'},
                {'role': 'user', 'content': 'Hello!'},
            ],
        }
        response = self.client.post(
            '/v1/chat/completions', json=request_data, headers=self.headers
        )
        assert response.status_code == 400

    def test_unsupported_provider(self):
        key_service.get_key_by_hashed_key = MagicMock(
            return_value=db_mock.get_sample_key_with_group(
                group_uuid=db_mock.GROUP_UUID
            )
        )
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)
        self.gateways_mock['rb-gateway'].invoke.side_effect = ModelInvokerBadRequest(
            "Unsupported provider: 'unsupported_provider'"
        )
        request_data = {
            'model': 'unsupported_provider/some-model',
            'messages': [
                {'role': 'system', 'content': 'You are a helpful assistant.'},
                {'role': 'user', 'content': 'Hello!'},
            ],
        }
        response = self.client.post(
            '/v1/chat/completions', json=request_data, headers=self.headers
        )
        assert response.status_code == 400

    def test_model_runnable_creation_fails(self):
        key_service.get_key_by_hashed_key = MagicMock(
            return_value=db_mock.get_sample_key_with_group(
                group_uuid=db_mock.GROUP_UUID
            )
        )
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)
        self.gateways_mock['rb-gateway'].invoke.side_effect = ModelInvokerInternalError(
            "Failed to create runnable for model 'openai/o1-mini'."
        )
        request_data = {
            'model': 'rb-gateway',
            'messages': [
                {'role': 'system', 'content': 'You are a helpful assistant.'},
                {'role': 'user', 'content': 'Hello!'},
            ],
        }
        response = self.client.post(
            '/v1/chat/completions', json=request_data, headers=self.headers
        )
        assert response.status_code == 500

    def test_missing_api_key(self):
        request_data = {
            'model': 'rb-gateway',
            'messages': [
                {'role': 'system', 'content': 'You are a helpful assistant.'},
                {'role': 'user', 'content': 'Hello!'},
            ],
        }
        response = self.client.post('/v1/chat/completions', json=request_data)
        assert response.status_code == 401

    def test_wrong_api_key(self):
        key_service.get_key_by_hashed_key = MagicMock(
            return_value=db_mock.get_sample_key_with_group(
                group_uuid=db_mock.GROUP_UUID
            )
        )
        group_service.check_key_uuid_for_route = MagicMock(return_value=False)
        request_data = {
            'model': 'rb-gateway',
            'messages': [
                {'role': 'system', 'content': 'You are a helpful assistant.'},
                {'role': 'user', 'content': 'Hello!'},
            ],
        }
        response = self.client.post(
            '/v1/chat/completions', json=request_data, headers=self.headers
        )
        assert response.status_code == 401

    def test_embeddings_success(self):
        api_key = db_mock.get_sample_key_with_group(group_uuid=db_mock.GROUP_UUID)
        key_service.get_key_by_hashed_key = MagicMock(return_value=api_key)
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)

        mock_embedding = CreateEmbeddingResponse(
            data=[
                Embedding(
                    embedding=[0.1, 0.2, 0.3],
                    index=0,
                    object='embedding',
                )
            ],
            model='text-embedding-3-small',
            object='list',
            usage=Usage(prompt_tokens=0, total_tokens=0),
        )

        self.gateways_mock['rb-gateway'].invoke_embeddings.return_value = mock_embedding

        request_data = {'model': 'rb-gateway', 'input': 'Hello world'}
        response = self.client.post(
            '/v1/embeddings', json=request_data, headers=self.headers
        )

        assert response.status_code == 200
        assert response.json() == jsonable_encoder(mock_embedding, exclude_none=True)
        self.gateways_mock['rb-gateway'].invoke_embeddings.assert_called_once_with(
            route_name='rb-gateway',
            input_texts=['Hello world'],
            request_uuid=str(db_mock.REQUEST_UUID),
            api_key_uuid=str(api_key.uuid),
            api_key_name=api_key.name,
            group_uuid=str(db_mock.GROUP_UUID),
            group_name='group',
        )

    def test_embeddings_wrong_model_name(self):
        key_service.get_key_by_hashed_key = MagicMock(
            return_value=db_mock.get_sample_key_with_group(
                group_uuid=db_mock.GROUP_UUID
            )
        )
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)
        request_data = {'model': 'openai', 'input': 'Hello world'}
        response = self.client.post(
            '/v1/embeddings', json=request_data, headers=self.headers
        )
        assert response.status_code == 400

    def test_embeddings_missing_api_key(self):
        request_data = {'model': 'rb-gateway', 'input': 'Hello world'}
        response = self.client.post('/v1/embeddings', json=request_data)
        assert response.status_code == 401

    def test_embeddings_wrong_api_key(self):
        key_service.get_key_by_hashed_key = MagicMock(
            return_value=db_mock.get_sample_key_with_group(
                group_uuid=db_mock.GROUP_UUID
            )
        )
        group_service.check_key_uuid_for_route = MagicMock(return_value=False)
        request_data = {'model': 'rb-gateway', 'input': 'Hello world'}
        response = self.client.post(
            '/v1/embeddings', json=request_data, headers=self.headers
        )
        assert response.status_code == 401

    def test_audio_transcriptions_success_json(self):
        api_key = db_mock.get_sample_key_with_group(group_uuid=db_mock.GROUP_UUID)
        key_service.get_key_by_hashed_key = MagicMock(return_value=api_key)
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)

        mock_result = Transcription(
            text='Ciao mondo', usage={'type': 'duration', 'seconds': 9}
        )
        self.gateways_mock['rb-gateway'].invoke_transcription = AsyncMock(
            return_value=mock_result
        )

        response = self.client.post(
            '/v1/audio/transcriptions',
            data={'model': 'rb-gateway', 'response_format': 'json'},
            files={'file': ('test.wav', b'fake-audio-bytes', 'audio/wav')},
            headers=self.headers,
        )

        assert response.status_code == 200
        assert response.json() == mock_result.model_dump()
        self.gateways_mock['rb-gateway'].invoke_transcription.assert_awaited_once_with(
            request_uuid=str(db_mock.REQUEST_UUID),
            api_key_uuid=str(api_key.uuid),
            api_key_name=api_key.name,
            group_uuid=str(db_mock.GROUP_UUID),
            group_name='group',
            route_name='rb-gateway',
            audio_bytes=b'fake-audio-bytes',
            filename='test.wav',
            content_type='audio/wav',
            requested_response_format='json',
            language=None,
            prompt=None,
            temperature=None,
        )

    def test_audio_transcriptions_success_verbose_json(self):
        api_key = db_mock.get_sample_key_with_group(group_uuid=db_mock.GROUP_UUID)
        key_service.get_key_by_hashed_key = MagicMock(return_value=api_key)
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)

        mock_result = TranscriptionVerbose(
            task='transcribe',
            language='italian',
            duration=8.25,
            text='Ciao mondo',
            segments=[],
            usage={'type': 'duration', 'seconds': 9},
        )
        self.gateways_mock['rb-gateway'].invoke_transcription = AsyncMock(
            return_value=mock_result
        )

        response = self.client.post(
            '/v1/audio/transcriptions',
            data={'model': 'rb-gateway', 'response_format': 'verbose_json'},
            files={'file': ('test.wav', b'fake-audio-bytes', 'audio/wav')},
            headers=self.headers,
        )

        assert response.status_code == 200
        assert response.json() == mock_result.model_dump()
        self.gateways_mock['rb-gateway'].invoke_transcription.assert_awaited_once_with(
            request_uuid=str(db_mock.REQUEST_UUID),
            api_key_uuid=str(api_key.uuid),
            api_key_name=api_key.name,
            group_uuid=str(db_mock.GROUP_UUID),
            group_name='group',
            route_name='rb-gateway',
            audio_bytes=b'fake-audio-bytes',
            filename='test.wav',
            content_type='audio/wav',
            requested_response_format='verbose_json',
            language=None,
            prompt=None,
            temperature=None,
        )

    def test_audio_transcriptions_rejects_unsupported_response_format(self):
        """response_format is pinned to `Literal['json', 'verbose_json']` at
        the request schema — anything else is rejected before it even
        reaches the invoker.
        """
        api_key = db_mock.get_sample_key_with_group(group_uuid=db_mock.GROUP_UUID)
        key_service.get_key_by_hashed_key = MagicMock(return_value=api_key)
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)

        response = self.client.post(
            '/v1/audio/transcriptions',
            data={'model': 'rb-gateway', 'response_format': 'text'},
            files={'file': ('test.wav', b'fake-audio-bytes', 'audio/wav')},
            headers=self.headers,
        )

        assert response.status_code == 422

    def test_audio_transcriptions_wrong_model_name(self):
        key_service.get_key_by_hashed_key = MagicMock(
            return_value=db_mock.get_sample_key_with_group(
                group_uuid=db_mock.GROUP_UUID
            )
        )
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)
        response = self.client.post(
            '/v1/audio/transcriptions',
            data={'model': 'unknown-route'},
            files={'file': ('test.wav', b'fake-audio-bytes', 'audio/wav')},
            headers=self.headers,
        )
        assert response.status_code == 400

    def test_audio_transcriptions_missing_api_key(self):
        response = self.client.post(
            '/v1/audio/transcriptions',
            data={'model': 'rb-gateway'},
            files={'file': ('test.wav', b'fake-audio-bytes', 'audio/wav')},
        )
        assert response.status_code == 401

    def test_audio_transcriptions_wrong_api_key(self):
        key_service.get_key_by_hashed_key = MagicMock(
            return_value=db_mock.get_sample_key_with_group(
                group_uuid=db_mock.GROUP_UUID
            )
        )
        group_service.check_key_uuid_for_route = MagicMock(return_value=False)
        response = self.client.post(
            '/v1/audio/transcriptions',
            data={'model': 'rb-gateway'},
            files={'file': ('test.wav', b'fake-audio-bytes', 'audio/wav')},
            headers=self.headers,
        )
        assert response.status_code == 401

    def test_audio_transcriptions_does_not_reject_by_extension(self):
        """The gateway no longer validates audio format/extension — an
        unsupported format is left to the upstream provider to reject (see
        `TranscriptionModelInvoker.transcribe`'s `openai.APIStatusError`
        handling), so a `.txt` upload still reaches `invoke_transcription`.
        """
        key_service.get_key_by_hashed_key = MagicMock(
            return_value=db_mock.get_sample_key_with_group(
                group_uuid=db_mock.GROUP_UUID
            )
        )
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)

        mock_result = Transcription(text='irrelevant')
        self.gateways_mock['rb-gateway'].invoke_transcription = AsyncMock(
            return_value=mock_result
        )

        response = self.client.post(
            '/v1/audio/transcriptions',
            data={'model': 'rb-gateway'},
            files={'file': ('test.txt', b'not-audio', 'text/plain')},
            headers=self.headers,
        )
        assert response.status_code == 200
        self.gateways_mock['rb-gateway'].invoke_transcription.assert_awaited_once()

    def test_audio_transcriptions_streaming(self):
        key_service.get_key_by_hashed_key = MagicMock(
            return_value=db_mock.get_sample_key_with_group(
                group_uuid=db_mock.GROUP_UUID
            )
        )
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)

        async def mock_invoke_transcription_stream(*args, **kwargs):
            yield TranscriptionTextDeltaEvent(
                type='transcript.text.delta', delta='Ciao, '
            )
            yield TranscriptionTextDeltaEvent(
                type='transcript.text.delta', delta='mondo.'
            )
            yield TranscriptionTextDoneEvent(
                type='transcript.text.done',
                text='Ciao, mondo.',
                usage={
                    'type': 'tokens',
                    'input_tokens': 1,
                    'output_tokens': 1,
                    'total_tokens': 2,
                },
            )

        self.gateways_mock[
            'rb-gateway'
        ].invoke_transcription_stream = mock_invoke_transcription_stream

        response = self.client.post(
            '/v1/audio/transcriptions',
            data={'model': 'rb-gateway', 'stream': 'true'},
            files={'file': ('test.wav', b'fake-audio-bytes', 'audio/wav')},
            headers=self.headers,
        )

        assert response.status_code == 200
        assert response.headers['content-type'] == 'text/event-stream; charset=utf-8'

        lines = response.text.strip().split('\n\n')
        assert len(lines) == 4
        assert lines[0].startswith('data: ')
        assert lines[1].startswith('data: ')
        assert lines[2].startswith('data: ')
        assert lines[3] == 'data: [DONE]'

        chunk1 = json.loads(lines[0][6:])
        assert chunk1['delta'] == 'Ciao, '
        chunk3 = json.loads(lines[2][6:])
        assert chunk3['text'] == 'Ciao, mondo.'

    def test_audio_transcriptions_streaming_whisper_rejected_returns_error_status(self):
        """When invoke_transcription_stream fails before yielding anything
        (e.g. stream=true against a whisper-1 route), the response should be
        a proper HTTP error, not a 200 with an error hidden in the SSE body.
        """
        key_service.get_key_by_hashed_key = MagicMock(
            return_value=db_mock.get_sample_key_with_group(
                group_uuid=db_mock.GROUP_UUID
            )
        )
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)

        async def mock_invoke_transcription_stream_error(*args, **kwargs):
            raise ModelInvokerBadRequest(
                'stream=true is only supported for the gpt-4o-transcribe family; '
                'whisper-1 does not support streaming.'
            )
            yield  # noqa: RUF027 — makes this an async generator

        self.gateways_mock[
            'rb-gateway'
        ].invoke_transcription_stream = mock_invoke_transcription_stream_error

        response = self.client.post(
            '/v1/audio/transcriptions',
            data={'model': 'rb-gateway', 'stream': 'true'},
            files={'file': ('test.wav', b'fake-audio-bytes', 'audio/wav')},
            headers=self.headers,
        )

        assert response.status_code == 400
        body = response.json()
        assert 'error' in body
        assert 'whisper-1 does not support streaming' in body['error']['message']

    @patch('radicalbit_ai_gateway.ai_gateway.emit_event', autospec=True)
    @patch('radicalbit_ai_gateway.invocation.model_invoker.emit_event', autospec=True)
    @pook.activate
    def test_cache_hit_header_in_http_response(
        self,
        mock_emit_event,
        model_invoker_emit_event,
    ):
        """Test end-to-end: verifies that the X-RB-AIGATEWAY-CACHE-HIT header is added
        to the HTTP response when cache is used.

        This test verifies the complete flow:
        1. First request populates the cache
        2. Second identical request uses the cache
        3. The cache_hit flag is propagated from thread pool to main thread
        4. The middleware adds the header to the HTTP response
        """
        pook.enable_network()

        # Setup: configure a real GatewayRoute with cache
        gateway_config = get_gateway_openai_cached()

        guardrail_engine = GuardrailEngine(
            presidio_engine=PresidioEngine(),
            judge_engine=JudgeEngine(prompt_manager=self.prompt_manager),
            cost_service=self.cost_service,
            guardrails=gateway_config.guardrails or [],
        )
        in_memory_cache = CacheToolsInMemory()
        gateway_cache = GatewayCache(in_memory_cache)
        route_cfg, chat_models, embedding_models = resolve_route_models(
            gateway_config, 'rb-gateway'
        )

        real_gateway = GatewayRoute(
            gateway_route_config=route_cfg,
            chat_models=chat_models,
            embedding_models=embedding_models,
            guardrail_engine=guardrail_engine,
            gateway_cache=gateway_cache,
            cost_service=self.cost_service,
        )

        # Replace the mock with the real GatewayRoute
        self.gateways_mock['rb-gateway'] = real_gateway
        app.state.routes = self.gateways_mock

        # Mock external HTTP response (only for the first call)
        mocked_response = to_mock_openai_chat_completion(content='Paris')
        pook.post(
            url='https://api.openai.com/v1/chat/completions',
            times=1,  # Only one HTTP call, the second will use cache
            reply=200,
            response_json=mocked_response.model_dump_json(),
        )

        api_key = db_mock.get_sample_key_with_group(group_uuid=db_mock.GROUP_UUID)
        key_service.get_key_by_hashed_key = MagicMock(return_value=api_key)
        group_service.check_key_uuid_for_route = MagicMock(return_value=True)

        request_data = {
            'model': 'rb-gateway',
            'messages': [
                {'role': 'user', 'content': 'What is the capital of France?'},
            ],
        }

        initial_datetime = datetime.datetime(
            year=2025, month=7, day=30, hour=10, minute=0, second=0
        )
        with freeze_time(initial_datetime):
            # First request: populates the cache
            response1 = self.client.post(
                '/v1/chat/completions', json=request_data, headers=self.headers
            )
            assert response1.status_code == 200
            assert response1.json()['choices'][0]['message']['content'] == 'Paris'
            # First request should not have the header (cache miss)
            assert 'X-RB-AIGATEWAY-CACHE-HIT' not in response1.headers

            # Second identical request: should use the cache
            response2 = self.client.post(
                '/v1/chat/completions', json=request_data, headers=self.headers
            )
            assert response2.status_code == 200
            assert response2.json()['choices'][0]['message']['content'] == 'Paris'
            # Second request SHOULD have the header (cache hit)
            assert 'X-RB-AIGATEWAY-CACHE-HIT' in response2.headers
            assert response2.headers['X-RB-AIGATEWAY-CACHE-HIT'] == 'true'

        # Verify that only one external HTTP call was made
        assert len(pook.pending_mocks()) == 0

        pook.disable_network()
