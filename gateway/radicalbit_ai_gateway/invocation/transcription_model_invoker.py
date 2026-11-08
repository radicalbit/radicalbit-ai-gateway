from collections.abc import AsyncIterator
from dataclasses import dataclass
import logging

import openai
from openai import AsyncAzureOpenAI, AsyncOpenAI
from openai.types.audio.transcription import Transcription
from openai.types.audio.transcription_stream_event import TranscriptionStreamEvent
from openai.types.audio.transcription_verbose import TranscriptionVerbose
from opentelemetry import trace
from traceloop.sdk.decorators import task

from radicalbit_ai_gateway.invocation.errors import Surface, raising
from radicalbit_ai_gateway.invocation.fallback_chain import (
    Attempt,
    CallContext,
    Candidate,
    FallbackChain,
    Reply,
    Skip,
    candidates,
)
from radicalbit_ai_gateway.invocation.model_invoker import ModelInvoker
from radicalbit_ai_gateway.invocation.recorder import Call
from radicalbit_ai_gateway.models.fallback import Fallback
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.models.request_identity import RequestIdentity
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

TRANSCRIPTION_MODEL_TYPE = 'transcription'
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
        """Build an openai SDK client: the transcription `usage` is needed for cost tracking."""
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

    def _chain(self, model_id: str, route_name: str, surface: Surface, **request):
        """Return the chain of ``model_id``: a 4xx is final, it would fail
        identically on any fallback.
        """
        model, client, fallbacks = self.model_map[model_id]
        call = Call(
            identity=RequestIdentity(route_name=route_name, **request),
            model_type=TRANSCRIPTION_MODEL_TYPE,
            target_model_id=model_id,
        )

        def record(candidate: Candidate, usage, latency_ms: float) -> None:
            self.recorder.invocation(
                call,
                candidate.model,
                latency_ms,
                fallback_triggered=candidate.is_fallback,
            )
            if isinstance(usage, _Usage):
                usage = usage.usage
            self.recorder.transcription_usage(call, candidate.model, usage)

        return FallbackChain(
            candidates((model, client), fallbacks),
            CallContext(
                call=call,
                recorder=self.recorder,
                record=record,
                final=lambda error: isinstance(error, ModelInvokerBadRequest),
                on_exhausted=raising(surface, route_name),
                **_failure_logs(model_id, surface),
            ),
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

        chain = self._chain(
            model_id,
            route_name,
            Surface.TRANSCRIPTION,
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            api_key_name=api_key_name,
            group_uuid=group_uuid,
            group_name=group_name,
            project_uuid=project_uuid,
            project_name=project_name,
        )

        async def transcribe(candidate: Candidate) -> Reply:
            _, name = parse_provider_and_model(candidate.model.model)
            whisper = name.startswith(WHISPER_FAMILY_PREFIX)
            create_kwargs = self._build_create_kwargs(
                name,
                audio_bytes,
                filename,
                content_type,
                'verbose_json' if whisper else 'json',
                language,
                prompt,
                temperature,
            )
            response = await self._create_upstream(candidate.client, create_kwargs)
            _set_transcription_response_attributes(response, whisper)
            _set_transcription_fallback_attributes(
                candidate.model.model_id, candidate.is_fallback
            )
            # The response stands for its usage: one without usage is recorded too.
            return Reply((response, whisper), usage=_Usage(response.usage))

        response, is_whisper = await chain.call(transcribe)
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

        chain = self._chain(
            model_id,
            route_name,
            Surface.TRANSCRIPTION_STREAM,
            request_uuid=request_uuid,
            api_key_uuid=api_key_uuid,
            api_key_name=api_key_name,
            group_uuid=group_uuid,
            group_name=group_name,
            project_uuid=project_uuid,
            project_name=project_name,
        )
        answered: list[tuple[Candidate, list[str]]] = []

        async def stream(attempt: Attempt) -> AsyncIterator[TranscriptionStreamEvent]:
            candidate = attempt.candidate
            _, name = parse_provider_and_model(candidate.model.model)
            if candidate.is_fallback and name.startswith(WHISPER_FAMILY_PREFIX):
                logger.warning(
                    'Skipping fallback transcription model %s for streaming: '
                    'whisper-1 does not support streaming.',
                    candidate.model.model_id,
                )
                raise Skip
            text_parts: list[str] = []
            upstream_stream = await self._create_upstream(
                candidate.client,
                self._build_create_kwargs(
                    name,
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
                    attempt.usage = event.usage
                yield event
            answered.append((candidate, text_parts))

        async for event in chain.stream(stream):
            yield event

        candidate, text_parts = answered[-1]
        try:
            span = trace.get_current_span()
            if span.is_recording():
                span.set_attribute(
                    'transcription.response.text_length', len(''.join(text_parts))
                )
        except Exception:
            pass
        _set_transcription_fallback_attributes(
            candidate.model.model_id, candidate.is_fallback
        )


@dataclass(frozen=True)
class _Usage:
    """A transcription's usage, which may be None."""

    usage: object


def _failure_logs(model_id: str, surface: Surface) -> dict:
    """Return the ``on_failure`` that logs a transcription model's failure."""
    if surface is Surface.TRANSCRIPTION_STREAM:
        primary = (
            'Primary transcription model %s stream failed: %s. Trying fallbacks...'
        )
        fallback = 'Fallback transcription model %s stream failed: %s'
    else:
        primary = 'Primary transcription model %s failed: %s. Trying fallbacks...'
        fallback = 'Fallback transcription model %s failed: %s'

    def log_failure(candidate: Candidate, error: BaseException) -> None:
        if candidate.is_fallback:
            logger.warning(fallback, candidate.model.model_id, str(error))
        else:
            logger.warning(primary, model_id, str(error))

    return {'on_failure': log_failure}
