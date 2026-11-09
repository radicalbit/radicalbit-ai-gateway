from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from radicalbit_ai_gateway.ai_gateway import GatewayRoute
from radicalbit_ai_gateway.pipeline import transcription as transcription_pipeline
from radicalbit_ai_gateway.pipeline.admission import Admission
from radicalbit_ai_gateway.pipeline.http import endpoint, sse_response
from radicalbit_ai_gateway.pipeline.transcription import Audio
from radicalbit_ai_gateway.utils.dependencies import (
    get_gateway_routes,
    get_request_uuid,
)
from radicalbit_ai_gateway.utils.open_ai_types import TranscriptionCreateParamsCustom
from radicalbit_ai_gateway.utils.trace_attributes import (
    OperationCategory,
    set_operation_category,
)


class TranscriptionsRoute:
    @staticmethod
    def get_transcriptions_router(admission: Admission) -> APIRouter:
        router = APIRouter()

        @router.post('/v1/audio/transcriptions')
        @endpoint('audio_transcriptions')
        async def audio_transcriptions(
            request: Request,
            transcription_params: Annotated[TranscriptionCreateParamsCustom, Form()],
            gateway_routes: dict[str, GatewayRoute] = Depends(get_gateway_routes),
            request_uuid: str = Depends(get_request_uuid),
        ):
            scope = await admission.admit(
                request,
                gateway_routes,
                transcription_params.model,
                request_uuid,
                streaming=transcription_params.stream,
            )
            file = transcription_params.file
            audio = Audio(
                content=await file.read(),
                filename=file.filename or 'audio',
                content_type=file.content_type,
                language=transcription_params.language,
                prompt=transcription_params.prompt,
                temperature=transcription_params.temperature,
                response_format=transcription_params.response_format,
            )
            set_operation_category(OperationCategory.ENDPOINT)
            if transcription_params.stream:
                return sse_response(
                    await transcription_pipeline.stream(scope, audio),
                    item_log='Streaming transcription event: %s',
                    error_log='Unhandled error during transcription streaming',
                )
            result = await transcription_pipeline.transcribe(scope, audio)
            return JSONResponse(content=jsonable_encoder(result))

        return router
