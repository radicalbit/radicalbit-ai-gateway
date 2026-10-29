from dataclasses import dataclass
import json
import logging
import time

from radicalbit_ai_gateway.invocation.decision_model_invoker import (
    DECISION_MODEL_TYPE,
    DecisionModelInvoker,
    billed_input_tokens,
    is_number,
)
from radicalbit_ai_gateway.llm.messages import BaseMessage
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.models.routing import DecisionRoutingConfig
from radicalbit_ai_gateway.routing.common import routing_text, set_span_attributes
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import ModelInvokerBadRequest
from radicalbit_ai_gateway.utils.request_context import record_routing_spend

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)

# Decision routing asks one question: its id only has to match the answer.
QUESTION_ID = 'decision_routing'

# Why the default model serves the request.
REASON_ERROR = 'error'
REASON_LOW_CONFIDENCE = 'low_confidence'
REASON_NO_TEXT = 'no_text'
REASON_UNKNOWN_OPTION = 'unknown_option'

_ATTRIBUTE_PREFIX = 'routing.decision.'


def _set_attributes(**attributes) -> None:
    """Set `routing.decision.*` attributes on the routing span."""
    set_span_attributes(_ATTRIBUTE_PREFIX, **attributes)


class _NoAnswer(Exception):
    """The decision model gave no usable answer: try the fallback."""


class _BadAnswer(Exception):
    """The answer is not one of the offered options, or is malformed."""


@dataclass(frozen=True)
class _Option:
    key: str
    model_id: str
    description: str


@dataclass(frozen=True)
class _Answer:
    """Jev's Choice answer: the chosen key, its confidence, every option's probability."""

    key: str
    confidence: float | None
    probabilities: dict | None


class DecisionRouter:
    """Asks a decision model one Choice question to pick the chat model.

    Fail open: any failure sends the request to the default model.
    """

    def __init__(
        self,
        config: DecisionRoutingConfig,
        models_by_id: dict[str, Model],
        invoker: DecisionModelInvoker,
    ):
        self._config = config
        self._models_by_id = models_by_id
        self._invoker = invoker
        # Keys are stable and say nothing about the model: Jev reads descriptions.
        self._options = [
            _Option(f'option_{i}', entry.model_id, entry.description)
            for i, entry in enumerate(config.output_mapping, start=1)
        ]

    async def select_model(self, messages: list[BaseMessage]) -> Model:
        state = self._state(messages)
        _set_attributes(
            instructions=self._config.instructions,
            options=json.dumps(
                {
                    o.key: {'model_id': o.model_id, 'description': o.description}
                    for o in self._options
                }
            ),
        )
        if not state:
            return self._default(REASON_NO_TEXT)
        # The text sent to Typesafe. Its own key, so EE privacy can drop it.
        _set_attributes(state=state)

        body = {
            'state': state,
            'questions': {
                QUESTION_ID: {
                    'type': 'choice',
                    'instructions': self._config.instructions,
                    'criteria': {o.key: o.description for o in self._options},
                }
            },
        }
        try:
            answer = await self._ask(body)
        except _NoAnswer:
            return self._default(REASON_ERROR)
        except _BadAnswer:
            return self._default(REASON_UNKNOWN_OPTION)

        if answer.confidence is not None:
            _set_attributes(confidence=answer.confidence)
        if answer.probabilities is not None:
            _set_attributes(probabilities=json.dumps(answer.probabilities))
        chosen = next(o for o in self._options if o.key == answer.key)
        min_confidence = self._config.min_confidence
        # Equal to min_confidence passes.
        if min_confidence is not None and answer.confidence < min_confidence:
            return self._default(REASON_LOW_CONFIDENCE)
        _set_attributes(chosen_model_id=chosen.model_id, default_used=False)
        return self._models_by_id[chosen.model_id]

    async def _ask(self, body: dict) -> _Answer:
        """Ask the decision model, then the fallback if the first gives no answer."""
        model_id = self._config.decision_model_id
        _set_attributes(model_id=model_id, fallback_used=False)
        try:
            return await self._ask_model(model_id, body)
        except _NoAnswer:
            fallback_id = self._config.fallback_model_id
            if not fallback_id:
                raise
        logger.warning(
            'Decision routing falls back from model %s to model %s',
            model_id,
            fallback_id,
        )
        _set_attributes(model_id=fallback_id, fallback_used=True)
        return await self._ask_model(fallback_id, body)

    async def _ask_model(self, model_id: str, body: dict) -> _Answer:
        start = time.monotonic()
        try:
            response = await self._invoker.call(model_id, body)
        except ModelInvokerBadRequest as e:
            logger.warning('Decision routing model %s: %s', model_id, e)
            raise _NoAnswer from e
        latency_ms = (time.monotonic() - start) * 1000
        if response is None:
            logger.warning('Decision routing model %s: no answer', model_id)
            raise _NoAnswer
        # Routing never fails a request: a 4xx also goes on to the fallback.
        if not response.is_success:
            logger.warning(
                'Decision routing model %s: Typesafe returned %s',
                model_id,
                response.status_code,
            )
            raise _NoAnswer
        try:
            payload = response.json()
        except ValueError:
            payload = None
        # Count before reading the choice. A bad answer still spent tokens.
        await self._record_spend(model_id, payload, latency_ms)
        return self._read_choice(payload)

    async def _record_spend(
        self, model_id: str, payload: object, latency_ms: float
    ) -> None:
        """Charge the call to the request. No usage, nothing to count."""
        input_tokens = billed_input_tokens(payload)
        if input_tokens == 0:
            return
        await record_routing_spend(
            self._invoker.model_map[model_id][0],
            input_tokens,
            latency_ms,
            model_type=DECISION_MODEL_TYPE,
            target_model_id=self._config.decision_model_id,
        )

    def _read_choice(self, payload: object) -> _Answer:
        """Read Jev's answer: `choice` is the chosen key, `confidence` how sure it is."""
        try:
            answer = payload['answers'][QUESTION_ID]
            key = answer['choice']
        except (KeyError, TypeError):
            raise _BadAnswer from None
        if not isinstance(key, str) or key not in {o.key for o in self._options}:
            raise _BadAnswer
        confidence = answer.get('confidence')
        if confidence is not None and not is_number(confidence):
            raise _BadAnswer
        # min_confidence has nothing to compare against without a confidence.
        if confidence is None and self._config.min_confidence is not None:
            raise _BadAnswer
        probabilities = answer.get('probabilities')
        return _Answer(
            key=key,
            confidence=float(confidence) if confidence is not None else None,
            probabilities=probabilities if isinstance(probabilities, dict) else None,
        )

    def _state(self, messages: list[BaseMessage]) -> str:
        return routing_text(messages, self._config.history, self._config.message_roles)

    def _default(self, reason: str) -> Model:
        logger.info('Decision routing uses the default model: %s', reason)
        _set_attributes(
            chosen_model_id=self._config.default_model_id,
            default_used=True,
            default_reason=reason,
        )
        return self._models_by_id[self._config.default_model_id]
