import logging

import httpx

from radicalbit_ai_gateway.invocation.decision_model_invoker import DecisionModelInvoker
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
        **kwargs,
    ) -> float:
        """Return the probability that the answer is yes, between 0 and 1.

        When the model is still failing after retries, or gives no valid noul,
        the fallback model (if any) answers instead. A 4xx other than 429 does
        not fall back. Fail closed: any failure left raises JudgeInternalError.
        """
        question: dict = {'type': 'noul', 'instructions': params.instructions}
        if params.criteria:
            question['criteria'] = params.criteria.model_dump()
        body = {
            'state': extract_content_for_judge(messages, **kwargs),
            'questions': {QUESTION_ID: question},
        }

        if self._invoker is None:
            raise self._error(params.model_id, 'no decision models are configured')
        try:
            return await self._ask_model(params.model_id, body)
        except _RejectedByModel:
            raise
        except JudgeInternalError:
            if not params.fallback_model_id:
                raise
        logger.warning(
            'Decision judge falls back from model %s to model %s',
            params.model_id,
            params.fallback_model_id,
        )
        return await self._ask_model(params.fallback_model_id, body)

    async def _ask_model(self, model_id: str, body: dict) -> float:
        try:
            response = await self._invoker.call(model_id, body)
        except ModelInvokerBadRequest as e:
            raise self._error(model_id, str(e)) from e
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

        return self._read_noul(response, model_id)

    def _read_noul(self, response: httpx.Response, model_id: str) -> float:
        try:
            noul = response.json()['answers'][QUESTION_ID]['noul']
        except (ValueError, KeyError, TypeError):
            raise self._error(model_id, 'the answer has no noul') from None
        # bool is an int: reject it, as any non-number.
        if isinstance(noul, bool) or not isinstance(noul, int | float):
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
