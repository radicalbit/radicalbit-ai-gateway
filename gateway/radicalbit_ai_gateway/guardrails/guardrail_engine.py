from radicalbit_ai_gateway.guardrails.guardrail_check import GuardrailCheck
from radicalbit_ai_gateway.guardrails.guardrail_redact import GuardrailRedact
from radicalbit_ai_gateway.guardrails.judges.judge_engine import JudgeEngine
from radicalbit_ai_gateway.guardrails.presidio import PresidioEngine
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.models.guardrails import (
    Guardrail,
    GuardrailClass,
    GuardrailWhereType,
)
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.services.cost_service import CostService


class GuardrailEngine:
    def __init__(
        self,
        presidio_engine: PresidioEngine,
        judge_engine: JudgeEngine,
        cost_service: CostService,
        guardrails: list[Guardrail] | None = None,
        chat_models_by_id: dict[str, Model] | None = None,
    ):
        self._presidio_engine = presidio_engine
        self._judge_engine = judge_engine
        self._guardrails_by_name: dict[str, Guardrail] = {
            g.name: g for g in (guardrails or [])
        }
        self._chat_models_by_id = chat_models_by_id
        self._guardrail_redact = GuardrailRedact(
            presidio_engine=self._presidio_engine,
            guardrails_by_name=self._guardrails_by_name,
        )
        self._guardrail_check = GuardrailCheck(
            presidio_engine=self._presidio_engine,
            judge_engine=self._judge_engine,
            guardrails_by_name=self._guardrails_by_name,
            chat_models_by_id=self._chat_models_by_id,
            cost_service=cost_service,
        )

    @property
    def guardrail_check(self):
        return self._guardrail_check

    @property
    def guardrail_redact(self):
        return self._guardrail_redact

    @property
    def judge_engine(self):
        return self._judge_engine

    def has_guardrails_for_route(
        self,
        route_config: GatewayRouteConfig,
        where: GuardrailWhereType,
        guardrail_class: GuardrailClass,
    ) -> bool:
        """Lightweight check: returns True if any enabled guardrail of the given class
        and where applies to the route. Avoids entering decorated functions when no
        matching guardrails exist (prevents creating empty trace spans).
        """
        for gr_name in route_config.guardrails or []:
            guardrail = self._guardrails_by_name.get(gr_name)
            if (
                guardrail
                and guardrail.enabled
                and guardrail.guardrail_class() == guardrail_class
                and guardrail.where in (where, GuardrailWhereType.IO)
            ):
                return True
        return False
