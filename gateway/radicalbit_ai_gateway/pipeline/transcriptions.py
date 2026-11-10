"""Audio transcriptions: the order a request goes through the route's
policies.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
import logging

from openai.types.audio.transcription import Transcription
from openai.types.audio.transcription_stream_event import TranscriptionStreamEvent
from openai.types.audio.transcription_verbose import TranscriptionVerbose
from traceloop.sdk.decorators import task

from radicalbit_ai_gateway.caching.route_cache import TranscriptionEntry
from radicalbit_ai_gateway.limiting.limits import Demand, Usage
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.pipeline.audio_duration import (
    estimate_audio_duration_seconds,
)
from radicalbit_ai_gateway.pipeline.conversation import check_limits
from radicalbit_ai_gateway.pipeline.scope import RequestScope
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import GatewayBadRequest
from radicalbit_ai_gateway.utils.trace_attributes import (
    OperationCategory,
    set_operation_category,
)

logger = logging.getLogger(get_app_config().log_config.logger_name)


@dataclass(frozen=True)
class Audio:
    """The audio of a transcription request, and how to transcribe it."""

    content: bytes
    filename: str
    content_type: str | None
    language: str | None = None
    prompt: str | None = None
    temperature: float | None = None
    response_format: str = 'json'

    def arguments(self) -> dict:
        return {
            'audio_bytes': self.content,
            'filename': self.filename,
            'content_type': self.content_type,
            'language': self.language,
            'prompt': self.prompt,
            'temperature': self.temperature,
        }


async def transcribe(
    scope: RequestScope, audio: Audio
) -> Transcription | TranscriptionVerbose:
    """Transcribe the audio of a request."""
    route = scope.route
    model = _select(scope)

    # Limits before the cache, as on chat: a caller over its limit is not
    # served. A hit spends no audio: its seconds count only on a miss.
    demand = _demand(audio.content)
    if scope.limits.applies(demand):
        await scope.limits.check(demand, count=False)

    scope.cached = await scope.cache.lookup(
        TranscriptionEntry(
            audio.content,
            model.model_id,
            audio.response_format,
            audio.language,
            audio.prompt,
            audio.temperature,
        )
    )
    if scope.cached.hit:
        return scope.cached.value

    await scope.limits.count_checked(demand)
    set_operation_category(OperationCategory.INVOCATION)
    result = await route.transcription_invoker.transcribe(
        identity=scope.identity,
        model_id=model.model_id,
        requested_response_format=audio.response_format,
        **audio.arguments(),
    )
    await scope.limits.count(Usage.transcription(model, result.usage))
    await scope.cached.store(result)
    return result


async def stream(
    scope: RequestScope, audio: Audio
) -> AsyncIterator[TranscriptionStreamEvent]:
    """Transcribe the audio of a request as a stream of events. The limits
    are checked before the stream opens: a refusal is an HTTP error, as for
    a transcription that is not streamed.
    """
    model = _select(scope)
    await check_limits(scope.limits, _demand(audio.content))
    return _relay(scope, audio, model)


async def _relay(
    scope: RequestScope, audio: Audio, model: Model
) -> AsyncIterator[TranscriptionStreamEvent]:
    """Relay the model's events, then count the final usage."""
    set_operation_category(OperationCategory.INVOCATION)
    final_event: TranscriptionStreamEvent | None = None
    async for event in scope.route.transcription_invoker.stream(
        identity=scope.identity, model_id=model.model_id, **audio.arguments()
    ):
        final_event = event
        yield event

    if final_event is not None:
        await scope.limits.count(
            Usage.transcription(model, getattr(final_event, 'usage', None))
        )


def _select(scope: RequestScope) -> Model:
    route = scope.route
    if not route.transcription_invoker:
        raise GatewayBadRequest(
            f'Route {route.gateway_route_config.route_name} '
            'has no transcription models defined'
        )
    set_operation_category(OperationCategory.ROUTING)
    return _select_model(scope)


@task(name='select_transcription_model')
def _select_model(scope: RequestScope) -> Model:
    """Return the route's first transcription model: it serves its traffic."""
    models = scope.route.transcription_models
    if not models:
        raise ValueError('Configuration for transcription model not found.')
    logger.debug('Selected transcription model: %s', models[0].model_id)
    return models[0]


def _demand(audio_bytes: bytes) -> Demand:
    """Return what a transcription demands: its cost and its audio seconds,
    read from the file's header ('unknown' when they can't be).
    """
    seconds = estimate_audio_duration_seconds(audio_bytes)
    return Demand(
        cost_room=True, audio_seconds='unknown' if seconds is None else seconds
    )
