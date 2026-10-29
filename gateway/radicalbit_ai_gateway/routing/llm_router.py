import asyncio
from dataclasses import dataclass
import json
import logging
import time

from pydantic import BaseModel, ConfigDict, Field, create_model

from radicalbit_ai_gateway.llm.chat_model import ChatModel
from radicalbit_ai_gateway.llm.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.models.routing import LLMRoutingConfig
from radicalbit_ai_gateway.routing.common import routing_text, set_span_attributes
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.request_context import record_routing_spend

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)

ROUTER_MODEL_TYPE = 'chat-model'

# Why the default model serves the request.
REASON_BELOW_THRESHOLD = 'below_threshold'
REASON_ERROR = 'error'
REASON_INVALID_ANSWER = 'invalid_answer'
REASON_NO_TEXT = 'no_text'

_ATTRIBUTE_PREFIX = 'routing.llm.'


def _set_attributes(**attributes) -> None:
    """Set `routing.llm.*` attributes on the routing span."""
    set_span_attributes(_ATTRIBUTE_PREFIX, **attributes)


class _NoAnswer(Exception):
    """The router model gave no answer: try the fallback."""


class _BadAnswer(Exception):
    """The answer does not carry one score per option."""


@dataclass(frozen=True)
class _Option:
    key: str
    model_id: str
    description: str


@dataclass(frozen=True)
class RouterModel:
    """A chat model the router can ask, with the client that calls it."""

    model: Model
    chat_model: ChatModel


def _options(config: LLMRoutingConfig) -> list[_Option]:
    # Keys are stable and say nothing about the model: the router model reads
    # descriptions, not model names.
    return [
        _Option(f'option_{i}', entry.model_id, entry.description)
        for i, entry in enumerate(config.output_mapping, start=1)
    ]


def build_system_prompt(config: LLMRoutingConfig) -> str:
    """Describe the task and the options. The reply's shape is not described
    here: the structured output schema enforces it.
    """
    option_lines = '\n'.join(f'- {o.key}: {o.description}' for o in _options(config))
    return (
        'You are a query router. Given a user query, score how pertinent the query '
        'is to each option below.\n\n'
        f'Options:\n{option_lines}\n\n'
        'Options are independent: scores do not need to sum to 1. Use low scores '
        'across all options when the query does not fit any of them.'
    )


def build_response_schema(config: LLMRoutingConfig) -> type[BaseModel]:
    """One required float per option, keyed by the option key."""
    fields = {
        o.key: (
            float,
            Field(
                description=f'How pertinent the query is to {o.key}, from 0.0 to 1.0.'
            ),
        )
        for o in _options(config)
    }
    return create_model(
        'routing_distribution',
        __doc__='Pertinence score of the query for each option.',
        __config__=ConfigDict(extra='forbid'),
        **fields,
    )


class LLMRouter:
    """Route by asking a chat model to score the query against each option.

    Follows the "LLM Distribution" strategy of the semantic routing
    experiment: one pertinence score per option, argmax wins, and a best score
    below the threshold falls back to the default model.

    Fail open: any failure sends the request to the default model.
    """

    def __init__(
        self,
        config: LLMRoutingConfig,
        models_by_id: dict[str, Model],
        router_models: dict[str, RouterModel],
    ):
        self._config = config
        self._models_by_id = models_by_id
        self._router_models = router_models
        self._options = _options(config)
        self._system_prompt = build_system_prompt(config)
        schema = build_response_schema(config)
        # None when the model offers no structured output: it never answers.
        self._structured_models = {
            model_id: _structured_model(router_model, schema)
            for model_id, router_model in router_models.items()
        }

    async def select_model(self, messages: list[BaseMessage]) -> Model:
        state = routing_text(messages, self._config.history, self._config.message_roles)
        _set_attributes(
            options=json.dumps(
                {
                    o.key: {'model_id': o.model_id, 'description': o.description}
                    for o in self._options
                }
            ),
            threshold=self._config.threshold,
        )
        if not state:
            return self._default(REASON_NO_TEXT)
        # The text sent to the router model. Its own key, so EE privacy can drop it.
        _set_attributes(state=state)

        try:
            scores = await self._ask(state)
        except _NoAnswer:
            return self._default(REASON_ERROR)
        except _BadAnswer:
            return self._default(REASON_INVALID_ANSWER)

        _set_attributes(scores=json.dumps(scores))
        # max keeps the first of equal scores: the earlier option wins a tie.
        best = max(self._options, key=lambda o: scores[o.key])
        best_score = scores[best.key]
        _set_attributes(best_score=best_score)
        # Equal to the threshold passes.
        if best_score < self._config.threshold:
            return self._default(REASON_BELOW_THRESHOLD)
        _set_attributes(chosen_model_id=best.model_id, default_used=False)
        return self._models_by_id[best.model_id]

    async def _ask(self, state: str) -> dict[str, float]:
        """Ask the router model, then the fallback if the first gives no answer."""
        model_id = self._config.router_model_id
        _set_attributes(model_id=model_id, fallback_used=False)
        try:
            return await self._ask_model(model_id, state)
        except _NoAnswer:
            fallback_id = self._config.fallback_model_id
            if not fallback_id:
                raise
        logger.warning(
            'LLM routing falls back from model %s to model %s',
            model_id,
            fallback_id,
        )
        _set_attributes(model_id=fallback_id, fallback_used=True)
        return await self._ask_model(fallback_id, state)

    async def _ask_model(self, model_id: str, state: str) -> dict[str, float]:
        structured_model = self._structured_models[model_id]
        if structured_model is None:
            raise _NoAnswer
        start = time.monotonic()
        try:
            response = await asyncio.wait_for(
                structured_model.ainvoke(
                    [
                        SystemMessage(content=self._system_prompt),
                        HumanMessage(content=state),
                    ]
                ),
                timeout=self._config.timeout,
            )
        except Exception as e:
            logger.warning('LLM routing model %s failed', model_id, exc_info=True)
            raise _NoAnswer from e
        latency_ms = (time.monotonic() - start) * 1000
        # Count before reading the scores. A bad answer still spent tokens.
        await self._record_spend(model_id, response.get('raw'), latency_ms)

        parsed = response.get('parsed')
        if not isinstance(parsed, BaseModel):
            logger.warning('LLM routing model %s: no parseable scores', model_id)
            raise _BadAnswer
        return parsed.model_dump()

    async def _record_spend(
        self, model_id: str, raw_response: object, latency_ms: float
    ) -> None:
        """Charge the router call, input and output tokens, to the request."""
        if not isinstance(raw_response, AIMessage) or not raw_response.usage_metadata:
            logger.warning('LLM routing model %s: no token usage', model_id)
            return
        await record_routing_spend(
            self._router_models[model_id].model,
            raw_response.usage_metadata.get('input_tokens', 0),
            latency_ms,
            model_type=ROUTER_MODEL_TYPE,
            target_model_id=self._config.router_model_id,
            output_tokens=raw_response.usage_metadata.get('output_tokens', 0),
        )

    def _default(self, reason: str) -> Model:
        logger.info('LLM routing uses the default model: %s', reason)
        _set_attributes(
            chosen_model_id=self._config.default_model_id,
            default_used=True,
            default_reason=reason,
        )
        return self._models_by_id[self._config.default_model_id]


def _structured_model(router_model: RouterModel, schema: type[BaseModel]):
    try:
        return router_model.chat_model.with_structured_output(
            schema=schema, include_raw=True
        )
    except NotImplementedError:
        logger.warning(
            'Router model %s does not support structured output, '
            'LLM routing cannot ask it',
            router_model.model.model_id,
        )
        return None
