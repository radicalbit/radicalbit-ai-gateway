from datetime import datetime, timezone
import logging

from cron_converter import Cron

from radicalbit_ai_gateway.limiting.limits import shared_limits
from radicalbit_ai_gateway.limiting.windows import Window
from radicalbit_ai_gateway.llm.messages import BaseMessage
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.models.routing import (
    DeterministicRoutingConfig,
    RoutingRuleType,
)
from radicalbit_ai_gateway.routing.common import RoutingSpendRecorder, last_human_text
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.build_user_content import build_user_content
from radicalbit_ai_gateway.utils.token_encoding import count_tokens

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)


class DeterministicRouter:
    def __init__(
        self,
        config: DeterministicRoutingConfig,
        models_by_id: dict[str, Model],
        budget: Window | None,
    ):
        self._config = config
        self._models_by_id = models_by_id
        # The route's budget, for the budget rule.
        self.budget = budget

    async def select_model(
        self,
        messages: list[BaseMessage],
        record_spend: RoutingSpendRecorder | None = None,
    ) -> Model:
        if self._config.rule == RoutingRuleType.KEYWORD:
            return self._apply_keyword_rule(messages)
        if self._config.rule == RoutingRuleType.TOKEN_LENGTH:
            return self._apply_token_length_rule(messages)
        if self._config.rule == RoutingRuleType.CONTEXT_LENGTH:
            return self._apply_context_length_rule(messages)
        if self._config.rule == RoutingRuleType.TIME:
            return self._apply_time_rule()
        if self._config.rule == RoutingRuleType.BUDGET:
            return await self._apply_budget_rule()
        return self._default_model()

    def _apply_keyword_rule(self, messages: list[BaseMessage]) -> Model:
        last_text = last_human_text(messages)
        if not last_text:
            logger.debug('No human message found, selecting default model')
            return self._default_model()
        lowered_text = last_text.lower()
        for entry in self._config.output_mapping:
            for keyword in entry.conditions:
                if str(keyword).lower() in lowered_text:
                    logger.debug(
                        "Keyword '%s' select model '%s'",
                        keyword,
                        entry.model_id,
                    )
                    return self._models_by_id[entry.model_id]

        logger.debug('No keyword matched, selecting default model')
        return self._default_model()

    def _apply_token_length_rule(self, messages: list[BaseMessage]) -> Model:
        last_text = last_human_text(messages)
        if not last_text:
            logger.debug('No human message found, selecting default model')
            return self._default_model()
        return self._apply_conditions_rule(last_text, 'Token count')

    def _apply_context_length_rule(self, messages: list[BaseMessage]) -> Model:
        full_text = build_user_content(messages)
        if not full_text:
            logger.debug('No message content found, selecting default model')
            return self._default_model()
        return self._apply_conditions_rule(full_text, 'Context token count')

    @staticmethod
    def _condition_sort_key(entry):
        cond = entry.conditions
        if cond.gte is not None:
            return cond.gte
        if cond.lte is not None:
            return -cond.lte
        if cond.between is not None:
            return cond.between[0]
        return 0

    def _apply_conditions_rule(self, text: str, log_prefix: str) -> Model:
        """Select a model by matching token count against conditions.

        Entries are sorted descending by their numeric value (gte/lte value
        or between[0]). The first matching entry wins.
        """
        default_model = self._default_model()
        token_count = count_tokens(text, default_model.model)
        logger.debug('%s for routing: %d', log_prefix, token_count)

        sorted_entries = sorted(
            self._config.output_mapping,
            key=self._condition_sort_key,
            reverse=True,
        )
        for entry in sorted_entries:
            cond = entry.conditions
            matched = False
            if cond.gte is not None:
                matched = token_count >= cond.gte
            elif cond.lte is not None:
                matched = token_count <= cond.lte
            elif cond.between is not None:
                matched = cond.between[0] <= token_count <= cond.between[1]

            if matched:
                logger.debug(
                    '%s %d matched conditions for model %s',
                    log_prefix,
                    token_count,
                    entry.model_id,
                )
                return self._models_by_id[entry.model_id]

        logger.debug(
            '%s %d matched no conditions, selecting default model',
            log_prefix,
            token_count,
        )
        return default_model

    def _apply_time_rule(self) -> Model:
        now = datetime.now(timezone.utc)
        for entry in self._config.output_mapping:
            for time_interval in entry.conditions:
                validate = Cron(str(time_interval)).validate(now)
                if validate:
                    logger.debug(
                        'Entry %s with model %s was selected',
                        time_interval,
                        entry.model_id,
                    )
                    return self._models_by_id[entry.model_id]
        return self._default_model()

    async def _apply_budget_rule(self) -> Model:
        if self.budget:
            if self.budget.config.limit == 0:
                return self._default_model()

            usage_ratio = await shared_limits.usage_ratio(self.budget)
            logger.debug('Budget usage ratio: %.4f', usage_ratio)

            sorted_entries = sorted(
                self._config.output_mapping,
                key=lambda e: e.conditions.threshold,
                reverse=True,
            )

            # Iterate reversed so highest threshold is checked first
            for entry in sorted_entries:
                threshold = entry.conditions.threshold
                if threshold <= usage_ratio:
                    logger.debug(
                        "Budget threshold %.2f met (usage=%.4f), selecting model '%s'",
                        threshold,
                        usage_ratio,
                        entry.model_id,
                    )
                    return self._models_by_id[entry.model_id]
            logger.debug('No budget threshold matched, selecting default model')
            return self._default_model()
        return self._default_model()

    def _default_model(self) -> Model:
        return self._models_by_id[self._config.default_model_id]
