from decimal import Decimal
import logging

from radicalbit_ai_gateway.utils.app_config import get_app_config

app_config = get_app_config()
logging_config_dict = app_config.log_config.model_dump()
logger = logging.getLogger(app_config.log_config.logger_name)


class CostService:
    def __init__(
        self,
        chat_models_by_id: dict | None = None,
        embedding_models_by_id: dict | None = None,
        transcription_models_by_id: dict | None = None,
        decision_models_by_id: dict | None = None,
    ):
        self.prices = self._extract_model_costs(
            chat_models_by_id or {},
            embedding_models_by_id or {},
            transcription_models_by_id or {},
            decision_models_by_id or {},
        )

    @staticmethod
    def _extract_model_costs(
        chat_models_by_id: dict,
        embedding_models_by_id: dict,
        transcription_models_by_id: dict | None = None,
        decision_models_by_id: dict | None = None,
    ) -> dict:
        results = {}
        for models_by_id in (
            chat_models_by_id,
            embedding_models_by_id,
            transcription_models_by_id or {},
            decision_models_by_id or {},
        ):
            for m in models_by_id.values():
                results[m.model_id] = (
                    m.input_cost_per_token,
                    m.output_cost_per_token,
                    m.input_cached_cost_per_token,
                    m.input_cache_creation_5m_cost_per_token,
                    m.input_cache_creation_1h_cost_per_token,
                    m.input_cost_per_second,
                    m.input_cost_per_audio_token,
                )
        return results

    def compute_cost(
        self, token_processed: int | float, where: str, model_id: str
    ) -> float:
        try:
            match where:
                case 'input':
                    cost_per_token = self.prices[model_id][0]
                case 'output':
                    cost_per_token = self.prices[model_id][1]
                case 'cached':
                    cost_per_token = self.prices[model_id][2]
                case 'cached_creation':
                    cost_per_token = self.prices[model_id][3]
                case 'cached_creation_1h':
                    cost_per_token = self.prices[model_id][4]
                case 'duration':
                    cost_per_token = self.prices[model_id][5]
                case 'audio':
                    cost_per_token = self.prices[model_id][6]
                case _:
                    raise ValueError(f'Invalid where value: {where}')
        except KeyError:
            logger.warning(
                'Failed to compute cost for %s',
                model_id,
            )
        return Decimal(str(token_processed)) * cost_per_token
