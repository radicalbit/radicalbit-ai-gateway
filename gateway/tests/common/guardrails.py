"""Run a route's check or redact guardrails for one phase, as its requests do."""

from radicalbit_ai_gateway.guardrails.guardrail_check import CheckResult
from radicalbit_ai_gateway.guardrails.guardrails import Guardrails
from radicalbit_ai_gateway.llm.messages import BaseMessage
from radicalbit_ai_gateway.models.guardrails import GuardrailWhereType
from radicalbit_ai_gateway.models.request_identity import RequestIdentity


def _identity(route_config, identity: dict) -> RequestIdentity:
    return RequestIdentity(route_name=route_config.route_name, **identity)


async def apply_check(
    guardrails: Guardrails,
    route_config,
    messages: list[BaseMessage],
    where: GuardrailWhereType,
    count_judge_usage=None,
    windowed: bool = True,
    skip: int = 0,
    **identity,
) -> CheckResult:
    """Apply the check guardrails ``route_config`` lists for ``where``."""
    route = guardrails.for_route(route_config)
    picked = (
        route.output_check if where == GuardrailWhereType.OUTPUT else route.input_check
    )
    return await route.check.apply(
        identity=_identity(route_config, identity),
        guardrails=picked,
        messages=messages,
        where=where,
        unknown=route.unknown,
        count_judge_usage=count_judge_usage,
        windowed=windowed,
        skip=skip,
    )


async def apply_redact(
    guardrails: Guardrails,
    route_config,
    messages: list[BaseMessage],
    where: GuardrailWhereType,
    windowed: bool = True,
    **identity,
) -> list[BaseMessage]:
    """Apply the redact guardrails ``route_config`` lists for ``where``."""
    route = guardrails.for_route(route_config)
    picked = (
        route.output_redact
        if where == GuardrailWhereType.OUTPUT
        else route.input_redact
    )
    return await route.redact.apply(
        identity=_identity(route_config, identity),
        guardrails=picked,
        messages=messages,
        where=where,
        unknown=route.unknown,
        windowed=windowed,
    )
