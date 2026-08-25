from collections.abc import AsyncIterator
from decimal import Decimal
import logging
import time

import openai
from openai import AsyncAzureOpenAI, AsyncOpenAI
from openai.types.audio.transcription import Transcription
from openai.types.audio.transcription_stream_event import TranscriptionStreamEvent
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


def _set_transcription_fallback_attributes(
    model_id_invoked: str,
    fallback_triggered: bool,
) -> None:
    try:
        span = trace.get_current_span()
        if span.is_recording():
            span.set_attribute('transcription.response.model_id', model_id_invoked)
            span.set_attribute(
                'transcription.response.fallback_triggered', fallback_triggered
            )
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

    def _resolve_model(
        self, model_id: str
    ) -> tuple[Model, AsyncOpenAI | AsyncAzureOpenAI, bool, str, list]:
        if model_id not in self.model_map:
            raise ModelInvokerBadRequest(f'Transcription model {model_id} not defined')
        model, client, fallbacks = self.model_map[model_id]
        _, model_name = parse_provider_and_model(model.model)
        is_whisper = model_name.startswith(WHISPER_FAMILY_PREFIX)
        return model, client, is_whisper, model_name, fallbacks

    @staticmethod
    def _build_create_kwargs(
        model_name: str,
        audio_bytes: bytes,
        filename: str,
        content_type: str | None,
        response_format: str,
        language: str | None,
        prompt: str | None,
        temperature: float | None,
        stream: bool = False,
    ) -> dict:
        create_kwargs: dict = {
            'model': model_name,
            'file': (filename, audio_bytes, content_type or 'application/octet-stream'),
            'response_format': response_format,
        }
        if stream:
            create_kwargs['stream'] = True
        if language:
            create_kwargs['language'] = language
        if prompt:
            create_kwargs['prompt'] = prompt
        if temperature is not None:
            create_kwargs['temperature'] = temperature
        return create_kwargs

    @staticmethod
    async def _create_upstream(
        client: AsyncOpenAI | AsyncAzureOpenAI, create_kwargs: dict
    ):
        try:
            return await client.audio.transcriptions.create(**create_kwargs)
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

    def _finalize_transcription(
        self,
        *,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        route_name: str,
        model_id: str,
        model: Model,
        latency_ms: float,
        usage,
        fallback_triggered: bool = False,
        project_uuid: str = '',
        project_name: str = '',
    ) -> None:
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
            fallback_triggered=fallback_triggered,
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
        model, client, is_whisper, model_name, fallbacks = self._resolve_model(model_id)
        if requested_response_format not in SUPPORTED_RESPONSE_FORMATS:
            raise ModelInvokerBadRequest(
                f'Unsupported response_format {requested_response_format!r}. '
                f'Supported formats: {sorted(SUPPORTED_RESPONSE_FORMATS)}.'
            )
        if requested_response_format == 'verbose_json' and not is_whisper:
            raise ModelInvokerBadRequest(
                'response_format=verbose_json is only supported for whisper-1 models.'
            )

        _set_transcription_request_attributes(
            filename=filename,
            content_type=content_type,
            audio_size_bytes=len(audio_bytes),
            model_id=model_id,
        )

        start_time = time.monotonic()
        model_invoked = model
        fallback_triggered = False
        create_kwargs = self._build_create_kwargs(
            model_name,
            audio_bytes,
            filename,
            content_type,
            'verbose_json' if is_whisper else 'json',
            language,
            prompt,
            temperature,
        )
        try:
            response = await self._create_upstream(client, create_kwargs)
        except Exception as primary_error:
            # A 4xx client-input error would fail identically on any fallback.
            if isinstance(primary_error, ModelInvokerBadRequest):
                raise
            logger.warning(
                'Primary transcription model %s failed: %s. Trying fallbacks...',
                model_id,
                str(primary_error),
            )
            response = None
            for fallback_model, fallback_client in fallbacks or []:
                _, fallback_model_name = parse_provider_and_model(fallback_model.model)
                fallback_is_whisper = fallback_model_name.startswith(
                    WHISPER_FAMILY_PREFIX
                )
                fallback_create_kwargs = self._build_create_kwargs(
                    fallback_model_name,
                    audio_bytes,
                    filename,
                    content_type,
                    'verbose_json' if fallback_is_whisper else 'json',
                    language,
                    prompt,
                    temperature,
                )
                try:
                    response = await self._create_upstream(
                        fallback_client, fallback_create_kwargs
                    )
                    model_invoked = fallback_model
                    is_whisper = fallback_is_whisper
                    fallback_triggered = True
                    break
                except Exception as fallback_error:
                    if isinstance(fallback_error, ModelInvokerBadRequest):
                        raise
                    logger.warning(
                        'Fallback transcription model %s failed: %s',
                        fallback_model.model_id,
                        str(fallback_error),
                    )
            if response is None:
                raise ModelInvokerInternalError(
                    f'All transcription models failed for route {route_name}: {primary_error}'
                ) from primary_error

        latency_ms = (time.monotonic() - start_time) * 1000
        _set_transcription_response_attributes(response, is_whisper)
        _set_transcription_fallback_attributes(
            model_invoked.model_id, fallback_triggered
        )

        usage = response.usage
        if requested_response_format == 'verbose_json' and is_whisper:
            body = response
        elif is_whisper:
            body = Transcription(
                text=response.text,
                usage=usage.model_dump() if usage else None,
            )
        else:
            body = response

        self._finalize_transcription(
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            group_uuid=group_uuid,
            api_key_name=api_key_name,
            group_name=group_name,
            route_name=route_name,
            model_id=model_id,
            model=model_invoked,
            latency_ms=latency_ms,
            usage=usage,
            fallback_triggered=fallback_triggered,
            project_uuid=project_uuid,
            project_name=project_name,
        )

        return body

    @task(name='llm_transcribe_stream')
    async def stream(
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
        language: str | None = None,
        prompt: str | None = None,
        temperature: float | None = None,
        project_uuid: str = '',
        project_name: str = '',
    ) -> AsyncIterator[TranscriptionStreamEvent]:
        model, client, is_whisper, model_name, fallbacks = self._resolve_model(model_id)
        if is_whisper:
            raise ModelInvokerBadRequest(
                'stream=true is only supported for the gpt-4o-transcribe family; '
                'whisper-1 does not support streaming.'
            )

        _set_transcription_request_attributes(
            filename=filename,
            content_type=content_type,
            audio_size_bytes=len(audio_bytes),
            model_id=model_id,
        )

        final_usage = None
        text_parts: list[str] = []

        async def _run_stream(
            target_client: AsyncOpenAI | AsyncAzureOpenAI, target_model_name: str
        ) -> AsyncIterator[TranscriptionStreamEvent]:
            nonlocal final_usage
            upstream_stream = await self._create_upstream(
                target_client,
                self._build_create_kwargs(
                    target_model_name,
                    audio_bytes,
                    filename,
                    content_type,
                    'json',
                    language,
                    prompt,
                    temperature,
                    stream=True,
                ),
            )
            async for event in upstream_stream:
                if event.type == 'transcript.text.delta':
                    text_parts.append(event.delta)
                elif event.type == 'transcript.text.done':
                    final_usage = event.usage
                yield event

        start_time = time.monotonic()
        model_invoked = model
        fallback_triggered = False
        try:
            async for event in _run_stream(client, model_name):
                yield event
        except Exception as primary_error:
            # See transcribe()'s equivalent check: a 4xx client-input error
            # propagates immediately, it would fail identically on any fallback.
            if isinstance(primary_error, ModelInvokerBadRequest):
                raise
            logger.warning(
                'Primary transcription model %s stream failed: %s. Trying fallbacks...',
                model_id,
                str(primary_error),
            )
            fallback_success = False
            for fallback_model, fallback_client in fallbacks or []:
                _, fallback_model_name = parse_provider_and_model(fallback_model.model)
                if fallback_model_name.startswith(WHISPER_FAMILY_PREFIX):
                    logger.warning(
                        'Skipping fallback transcription model %s for streaming: '
                        'whisper-1 does not support streaming.',
                        fallback_model.model_id,
                    )
                    continue
                try:
                    text_parts.clear()
                    final_usage = None
                    async for event in _run_stream(
                        fallback_client, fallback_model_name
                    ):
                        yield event
                    model_invoked = fallback_model
                    fallback_triggered = True
                    fallback_success = True
                    break
                except Exception as fallback_error:
                    if isinstance(fallback_error, ModelInvokerBadRequest):
                        raise
                    logger.warning(
                        'Fallback transcription model %s stream failed: %s',
                        fallback_model.model_id,
                        str(fallback_error),
                    )
            if not fallback_success:
                raise ModelInvokerInternalError(
                    f'All transcription models failed for streaming {route_name}: {primary_error}'
                ) from primary_error
        latency_ms = (time.monotonic() - start_time) * 1000

        try:
            span = trace.get_current_span()
            if span.is_recording():
                span.set_attribute(
                    'transcription.response.text_length', len(''.join(text_parts))
                )
        except Exception:
            pass
        _set_transcription_fallback_attributes(
            model_invoked.model_id, fallback_triggered
        )

        self._finalize_transcription(
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            group_uuid=group_uuid,
            api_key_name=api_key_name,
            group_name=group_name,
            route_name=route_name,
            model_id=model_id,
            model=model_invoked,
            latency_ms=latency_ms,
            usage=final_usage,
            fallback_triggered=fallback_triggered,
            project_uuid=project_uuid,
            project_name=project_name,
        )

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
