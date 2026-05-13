import logging

import httpx
from langchain_core.messages import BaseMessage, HumanMessage

from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.models.routing import TextClassificationRoutingConfig
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.build_user_content import stringify_message_content

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)


class TextClassificationRouter:
    def __init__(
        self,
        config: TextClassificationRoutingConfig,
        models_by_id: dict[str, Model],
    ):
        self._config = config
        self._models_by_id = models_by_id

    async def select_model(self, messages: list[BaseMessage]) -> Model:
        user_text = None
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                text = stringify_message_content(msg.content)
                if text:
                    user_text = text
                    break
        if not user_text:
            logger.warning('No human message found, selecting default model')
            return self._default_model()
        try:
            async with httpx.AsyncClient(timeout=self._config.timeout) as client:
                resp = await client.post(
                    f'{self._config.url}/invocations',
                    json={'dataframe_records': [{'inputs': user_text}]},
                )
                resp.raise_for_status()
                predictions = resp.json().get('predictions', [])
                predicted_class = predictions[0].get('class', '') if predictions else ''
            for entry in self._config.output_mapping:
                if (
                    isinstance(entry.conditions, list)
                    and predicted_class in entry.conditions
                ):
                    logger.debug(
                        "Class '%s' mapped to model '%s'",
                        predicted_class,
                        entry.model_id,
                    )
                    return self._models_by_id[entry.model_id]
            logger.warning(
                'Class %s not in output_mapping, using default', predicted_class
            )
        except Exception:
            logger.warning('Classifier call failed, using default model', exc_info=True)
        return self._default_model()

    def _default_model(self) -> Model:
        return self._models_by_id[self._config.default_model_id]
