from dataclasses import dataclass
import json
import logging
import time

import httpx
from opentelemetry import trace

from radicalbit_ai_gateway.guardrails.judges.judge_engine import JudgeUsageCounter
from radicalbit_ai_gateway.invocation.decision_model_invoker import (
    DecisionModelInvoker,
    billed_input_tokens,
    is_number,
)
from radicalbit_ai_gateway.llm.messages import BaseMessage
from radicalbit_ai_gateway.models.guardrails import DecisionJudgeParameter
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import (
    JudgeInternalError,
    ModelInvokerBadRequest,
)
from radicalbit_ai_gateway.utils.judge import extract_content_for_judge

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)

# A decision judge asks one question: its id only has to match the answer.
QUESTION_ID = 'decision_judge'

# The guardrail kwargs that name the request on its cost events.
_IDENTITY_KEYS = (
    'request_uuid',
    'api_key_uuid',
    'api_key_name',
    'group_uuid',
    'group_name',
    'route_name',
    'project_uuid',
    'project_name',
)


def _set_judge_request_attributes(params: DecisionJudgeParameter, state: str) -> None:
    try:
        span = trace.get_current_span()
        if span.is_recording():
            span.set_attribute('guardrail.decision_judge.model_id', params.model_id)
            span.set_attribute(
                'guardrail.decision_judge.instructions', params.instructions
            )
            if params.criteria:
                span.set_attribute(
                    'guardrail.decision_judge.criteria',
                    json.dumps(params.criteria.model_dump()),
                )
            span.set_attribute('guardrail.decision_judge.threshold', params.threshold)
            # The text sent to Typesafe. Its own key, so EE privacy can drop it.
            span.set_attribute('guardrail.decision_judge.state', state)
    except Exception:
        pass


def _set_judge_answer_attributes(
    answered_model_id: str, fallback_triggered: bool, noul: float
) -> None:
    try:
        span = trace.get_current_span()
        if span.is_recording():
            span.set_attribute(
                'guardrail.decision_judge.answered_model_id', answered_model_id
            )
            span.set_attribute(
                'guardrail.decision_judge.fallback_triggered', fallback_triggered
            )
            span.set_attribute('guardrail.decision_judge.noul', noul)
    except Exception:
        pass


@dataclass(frozen=True)
class _JudgeSpend:
    """Who a judge call bills, and the limits it consumes."""

    target_model_id: str
    identity: dict[str, str]
    count_usage: JudgeUsageCounter | None


class _RejectedByModel(JudgeInternalError):
    """The model rejected the request (a 4xx other than 429).

    The same request would be rejected by the fallback too: do not fall back.
    """


class DecisionJudgeEngine:
    """Asks a decision model one Noul question about the text.

    Any decision model of the project can answer, not only those on the route.
    """

    def __init__(
        self,
        decision_models: list[Model] | None,
        cost_service: CostService,
        httpx_client: httpx.AsyncClient | None = None,
    ):
        self._invoker = (
            DecisionModelInvoker(
                models=decision_models,
                cost_service=cost_service,
                httpx_client=httpx_client,
            )
            if decision_models
            else None
        )

    async def ask(
        self,
        messages: list[BaseMessage],
        params: DecisionJudgeParameter,
        count_judge_usage: JudgeUsageCounter | None = None,
        **kwargs,
    ) -> float:
        """Return the probability that the answer is yes, between 0 and 1.

        When the model is still failing after retries, or gives no valid noul,
        the fallback model (if any) answers instead. A 4xx other than 429 does
        not fall back. Fail closed: any failure left raises JudgeInternalError.

        Every answer with usage is judge spend: it emits cost events and
        consumes the request's limits through `count_judge_usage`.
        """
        question: dict = {'type': 'noul', 'instructions': params.instructions}
        if params.criteria:
            question['criteria'] = params.criteria.model_dump()
        body = {
            'state': extract_content_for_judge(messages, **kwargs),
            'questions': {QUESTION_ID: question},
        }

        _set_judge_request_attributes(params, body['state'])

        if self._invoker is None:
            raise self._error(params.model_id, 'no decision models are configured')
        spend = _JudgeSpend(
            target_model_id=params.model_id,
            identity={k: kwargs.get(k, '') for k in _IDENTITY_KEYS},
            count_usage=count_judge_usage,
        )
        try:
            noul = await self._ask_model(params.model_id, body, spend)
        except _RejectedByModel:
            raise
        except JudgeInternalError:
            if not params.fallback_model_id:
                raise
        else:
            _set_judge_answer_attributes(
                params.model_id, fallback_triggered=False, noul=noul
            )
            return noul
        logger.warning(
            'Decision judge falls back from model %s to model %s',
            params.model_id,
            params.fallback_model_id,
        )
        noul = await self._ask_model(params.fallback_model_id, body, spend)
        _set_judge_answer_attributes(
            params.fallback_model_id, fallback_triggered=True, noul=noul
        )
        return noul

    async def _ask_model(self, model_id: str, body: dict, spend: _JudgeSpend) -> float:
        start_time = time.monotonic()
        try:
            response = await self._invoker.call(model_id, body)
        except ModelInvokerBadRequest as e:
            raise self._error(model_id, str(e)) from e
        latency_ms = (time.monotonic() - start_time) * 1000
        if response is None:
            raise self._error(model_id, 'no answer after retries')
        if not response.is_success:
            # A 429 here means retries ran out: the fallback may still answer.
            rejected = response.is_client_error and response.status_code != 429
            raise self._error(
                model_id,
                f'Typesafe returned {response.status_code}',
                _RejectedByModel if rejected else JudgeInternalError,
            )

        try:
            payload = response.json()
        except ValueError:
            payload = None
        # Count before reading the noul. A bad answer still spent tokens.
        await self._count_spend(model_id, payload, latency_ms, spend)
        return self._read_noul(payload, model_id)

    async def _count_spend(
        self,
        model_id: str,
        payload: object,
        latency_ms: float,
        spend: _JudgeSpend,
    ) -> None:
        """Emit the call's cost events and consume the request's limits.

        Typesafe bills input tokens only. No usage, nothing to count.
        """
        input_tokens = billed_input_tokens(payload)
        if input_tokens == 0:
            return
        model = self._invoker.record_judge_call(
            model_id=model_id,
            target_model_id=spend.target_model_id,
            input_tokens=input_tokens,
            latency_ms=latency_ms,
            identity=spend.identity,
        )
        if spend.count_usage:
            await spend.count_usage(model, input_tokens, 0)

    def _read_noul(self, payload: object, model_id: str) -> float:
        try:
            noul = payload['answers'][QUESTION_ID]['noul']
        except (KeyError, TypeError):
            raise self._error(model_id, 'the answer has no noul') from None
        if not is_number(noul):
            raise self._error(model_id, f'noul is not a number: {noul!r}')
        return float(noul)

    @staticmethod
    def _error(
        model_id: str,
        reason: str,
        error_class: type[JudgeInternalError] = JudgeInternalError,
    ) -> JudgeInternalError:
        logger.error('Decision judge on model %s failed: %s', model_id, reason)
        return error_class(
            'Decision judge failed',
            log_message=f'Decision judge on model {model_id} failed: {reason}',
            model_id=model_id,
        )
