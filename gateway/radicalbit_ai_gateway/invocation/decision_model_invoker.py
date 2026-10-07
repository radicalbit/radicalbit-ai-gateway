from dataclasses import dataclass
import json
import logging
import time

import httpx
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

DECISION_MODEL_TYPE = 'decision_model'
TYPESAFE_DEFAULT_BASE_URL = 'https://api.typesafe.ai'
SYSTEMONE_PATH = '/v1/systemone'


@dataclass(frozen=True)
class DecisionUpstream:
    url: str
    api_key: str | None
    model_name: str


@dataclass(frozen=True)
class DecisionResponse:
    """Typesafe's response, kept as raw bytes so the client gets it unchanged."""

    status_code: int
    content: bytes
    media_type: str | None


def _set_decision_request_attributes(forwarded_body: dict, model_id: str) -> None:
    try:
        span = trace.get_current_span()
        if span.is_recording():
            span.set_attribute(
                'decision.request.state', json.dumps(forwarded_body.get('state'))
            )
            span.set_attribute(
                'decision.request.questions',
                json.dumps(forwarded_body.get('questions')),
            )
            span.set_attribute('decision.request.model_id', model_id)
    except Exception:
        pass


def _set_decision_response_attributes(
    payload: dict, model_id_invoked: str, fallback_triggered: bool
) -> None:
    try:
        span = trace.get_current_span()
        if span.is_recording():
            span.set_attribute(
                'decision.response.answers', json.dumps(payload.get('answers'))
            )
            span.set_attribute(
                'decision.response.usage', json.dumps(payload.get('usage'))
            )
            span.set_attribute('decision.response.model_id', model_id_invoked)
            span.set_attribute(
                'decision.response.fallback_triggered', fallback_triggered
            )
    except Exception:
        pass


class DecisionModelInvoker(ModelInvoker):
    """Forwards Typesafe's own request to Typesafe with plain httpx (ADR 0004)."""

    def __init__(
        self,
        models: list[Model],
        cost_service: CostService,
        fallbacks: list[Fallback] | None = None,
        httpx_client: httpx.AsyncClient | None = None,
    ):
        super().__init__(
            models=models,
            cost_service=cost_service,
            fallbacks=fallbacks,
            httpx_client=httpx_client,
        )
        self._initialize_models(self._build_model)

    def _build_model(self, model: Model) -> DecisionUpstream:
        _, model_name = parse_provider_and_model(model.model)
        credentials = model.credentials
        base_url = (
            credentials.base_url if credentials else None
        ) or TYPESAFE_DEFAULT_BASE_URL
        return DecisionUpstream(
            url=base_url.rstrip('/') + SYSTEMONE_PATH,
            api_key=credentials.api_key if credentials else None,
            model_name=model_name,
        )

    @task(name='decide')
    async def decide(
        self,
        request_uuid: str,
        api_key_uuid: str,
        group_uuid: str,
        api_key_name: str,
        group_name: str,
        route_name: str,
        body: dict,
        model_id: str,
        project_uuid: str = '',
        project_name: str = '',
    ) -> DecisionResponse:
        if model_id not in self.model_map:
            raise ModelInvokerBadRequest(f'Decision model {model_id} not defined')
        model, upstream, _ = self.model_map[model_id]

        # The configured upstream model and credential replace the client's.
        forwarded_body = {**body, 'model': upstream.model_name}
        headers = (
            {'Authorization': f'Bearer {upstream.api_key}'} if upstream.api_key else {}
        )
        _set_decision_request_attributes(forwarded_body, model_id)

        start_time = time.monotonic()
        try:
            response = await self._post(upstream.url, forwarded_body, headers)
        except httpx.HTTPError as e:
            raise ModelInvokerInternalError(
                f'Decision upstream call failed: {e}'
            ) from e
        latency_ms = (time.monotonic() - start_time) * 1000

        if response.is_success:
            payload = self._parse_json(response, model_id)
            input_tokens = (payload.get('usage') or {}).get('input_tokens') or 0
            _set_decision_response_attributes(
                payload, model_id_invoked=model.model_id, fallback_triggered=False
            )
            # Typesafe bills input tokens only: output is recorded as 0.
            self._record_metrics(
                request_uuid=request_uuid,
                api_key_uuid=api_key_uuid,
                api_key_name=api_key_name,
                group_name=group_name,
                group_uuid=group_uuid,
                route_name=route_name,
                target_model_id=model.model_id,
                model=model,
                latency_ms=latency_ms,
                model_type=DECISION_MODEL_TYPE,
                token_input_count=input_tokens,
                token_output_count=0,
                project_uuid=project_uuid,
                project_name=project_name,
            )

        return DecisionResponse(
            status_code=response.status_code,
            content=response.content,
            media_type=response.headers.get('content-type'),
        )

    async def _post(self, url: str, body: dict, headers: dict) -> httpx.Response:
        if self.httpx_client is not None:
            return await self.httpx_client.post(url, json=body, headers=headers)
        # No shared client (tests, scripts): use a short-lived one.
        async with httpx.AsyncClient() as client:
            return await client.post(url, json=body, headers=headers)

    @staticmethod
    def _parse_json(response: httpx.Response, model_id: str) -> dict:
        try:
            payload = response.json()
        except ValueError:
            logger.warning('Decision model %s returned a non-JSON body', model_id)
            return {}
        return payload if isinstance(payload, dict) else {}
