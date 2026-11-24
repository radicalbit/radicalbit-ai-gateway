from decimal import Decimal
import logging

from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.utils.app_config import get_app_config

app_config = get_app_config()
logging_config_dict = app_config.log_config.model_dump()
logger = logging.getLogger(app_config.log_config.logger_name)


# A model's prices: input, output, cached input, 5m and 1h cache creation per
# token, input per second, input per audio token.
_ModelPrices = tuple[Decimal, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]


class CostService:
    def __init__(
        self,
        chat_models_by_id: dict[str, Model] | None = None,
        embedding_models_by_id: dict[str, Model] | None = None,
        transcription_models_by_id: dict[str, Model] | None = None,
        decision_models_by_id: dict[str, Model] | None = None,
    ):
        self.prices = self._extract_model_costs(
            chat_models_by_id or {},
            embedding_models_by_id or {},
            transcription_models_by_id or {},
            decision_models_by_id or {},
        )

    @staticmethod
    def _extract_model_costs(
        chat_models_by_id: dict[str, Model],
        embedding_models_by_id: dict[str, Model],
        transcription_models_by_id: dict[str, Model] | None = None,
        decision_models_by_id: dict[str, Model] | None = None,
    ) -> dict[str, _ModelPrices]:
        results: dict[str, _ModelPrices] = {}
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
    ) -> Decimal:
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
            # A missing price must never fail the request: cost it at 0.
            logger.warning(
                'No price entry for model %s, costing it at 0',
                model_id,
            )
            return Decimal('0')
        return Decimal(str(token_processed)) * cost_per_token
