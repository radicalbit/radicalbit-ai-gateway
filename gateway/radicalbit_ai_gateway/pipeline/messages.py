"""Anthropic Messages API requests: the order a request goes through the
route's policies.

The policies read the request's texts as chat messages (see
``MessagesRequest``); what they change is written back into the body that
goes upstream.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass

from radicalbit_ai_gateway.messages.events import relay_frame
from radicalbit_ai_gateway.messages.request import MessagesRequest
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.pipeline.conversation import (
    apply_config_prompt,
    route_chat,
)
from radicalbit_ai_gateway.pipeline.scope import RequestScope
from radicalbit_ai_gateway.preprocessing import run_preprocessing
from radicalbit_ai_gateway.utils.exceptions import GatewayBadRequest
from radicalbit_ai_gateway.utils.trace_attributes import (
    OperationCategory,
    set_operation_category,
    set_streaming,
)


@dataclass
class MessagesPrepared:
    """A Messages API request after the gateway's policies, before the model
    call: the body and the client's ``anthropic-*`` headers to forward
    upstream, and the model routing selected.
    """

    body: dict
    headers: dict[str, str]
    model: Model


async def prepare(
    scope: RequestScope, body: dict, headers: dict[str, str]
) -> MessagesPrepared:
    """Apply the route's policies to a Messages API request."""
    route = scope.route
    config = route.gateway_route_config
    route_name = config.route_name
    if not route.chat_invoker:
        raise GatewayBadRequest(f'Route {route_name} has no chat models defined')

    request = MessagesRequest(body)
    set_operation_category(OperationCategory.PREPROCESSING)
    messages = await run_preprocessing(request.messages(), config.plugins)
    # Input guardrails (redact before routing, check, soft block) go here,
    # as on the Responses API: AG-1132.
    model = await route_chat(scope, messages)
    if not route.chat_invoker.supports_messages(model.model_id):
        raise GatewayBadRequest(
            f'Model {model.model_id} of route {route_name} '
            'does not serve the Messages API'
        )

    added = apply_config_prompt(messages, model)
    request.write_back(messages[added:])
    if added:
        # A deliberate choice, as on the Responses API: the configured
        # prompt goes first in ``system``. It changes the prefix the
        # client's prompt cache sees.
        request.insert_system_prompt(messages[0])

    # The cache lookup and the limits go here, as on the Responses API:
    # AG-1132.
    return MessagesPrepared(request.body, headers, model)


def _call(scope: RequestScope, prepared: MessagesPrepared) -> dict:
    """Return the arguments of the invoker's call for a prepared request."""
    return {
        'identity': scope.identity,
        'body': prepared.body,
        'headers': prepared.headers,
        'model_id': prepared.model.model_id,
    }


async def respond(scope: RequestScope, prepared: MessagesPrepared) -> dict:
    """Answer a prepared Messages API request; return the message object."""
    set_operation_category(OperationCategory.INVOCATION)
    message, _ = await scope.route.chat_invoker.complete_messages(
        **_call(scope, prepared)
    )
    # Output guardrails and usage accounting go here: AG-1132.
    return {**message, 'model': scope.route.gateway_route_config.route_name}


async def stream(
    scope: RequestScope, prepared: MessagesPrepared
) -> AsyncIterator[str]:
    """Relay a prepared Messages API request's upstream events as SSE frames."""
    set_streaming()
    set_operation_category(OperationCategory.INVOCATION)
    route_name = scope.route.gateway_route_config.route_name
    async for event, data in scope.route.chat_invoker.stream_messages(
        **_call(scope, prepared)
    ):
        yield relay_frame(event, data, route_name)
    # Buffered mode, for output guardrails and the cache: AG-1132.
