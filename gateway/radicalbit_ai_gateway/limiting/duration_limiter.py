import io
import logging
import wave

from traceloop.sdk.decorators import task

from radicalbit_ai_gateway.events.events_processor import emit_event
from radicalbit_ai_gateway.limiter import (
    AlignedFixedWindowLimiter,
    FixedWindowLimiter,
    InMemoryStorage,
    RedisStorage,
    ScenarioType,
    WindowConfig,
)
from radicalbit_ai_gateway.metrics.define_metrics import audio_duration_limiting_counter
from radicalbit_ai_gateway.models.event_payload import LimitEventPayload
from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.models.limiting import Limiting, LimitingAlgorithmType
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import AudioDurationLimitExceeded

app_config = get_app_config()
logging_config_dict = app_config.log_config.model_dump()
logger = logging.getLogger(app_config.log_config.logger_name)


def estimate_audio_duration_seconds(audio_bytes: bytes) -> float | None:
    """Header-only duration estimate, no upstream call and no full decode.

    WAV only (stdlib `wave` module — no external dependency). Returns None
    for any other format, or a malformed WAV — callers must treat that as
    "unknown", not as zero.
    """
    try:
        with wave.open(io.BytesIO(audio_bytes), 'rb') as wav_file:
            frames = wav_file.getnframes()
            rate = wav_file.getframerate()
    except Exception:
        return None
    if not rate:
        return None
    return frames / rate


class DurationLimiter:
    """Duration-based limiting for transcription requests (audio-seconds per
    window) — the closest pre-call proxy to token limiting available for
    transcription, since audio/output tokens can't be estimated locally the
    way text can.
    """

    def __init__(
        self,
        project_uuid: str,
        route_name: str,
        config: Limiting | None = None,
    ):
        self.route_name = route_name
        self.config = config
        # Key isolation only: route_name stays the bare route everywhere it is
        # reported (metrics, limit events, logs).
        self.project_uuid = project_uuid

        if app_config.redis_config.redis_url:
            self.storage = RedisStorage(uri=app_config.redis_config.redis_url)
        else:
            self.storage = InMemoryStorage()

        self.limiter = self._create_limiter(config) if config else None
        self.item = (
            self._create_item(
                config, project_uuid, route_name, ScenarioType.AUDIO_DURATION
            )
            if config
            else None
        )

    def _create_limiter(
        self, config: Limiting
    ) -> FixedWindowLimiter | AlignedFixedWindowLimiter:
        if config.algorithm == LimitingAlgorithmType.ALIGNED_FIXED_WINDOW:
            return AlignedFixedWindowLimiter(self.storage)
        return FixedWindowLimiter(self.storage)

    @staticmethod
    def _create_item(
        config: Limiting,
        project_uuid: str,
        route_name: str,
        scenario_type: ScenarioType,
    ) -> WindowConfig:
        if not config.max_duration_seconds:
            raise ValueError('max_duration_seconds must be set for duration limiting')
        return WindowConfig.from_parts(
            limit=round(config.max_duration_seconds),
            window=config.window_size,
            project_uuid=project_uuid,
            route_name=route_name,
            scenario_type=scenario_type,
        )

    @task(name='check_audio_duration_limit')
    async def check_and_count_duration(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        audio_bytes: bytes,
        project_uuid: str = '',
        project_name: str = '',
    ) -> None:
        """Check if the audio duration limit is exceeded and count it if
        allowed. Raises AudioDurationLimitExceeded if the limit is exceeded.

        If the audio duration can't be determined locally (unrecognized
        format, malformed file), the request is allowed through uncounted —
        rate limiting and budget limiting still apply as a safety net.
        """
        if not self.limiter or not self.item or not self.config:
            logger.debug(
                '[DURATION LIMIT] [route=%s] [kind=AUDIO_DURATION] '
                '[configured=false] [action=SKIP]',
                self.route_name,
            )
            return

        duration_seconds = estimate_audio_duration_seconds(audio_bytes)
        if duration_seconds is None:
            logger.warning(
                '[DURATION LIMIT] [route=%s] [kind=AUDIO_DURATION] '
                '[action=SKIP] [reason=duration_not_determinable]',
                self.route_name,
            )
            return

        cost = round(duration_seconds)
        allowed = await self.limiter.test(self.item, cost=cost)

        if not allowed:
            state = await self.limiter.get_window_stats(self.item)

            log_message = (
                '[DURATION LIMIT] '
                f'[route={self.route_name}] '
                '[kind=AUDIO_DURATION] '
                f'[attempted={cost}] '
                f'[limit={self.config.max_duration_seconds}] '
                f'[window={self.config.window_size}] '
                f'[remaining={state.remaining}] '
                f'[reset_s={state.remaining_time}] '
                '[action=BLOCK]'
            )
            emit_event(
                LimitEventPayload(
                    request_uuid=request_uuid,
                    api_key_uuid=api_key_uuid,
                    group_uuid=group_uuid,
                    api_key_name=api_key_name,
                    group_name=group_name,
                    project_uuid=project_uuid,
                    project_name=project_name,
                    event_type=EventType.AUDIO_DURATION_LIMIT,
                    route_name=self.route_name,
                    value=1.0,
                )
            )
            audio_duration_limiting_counter.add(1, {'route_name': self.route_name})

            user_message = (
                f'Audio duration limit exceeded: {self.config.max_duration_seconds} '
                f'seconds per {self.config.window_size}.'
                f' Please retry after {state.remaining_time} seconds.'
            )

            raise AudioDurationLimitExceeded(
                message=user_message,
                log_message=log_message,
                route_name=self.route_name,
            )

        logger.debug(
            '[DURATION LIMIT] [route=%s] [kind=AUDIO_DURATION] '
            '[attempted=%s] [limit=%s] [window=%s] [action=ALLOW]',
            self.route_name,
            cost,
            self.config.max_duration_seconds,
            self.config.window_size,
        )

        await self.limiter.hit(self.item, cost=cost)
