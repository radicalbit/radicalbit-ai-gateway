"""Decision models: the order a request goes through the route's policies."""

from typing import Any

from radicalbit_ai_gateway.caching.route_cache import DecisionEntry
from radicalbit_ai_gateway.guardrails.guardrails import RequestGuardrails, Texts
from radicalbit_ai_gateway.invocation.decision_model_invoker import DecisionResponse
from radicalbit_ai_gateway.limiting.limits import Demand, Usage
from radicalbit_ai_gateway.pipeline.conversation import check_limits
from radicalbit_ai_gateway.pipeline.scope import RequestScope
from radicalbit_ai_gateway.utils.exceptions import (
    GatewayBadRequest,
    GuardrailBadRequest,
)
from radicalbit_ai_gateway.utils.state_leaves import string_leaves, with_string_leaves
from radicalbit_ai_gateway.utils.trace_attributes import (
    OperationCategory,
    set_operation_category,
)

SCREENED_FIELDS = ('state', 'questions')


async def decide(scope: RequestScope, body: dict) -> DecisionResponse:
    """Answer a decision request, Typesafe's body passed through (ADR 0004)."""
    route = scope.route
    config = route.gateway_route_config
    if not route.decision_invoker:
        raise GatewayBadRequest(
            f'Route {config.route_name} has no decision models defined'
        )

    # The first decision model listed on the route serves its traffic.
    set_operation_category(OperationCategory.ROUTING)
    model = route.decision_models[0]

    # Limits come first, before the judges spend. The input size is known
    # only from the response, so a limit blocks only when its counter is full.
    await check_limits(scope.limits, Demand(input='room', cost_room=True))

    screened = {f: body[f] for f in SCREENED_FIELDS if f in body}
    if config.guardrails and screened:
        body = {**body, **await _screen_fields(scope.guardrails, screened)}

    scope.cached = await scope.cache.lookup(
        DecisionEntry(body.get('state'), body.get('questions'), model.model_id)
    )
    if scope.cached.hit:
        return DecisionResponse(
            status_code=scope.cached.value['status_code'],
            content=scope.cached.value['content'].encode('utf-8'),
            media_type=scope.cached.value['media_type'],
        )

    set_operation_category(OperationCategory.INVOCATION)
    response = await route.decision_invoker.decide(
        identity=scope.identity, body=body, model_id=model.model_id
    )
    if response.model_invoked is not None:
        # Typesafe bills input tokens only: output-token counters get nothing.
        if response.input_tokens > 0:
            await scope.limits.count(
                Usage.priced(response.model_invoked, response.input_tokens)
            )
        await scope.cached.store(
            {
                'status_code': response.status_code,
                'content': response.content.decode('utf-8'),
                'media_type': response.media_type,
                'model_id': response.model_invoked.model_id,
                'input_tokens': response.input_tokens,
            }
        )
    return response


async def _screen_fields(
    guardrails: RequestGuardrails, fields: dict[str, Any]
) -> dict[str, Any]:
    """Screen each string leaf of ``fields`` (``state`` and ``questions``) as
    one text. Return ``fields`` with the leaves redacted.

    A soft block raises the 400 a block raises (ADR 0005): Typesafe's 200
    body has no room for it. It is still recorded as a soft block.
    """
    texts = string_leaves(fields)
    if not texts:
        return fields
    screened = await guardrails.screen_input(Texts(texts))
    if screened.soft_block:
        raise GuardrailBadRequest(
            screened.soft_block.get_soft_block_message(),
            screened.soft_block.guardrail,
        )
    return with_string_leaves(fields, screened.payload.items)
