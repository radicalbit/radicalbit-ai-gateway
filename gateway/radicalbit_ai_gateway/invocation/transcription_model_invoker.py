from decimal import Decimal
import logging
import time

import openai
from openai import AsyncAzureOpenAI, AsyncOpenAI
from openai.types.audio.transcription import Transcription
from openai.types.audio.transcription_verbose import TranscriptionVerbose
from opentelemetry import trace
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

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)

WHISPER_FAMILY_PREFIX = 'whisper'
SUPPORTED_RESPONSE_FORMATS = {'json', 'verbose_json'}


def _set_transcription_request_attributes(
    filename: str,
    content_type: str | None,
    audio_size_bytes: int,
    model_id: str,
) -> None:
    """Metadata only — never the raw audio bytes."""
    try:
        span = trace.get_current_span()
        if span.is_recording():
            span.set_attribute('transcription.request.filename', filename)
            span.set_attribute('transcription.request.content_type', content_type or '')
            span.set_attribute(
                'transcription.request.audio_size_bytes', audio_size_bytes
            )
            span.set_attribute('transcription.request.model_id', model_id)
    except Exception:
        pass


def _set_transcription_response_attributes(
    response: Transcription | TranscriptionVerbose,
    is_whisper: bool,
) -> None:
    """Metadata only — never the full segments/timestamps array."""
    try:
        span = trace.get_current_span()
        if not span.is_recording():
            return
        span.set_attribute(
            'transcription.response.text_length', len(response.text or '')
        )
        if is_whisper:
            span.set_attribute(
                'transcription.response.language', response.language or ''
            )
            span.set_attribute(
                'transcription.response.duration_seconds', response.duration or 0
            )
            span.set_attribute(
                'transcription.response.segment_count', len(response.segments or [])
            )
    except Exception:
        pass


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
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        route_name: str,
        audio_bytes: bytes,
        filename: str,
        content_type: str | None,
        model_id: str,
        requested_response_format: str = 'json',
        language: str | None = None,
        prompt: str | None = None,
        temperature: float | None = None,
        project_uuid: str = '',
        project_name: str = '',
    ) -> Transcription | TranscriptionVerbose:
        if model_id not in self.model_map:
            raise ModelInvokerBadRequest(f'Transcription model {model_id} not defined')
        if requested_response_format not in SUPPORTED_RESPONSE_FORMATS:
            raise ModelInvokerBadRequest(
                f'Unsupported response_format {requested_response_format!r}. '
                f'Supported formats: {sorted(SUPPORTED_RESPONSE_FORMATS)}.'
            )

        model, client, _fallbacks = self.model_map[model_id]
        _, model_name = parse_provider_and_model(model.model)
        is_whisper = model_name.startswith(WHISPER_FAMILY_PREFIX)
        if requested_response_format == 'verbose_json' and not is_whisper:
            raise ModelInvokerBadRequest(
                'response_format=verbose_json is only supported for whisper-1 models.'
            )
        upstream_format = 'verbose_json' if is_whisper else 'json'

        _set_transcription_request_attributes(
            filename=filename,
            content_type=content_type,
            audio_size_bytes=len(audio_bytes),
            model_id=model_id,
        )

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
            response: (
                Transcription | TranscriptionVerbose
            ) = await client.audio.transcriptions.create(**create_kwargs)
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
        _set_transcription_response_attributes(response, is_whisper)

        usage = response.usage
        if requested_response_format == 'verbose_json':
            # Only reachable for whisper-1
            body = response
        elif is_whisper:
            body = Transcription(
                text=response.text,
                usage=usage.model_dump() if usage else None,
            )
        else:
            body = response

        self._record_metrics(
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            group_uuid=group_uuid,
            api_key_name=api_key_name,
            group_name=group_name,
            route_name=route_name,
            target_model_id=model_id,
            model=model,
            latency_ms=latency_ms,
            model_type='transcription',
            project_uuid=project_uuid,
            project_name=project_name,
        )
        self._record_transcription_usage_cost(
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            group_uuid=group_uuid,
            api_key_name=api_key_name,
            group_name=group_name,
            route_name=route_name,
            model=model,
            usage=usage,
            project_uuid=project_uuid,
            project_name=project_name,
        )

        return body

    def _record_transcription_usage_cost(
        self,
        request_uuid: str,
        api_key_uuid: str,
        api_key_name: str,
        group_name: str,
        group_uuid: str,
        route_name: str,
        model: Model,
        usage,
        project_uuid: str = '',
        project_name: str = '',
    ) -> Decimal:
        if usage is None:
            return Decimal(0)

        common = {
            'request_uuid': request_uuid,
            'api_key_uuid': api_key_uuid,
            'api_key_name': api_key_name,
            'group_name': group_name,
            'group_uuid': group_uuid,
            'route_name': route_name,
            'model': model,
            'model_type': 'transcription',
            'project_uuid': project_uuid,
            'project_name': project_name,
        }

        if usage.type == 'duration':
            return self._emit_input_token_metrics(
                **common,
                token_count=usage.seconds,
                where='duration',
                cache_type='duration',
            )

        details = getattr(usage, 'input_token_details', None)
        audio_tokens = getattr(details, 'audio_tokens', None) or 0
        text_tokens = getattr(details, 'text_tokens', None)
        if text_tokens is None:
            text_tokens = usage.input_tokens

        total_cost = Decimal(0)
        if audio_tokens > 0:
            total_cost += self._emit_input_token_metrics(
                **common,
                token_count=audio_tokens,
                where='audio',
                cache_type='audio',
            )
        if text_tokens > 0:
            total_cost += self._emit_input_token_metrics(
                **common,
                token_count=text_tokens,
                where='input',
                cache_type=None,
            )
        if usage.output_tokens > 0:
            total_cost += self._emit_output_token_metrics(
                **common,
                token_count=usage.output_tokens,
            )
        return total_cost
