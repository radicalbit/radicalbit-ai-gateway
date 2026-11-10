from fastapi import APIRouter, Depends, Request, Response

from radicalbit_ai_gateway.endpoints.common.admission import Admission
from radicalbit_ai_gateway.endpoints.common.http import endpoint
from radicalbit_ai_gateway.endpoints.decision import pipeline as decision_pipeline
from radicalbit_ai_gateway.endpoints.decision.request import DecisionRequest
from radicalbit_ai_gateway.gateway_route.route import GatewayRoute
from radicalbit_ai_gateway.routes.dependencies import (
    get_gateway_routes,
    get_request_uuid,
)
from radicalbit_ai_gateway.utils.trace_attributes import (
    OperationCategory,
    set_operation_category,
)


class DecisionRoute:
    @staticmethod
    def get_decision_router(admission: Admission) -> APIRouter:
        router = APIRouter(tags=['decision'])

        # This endpoint follows Typesafe's own contract, passed through
        # unchanged (ADR 0004): https://docs.typesafe.ai
        @router.post('/v1/systemone')
        @endpoint('decision_model')
        async def systemone(
            request: Request,
            decision_request: DecisionRequest,
            gateway_routes: dict[str, GatewayRoute] = Depends(get_gateway_routes),
            request_uuid: str = Depends(get_request_uuid),
        ) -> Response:
            scope = await admission.admit(
                request, gateway_routes, decision_request.model, request_uuid
            )
            set_operation_category(OperationCategory.ENDPOINT)
            result = await decision_pipeline.decide(
                scope, decision_request.model_dump()
            )

            return Response(
                content=result.content,
                status_code=result.status_code,
                media_type=result.media_type,
            )

        return router
