"""Embeddings: the order a request goes through the route's policies."""

import logging

from openai.types.create_embedding_response import CreateEmbeddingResponse
from traceloop.sdk.decorators import task

from radicalbit_ai_gateway.endpoints.common.conversation import (
    check_limits,
    checked_in_span,
)
from radicalbit_ai_gateway.endpoints.embeddings.cache import EmbeddingEntry
from radicalbit_ai_gateway.gateway_route.scope import RequestScope
from radicalbit_ai_gateway.guardrails.guardrails import Texts
from radicalbit_ai_gateway.limiting.limits import Demand, InputEstimate, Usage
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.build_user_content import build_user_content_from_texts
from radicalbit_ai_gateway.utils.exceptions import (
    GatewayBadRequest,
    GuardrailBadRequest,
)
from radicalbit_ai_gateway.utils.trace_attributes import (
    OperationCategory,
    set_operation_category,
)

logger = logging.getLogger(get_app_config().log_config.logger_name)


_check_in_span = checked_in_span('check_embedding_limiters')


async def embed(scope: RequestScope, texts: list[str]) -> CreateEmbeddingResponse:
    """Embed the texts of a request."""
    route = scope.route
    route_name = route.gateway_route_config.route_name
    if not route.embedding_invoker:
        raise GatewayBadRequest(f'Route {route_name} has no embedding models defined')

    set_operation_category(OperationCategory.ROUTING)
    model = _select_model(scope)

    # Limits come first, before the judges spend.
    demand = Demand(
        input=InputEstimate(build_user_content_from_texts(texts), model.model),
        cost_room=True,
    )
    await check_limits(scope.limits, demand, _check_in_span)

    redaction = await scope.guardrails.redact_input(Texts(texts))
    try:
        screened = await scope.guardrails.check_input(redaction.payload)
    except GuardrailBadRequest as e:
        logger.warning('Guardrail BLOCK triggered: %s', e.log_message)
        raise
    if screened.soft_block:
        return screened.soft_block.build_soft_block_embedding_response(route_name)
    texts = screened.payload.items

    scope.cached = await scope.cache.lookup(EmbeddingEntry(texts))
    if scope.cached.hit:
        return scope.cached.value

    set_operation_category(OperationCategory.INVOCATION)
    response = await route.embedding_invoker.embed(
        identity=scope.identity, input_texts=texts, model_id=model.model_id
    )
    if response.usage:
        await scope.limits.count(Usage.priced(model, response.usage.prompt_tokens))
    await scope.cached.store(response)
    return response


@task(name='select_embedding_model')
def _select_model(scope: RequestScope) -> Model:
    """Return the route's first embedding model: it serves its traffic."""
    models = scope.route.embedding_models
    if not models:
        raise ValueError('Configuration for embedding model not found.')
    logger.debug('Selected embedding model: %s', models[0].model_id)
    return models[0]
