import asyncio
import contextlib
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
    ModelInvokerBadGateway,
    ModelInvokerBadRequest,
)
from radicalbit_ai_gateway.utils.parse_provider_and_model import (
    parse_provider_and_model,
)

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)

DECISION_MODEL_TYPE = 'decision_model'
TYPESAFE_DEFAULT_BASE_URL = 'https://api.typesafe.ai'
SYSTEMONE_PATH = '/v1/systemone'
BACKOFF_BASE_SECONDS = 0.2
BACKOFF_CAP_SECONDS = 2.0


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


def _set_decision_request_attributes(body: dict, model_id: str) -> None:
    try:
        span = trace.get_current_span()
        if span.is_recording():
            span.set_attribute('decision.request.state', json.dumps(body.get('state')))
            span.set_attribute(
                'decision.request.questions',
                json.dumps(body.get('questions')),
            )
            span.set_attribute('decision.request.model_id', model_id)
    except Exception:
        pass


def _set_decision_fallback_attributes(
    model_id_invoked: str, fallback_triggered: bool
) -> None:
    try:
        span = trace.get_current_span()
        if span.is_recording():
            span.set_attribute('decision.response.model_id', model_id_invoked)
            span.set_attribute(
                'decision.response.fallback_triggered', fallback_triggered
            )
    except Exception:
        pass


def _set_decision_response_attributes(payload: dict) -> None:
    try:
        span = trace.get_current_span()
        if span.is_recording():
            span.set_attribute(
                'decision.response.answers', json.dumps(payload.get('answers'))
            )
            span.set_attribute(
                'decision.response.usage', json.dumps(payload.get('usage'))
            )
    except Exception:
        pass


def _is_transient(response: httpx.Response) -> bool:
    """429 and 5xx may pass on retry. Other 4xx are the client's mistake."""
    return response.status_code == 429 or response.status_code >= 500


def _backoff_seconds(attempt: int, last_response: httpx.Response | None) -> float:
    """Exponential backoff, capped. A small Retry-After on a 429 wins."""
    delay = BACKOFF_BASE_SECONDS * 2 ** (attempt - 1)
    if last_response is not None and last_response.status_code == 429:
        with contextlib.suppress(ValueError):
            delay = float(last_response.headers.get('retry-after', ''))
    return max(0.0, min(delay, BACKOFF_CAP_SECONDS))


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
        model, upstream, fallbacks = self.model_map[model_id]
        _set_decision_request_attributes(body, model_id)

        start_time = time.monotonic()
        # The target first, then its fallbacks, each with its own retries.
        response: httpx.Response | None = None
        model_invoked = model
        fallback_triggered = False
        previous = model
        for candidate, candidate_upstream in [(model, upstream), *fallbacks]:
            if candidate is not model:
                logger.warning(
                    'Decision model %s failed. Falling back to %s',
                    previous.model_id,
                    candidate.model_id,
                )
                fallback_triggered = True
            previous = candidate
            candidate_response = await self._call_with_retries(
                candidate, candidate_upstream, body
            )
            if candidate_response is None:
                continue
            # Keep the last real response: it is returned if the chain runs out.
            response, model_invoked = candidate_response, candidate
            if not _is_transient(candidate_response):
                break
        _set_decision_fallback_attributes(model_invoked.model_id, fallback_triggered)
        if response is None:
            raise ModelInvokerBadGateway(
                f'No decision model answered for route {route_name}'
            )
        latency_ms = (time.monotonic() - start_time) * 1000

        if response.is_success:
            payload = self._parse_json(response, model_id)
            input_tokens = (payload.get('usage') or {}).get('input_tokens') or 0
            _set_decision_response_attributes(payload)
            # Typesafe bills input tokens only: output is recorded as 0.
            self._record_metrics(
                request_uuid=request_uuid,
                api_key_uuid=api_key_uuid,
                api_key_name=api_key_name,
                group_name=group_name,
                group_uuid=group_uuid,
                route_name=route_name,
                target_model_id=model.model_id,
                model=model_invoked,
                latency_ms=latency_ms,
                model_type=DECISION_MODEL_TYPE,
                token_input_count=input_tokens,
                token_output_count=0,
                fallback_triggered=fallback_triggered,
                project_uuid=project_uuid,
                project_name=project_name,
            )

        return DecisionResponse(
            status_code=response.status_code,
            content=response.content,
            media_type=response.headers.get('content-type'),
        )

    async def _call_with_retries(
        self, model: Model, upstream: DecisionUpstream, body: dict
    ) -> httpx.Response | None:
        """Call one decision model, retrying transient failures.

        Return the first non-transient response. When every attempt fails,
        return the last response received, or None if no attempt got one.
        """
        # The configured upstream model and credential replace the client's.
        forwarded_body = {**body, 'model': upstream.model_name}
        headers = (
            {'Authorization': f'Bearer {upstream.api_key}'} if upstream.api_key else {}
        )
        last_response: httpx.Response | None = None
        for attempt in range((model.retry_attempts or 0) + 1):
            if attempt:
                await asyncio.sleep(_backoff_seconds(attempt, last_response))
            try:
                response = await self._post(upstream.url, forwarded_body, headers)
            except httpx.HTTPError as e:
                logger.warning('Decision model %s call failed: %r', model.model_id, e)
                continue
            if not _is_transient(response):
                return response
            logger.warning(
                'Decision model %s returned %s', model.model_id, response.status_code
            )
            last_response = response
        return last_response

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
