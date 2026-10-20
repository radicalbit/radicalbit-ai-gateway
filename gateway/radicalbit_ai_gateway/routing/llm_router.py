import asyncio
import logging
import time

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.models.routing import LLMRoutingConfig
from radicalbit_ai_gateway.routing.usage import OnRoutingUsage, RoutingUsage
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.build_user_content import stringify_message_content

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)


def _last_human_text(messages: list[BaseMessage]) -> str | None:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            text = stringify_message_content(msg.content)
            if text:
                return text
    return None


def build_system_prompt(config: LLMRoutingConfig) -> str:
    model_ids = [entry.model_id for entry in config.output_mapping]
    model_lines = '\n'.join(
        f'- {entry.model_id}: {"; ".join(entry.conditions)}'
        for entry in config.output_mapping
    )
    return (
        'You are a query router. Given a user query, score how pertinent the query '
        'is to each model below.\n\n'
        f'Models:\n{model_lines}\n\n'
        f'Respond with a JSON object whose keys are exactly: {", ".join(model_ids)}.\n'
        'Each value is a float between 0.0 and 1.0 representing how pertinent the '
        'query is to that model. Models are independent — scores do not need to '
        'sum to 1. Use low scores across all models when the query does not fit '
        'any of them.'
    )


def build_response_schema(config: LLMRoutingConfig) -> dict:
    model_ids = [entry.model_id for entry in config.output_mapping]
    return {
        'title': 'routing_distribution',
        'description': 'Pertinence score of the query for each model.',
        'type': 'object',
        'properties': {model_id: {'type': 'number'} for model_id in model_ids},
        'required': model_ids,
        'additionalProperties': False,
    }


class LLMRouter:
    """Route by asking a chat model to score the query against each model.

    Follows the "LLM Distribution" strategy of the semantic routing
    experiment: one pertinence score per model, argmax wins, and a best score
    below the threshold falls back to the default model.
    """

    def __init__(
        self,
        config: LLMRoutingConfig,
        models_by_id: dict[str, Model],
        router_model: Model,
        chat_model: BaseChatModel,
    ):
        self._config = config
        self._models_by_id = models_by_id
        self._router_model = router_model
        self._system_prompt = build_system_prompt(config)
        try:
            self._structured_model = chat_model.with_structured_output(
                schema=build_response_schema(config), include_raw=True
            )
        except NotImplementedError:
            logger.warning(
                'Router model %s does not support structured output, '
                'LLM routing will always select the default model',
                router_model.model_id,
            )
            self._structured_model = None

    async def select_model(
        self,
        messages: list[BaseMessage],
        on_usage: OnRoutingUsage | None = None,
    ) -> Model:
        if self._structured_model is None:
            return self._default_model()

        last_text = _last_human_text(messages)
        if not last_text:
            logger.debug('No human message found, selecting default model')
            return self._default_model()

        start_time = time.monotonic()
        try:
            response = await asyncio.wait_for(
                self._structured_model.ainvoke(
                    [
                        SystemMessage(content=self._system_prompt),
                        HumanMessage(content=last_text),
                    ]
                ),
                timeout=self._config.timeout,
            )
        except Exception:
            logger.warning('LLM router call failed, using default model', exc_info=True)
            return self._default_model()
        latency_ms = (time.monotonic() - start_time) * 1000

        await self._report_usage(response.get('raw'), latency_ms, on_usage)

        scores = response.get('parsed')
        if not isinstance(scores, dict):
            logger.warning(
                'LLM router returned no parseable scores, using default model'
            )
            return self._default_model()

        best_model_id = self._config.default_model_id
        best_score = -1.0
        for entry in self._config.output_mapping:
            try:
                score = float(scores.get(entry.model_id, 0.0))
            except (TypeError, ValueError):
                continue
            if score > best_score:
                best_score = score
                best_model_id = entry.model_id

        logger.debug(
            'LLM routing: best match model=%s score=%.4f threshold=%.4f',
            best_model_id,
            best_score,
            self._config.threshold,
        )
        if best_score < self._config.threshold:
            return self._default_model()

        return self._models_by_id[best_model_id]

    async def _report_usage(
        self,
        raw_response,
        latency_ms: float,
        on_usage: OnRoutingUsage | None,
    ) -> None:
        if on_usage is None:
            return
        if not isinstance(raw_response, AIMessage) or not raw_response.usage_metadata:
            logger.warning('LLM router response carries no token usage')
            return
        await on_usage(
            RoutingUsage(
                model=self._router_model,
                model_type='chat-model',
                latency_ms=latency_ms,
                input_tokens=raw_response.usage_metadata.get('input_tokens', 0),
                output_tokens=raw_response.usage_metadata.get('output_tokens', 0),
            )
        )

    def _default_model(self) -> Model:
        return self._models_by_id[self._config.default_model_id]
