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
    ):
        self.prices = self._extract_model_costs(
            chat_models_by_id or {},
            embedding_models_by_id or {},
        )

    @staticmethod
    def _extract_model_costs(
        chat_models_by_id: dict,
        embedding_models_by_id: dict,
    ) -> dict:
        results = {}
        for m in chat_models_by_id.values():
            results[m.model_id] = (
                m.input_cost_per_token,
                m.output_cost_per_token,
                m.input_cached_cost_per_token,
                m.input_cache_creation_5m_cost_per_token,
                m.input_cache_creation_1h_cost_per_token,
            )
        for e in embedding_models_by_id.values():
            results[e.model_id] = (
                e.input_cost_per_token,
                e.output_cost_per_token,
                e.input_cached_cost_per_token,
                e.input_cache_creation_5m_cost_per_token,
                e.input_cache_creation_1h_cost_per_token,
            )
        return results

    def compute_cost(self, token_processed: int, where: str, model_id: str) -> float:
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
                case _:
                    raise ValueError(f'Invalid where value: {where}')
        except KeyError:
            logger.warning(
                'Failed to compute cost for %s',
                model_id,
            )
        return Decimal(token_processed) * cost_per_token
