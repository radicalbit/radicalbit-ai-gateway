import logging
import time

import openai
from openai import AsyncAzureOpenAI, AsyncOpenAI
from traceloop.sdk.decorators import task

from radicalbit_ai_gateway.invocation.model_invoker import ModelInvoker
from radicalbit_ai_gateway.models.fallback import Fallback
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import (
    ModelInvokerBadRequest,
    ModelInvokerInternalError,
)
from radicalbit_ai_gateway.utils.parse_provider_and_model import (
    parse_provider_and_model,
)
from radicalbit_ai_gateway.utils.transcription_format import (
    convert_transcription_response,
)

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)

WHISPER_FAMILY_PREFIX = 'whisper'


class TranscriptionResult:
    def __init__(
        self,
        body: str | dict,
        content_type: str,
        usage,
        model_invoked: Model,
        latency_ms: float,
    ):
        self.body = body
        self.content_type = content_type
        self.usage = usage
        self.model_invoked = model_invoked
        self.latency_ms = latency_ms


class TranscriptionModelInvoker(ModelInvoker):
    def __init__(
        self,
        models: list[Model],
        cost_service: CostService,
        fallbacks: list[Fallback] | None = None,
        httpx_client=None,
    ):
        super().__init__(
            models=models,
            cost_service=cost_service,
            fallbacks=fallbacks,
            httpx_client=httpx_client,
        )
        self._initialize_models(self._build_model)

    def _build_model(self, model: Model) -> AsyncOpenAI | AsyncAzureOpenAI:
        """Bypasses LangChain: `OpenAIWhisperParser` discards `usage`, needed for cost tracking."""
        provider, _ = parse_provider_and_model(model.model)
        credentials = (
            model.credentials.model_dump(exclude_none=True) if model.credentials else {}
        )
        if provider == 'azure':
            return AsyncAzureOpenAI(
                api_key=credentials.get('api_key'),
                azure_ad_token=credentials.get('azure_ad_token'),
                api_version=credentials.get('api_version'),
                azure_endpoint=credentials.get('api_base')
                or credentials.get('base_url'),
                http_client=self.httpx_client,
            )
        return AsyncOpenAI(
            api_key=credentials.get('api_key'),
            base_url=credentials.get('base_url') or credentials.get('api_base'),
            organization=credentials.get('organization'),
            http_client=self.httpx_client,
        )

    @task(name='llm_transcribe')
    async def transcribe(
        self,
        audio_bytes: bytes,
        filename: str,
        content_type: str | None,
        model_id: str,
        requested_response_format: str,
        language: str | None = None,
        prompt: str | None = None,
        temperature: float | None = None,
    ) -> TranscriptionResult:
        if model_id not in self.model_map:
            raise ModelInvokerBadRequest(f'Transcription model {model_id} not defined')

        model, client, _fallbacks = self.model_map[model_id]
        _, model_name = parse_provider_and_model(model.model)
        is_whisper = model_name.startswith(WHISPER_FAMILY_PREFIX)
        upstream_format = 'verbose_json' if is_whisper else 'json'

        create_kwargs: dict = {
            'model': model_name,
            'file': (filename, audio_bytes, content_type or 'application/octet-stream'),
            'response_format': upstream_format,
        }
        if language:
            create_kwargs['language'] = language
        if prompt:
            create_kwargs['prompt'] = prompt
        if temperature is not None:
            create_kwargs['temperature'] = temperature

        start_time = time.monotonic()
        try:
            response = await client.audio.transcriptions.create(**create_kwargs)
        except openai.APIStatusError as e:
            if 400 <= e.status_code < 500:
                raise ModelInvokerBadRequest(
                    f'Transcription request rejected by upstream provider: {e}'
                ) from e
            raise ModelInvokerInternalError(
                f'Transcription upstream call failed: {e}'
            ) from e
        except openai.APIError as e:
            raise ModelInvokerInternalError(
                f'Transcription upstream call failed: {e}'
            ) from e
        latency_ms = (time.monotonic() - start_time) * 1000

        body, response_content_type = convert_transcription_response(
            response=response,
            requested_format=requested_response_format,
            is_whisper=is_whisper,
        )

        return TranscriptionResult(
            body=body,
            content_type=response_content_type,
            usage=getattr(response, 'usage', None),
            model_invoked=model,
            latency_ms=latency_ms,
        )
