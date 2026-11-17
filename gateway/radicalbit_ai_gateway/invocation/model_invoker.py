from collections.abc import Callable
import logging
from typing import Any, TypeAlias

from radicalbit_ai_gateway.invocation.recorder import Recorder
from radicalbit_ai_gateway.models.fallback import Fallback
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.app_config import get_app_config

app_config = get_app_config()

logger = logging.getLogger(app_config.log_config.logger_name)

PrimaryModel: TypeAlias = Any
FallbackModels: TypeAlias = list[tuple[Model, Any]]


class ModelInvoker:
    def __init__(
        self,
        models: list[Model],
        cost_service: CostService,
        fallbacks: list[Fallback] | None = None,
        httpx_client=None,
    ):
        self.models = models
        self.cost_service = cost_service
        self.fallbacks = fallbacks
        self.httpx_client = httpx_client
        self.recorder = Recorder(cost_service)
        self.model_map: dict[str, tuple[Model, PrimaryModel, FallbackModels]] = {}

    def _initialize_models(self, build_fn: Callable[[Model], Any]):
        models_lookup: dict[str, Model] = {m.model_id: m for m in self.models}

        fallback_lookup: dict[str, list[str]] = {}
        if self.fallbacks:
            for f in self.fallbacks:
                fallback_lookup.setdefault(f.target, []).extend(f.fallbacks)

        for model in self.models:
            model_id = model.model_id
            primary_runnable = build_fn(model)
            fallbacks_runnable = []
            for f in fallback_lookup.get(model_id, []):
                fallback_model = models_lookup.get(f)
                if fallback_model:
                    try:
                        runnable = build_fn(fallback_model)
                        fallbacks_runnable.append((fallback_model, runnable))
                    except Exception as e:
                        logger.warning(
                            'Failed to create fallback model %s for target %s: %s',
                            fallback_model.model_id,
                            model_id,
                            str(e),
                        )
            self.model_map[model_id] = (model, primary_runnable, fallbacks_runnable)

    def _build_model(self, model: Model):
        raise NotImplementedError
